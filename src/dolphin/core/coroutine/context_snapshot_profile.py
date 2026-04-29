"""ContextSnapshot Profile - Snapshot Visualization Analysis Tool
Follows Design Document v1.1 Specification
"""
import json
import zlib
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime


@dataclass
class VariableInfo:
    """Variable Information"""
    name: str
    type: str
    size_bytes: int


@dataclass
class ComponentCompression:
    """Component Compression Information"""
    original_bytes: int
    compressed_bytes: int
    compression_ratio: float
    space_saved_ratio: float
    compressibility: str  # high / medium / low


@dataclass
class MessageBuckets:
    """Message Bucket Statistics"""
    by_role: Dict[str, int] = field(default_factory=dict)
    by_role_size_bytes: Dict[str, int] = field(default_factory=dict)
    by_size: Dict[str, int] = field(default_factory=dict)
    by_size_bytes: Dict[str, int] = field(default_factory=dict)
    by_content_type: Dict[str, int] = field(default_factory=dict)
    by_content_type_size_bytes: Dict[str, int] = field(default_factory=dict)
    by_token_range: Dict[str, int] = field(default_factory=dict)
    tool_calls_count: int = 0
    estimated_total_tokens: int = 0


@dataclass
class VariableBuckets:
    """Bucket Statistics for Variables"""
    by_type: Dict[str, int] = field(default_factory=dict)
    by_type_size_bytes: Dict[str, int] = field(default_factory=dict)
    by_size: Dict[str, int] = field(default_factory=dict)
    by_size_bytes: Dict[str, int] = field(default_factory=dict)
    by_namespace: Dict[str, int] = field(default_factory=dict)
    by_namespace_size_bytes: Dict[str, int] = field(default_factory=dict)
    top_variables: List[VariableInfo] = field(default_factory=list)


@dataclass
class CompressionBuckets:
    """Compressed Bucket Statistics"""
    components: Dict[str, ComponentCompression] = field(default_factory=dict)
    highly_compressible: List[Tuple[str, int, str]] = field(default_factory=list)
    poorly_compressible: List[Tuple[str, int, str]] = field(default_factory=list)
    optimization_suggestions: List[str] = field(default_factory=list)


@dataclass
class SnapshotProfile:
    """Snapshot Profile Data Model"""
    # Metadata
    snapshot_id: str
    frame_id: str
    timestamp: float
    schema_version: str = "1.1"

    # Message Statistics
    message_count: int = 0
    message_size_bytes: int = 0
    message_buckets: Optional[MessageBuckets] = None

    # Variable Statistics
    variable_count: int = 0
    variable_size_bytes: int = 0
    variable_buckets: Optional[VariableBuckets] = None

    # Compress Information
    original_size_bytes: int = 0
    compressed_size_bytes: int = 0
    compression_ratio: float = 0.0
    space_saved_ratio: float = 0.0
    compression_buckets: Optional[CompressionBuckets] = None

    # Status Information
    runtime_state_size_bytes: int = 0
    skillkit_state_size_bytes: int = 0
    estimated_memory_mb: float = 0.0
    optimization_suggestions: List[str] = field(default_factory=list)


class ProfileOptions:
    """Profile Configuration Options"""
    def __init__(
        self,
        # Rendering Options
        ascii: bool = True,
        bar_width: int = 12,
        max_output_kb: int = 100,
        # Threshold Configuration
        size_thresholds: Optional[Dict[str, List[int]]] = None,
        token_ranges: Optional[List[int]] = None,
        max_rows: Optional[Dict[str, int]] = None,
        # Security and Privacy
        redact_sensitive: bool = False,
        sensitive_patterns: Optional[List[str]] = None,
        redact_values: bool = False,
        # Performance Optimization
        enable_sampling: bool = False,
        sampling_threshold_mb: int = 5,
        cache_encoded: bool = True,
    ):
        self.ascii = ascii
        self.bar_width = bar_width
        self.max_output_kb = max_output_kb

        self.size_thresholds = size_thresholds or {
            'message_bytes': [1000, 10000],
            'variable_bytes': [1000, 10000]
        }
        self.token_ranges = token_ranges or [100, 1000]
        self.max_rows = max_rows or {'top_variables': 10}

        self.redact_sensitive = redact_sensitive
        self.sensitive_patterns = sensitive_patterns or ['password', 'api_key', 'secret']
        self.redact_values = redact_values

        self.enable_sampling = enable_sampling
        self.sampling_threshold_mb = sampling_threshold_mb
        self.cache_encoded = cache_encoded


