import time
import uuid
from dataclasses import dataclass, asdict
from typing import Dict, List, Any


@dataclass
class ContextSnapshot:
    """Context Snapshot - Saves runtime data at execution time"""

    snapshot_id: str
    frame_id: str
    timestamp: float
    schema_version: str = "2.0"  # Upgrade version number to support context_manager_state
    variables: Dict[str, Any] = None
    messages: List[Dict] = None
    runtime_state: Dict = None
    skillkit_state: Dict = None
    context_manager_state: Dict = None  # Added: Save the complete bucket structure

    def __post_init__(self):
        if self.variables is None:
            self.variables = {}
        if self.messages is None:
            self.messages = []
        if self.runtime_state is None:
            self.runtime_state = {}
        if self.skillkit_state is None:
            self.skillkit_state = {}
        if self.context_manager_state is None:
            self.context_manager_state = {}

    @classmethod
    def create_snapshot(
        cls,
        frame_id: str,
        variables: Dict = None,
        messages: List = None,
        runtime_state: Dict = None,
        skillkit_state: Dict = None,
        context_manager_state: Dict = None,
    ) -> "ContextSnapshot":
        """Create Snapshot"""
        return cls(
            snapshot_id=str(uuid.uuid4()),
            frame_id=frame_id,
            timestamp=time.time(),
            variables=variables or {},
            messages=messages or [],
            runtime_state=runtime_state or {},
            skillkit_state=skillkit_state or {},
            context_manager_state=context_manager_state or {},
        )

    def encode(self) -> Dict:
        """Encode as dictionary format for serialization"""
        return asdict(self)

    @classmethod
    def decode(cls, data: Dict) -> "ContextSnapshot":
        """Create a snapshot from dictionary decoding"""
        return cls(**data)

    def get_variable(self, name: str, default_value=None):
        """Get variable value"""
        return self.variables.get(name, default_value)

    def set_variable(self, name: str, value: Any):
        """Set variable value"""
        self.variables[name] = value

    def update_variables(self, new_variables: Dict[str, Any]):
        """Batch update variables"""
        self.variables.update(new_variables)

    def get_message_count(self) -> int:
        """Get message count"""
        return len(self.messages)

    def add_message(self, message: Dict):
        """Add message"""
        self.messages.append(message)

    def get_size_info(self) -> Dict[str, int]:
        """Get snapshot size information"""
        import json

        encoded = self.encode()
        return {
            "variables_count": len(self.variables),
            "messages_count": len(self.messages),
            "total_size_bytes": len(json.dumps(encoded, ensure_ascii=False)),
        }

    def profile(
        self,
        format: str = 'markdown',
        title: str = None,
        options: Dict = None
    ):
        """Visual analysis report for generating snapshots

        Args:
            format: Output format, 'markdown' or 'json'
            title: Custom title (used only for markdown)
            options: Configuration options dictionary

        Returns:
            str (markdown) or Dict (json)

        Examples:
            # Basic usage
            profile_md = snapshot.profile()
            print(profile_md)

                    # JSON output
            profile_json = snapshot.profile(format='json')

                    # Custom configuration
            profile = snapshot.profile(
                format='markdown',
                title='Step 5: After Processing',
                options={
                    'size_thresholds': {
                        'message_bytes': [1000, 10000],
                        'variable_bytes': [1000, 10000]
                    }
                }
            )
        """
        from .context_snapshot_profile import (
            SnapshotProfileAnalyzer,
            ProfileOptions,
            MarkdownFormatter,
            JSONFormatter
        )

        # Parse options
        if options is None:
            profile_options = ProfileOptions()
        else:
            profile_options = ProfileOptions(**options)

        # Analyze Snapshot
        analyzer = SnapshotProfileAnalyzer(self, profile_options)
        snapshot_profile = analyzer.analyze()

        # Formatted output
        if format == 'json':
            formatter = JSONFormatter(snapshot_profile)
            return formatter.format()
        else:  # markdown
            formatter = MarkdownFormatter(snapshot_profile, title=title, options=profile_options)
            return formatter.format()