class SnapshotProfileAnalyzer:
    """Snapshot Analyzer - Core Analysis Logic"""

    def __init__(self, snapshot: 'ContextSnapshot', options: Optional[ProfileOptions] = None):
        self.snapshot = snapshot
        self.options = options or ProfileOptions()
        self._encoded_cache: Optional[bytes] = None

    def analyze(self) -> SnapshotProfile:
        """Analyze snapshots and generate Profile"""
        # Calculate size
        original_bytes = self._calc_total_size()
        compressed_bytes = self._calc_compressed_size()

        # Analyze message
        message_buckets = self._analyze_messages()
        message_size = self._calc_component_size(self.snapshot.messages)

        # Analyze variables
        variable_buckets = self._analyze_variables()
        variable_size = self._calc_component_size(self.snapshot.variables)

        # Analyze Compression
        compression_buckets = self._analyze_compression()

        # Calculate compression ratio
        compression_ratio = compressed_bytes / original_bytes if original_bytes > 0 else 0.0
        space_saved_ratio = 1.0 - compression_ratio

        # State size
        runtime_size = self._calc_component_size(self.snapshot.runtime_state)
        skillkit_size = self._calc_component_size(self.snapshot.skillkit_state)

        # Memory Estimation
        estimated_memory = self._estimate_memory(original_bytes)

        # Generate optimization suggestions
        suggestions = self._generate_suggestions(variable_buckets, message_buckets)

        return SnapshotProfile(
            snapshot_id=self.snapshot.snapshot_id,
            frame_id=self.snapshot.frame_id,
            timestamp=self.snapshot.timestamp,
            schema_version="1.1",
            message_count=len(self.snapshot.messages),
            message_size_bytes=message_size,
            message_buckets=message_buckets,
            variable_count=len(self.snapshot.variables),
            variable_size_bytes=variable_size,
            variable_buckets=variable_buckets,
            original_size_bytes=original_bytes,
            compressed_size_bytes=compressed_bytes,
            compression_ratio=compression_ratio,
            space_saved_ratio=space_saved_ratio,
            compression_buckets=compression_buckets,
            runtime_state_size_bytes=runtime_size,
            skillkit_state_size_bytes=skillkit_size,
            estimated_memory_mb=estimated_memory,
            optimization_suggestions=suggestions,
        )

    def _calc_size(self, obj: Any) -> int:
        """Calculate the byte size after serializing an object"""
        try:
            serialized = json.dumps(obj, ensure_ascii=False)
            return len(serialized.encode('utf-8'))
        except (TypeError, ValueError):
            # Unserializable object, attempted repr
            try:
                repr_str = repr(obj)[:1000]  # Up to 1000 characters
                return len(f"<non-serializable: {type(obj).__name__}>".encode('utf-8'))
            except:
                return 50  # Default placeholder

    def _calc_component_size(self, component: Any) -> int:
        """Calculate component size"""
        return self._calc_size(component)

    def _calc_total_size(self) -> int:
        """Calculate total size"""
        if self.options.cache_encoded and self._encoded_cache is None:
            encoded = self.snapshot.encode()
            self._encoded_cache = json.dumps(encoded, ensure_ascii=False).encode('utf-8')

        if self._encoded_cache:
            return len(self._encoded_cache)

        return self._calc_size(self.snapshot.encode())

    def _calc_compressed_size(self) -> int:
        """Calculate compressed size"""
        if self.options.cache_encoded and self._encoded_cache:
            return len(zlib.compress(self._encoded_cache, level=6))

        encoded = json.dumps(self.snapshot.encode(), ensure_ascii=False).encode('utf-8')
        return len(zlib.compress(encoded, level=6))

    def _estimate_memory(self, size_bytes: int) -> float:
        """Estimate memory usage (MB)"""
        return size_bytes * 3.0 / 1e6

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count (approximate)"""
        if not text:
            return 0

        # Count character types
        ascii_count = sum(1 for c in text if ord(c) < 128)
        non_ascii_count = len(text) - ascii_count

        # Mixed text adopts a conservative estimate
        if non_ascii_count > 0:
            return len(text) // 2  # Chinese/Japanese/Korean
        else:
            return len(text) // 4  # Pure ASCII

    def _estimate_message_tokens(self, message: Dict) -> int:
        """Estimate the number of tokens in a message"""
        text_parts = []

        # Extract text content
        if 'content' in message:
            content = message['content']
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and 'text' in item:
                        text_parts.append(item['text'])

        # Tool Calling
        if 'tool_calls' in message:
            text_parts.append(json.dumps(message['tool_calls']))

        combined_text = ' '.join(text_parts)
        return self._estimate_tokens(combined_text)

    def _extract_namespace(self, var_name: str) -> str:
        """Extract variable namespace"""
        # Handling None or empty strings
        if not var_name:
            return '(unnamed)'

        if var_name.startswith('__'):
            return '__builtin__'
        if var_name.startswith('_'):
            return '_private'

        if '_' in var_name:
            return var_name.split('_')[0] + '_'

        return '(other)'

    def _get_size_bucket(self, size_bytes: int, thresholds: List[int]) -> str:
        """Get size buckets"""
        if size_bytes < thresholds[0]:
            return f'<{thresholds[0] // 1000} KB'
        elif size_bytes < thresholds[1]:
            return f'{thresholds[0] // 1000}–{thresholds[1] // 1000} KB'
        else:
            return f'>={thresholds[1] // 1000} KB'

    def _get_token_bucket(self, tokens: int) -> str:
        """Get token buckets"""
        ranges = self.options.token_ranges
        if tokens < ranges[0]:
            return f'<{ranges[0]}'
        elif tokens < ranges[1]:
            return f'{ranges[0]}–{ranges[1]}'
        else:
            return f'>={ranges[1]}'

    def _get_compressibility(self, compression_ratio: float) -> str:
        """Get compressibility classification"""
        if compression_ratio < 0.4:
            return 'high'
        elif compression_ratio < 0.7:
            return 'medium'
        else:
            return 'low'

    def _analyze_messages(self) -> MessageBuckets:
        """Analyze message"""
        buckets = MessageBuckets()

        for msg in self.snapshot.messages:
            # Role Bucket
            role = msg.get('role', 'unknown')
            buckets.by_role[role] = buckets.by_role.get(role, 0) + 1

            # Size
            msg_size = self._calc_size(msg)
            buckets.by_role_size_bytes[role] = buckets.by_role_size_bytes.get(role, 0) + msg_size

            # Bucket Size
            size_bucket = self._get_size_bucket(msg_size, self.options.size_thresholds['message_bytes'])
            buckets.by_size[size_bucket] = buckets.by_size.get(size_bucket, 0) + 1
            buckets.by_size_bytes[size_bucket] = buckets.by_size_bytes.get(size_bucket, 0) + msg_size

            # Content Type
            content_type = 'text'
            if 'tool_calls' in msg:
                content_type = 'tool_call'
                buckets.tool_calls_count += len(msg['tool_calls'])
            elif role == 'tool':
                content_type = 'tool_response'

            buckets.by_content_type[content_type] = buckets.by_content_type.get(content_type, 0) + 1
            buckets.by_content_type_size_bytes[content_type] = buckets.by_content_type_size_bytes.get(content_type, 0) + msg_size

            # Token Estimation
            tokens = self._estimate_message_tokens(msg)
            buckets.estimated_total_tokens += tokens

            token_bucket = self._get_token_bucket(tokens)
            buckets.by_token_range[token_bucket] = buckets.by_token_range.get(token_bucket, 0) + 1

        return buckets

    def _analyze_variables(self) -> VariableBuckets:
        """Analyze variables"""
        buckets = VariableBuckets()
        var_info_list = []

        for name, value in self.snapshot.variables.items():
            # Type
            var_type = type(value).__name__
            buckets.by_type[var_type] = buckets.by_type.get(var_type, 0) + 1

            # Size
            var_size = self._calc_size(value)
            buckets.by_type_size_bytes[var_type] = buckets.by_type_size_bytes.get(var_type, 0) + var_size

            # Bucket Size
            size_bucket = self._get_size_bucket(var_size, self.options.size_thresholds['variable_bytes'])
            buckets.by_size[size_bucket] = buckets.by_size.get(size_bucket, 0) + 1
            buckets.by_size_bytes[size_bucket] = buckets.by_size_bytes.get(size_bucket, 0) + var_size

            # Namespace
            namespace = self._extract_namespace(name)
            buckets.by_namespace[namespace] = buckets.by_namespace.get(namespace, 0) + 1
            buckets.by_namespace_size_bytes[namespace] = buckets.by_namespace_size_bytes.get(namespace, 0) + var_size

            # Collect information for Top N
            var_info_list.append(VariableInfo(name=name, type=var_type, size_bytes=var_size))

        # Top N
        var_info_list.sort(key=lambda x: x.size_bytes, reverse=True)
        max_top = self.options.max_rows.get('top_variables', 10)
        buckets.top_variables = var_info_list[:max_top]

        return buckets

    def _analyze_compression(self) -> CompressionBuckets:
        """Analyze Compression"""
        buckets = CompressionBuckets()

        # Analyze each component (including context_manager_state)
        components = {
            'messages': self.snapshot.messages,
            'variables': self.snapshot.variables,
            'runtime_state': self.snapshot.runtime_state,
            'skillkit_state': self.snapshot.skillkit_state,
            'context_manager_state': self.snapshot.context_manager_state,
        }

        for name, component in components.items():
            original = self._calc_component_size(component)
            compressed = len(zlib.compress(json.dumps(component, ensure_ascii=False).encode('utf-8'), level=6))

            ratio = compressed / original if original > 0 else 1.0
            saved = 1.0 - ratio
            compressibility = self._get_compressibility(ratio)

            buckets.components[name] = ComponentCompression(
                original_bytes=original,
                compressed_bytes=compressed,
                compression_ratio=ratio,
                space_saved_ratio=saved,
                compressibility=compressibility,
            )

            # High/Low Compressibility
            if compressibility == 'high':
                buckets.highly_compressible.append((name, original, f"{ratio:.1%} compression ratio"))
            elif compressibility == 'low':
                buckets.poorly_compressible.append((name, original, f"{ratio:.1%} compression ratio"))

        return buckets

    def _generate_suggestions(self, var_buckets: VariableBuckets, msg_buckets: MessageBuckets) -> List[str]:
        """Generate optimization suggestions"""
        suggestions = []

        # Top Variable Suggestions
        if var_buckets.top_variables:
            top_var = var_buckets.top_variables[0]
            if top_var.size_bytes > 3000:  # > 3KB
                suggestions.append(
                    f"{top_var.name} ({top_var.size_bytes / 1000:.2f} KB) - Consider incremental snapshot or partial loading"
                )

        # Temporary Variable Cleanup
        temp_count = var_buckets.by_namespace.get('temp_', 0)
        if temp_count > 0:
            temp_size = var_buckets.by_namespace_size_bytes.get('temp_', 0)
            suggestions.append(
                f"{temp_count} temp_* variables ({temp_size / 1000:.2f} KB) - Cleanup before snapshot"
            )

        # Message Suggestions
        assistant_size = msg_buckets.by_role_size_bytes.get('assistant', 0)
        if assistant_size > 5000:  # > 5KB
            suggestions.append(
                f"Assistant messages ({assistant_size / 1000:.2f} KB) - Consider archiving older messages"
            )

        return suggestions


def dataclass_to_dict(obj: Any) -> Any:
    """Recursively convert dataclass to dictionary"""
    if hasattr(obj, '__dataclass_fields__'):
        result = {}
        for key, value in asdict(obj).items():
            result[key] = dataclass_to_dict(value)
        return result
    elif isinstance(obj, dict):
        return {k: dataclass_to_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [dataclass_to_dict(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(dataclass_to_dict(item) for item in obj)
    else:
        return obj


class MarkdownFormatter:
    """Markdown formatted output"""

    def __init__(self, profile: SnapshotProfile, title: Optional[str] = None, options: Optional[ProfileOptions] = None):
        self.profile = profile
        self.title = title or "ContextSnapshot Profile"
        self.options = options or ProfileOptions()

    def format(self) -> str:
        """Generate Markdown output"""
        sections = [
            self._format_header(),
            self._format_overview(),
            self._format_messages(),
            self._format_variables(),
            self._format_compression(),
            self._format_runtime_skillkit(),
            self._format_summary(),
        ]
        return '\n\n'.join(sections)

    def _format_header(self) -> str:
        """Formatting Titles"""
        timestamp_str = datetime.fromtimestamp(self.profile.timestamp).strftime('%Y-%m-%d %H:%M:%S')
        return f"""# {self.title}

Snapshot ID: `{self.profile.snapshot_id[:8]}` | Frame ID: `{self.profile.frame_id[:8]}`
Timestamp: {timestamp_str} | Schema Version: {self.profile.schema_version}

---"""

    def _format_overview(self) -> str:
        """Formatting Overview"""
        p = self.profile
        return f"""## Overview

| Metric                | Value        |
|-----------------------|--------------|
| Original Size         | {self._format_bytes(p.original_size_bytes)} |
| Compressed Size       | {self._format_bytes(p.compressed_size_bytes)} |
| Compression Ratio     | {p.compression_ratio:.1%} |
| Space Saved Ratio     | {p.space_saved_ratio:.1%} |
| Estimated Memory (MB) | ~{p.estimated_memory_mb:.3f} MB |

---"""

    def _format_messages(self) -> str:
        """Message Statistics Formatting"""
        p = self.profile
        b = p.message_buckets

        if not b or p.message_count == 0:
            return "## Messages\n\nNo messages in snapshot."

        sections = [
            f"## Messages ({p.message_count} items, {self._format_bytes(p.message_size_bytes)})",
            "",
            "### Bucket: By Role",
            "",
            self._format_table(
                ['Role', 'Count', '% (by count)', 'Size (KB)', '% (by bytes)'],
                self._build_role_rows(b)
            ),
            "",
            "### Bucket: By Size",
            "",
            self._format_table(
                ['Range', 'Count', '% (by count)', 'Size (KB)'],
                self._build_size_rows(b.by_size, b.by_size_bytes, p.message_count, 'message_bytes')
            ),
            "",
            "### Bucket: By Content Type",
            "",
            self._format_table(
                ['Type', 'Count', '% (by count)', 'Size (KB)'],
                self._build_content_type_rows(b)
            ),
            "",
            "### Bucket: By Token Range",
            "",
            self._format_table(
                ['Range', 'Count', '% (by count)'],
                self._build_token_range_rows(b)
            ),
            "",
            f"Stats: tool_calls = {b.tool_calls_count} • estimated_total_tokens ≈ {b.estimated_total_tokens:,}",
        ]

        return '\n'.join(sections) + "\n\n---"

    def _format_variables(self) -> str:
        """Formatting Variable Statistics"""
        p = self.profile
        b = p.variable_buckets

        if not b or p.variable_count == 0:
            return "## Variables\n\nNo variables in snapshot."

        sections = [
            f"## Variables ({p.variable_count} items, {self._format_bytes(p.variable_size_bytes)})",
            "",
            "### Bucket: By Type",
            "",
            self._format_table(
                ['Type', 'Count', '% (by count)', 'Size (KB)', '% (by bytes)'],
                self._build_type_rows(b, p.variable_size_bytes)
            ),
            "",
            "### Bucket: By Size",
            "",
            self._format_table(
                ['Range', 'Count', '% (by count)', 'Size (KB)'],
                self._build_size_rows(b.by_size, b.by_size_bytes, p.variable_count, 'variable_bytes')
            ),
            "",
            "### Bucket: By Namespace",
            "",
            self._format_table(
                ['Namespace', 'Count', '% (by count)', 'Size (KB)', 'Note'],
                self._build_namespace_rows(b)
            ),
        ]

        # Top Variables
        if b.top_variables:
            sections.extend([
                "",
                "### Top 10 Largest Variables",
                "",
                self._format_table(
                    ['Rank', 'Name', 'Type', 'Size (KB)', '% (of total)'],
                    self._build_top_variables_rows(b.top_variables, p.variable_size_bytes)
                ),
            ])

        return '\n'.join(sections) + "\n\n---"

    def _format_compression(self) -> str:
        """Formatting compression statistics"""
        p = self.profile
        b = p.compression_buckets

        if not b:
            return ""

        sections = [
            f"## Compression ({self._format_bytes(p.original_size_bytes)} → {self._format_bytes(p.compressed_size_bytes)})",
            "",
            "### By Component",
            "",
            self._format_table(
                ['Component', 'Original (KB)', 'Compressed (KB)', 'Compression Ratio', 'Space Saved Ratio', 'Compressibility'],
                self._build_compression_rows(b)
            ),
        ]

        # Optimization Suggestions
        if p.optimization_suggestions:
            sections.extend([
                "",
                "### Optimization Suggestions",
                "",
                *[f"- {suggestion}" for suggestion in p.optimization_suggestions]
            ])

        return '\n'.join(sections) + "\n\n---"

    def _format_runtime_skillkit(self) -> str:
        """Formatting runtime and Skillkit status"""
        p = self.profile
        b = p.compression_buckets

        runtime_comp = b.components.get('runtime_state') if b else None
        skillkit_comp = b.components.get('skillkit_state') if b else None

        lines = ["## Runtime & Skillkit", ""]

        if runtime_comp:
            lines.append(f"- Runtime State: {self._format_bytes(runtime_comp.original_bytes)} → "
                        f"{self._format_bytes(runtime_comp.compressed_bytes)} "
                        f"(compression_ratio {runtime_comp.compression_ratio:.1%}, {runtime_comp.compressibility})")

        if skillkit_comp:
            if skillkit_comp.compression_ratio >= 0.99:
                lines.append(f"- Skillkit State: {self._format_bytes(skillkit_comp.original_bytes)} "
                           f"(uncompressed, {skillkit_comp.compressibility} compressibility)")
            else:
                lines.append(f"- Skillkit State: {self._format_bytes(skillkit_comp.original_bytes)} → "
                           f"{self._format_bytes(skillkit_comp.compressed_bytes)} "
                           f"(compression_ratio {skillkit_comp.compression_ratio:.1%}, {skillkit_comp.compressibility})")

        return '\n'.join(lines) + "\n\n---"

    def _format_summary(self) -> str:
        """Formatting Summary"""
        p = self.profile
        b = p.message_buckets

        ns_count = len(p.variable_buckets.by_namespace) if p.variable_buckets else 0
        tool_calls = b.tool_calls_count if b else 0
        total_tokens = b.estimated_total_tokens if b else 0

        return f"""## Summary

- Messages: {p.message_count} (tool_calls={tool_calls}, ~{total_tokens / 1000:.1f}K tokens)
- Variables: {p.variable_count} (namespaces={ns_count})
- Size: {self._format_bytes(p.original_size_bytes)} → {self._format_bytes(p.compressed_size_bytes)} (space_saved_ratio {p.space_saved_ratio:.1%})
- Estimated Memory: ~{p.estimated_memory_mb:.3f} MB"""

    def _format_bytes(self, bytes_count: int) -> str:
        """Format byte count as KB/MB"""
        if bytes_count < 1000:
            return f"{bytes_count} B"
        elif bytes_count < 1000000:
            return f"{bytes_count / 1000:.2f} KB"
        else:
            return f"{bytes_count / 1000000:.2f} MB"

    def _format_table(self, headers: List[str], rows: List[List[str]]) -> str:
        """Formatted Table"""
        if not rows:
            return "*(no data)*"

        # Calculate column width
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(cell)))

        # Formatting Header
        header_line = '| ' + ' | '.join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + ' |'
        separator = '|' + '|'.join('-' * (w + 2) for w in col_widths) + '|'

        # Format data line
        data_lines = []
        for row in rows:
            line = '| ' + ' | '.join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)) + ' |'
            data_lines.append(line)

        return '\n'.join([header_line, separator] + data_lines)

    def _build_role_rows(self, buckets: MessageBuckets) -> List[List[str]]:
        """Build character bucket table row"""
        rows = []
        total_count = sum(buckets.by_role.values())
        total_size = sum(buckets.by_role_size_bytes.values())

        for role in sorted(buckets.by_role.keys()):
            count = buckets.by_role[role]
            size = buckets.by_role_size_bytes.get(role, 0)
            rows.append([
                role,
                str(count),
                f"{count / total_count * 100:.1f}%" if total_count > 0 else "0%",
                f"{size / 1000:.2f}",
                f"{size / total_size * 100:.1f}%" if total_size > 0 else "0%",
            ])

        # Total lines
        rows.append([
            'Total',
            str(total_count),
            '100%',
            f"{total_size / 1000:.2f}",
            '100%',
        ])

        return rows

    def _get_size_bucket_order(self, thresholds: List[int]) -> List[str]:
        """Dynamically generate bucket order by threshold"""
        return [
            f'<{thresholds[0] // 1000} KB',
            f'{thresholds[0] // 1000}–{thresholds[1] // 1000} KB',
            f'>={thresholds[1] // 1000} KB'
        ]

    def _get_token_bucket_order(self, ranges: List[int]) -> List[str]:
        """Dynamically generate token bucket order according to configuration"""
        return [
            f'<{ranges[0]}',
            f'{ranges[0]}–{ranges[1]}',
            f'>={ranges[1]}'
        ]

    def _build_size_rows(self, by_size: Dict, by_size_bytes: Dict, total_count: int, threshold_key: str = 'message_bytes') -> List[List[str]]:
        """Build size bucket table row"""
        rows = []
        thresholds = self.options.size_thresholds.get(threshold_key, [1000, 10000])
        order = self._get_size_bucket_order(thresholds)

        for bucket in order:
            count = by_size.get(bucket, 0)
            size = by_size_bytes.get(bucket, 0)
            if count > 0 or bucket in by_size:
                rows.append([
                    bucket,
                    str(count),
                    f"{count / total_count * 100:.1f}%" if total_count > 0 else "0%",
                    f"{size / 1000:.2f}",
                ])

        return rows

    def _build_content_type_rows(self, buckets: MessageBuckets) -> List[List[str]]:
        """Build content type table row"""
        rows = []
        total_count = sum(buckets.by_content_type.values())

        for content_type in sorted(buckets.by_content_type.keys()):
            count = buckets.by_content_type[content_type]
            size = buckets.by_content_type_size_bytes.get(content_type, 0)
            rows.append([
                content_type,
                str(count),
                f"{count / total_count * 100:.1f}%" if total_count > 0 else "0%",
                f"{size / 1000:.2f}",
            ])

        return rows

    def _build_token_range_rows(self, buckets: MessageBuckets) -> List[List[str]]:
        """Build token range table row"""
        rows = []
        total_count = sum(buckets.by_token_range.values())

        order = self._get_token_bucket_order(self.options.token_ranges)
        for bucket in order:
            count = buckets.by_token_range.get(bucket, 0)
            if count > 0 or bucket in buckets.by_token_range:
                rows.append([
                    bucket,
                    str(count),
                    f"{count / total_count * 100:.1f}%" if total_count > 0 else "0%",
                ])

        return rows

    def _build_type_rows(self, buckets: VariableBuckets, total_size: int) -> List[List[str]]:
        """Build type bucket table row"""
        rows = []
        total_count = sum(buckets.by_type.values())

        for var_type in sorted(buckets.by_type.keys()):
            count = buckets.by_type[var_type]
            size = buckets.by_type_size_bytes.get(var_type, 0)
            rows.append([
                var_type,
                str(count),
                f"{count / total_count * 100:.1f}%" if total_count > 0 else "0%",
                f"{size / 1000:.2f}",
                f"{size / total_size * 100:.1f}%" if total_size > 0 else "0%",
            ])

        # Total lines
        rows.append([
            'Total',
            str(total_count),
            '100%',
            f"{total_size / 1000:.2f}",
            '100%',
        ])

        return rows

    def _build_namespace_rows(self, buckets: VariableBuckets) -> List[List[str]]:
        """Build namespace table row"""
        rows = []
        total_count = sum(buckets.by_namespace.values())

        # Special namespace priority
        priority = ['temp_', 'result_', 'cache_', '_private']
        other_namespaces = [ns for ns in buckets.by_namespace.keys() if ns not in priority and ns != '(other)']

        for ns in priority + sorted(other_namespaces):
            if ns not in buckets.by_namespace:
                continue

            count = buckets.by_namespace[ns]
            size = buckets.by_namespace_size_bytes.get(ns, 0)
            note = "Can cleanup" if ns == 'temp_' else "-"

            rows.append([
                ns,
                str(count),
                f"{count / total_count * 100:.1f}%" if total_count > 0 else "0%",
                f"{size / 1000:.2f}",
                note,
            ])

        # (other)
        if '(other)' in buckets.by_namespace:
            count = buckets.by_namespace['(other)']
            size = buckets.by_namespace_size_bytes.get('(other)', 0)
            rows.append([
                '(other)',
                str(count),
                f"{count / total_count * 100:.1f}%" if total_count > 0 else "0%",
                f"{size / 1000:.2f}",
                "-",
            ])

        return rows

    def _build_top_variables_rows(self, top_vars: List[VariableInfo], total_size: int) -> List[List[str]]:
        """Build Top Variables table row"""
        rows = []
        for i, var in enumerate(top_vars, 1):
            rows.append([
                str(i),
                var.name,
                var.type,
                f"{var.size_bytes / 1000:.2f}",
                f"{var.size_bytes / total_size * 100:.1f}%" if total_size > 0 else "0%",
            ])
        return rows

    def _build_compression_rows(self, buckets: CompressionBuckets) -> List[List[str]]:
        """Build compressed component table row"""
        rows = []
        order = ['messages', 'variables', 'runtime_state', 'skillkit_state', 'context_manager_state']

        for name in order:
            if name not in buckets.components:
                continue

            comp = buckets.components[name]
            rows.append([
                name,
                f"{comp.original_bytes / 1000:.2f}",
                f"{comp.compressed_bytes / 1000:.2f}",
                f"{comp.compression_ratio:.1%}",
                f"{comp.space_saved_ratio:.1%}",
                comp.compressibility,
            ])

        return rows


class JSONFormatter:
    """JSON formatted output"""

    def __init__(self, profile: SnapshotProfile):
        self.profile = profile

    def format(self) -> Dict:
        """Generate JSON output"""
        return dataclass_to_dict(self.profile)
