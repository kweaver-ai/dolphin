# Dolphin Language 多模态支持设计文档

| 属性 | 值 |
|------|-----|
| 版本 | v0.3 (Draft) |
| 状态 | 设计完成，待实施 (Design Complete, Pending Implementation) |
| 作者 | - |
| 创建日期 | 2024-12-24 |
| 最后更新 | 2025-12-29 |

> **📋 实施状态**
> 
> | 模块 | 状态 | 说明 |
> |------|------|------|
> | `SingleMessage` 类型扩展 | ✅ 已完成 | `content` 已改为 `Union[str, List[Dict]]`，支持多模态内容 |
> | Token 估算适配 | ✅ 已完成 | 增加了图片 Token 估算逻辑 (`ImageTokenConfig`) |
> | 消息压缩适配 | ✅ 已完成 | 压缩策略已支持多模态消息处理 |
> | LLM 客户端适配 | ✅ 已完成 | 日志预览使用 `get_content_preview()` 处理多模态 |
> | 模型能力校验 | ✅ 已完成 | `MultimodalValidator` 和异常类已实现 |
> | 配置扩展 | ⏳ 待实施 | `LLMConfig` 多模态字段 (可选) |
> | **CLI 多模态输入** | ✅ 已完成 | 剪贴板粘贴 `@paste`、文件 `@image:`、URL `@url:`，**支持 Ctrl+V 自动检测剪贴板图片** |
>
> **📚 相关文档**：
> - [模块重构设计](../architecture/module_restructure_design.md) - 了解新的模块结构

## 1. 背景 (Background)

随着大语言模型（LLM）能力的演进，多模态（Multimodal）交互已成为智能 Agent 的关键能力之一。GPT-4o, Claude 3.5 Sonnet, Gemini Pro Vision 等前沿模型均具备极强的视觉理解能力。

目前 Dolphin Language 系统中的 `SingleMessage` 和相关处理链路主要设计为纯文本（`str`）处理。为了使 Dolphin 能够支持“看图说话”、UI 自动化识别、文档图像分析等场景，必须在内核层面引入对非文本内容（主要是图片）的支持。

本设计旨在以最小的侵入性改动，赋予系统处理混合模态（文本+图片）的能力，同时保持现有的 API 简洁性和稳定性。

## 2. 设计思路与折衷 (Design Strategy & Trade-offs)

### 2.1 方案选择

#### 2.1.1 主流方案调研

在设计多模态支持之前，我们对主流 LLM 供应商的多模态 API 格式进行了调研：

| 供应商 | API 格式 | 示例结构 | 特点 |
|--------|----------|----------|------|
| **OpenAI** (GPT-4o) | `content: Union[str, List[ContentBlock]]` | `[{type: "text", text: "..."}, {type: "image_url", image_url: {url: "..."}}]` | **事实标准**，兼容性最好，大多数第三方 SDK 均遵循此格式 |
| **Anthropic** (Claude) | `content: List[ContentBlock]` | `[{type: "text", text: "..."}, {type: "image", source: {type: "base64", ...}}]` | 结构类似，但图片使用 `source` 字段而非 `image_url`，需适配层转换 |
| **Google** (Gemini) | `contents: List[Part]` | `[{text: "..."}, {inline_data: {mime_type: "...", data: "..."}}]` | 概念相似但字段命名不同，需适配层转换 |

**调研结论**：
- OpenAI 的 `Union[str, List[ContentBlock]]` 格式已成为行业事实标准
- 大多数 LLM 代理服务（如 Azure OpenAI、各类国产模型网关）均兼容此格式
- Anthropic 和 Google 的格式虽有差异，但可通过轻量级适配层转换

**设计决策**：采用 **OpenAI 格式作为内部表示的基准格式**，在驱动层按需转换为其他供应商格式。

#### 2.1.2 技术路线对比

在引入多模态数据结构时，主要有以下几种技术路线：

*   **方案 A：特殊 Token 嵌入 (Special Tokens)**
    *   **描述**：在 `content` 字符串中嵌入特定标记，如 `User: 请看图 <image src="...">`。在发送给 LLM 前，通过中间件解析并替换。
    *   **优点**：保持 `content` 为 `str` 类型，对现有系统改动极小。
    *   **缺点**：解析逻辑脆弱；不同模型的 API对此类标记的支持不统一；难以精确计算 Token。

*   **方案 B：独立附件字段 (Attachment Field)**
    *   **描述**：在 `SingleMessage` 中增加 `attachments` 字段，专门存放图片/文件。
    *   **优点**：结构清晰，文本与媒体分离。
    *   **缺点**：破坏了 LLM 输入的标准语义（OpenAI 等标准 API 通常要求文本和图片在 `content` 中混合排列以保持语序）；增加了消息序列化和重组的复杂度。

*   **方案 C：结构化内容 (Structured Content / OpenAI Style)**
    *   **描述**：将 `content` 字段的类型定义扩展为 `Union[str, List[ContentBlock]]`。遵循 OpenAI Chat Completion API 的标准格式。
    *   **优点**：符合行业事实标准；能够精确表达文本和图片在对话流中的相对位置；直接映射到主流 LLM API 入参。
    *   **缺点**：所有操作 `content` 的下游组件（日志、压缩、存储、Token 计算）都需要适配 `List` 类型，改动面较广。

### 2.2 决策与折衷

**决策**：采用 **方案 C（结构化内容）**。

**折衷分析**：
虽然方案 C 需要修改 `common.py` 中的核心类型定义以及 `ContextEngineer` 中的处理逻辑，但它提供了最好的模型兼容性和最清晰的语义表达。为了缓解改动风险，我们采取**由内向外**的兼容策略：
1.  **内核层兼容**：`SingleMessage` 内部自动处理 `str` 到 `List` 的归一化，对外尽可能保持兼容。
2.  **工具层适配**：仅修改必要的压缩和 Token 计算组件，对于不涉及内容操作的组件保持透明。

## 3. 总体架构 (Architecture)

### 3.1 核心数据流变化

1.  **输入端**：Agent/Skill 构造消息时，可以传入 `str`（纯文本）或 `List[Dict]`（多模态列表）。
2.  **存储层**：`Messages` 容器在内存中保持该结构；序列化（Session 存储）时直接 dump 为 JSON 结构。
3.  **中间件**：`ContextEngineer` / `MessageCompressor` 在计算 Token 和截断时，能够识别 List 结构，对图片计算固定 Token 开销，对文本计算字符 Token。
4.  **IO 层**：`LLMClient` 在调用模型 API 时，直接透传 List 结构给支持多模态的驱动（如 OpenAI 驱动）；对于不支持的驱动，可选择降级（仅提取文本）或报错。

## 4. 模块详细设计 (Module Design)

> **📁 路径更新说明**：根据模块重构（参见 `docs/design/architecture/module_restructure_design.md`），原 `DolphinLanguageSDK` 已迁移至 `dolphin.core`/`dolphin.lib`/`dolphin.sdk` 结构。

### 4.1 dolphin.core.common

#### 4.1.0 ContentBlock 规范（必须遵循）

本设计采用 OpenAI 风格的 `content` 结构作为内部基准表示，但为了避免“`List[Dict]` 任意扩展导致互操作不可控”，需要在 SDK 内部**明确约束** ContentBlock 的 schema。

**类型定义**：
- `MessageContent = Union[str, List[ContentBlock]]`
- `ContentBlock` 为 `Dict`，且必须包含字段 `type`

**支持的 ContentBlock 类型（v0）**：

1) `text`
```json
{"type": "text", "text": "string"}
```
- 必填：`text: str`

2) `image_url`
```json
{"type": "image_url", "image_url": {"url": "https://example.com/a.png", "detail": "auto"}}
```
- 必填：`image_url.url: str`
- 可选：`image_url.detail: "auto" | "low" | "high"`（缺省按 `"auto"`）

**约束**：
- `List[ContentBlock]` 不允许为空列表。
- `type` 非上述枚举值：在进入压缩/发送前应抛出 `UnsupportedContentBlockTypeError`（见 4.5.3 扩展）。
- `image_url.image_url.url` 建议仅允许 `https://`（安全策略见 6.7）。
- Base64（例如 `data:image/png;base64,...`）属于可选扩展：默认不推荐且应限制大小（见 6.5、4.5.2）。

**推荐 helper（可选）**：
```python
def text_block(text: str) -> Dict:
    return {"type": "text", "text": text}

def image_url_block(url: str, detail: str = "auto") -> Dict:
    return {"type": "image_url", "image_url": {"url": url, "detail": detail}}
```

**`SingleMessage` 类变更**：

```python
class SingleMessage:
    def __init__(self, role, content: Union[str, List[Dict]], ...):
        # ...
    
    # 新增长度计算逻辑
    def length(self):
        if isinstance(self.content, list):
            # 仅计算文本部分的长度用于基础统计
            return sum(len(x['text']) for x in self.content if x['type'] == 'text')
        return len(self.content)
```

**`Messages` 类变更**：
*   所有 `add/insert/append` 方法需支持 `List` 类型的 user input。
*   `append`（追加）操作需要做特殊处理：如果原消息是 str，新消息是 list，涉及类型升级；如果都是 list，则是列表合并。

#### 4.1.1 `append_content` 的语义边界（必须明确）

为避免“追加导致语义漂移”，`append_content` 只应被用于以下场景：
- **流式输出拼接**：模型/工具持续产出文本增量（delta），需要追加到同一条消息中。
- **同角色同语义的续写**：同一 role 的同一段内容被分段生产（例如分段生成 prompt）。

**不建议用于**：跨 role 合并、将两段独立语义“硬拼接”成一条消息（这会让压缩、审计、日志追溯变差）。

**追加时的规则建议**：
- 只允许对“同一条 `SingleMessage`”追加；不改变 `role`。
- `str + str`：保持原行为（直接拼接），但建议上层自行控制分隔符（如 `"\n"`）。
- 任何涉及 `list` 的追加：保持 block 结构，不隐式改写 block 顺序。
- `list + str`：追加为一个新的 `text` block（避免破坏原有 block 语义）。

**`append` 操作的详细语义**：

```python
def append_content(self, new_content: Union[str, List[Dict]]):
    """向现有消息追加内容"""
    current = self.content

    # Case 1: str + str -> str
    if isinstance(current, str) and isinstance(new_content, str):
        self.content = current + new_content

    # Case 2: str + list -> list (类型升级)
    elif isinstance(current, str) and isinstance(new_content, list):
        self.content = [{"type": "text", "text": current}] + new_content

    # Case 3: list + str -> list (追加文本块)
    elif isinstance(current, list) and isinstance(new_content, str):
        self.content = current + [{"type": "text", "text": new_content}]

    # Case 4: list + list -> list (合并)
    elif isinstance(current, list) and isinstance(new_content, list):
        self.content = current + new_content
```

**归一化辅助方法**：

```python
def normalize_content(content: Union[str, List[Dict]]) -> List[Dict]:
    """将任意格式的 content 归一化为 List[Dict]"""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content

def extract_text(content: Union[str, List[Dict]]) -> str:
    """提取纯文本内容（用于日志、降级等场景）"""
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content if block.get("type") == "text")
```

### 4.2 dolphin.core.message / dolphin.core.context_engineer

**Token 估算 (`estimate_tokens_for_message`)**：
需要引入一种混合估算机制：
*   **文本块**：沿用 `CHINESE_CHAR_TO_TOKEN_RATIO` 进行估算。
*   **图片块**：采用**基于尺寸的精确计算**，与业界主流 LLM 厂商对齐。

#### 4.2.1 业界图片 Token 计算方法参考

| 厂商 | 计算方法 | 详情 |
|------|----------|------|
| **OpenAI (GPT-4o)** | `85 + 170 × tiles` | 基础 85 token + 每个 512×512 Tile 170 token；`low` 模式固定 85 token |
| **Anthropic (Claude 3)** | `(width × height) / 750` | 按像素面积计算；提供免费的 Token Counting API |
| **Google (Gemini 2.0+)** | `258 × tiles` | ≤384px 固定 258 token；>384px 按 768×768 Tile 计算，每 Tile 258 token |

#### 4.2.2 图片 Token 估算配置（简化版）

> **设计原则**：Token 估算仅用于压缩/裁剪的预判断，服务端会返回真实 usage。因此采用**单一通用算法**，避免过度工程。

```python
import math
from dataclasses import dataclass, field
from typing import Dict, Optional

@dataclass
class ImageTokenConfig:
    """简化的图片 Token 估算配置
    
    设计决策：
    - 采用 OpenAI 风格的 tile-based 算法作为通用估算（业界事实标准）
    - 不区分厂商，误差 ±20% 对压缩决策完全可接受
    - 服务端返回的 usage 才是计费和限制的真实依据
    """
    
    # Tile-based 估算参数（OpenAI 风格，通用适用）
    base_tokens: int = 85           # 基础开销
    tokens_per_tile: int = 170      # 每个 512×512 tile 的 token 数
    tile_size: int = 512            # tile 边长
    
    # 固定值后备（未知尺寸时使用）
    fallback_tokens: Dict[str, int] = field(default_factory=lambda: {
        "low": 85,      # 低分辨率模式
        "auto": 600,    # 默认保守估算
        "high": 1500,   # 高分辨率保守估算
    })
    
    def estimate_tokens(
        self, 
        width: Optional[int] = None, 
        height: Optional[int] = None,
        detail: str = "auto"
    ) -> int:
        """
        估算图片的 Token 数量
        
        Args:
            width: 图片宽度 (像素)，可选
            height: 图片高度 (像素)，可选
            detail: 分辨率级别 ("low", "auto", "high")
            
        Returns:
            估算的 Token 数量
        """
        # low 模式固定返回基础开销
        if detail == "low":
            return self.base_tokens
        
        # 未知尺寸时使用后备值
        if width is None or height is None:
            return self.fallback_tokens.get(detail, self.fallback_tokens["auto"])
        
        # Tile-based 计算：base + tiles × tokens_per_tile
        tiles_x = math.ceil(width / self.tile_size)
        tiles_y = math.ceil(height / self.tile_size)
        return self.base_tokens + self.tokens_per_tile * tiles_x * tiles_y
```

#### 4.2.3 使用示例

```python
config = ImageTokenConfig()

# 已知尺寸的估算
tokens = config.estimate_tokens(width=1024, height=768)
# 85 + 170 × 2 × 2 = 765 tokens

# 低分辨率模式
tokens = config.estimate_tokens(width=1024, height=768, detail="low")
# 固定 85 tokens

# 未知尺寸时使用后备值
tokens = config.estimate_tokens(detail="high")
# 返回 1500 tokens (保守估算)
```

> **为什么不区分厂商？**
> 
> | 考量 | 说明 |
> |------|------|
> | **目的不同** | 估算用于预判断，非精确计费 |
> | **服务端可信** | 真实 token 消耗由服务端 `usage` 字段返回 |
> | **维护成本** | 厂商公式变更无需同步代码 |
> | **误差可接受** | ±20% 误差对压缩决策无实质影响 |

**压缩策略适配**：
*   `TruncationStrategy`（截断策略）：
    *   旧逻辑：直接切片字符串 `content[:limit]`。
    *   新逻辑：
        *   **允许仅对 `text` block 截断**（仍保持 List 结构不变）；不对 `image_url` block 做“截断”。
        *   当需要缩减上下文时，优先按 `MultimodalCompressionMode` 执行“降级/裁剪”，再对文本部分执行常规截断（若启用）。

**多模态消息压缩降级策略**（可配置）：

```python
class MultimodalCompressionMode(Enum):
    ATOMIC = "atomic"           # 整条保留或整条丢弃（默认）
    TEXT_ONLY = "text_only"     # 超限时仅保留文本部分，丢弃图片
    LATEST_IMAGE = "latest_image"  # 仅保留最新的 N 张图片

class MultimodalCompressionConfig:
    mode: MultimodalCompressionMode = MultimodalCompressionMode.ATOMIC
    max_images_to_keep: int = 3  # LATEST_IMAGE 模式下保留的图片数
    allow_truncate_text_blocks: bool = True  # 是否允许截断 text block
```

**降级处理流程**：
```
多模态消息超限
  → 检查 compression_mode
    → ATOMIC: 整条丢弃
    → TEXT_ONLY: 调用 extract_text() 降级为纯文本消息（随后允许按旧逻辑截断）
    → LATEST_IMAGE: 保留文本 + 最后 N 张图片（文本部分可选截断）
```

**text block 截断建议（实现提示）**：
- 只对 `{"type":"text"}` 的 `text` 字段进行截断；截断后仍保持原 block 为合法 JSON。
- 截断策略建议从“最早的文本”开始裁剪，或仅裁剪“最老消息中的文本”；避免破坏最近轮对话。

### 4.3 dolphin.core.llm.llm_client

**适配层**：
*   `_basic_mf_chat_stream`：
    *   入参透传：无需特殊修改，直接将 `messages` 传递给 `payload`。
    *   日志记录 (`messages_preview`)：需要修改，遇到 List 类型内容时，打印 `[Multimodal: N images]` 而非直接 `len()` 报错。
    *   Token Usage 更新：确保 `update_usage` 能正确处理服务端返回的 usage 字段（通常服务端计算是准确的）。
    *   **脱敏要求**：日志中不得输出 Base64 原文，不建议输出完整图片 URL（避免泄露敏感路径/临时签名）。

**日志适配示例**：
```python
def get_content_preview(content: Union[str, List[Dict]]) -> Dict:
    """生成用于日志的内容预览"""
    if isinstance(content, str):
        return {"type": "text", "length": len(content)}

    image_count = sum(1 for block in content if block.get("type") == "image_url")
    text_length = sum(len(block.get("text", "")) for block in content if block.get("type") == "text")
    return {
        "type": "multimodal",
        "text_length": text_length,
        "image_count": image_count
    }
```

### 4.4 驱动层适配 (Driver Adaptation)

系统当前支持两种 API 类型：`TypeAPI.OPENAI` 和 `TypeAPI.AISHU_MODEL_FACTORY`。多模态支持需要在各驱动层进行适配。

**4.4.1 驱动层架构**

```
LLMClient._chat_stream
  │
  ├── TypeAPI.OPENAI → LLMOpenai.chat()
  │                       └── 直接透传 content（已兼容多模态格式）
  │
  └── TypeAPI.AISHU_MODEL_FACTORY → LLMModelFactory.chat()
                                      └── 需验证模型工厂 API 是否支持多模态
```

**4.4.2 OpenAI 驱动 (`LLMOpenai`)**

OpenAI 格式是本设计的基准格式，理论上无需特殊适配：
```python
# OpenAI 多模态格式（本设计直接采用）
{
    "role": "user",
    "content": [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "https://..."}}
    ]
}
```

**4.4.3 模型工厂驱动 (`LLMModelFactory`)**

需要确认模型工厂 API 的多模态支持情况：
*   **如果支持 OpenAI 格式**：直接透传，无需修改。
*   **如果不支持**：需要在驱动层添加格式转换逻辑或抛出 `MultimodalNotSupportedError`。

**4.4.4 Claude 格式兼容（可选扩展）**

如果未来需要支持 Claude API，需要注意其格式差异：
```python
# Claude 多模态格式（与 OpenAI 不同）
{
    "role": "user",
    "content": [
        {"type": "text", "text": "What's in this image?"},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "<base64_data>"
            }
        }
    ]
}
```

**建议**：在 `LLMClient` 层引入 `MultimodalAdapter` 接口，各驱动实现自己的格式转换。

### 4.5 模型能力校验 (Model Capability Validation)

当前 `LLMInstanceConfig` 缺少多模态能力标识，导致无法在请求前进行校验。

**4.5.1 配置扩展**

在 `LLMConfig` 中新增能力字段：
```python
@dataclass
class LLMConfig:
    # ... 现有字段 ...

    # 多模态能力配置
    supports_vision: bool = False          # 是否支持图片输入
    supports_audio: bool = False           # 是否支持音频输入（预留）
    max_images_per_request: int = 10       # 单次请求最大图片数
    supported_image_formats: List[str] = field(
        default_factory=lambda: ["png", "jpg", "jpeg", "gif", "webp"]
    )
    allowed_image_schemes: List[str] = field(default_factory=lambda: ["https"])
    allowed_image_hosts: Optional[List[str]] = None   # None 表示不启用 allowlist
    allow_data_url: bool = False                      # 是否允许 data:image/...;base64,...
    max_base64_bytes: int = 2 * 1024 * 1024           # 仅在 allow_data_url=True 时生效
```

**4.5.2 运行时校验**

在消息压缩或 LLM 调用前进行校验：
```python
class MultimodalValidator:
    @staticmethod
    def validate(messages: Messages, model_config: LLMInstanceConfig):
        """校验消息是否与模型能力匹配"""
        # 1) 识别是否包含图片
        has_images = any(
            isinstance(msg.content, list) and
            any(block.get("type") == "image_url" for block in msg.content)
            for msg in messages
        )

        if has_images and not model_config.supports_vision:
            raise MultimodalNotSupportedError(
                f"Model '{model_config.model_name}' does not support vision input. "
                f"Please use a vision-capable model like gpt-4o or claude-3-5-sonnet."
            )

        # 2) 校验 schema + 统计图片数量
        image_count = sum(
            sum(1 for block in msg.content if block.get("type") == "image_url")
            for msg in messages
            if isinstance(msg.content, list)
        )

        if image_count > model_config.max_images_per_request:
            raise TooManyImagesError(
                f"Request contains {image_count} images, but model limit is "
                f"{model_config.max_images_per_request}."
            )

        # 3) 校验每个 block（格式、detail、URL/base64、安全策略）
        for msg in messages:
            if not isinstance(msg.content, list):
                continue
            if len(msg.content) == 0:
                raise EmptyMultimodalContentError("Multimodal content list must not be empty.")

            for block in msg.content:
                t = block.get("type")
                if t == "text":
                    if not isinstance(block.get("text"), str):
                        raise InvalidTextBlockError("Text block requires 'text: str'.")
                    continue

                if t == "image_url":
                    image_url = block.get("image_url") or {}
                    url = image_url.get("url")
                    detail = image_url.get("detail", "auto")
                    if detail not in ("auto", "low", "high"):
                        raise InvalidImageDetailError(f"Invalid image detail: {detail}")
                    if not isinstance(url, str) or not url:
                        raise InvalidImageUrlError("image_url block requires non-empty url.")

                    # URL scheme / allowlist / data-url 限制（具体实现可按 urllib.parse）
                    # - https:// 允许
                    # - data:image/...;base64,... 仅在 allow_data_url=True 且大小受限时允许
                    continue

                raise UnsupportedContentBlockTypeError(f"Unsupported content block type: {t}")
```

**4.5.3 异常定义**

```python
class MultimodalError(Exception):
    """多模态相关错误的基类"""
    pass

class MultimodalNotSupportedError(MultimodalError):
    """模型不支持多模态输入"""
    pass

class TooManyImagesError(MultimodalError):
    """图片数量超过模型限制"""
    pass

class UnsupportedImageFormatError(MultimodalError):
    """不支持的图片格式"""
    pass

class UnsupportedContentBlockTypeError(MultimodalError):
    """不支持的 ContentBlock 类型"""
    pass

class EmptyMultimodalContentError(MultimodalError):
    """多模态 content 为空列表"""
    pass

class InvalidTextBlockError(MultimodalError):
    """text block 不合法"""
    pass

class InvalidImageUrlError(MultimodalError):
    """image_url block 的 url 不合法"""
    pass

class InvalidImageDetailError(MultimodalError):
    """image_url block 的 detail 不合法"""
    pass

class ImagePayloadTooLargeError(MultimodalError):
    """Base64 图片 payload 超过限制"""
    pass
```

### 4.6 配置层扩展 (Configuration Extension)

**4.6.1 global.yaml 格式变更**

```yaml
llm:
  models:
    gpt-4o:
      model_name: "gpt-4o"
      temperature: 0.7
      max_tokens: 4096
      # 多模态配置
      supports_vision: true
      max_images_per_request: 20
      supported_image_formats: ["png", "jpg", "jpeg", "gif", "webp"]
      allowed_image_schemes: ["https"]
      allowed_image_hosts: null
      allow_data_url: false
      max_base64_bytes: 2097152

    gpt-4o-mini:
      model_name: "gpt-4o-mini"
      supports_vision: true
      max_images_per_request: 10

    deepseek-v3:
      model_name: "deepseek-v3"
      supports_vision: false  # 明确标注不支持

    claude-3-5-sonnet:
      model_name: "claude-3-5-sonnet-20241022"
      supports_vision: true
      max_images_per_request: 20

# 多模态全局配置
multimodal:
  default_image_tokens: 1000
  compression_mode: "atomic"  # atomic | text_only | latest_image
  max_images_to_keep: 3       # latest_image 模式下保留的图片数
```

**4.6.2 配置解析**

```python
def parse_llm_config(config_dict: dict) -> LLMConfig:
    return LLMConfig(
        # ... 现有字段 ...
        supports_vision=config_dict.get("supports_vision", False),
        max_images_per_request=config_dict.get("max_images_per_request", 10),
        supported_image_formats=config_dict.get(
            "supported_image_formats",
            ["png", "jpg", "jpeg", "gif", "webp"]
        ),
    )
```

## 5. API 设计 (API Design)

### 5.1 构造消息

保持 `add_message` 签名不变，但在文档中明确 `content` 支持的格式。

```python
# 方式 1：传统文本
agent.messages.add_message(role="user", content="Hello")

# 方式 2：多模态 (OpenAI 格式)
agent.messages.add_message(
    role="user", 
    content=[
        {"type": "text", "text": "分析这张图片"},
        {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}}
    ]
)
```

### 5.2 内部工具方法

在 `common.py` 或 `utils` 中提供构建 helper（可选）：

```python
def build_image_message(text: str, image_urls: List[str]) -> List[Dict]:
    content = [{"type": "text", "text": text}]
    for url in image_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})
    return content
```

## 6. 边界考虑 (Boundary Consideration)

1.  **不支持多模态的模型**：
    *   如果用户向 DeepSeek-V2（纯文本模型）发送图片消息，API 通常会返回 400 Bad Request。
    *   **处理**：通过 4.5 节的 `MultimodalValidator` 在请求前进行校验，抛出明确的 `MultimodalNotSupportedError`，避免无意义的 API 调用。

2.  **Context 爆满**：
    *   图片通常占用大量 Token（特别是高分辨率模式）。
    *   **处理**：Context Engineer 的 Token 估算必须偏保守。如果单张图超过窗口，应在请求前抛出明确的 `ContextOverflowError`。

3.  **序列化兼容性**：
    *   `to_dict` 和 `json.dump` 原生支持 List/Dict 嵌套，因此序列化通常没问题。
    *   需要检查是否有代码假设 `content` 必定是 `str` 并尝试调用 `.startswith()`, `.replace()` 等方法。这部分是重构的高风险区，需要全量搜索代码库中的 `message.content` 引用进行排查。

4.  **图片 URL 有效性**：
    *   SDK 不负责验证 URL 可达性，由模型端验证。

5.  **Base64 图片**：
    *   虽然 OpenAI 支持 Base64，但由于 Base64 字符串极大，极易撑爆日志和调试终端。
    *   **建议**：设计上推荐传递 URL。如果必须支持 Base64，建议在 `__str__` 和日志中对 Base64 字符串进行脱敏或截断显示。
    *   **强制限制**：如支持 Base64，必须增加 `max_base64_bytes`（或等价配置）上限；超过上限直接拒绝请求并抛出 `ImagePayloadTooLargeError`（见 4.5.3 扩展）。

6.  **多模态输出**：
    *   部分模型（如 GPT-4o）支持生成图片/音频输出。
    *   **当前范围**：本设计仅覆盖多模态**输入**，输出侧暂不支持。
    *   **后续扩展**：如需支持，需在响应解析层增加对 `content` 为 List 的处理。

7.  **URL 图片的安全边界（必须定义）**：
    *   直接透传用户提供的图片 URL，可能引入 SSRF/内网探测/合规风险。
    *   **建议默认策略**：
        - 仅允许 `https://`；
        - 可选：配置域名 allowlist（如 `allowed_image_hosts`）；
        - 更推荐：走自家图片代理/转存服务，将外部 URL 转换为受控的临时 URL，再发给模型。
    *   日志中不应输出完整 URL（见 4.3 的 preview 和 6.5 的脱敏建议）。

## 7. 测试计划 (Test Plan)

### 7.1 单元测试

| 测试模块 | 测试内容 | 优先级 |
|----------|----------|--------|
| `SingleMessage` | `content` 类型为 `str` 和 `List` 的构造和序列化 | P0 |
| `SingleMessage.length()` | 纯文本和混合内容的长度计算 | P0 |
| `Messages.append_content()` | 四种类型组合的追加逻辑 | P0 |
| `normalize_content()` | `str` → `List` 归一化 | P1 |
| `extract_text()` | 从多模态消息提取文本 | P1 |
| `ImageTokenConfig` | 模型特定 Token 查询 | P1 |
| `MultimodalValidator` | 能力校验和异常抛出 | P0 |
| `get_content_preview()` | 日志预览生成 | P2 |

### 7.2 集成测试

| 测试场景 | 验证内容 | 优先级 |
|----------|----------|--------|
| OpenAI GPT-4o 图片理解 | 端到端多模态调用成功 | P0 |
| 不支持多模态的模型 | `MultimodalNotSupportedError` 正确抛出 | P0 |
| 超过图片数量限制 | `TooManyImagesError` 正确抛出 | P1 |
| Context 压缩 | 多模态消息的滑动窗口行为 | P0 |
| Token 估算准确性 | 估算值 vs 实际消耗对比（误差 < 20%） | P1 |
| 会话序列化/反序列化 | 多模态消息的 JSON 持久化 | P1 |

### 7.3 回归测试

确保现有纯文本场景不受影响：
- 所有现有单元测试通过
- 纯文本消息的 Token 计算、压缩、调用行为不变

## 8. 高风险代码清单 (High-Risk Code Checklist)

以下代码位置假设 `content` 为 `str` 类型，需要逐一排查和适配：

### 8.1 已识别风险点

| 文件路径 | 行号 | 风险描述 | 处理方式 |
|----------|------|----------|----------|
| `src/dolphin/core/llm/llm_client.py` | 128-136 | 日志/preview 中假设 `content` 为 `str` | 使用 `get_content_preview()` 并对 URL/文本做脱敏 |
| `src/dolphin/core/context_engineer/` | - | Token 估算/窗口裁剪假设 `content` 为 `str` | 增加 List 分支处理（文本+图片） |
| `src/dolphin/core/message/compressor.py` | - | 截断逻辑可能直接切片字符串 | 仅截断 `text` block 或按模式降级 |
| `src/dolphin/core/common/enums.py` | 35-164 | `SingleMessage` 类 `content` 为 `str`，`__str__` / 序列化 / 追加逻辑假设 `content` 为 `str` | 扩展类型为 `Union[str, List[Dict]]`，增加 Base64/URL 脱敏与 normalize/extract_text |

### 8.2 排查命令

```bash
# 搜索所有对 message.content 的字符串操作（使用新路径）
rg -n "\.content\." src/dolphin/
rg -n "content\[" src/dolphin/
rg -n "len\\(.*content" src/dolphin/
rg -n "content\\.(startswith|replace|split)" src/dolphin/
rg -n "isinstance\\(.*content,\\s*list\\)" src/dolphin/
```

### 8.3 排查清单

- [ ] `dolphin/core/common/enums.py` - Messages 和 SingleMessage 类
- [ ] `dolphin/core/llm/llm_client.py` - LLM 调用和日志
- [ ] `dolphin/core/message/compressor.py` - 消息压缩
- [ ] `dolphin/core/context_engineer/` - 上下文工程模块
- [ ] `dolphin/lib/memory/` - 会话存储和恢复
- [ ] 所有 `__str__` 和 `__repr__` 方法

## 9. 发布策略 (Release Strategy)

### 9.1 灰度发布

建议采用 Feature Flag 控制多模态功能的启用：

```python
class FeatureFlags:
    MULTIMODAL_ENABLED: bool = False  # 默认关闭

# 使用示例
if FeatureFlags.MULTIMODAL_ENABLED:
    MultimodalValidator.validate(messages, model_config)
```

**灰度阶段**：
1. **Alpha**：内部测试，仅限开发环境
2. **Beta**：开放给部分用户，收集反馈
3. **GA**：全量开放，移除 Feature Flag

### 9.2 回滚策略

**触发条件**：
- 多模态请求成功率 < 95%
- Token 估算误差 > 50% 导致 Context Overflow
- 序列化/反序列化失败

**回滚步骤**：
1. 将 `FeatureFlags.MULTIMODAL_ENABLED` 设为 `False`
2. 多模态消息自动降级为纯文本（调用 `extract_text()`）
3. 记录降级日志用于后续分析

**回滚影响**：
- 用户发送的图片将被忽略，仅保留文本部分
- 不会导致请求失败，但会丢失图片信息

### 9.3 版本兼容性

| 版本 | 行为 |
|------|------|
| v1.x (当前) | 仅支持纯文本 `content: str` |
| v2.0 (本次) | 支持 `content: Union[str, List]`，向后兼容 |
| v2.1+ | 可选：移除 `str` 类型，统一为 `List` |

## 10. 兼容性、非侵入性和熵减考虑 (Compatibility, Non-Invasiveness & Entropy Reduction)

本节阐述多模态支持设计中遵循的三个核心原则：**向后兼容**、**最小侵入**、**系统熵减**。这些原则贯穿整个设计过程，确保新能力的引入不会破坏现有系统的稳定性。

### 10.1 向后兼容原则 (Backward Compatibility)

#### 10.1.1 类型兼容

`content` 字段的类型扩展采用 **Union 类型**而非类型替换：

```python
# 旧类型（仍然有效）
content: str = "Hello"

# 新类型（扩展支持）
content: Union[str, List[Dict]] = [{"type": "text", "text": "Hello"}]
```

**设计保证**：
- ✅ 所有现有的 `content: str` 代码无需修改
- ✅ `str` 类型自动参与处理，无需显式转换
- ✅ 序列化/反序列化自动识别两种格式

#### 10.1.2 API 签名兼容

所有公开 API 保持签名不变：

| API | 旧签名 | 新行为 |
|-----|--------|--------|
| `Messages.add_message()` | `content: str` | 隐式扩展为 `Union[str, List]`，无破坏性变更 |
| `SingleMessage.length()` | 返回 `len(content)` | 对 `List` 类型智能计算文本长度 |
| `to_dict()` / `to_json()` | 输出 `{"content": "..."}` | 自动适配两种格式输出 |

#### 10.1.3 配置兼容

新增配置项均提供**合理默认值**，确保零配置升级：

```yaml
# 默认配置（用户无需修改即可使用）
multimodal:
  default_image_tokens: 1000      # 保守估算
  compression_mode: "atomic"      # 最安全的策略
```

### 10.2 最小侵入原则 (Minimal Invasiveness)

#### 10.2.1 改动范围控制

本设计严格控制代码改动范围，遵循**最小触及原则**：

| 改动层级 | 影响模块 | 改动性质 |
|----------|----------|----------|
| **核心层** | `SingleMessage`, `Messages` | 类型扩展 + helper 方法 |
| **处理层** | `compressor.py`, `context_engineer` | 增加 `isinstance` 分支 |
| **IO 层** | `llm_client.py` | 日志适配 + 透传 |
| **驱动层** | `LLMOpenai`, `LLMModelFactory` | 无变更（已兼容） |

**不改动的模块**（透明传递）：
- Session 存储/加载
- 消息路由
- Hook 系统
- 大部分 Skill 实现

#### 10.2.2 渐进式改动策略

采用 **Feature Flag + 渐进增强** 模式：

```python
# Phase 1: 类型支持（静默兼容）
# - content 支持 List 类型
# - 不触发任何新行为
# - 所有测试绿色

# Phase 2: 能力校验（可选开启）
if FeatureFlags.MULTIMODAL_VALIDATION:
    MultimodalValidator.validate(messages, config)

# Phase 3: 全量开放（移除 flag）
```

#### 10.2.3 回退路径设计

每个改动点都设计了**安全回退路径**：

| 场景 | 回退行为 |
|------|----------|
| 图片发送到不支持的模型 | 自动调用 `extract_text()` 降级为纯文本 |
| Token 估算失败 | 使用保守的固定值 `1000` |
| 压缩策略无法处理 | 整条消息保留（`ATOMIC` 模式）|
| 驱动层格式不兼容 | 抛出明确异常，不静默失败 |

### 10.3 系统熵减原则 (Entropy Reduction)

> **熵减**：在引入新能力的同时，力求减少而非增加系统复杂度。

#### 10.3.1 统一数据格式

采用 **OpenAI 格式作为内部基准**，避免多格式共存带来的熵增：

```
输入端            内部表示              输出端
────────         ────────────         ────────
OpenAI   ───┐                    ┌──→ OpenAI (透传)
Claude   ───┼──→ OpenAI 格式 ────┼──→ Claude (适配转换)
Gemini   ───┘    (基准格式)      └──→ Gemini (适配转换)
```

**熵减效果**：
- 中间层只处理一种格式
- 格式转换集中在驱动层的 Adapter
- 新增供应商只需实现一个 Adapter

#### 10.3.2 复用现有抽象

多模态支持**复用**而非新建抽象层：

| 现有抽象 | 多模态复用方式 |
|----------|----------------|
| `CompressionStrategy` | 新增 `MultimodalCompressionMode`，不改变策略接口 |
| `TokenEstimator` | 扩展 `estimate_tokens()`，不新建类 |
| `LLMDriver` | 复用驱动接口，适配层内置 |
| `Messages` 容器 | 复用迭代器、序列化，仅扩展元素类型 |

#### 10.3.3 减少隐式行为

明确行为边界，减少"魔法"代码：

```python
# ❌ 隐式行为（增加熵）
def append_content(self, new_content):
    # 自动猜测如何合并，行为不可预测
    self.content = magic_merge(self.content, new_content)

# ✅ 显式行为（减少熵）
def append_content(self, new_content: Union[str, List[Dict]]):
    """
    追加规则（明确定义）：
    - str + str → str
    - str + list → list (类型升级)
    - list + str → list (追加 text block)
    - list + list → list (合并)
    """
    # 实现对应四种 case
```

#### 10.3.4 错误信息清晰化

提供**可操作的错误信息**，降低调试成本：

```python
# ❌ 模糊错误
raise ValueError("Invalid content")

# ✅ 清晰错误
raise MultimodalNotSupportedError(
    f"Model '{model_config.model_name}' does not support vision input. "
    f"Please use a vision-capable model like gpt-4o or claude-3-5-sonnet."
)
```

### 10.4 设计决策检查清单

在评审每个设计决策时，使用以下检查清单：

| 检查项 | 问题 | 预期答案 |
|--------|------|----------|
| **兼容性** | 现有代码是否需要修改？ | 否（除非使用新特性） |
| **侵入性** | 影响多少个模块？ | 尽可能少，边界清晰 |
| **熵减** | 是否增加了新的抽象层/概念？ | 优先复用现有抽象 |
| **可回退** | 出问题时能否安全降级？ | 有明确的回退路径 |
| **可测试** | 能否单独测试此变更？ | 可独立编写单元测试 |

### 10.5 总结

| 原则 | 核心要点 | 验证方式 |
|------|----------|----------|
| **向后兼容** | `str` 仍然有效，API 签名不变 | 所有现有测试通过 |
| **最小侵入** | 改动集中在核心层，多数模块透明 | 代码影响面分析 |
| **熵减** | 统一格式、复用抽象、显式行为 | 架构复杂度不增加 |

通过遵循这三个原则，多模态支持的引入将是**渐进的、可控的、可回退的**，最大程度降低对现有系统的风险。

## 11. CLI 多模态输入设计 (CLI Multimodal Input Design)

本节描述如何在 Dolphin CLI 中支持用户输入图片，采用**剪贴板粘贴**作为主要交互方式。

### 10.1 设计目标

1. **直观的用户体验**：用户无需记忆复杂的命令或路径，直接"粘贴"即可
2. **与现有 CLI 无缝集成**：复用 `prompt_toolkit` 的输入基础设施
3. **多种输入来源**：支持剪贴板、本地文件路径、URL 三种方式
4. **安全可控**：限制图片大小、格式，防止恶意输入

### 10.2 输入语法设计

#### 10.2.1 主要方式：剪贴板粘贴

```
You> @paste 请描述这张图片
```

- `@paste` 指令告诉 CLI 从系统剪贴板读取图片
- 指令位置可以在消息的任意位置
- 支持多次 `@paste` 插入多张图片

**用户操作流程**：
1. 用户截图或复制图片到剪贴板 (Cmd+C / Ctrl+C)
2. 在 CLI 中输入 `@paste 描述这张图片`
3. CLI 自动读取剪贴板图片，转换为多模态消息

#### 10.2.1.1 自动检测模式（推荐）

类似 Claude Code 的交互体验，用户可以直接按 **Ctrl+V** 粘贴，CLI 会自动检测剪贴板中是否包含图片：

```
You> [用户按下 Ctrl+V，剪贴板中有图片]
📷 检测到剪贴板图片: 800x600, 123KB
You> @paste 这张图片是什么意思？
```

**自动检测行为**：
1. 用户按下 Ctrl+V
2. CLI 检查剪贴板是否包含图片
3. 如果有图片：自动插入 `@paste ` 标记，并显示图片信息（尺寸、大小）
4. 如果没有图片：执行普通的文本粘贴

**实现细节**：
- 使用 `prompt_toolkit` 的自定义按键绑定拦截 Ctrl+V
- 调用 `ClipboardImageReader.has_image()` 检测图片
- 自动插入 `@paste ` 标记到输入缓冲区

#### 10.2.2 辅助方式：文件路径引用

```
You> @image:/path/to/screenshot.png 请分析这张截图
You> @image:./relative/path.jpg 这个图表是什么意思
```

- `@image:` 前缀 + 本地文件路径
- 支持绝对路径和相对路径（相对于当前工作目录）
- 支持 `~` 展开为用户主目录

#### 10.2.3 辅助方式：URL 引用

```
You> @url:https://example.com/chart.png 请解释这个图表
```

- `@url:` 前缀 + 图片 URL
- 仅支持 `https://` 协议（安全策略）

#### 10.2.4 语法汇总

| 语法 | 说明 | 示例 |
|------|------|------|
| `@paste` | 从剪贴板读取图片 | `@paste 这是什么？` |
| `@image:<path>` | 从本地文件读取 | `@image:~/Desktop/test.png 分析一下` |
| `@url:<url>` | 引用网络图片 | `@url:https://example.com/a.png 描述图片` |

### 10.3 实现架构

#### 10.3.1 模块结构

```
src/dolphin/cli/
├── multimodal/                    # 新增多模态输入模块
│   ├── __init__.py
│   ├── clipboard.py               # 剪贴板读取
│   ├── image_processor.py         # 图片处理（格式转换、压缩）
│   └── input_parser.py            # 输入解析（识别 @paste/@image/@url）
└── ui/
    └── input.py                   # 现有输入模块，需集成多模态解析
```

#### 10.3.2 核心类设计

```python
# src/dolphin/cli/multimodal/input_parser.py

from dataclasses import dataclass
from typing import List, Union
from enum import Enum

class ImageSourceType(Enum):
    CLIPBOARD = "clipboard"      # @paste
    FILE = "file"                # @image:<path>
    URL = "url"                  # @url:<url>

@dataclass
class ImageReference:
    """用户输入中的图片引用"""
    source_type: ImageSourceType
    source: str                   # 路径、URL 或 "clipboard"
    position: int                 # 在原始文本中的位置

@dataclass
class ParsedMultimodalInput:
    """解析后的多模态输入"""
    text_parts: List[str]         # 文本片段（去除图片引用后）
    image_refs: List[ImageReference]  # 图片引用列表
    
    def has_images(self) -> bool:
        return len(self.image_refs) > 0

class MultimodalInputParser:
    """解析用户输入中的多模态引用"""
    
    # 匹配模式
    PASTE_PATTERN = r"@paste"
    IMAGE_PATTERN = r"@image:([^\s]+)"
    URL_PATTERN = r"@url:(https://[^\s]+)"
    
    def parse(self, raw_input: str) -> ParsedMultimodalInput:
        """解析原始输入，提取图片引用"""
        # ... 实现正则匹配和解析
        pass
```

#### 10.3.3 剪贴板读取

```python
# src/dolphin/cli/multimodal/clipboard.py

import io
import base64
from typing import Optional, Tuple
from PIL import Image

class ClipboardImageReader:
    """跨平台剪贴板图片读取"""
    
    def read(self) -> Optional[bytes]:
        """读取剪贴板中的图片数据"""
        try:
            # macOS
            from AppKit import NSPasteboard, NSPasteboardTypePNG, NSPasteboardTypeTIFF
            pb = NSPasteboard.generalPasteboard()
            
            # 尝试 PNG
            data = pb.dataForType_(NSPasteboardTypePNG)
            if data:
                return bytes(data)
            
            # 尝试 TIFF (macOS 截图默认格式)
            data = pb.dataForType_(NSPasteboardTypeTIFF)
            if data:
                return self._convert_to_png(bytes(data))
                
            return None
        except ImportError:
            # Linux/Windows fallback
            return self._fallback_read()
    
    def _convert_to_png(self, tiff_data: bytes) -> bytes:
        """将 TIFF 转换为 PNG"""
        img = Image.open(io.BytesIO(tiff_data))
        output = io.BytesIO()
        img.save(output, format='PNG')
        return output.getvalue()
    
    def _fallback_read(self) -> Optional[bytes]:
        """Linux/Windows 后备方案，使用 Pillow 的 ImageGrab"""
        try:
            from PIL import ImageGrab
            img = ImageGrab.grabclipboard()
            if img is None:
                return None
            output = io.BytesIO()
            img.save(output, format='PNG')
            return output.getvalue()
        except Exception:
            return None
    
    def to_base64_url(self, image_data: bytes) -> str:
        """转换为 Base64 data URL"""
        b64 = base64.b64encode(image_data).decode('utf-8')
        return f"data:image/png;base64,{b64}"
```

#### 10.3.4 图片处理

```python
# src/dolphin/cli/multimodal/image_processor.py

from dataclasses import dataclass
from typing import Optional
from PIL import Image
import io

@dataclass
class ImageProcessConfig:
    max_size_bytes: int = 4 * 1024 * 1024      # 4MB
    max_dimension: int = 2048                   # 最大边长
    quality: int = 85                           # JPEG 压缩质量
    allowed_formats: tuple = ("PNG", "JPEG", "GIF", "WEBP")

class ImageProcessor:
    """图片预处理：格式验证、尺寸压缩"""
    
    def __init__(self, config: Optional[ImageProcessConfig] = None):
        self.config = config or ImageProcessConfig()
    
    def process(self, image_data: bytes) -> bytes:
        """处理图片：验证格式、压缩尺寸"""
        img = Image.open(io.BytesIO(image_data))
        
        # 验证格式
        if img.format not in self.config.allowed_formats:
            raise UnsupportedImageFormatError(f"Format {img.format} not supported")
        
        # 检查并压缩尺寸
        if max(img.size) > self.config.max_dimension:
            img = self._resize(img)
        
        # 输出
        output = io.BytesIO()
        fmt = "PNG" if img.mode == "RGBA" else "JPEG"
        img.save(output, format=fmt, quality=self.config.quality)
        
        result = output.getvalue()
        
        # 检查大小
        if len(result) > self.config.max_size_bytes:
            raise ImagePayloadTooLargeError(
                f"Image size {len(result)} exceeds limit {self.config.max_size_bytes}"
            )
        
        return result
    
    def _resize(self, img: Image.Image) -> Image.Image:
        """等比例缩放"""
        ratio = self.config.max_dimension / max(img.size)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        return img.resize(new_size, Image.Resampling.LANCZOS)
```

#### 10.3.5 与 CLI 输入集成

```python
# 在 src/dolphin/cli/ui/input.py 中集成

async def prompt_conversation_with_multimodal(
    prompt_text: str = "\n> ",
    interrupt_token: Optional["InterruptToken"] = None
) -> Union[str, List[Dict]]:
    """
    增强的对话输入，支持多模态。
    
    Returns:
        str: 纯文本输入
        List[Dict]: 包含图片的多模态内容
    """
    from dolphin.cli.multimodal import (
        MultimodalInputParser, 
        ClipboardImageReader,
        ImageProcessor
    )
    
    # 获取原始输入
    raw_input = await prompt_with_interrupt(
        prompt_text=prompt_text,
        interrupt_token=interrupt_token,
        completer=ConversationCompleter()
    )
    
    # 解析多模态引用
    parser = MultimodalInputParser()
    parsed = parser.parse(raw_input)
    
    if not parsed.has_images():
        return raw_input  # 纯文本，直接返回
    
    # 处理图片引用，构建多模态 content
    content = []
    clipboard_reader = ClipboardImageReader()
    processor = ImageProcessor()
    
    for i, text_part in enumerate(parsed.text_parts):
        if text_part.strip():
            content.append({"type": "text", "text": text_part.strip()})
        
        # 在对应位置插入图片
        if i < len(parsed.image_refs):
            ref = parsed.image_refs[i]
            image_url = _resolve_image_ref(ref, clipboard_reader, processor)
            content.append({
                "type": "image_url",
                "image_url": {"url": image_url, "detail": "auto"}
            })
    
    return content

def _resolve_image_ref(
    ref: ImageReference,
    clipboard: ClipboardImageReader,
    processor: ImageProcessor
) -> str:
    """将图片引用解析为可用的 URL（Base64 或 HTTPS）"""
    if ref.source_type == ImageSourceType.CLIPBOARD:
        data = clipboard.read()
        if data is None:
            raise ClipboardEmptyError("No image found in clipboard")
        processed = processor.process(data)
        return clipboard.to_base64_url(processed)
    
    elif ref.source_type == ImageSourceType.FILE:
        path = os.path.expanduser(ref.source)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Image file not found: {path}")
        with open(path, "rb") as f:
            data = f.read()
        processed = processor.process(data)
        return f"data:image/png;base64,{base64.b64encode(processed).decode()}"
    
    elif ref.source_type == ImageSourceType.URL:
        # URL 直接透传，不做预处理
        return ref.source
    
    raise ValueError(f"Unknown source type: {ref.source_type}")
```

### 10.4 Slash 命令扩展

在 `SLASH_COMMANDS` 中添加多模态相关命令：

```python
# 在 src/dolphin/cli/ui/input.py 的 SLASH_COMMANDS 中添加

SLASH_COMMANDS = [
    # ... 现有命令 ...
    ("/paste", "从剪贴板粘贴图片 (等同于 @paste)"),
    ("/image", "从文件读取图片: /image <path>"),
    ("/clipboard-status", "检查剪贴板中是否有图片"),
]
```

### 10.5 用户反馈与状态提示

#### 10.5.1 成功反馈

```
You> @paste 这是什么？
📎 已读取剪贴板图片 (1920x1080, 245KB)

Assistant> 这是一张...
```

#### 10.5.2 错误反馈

```
You> @paste 描述图片
⚠️ 剪贴板中没有图片，请先复制一张图片

You> @image:/not/exist.png 分析
⚠️ 文件不存在: /not/exist.png

You> @paste 大图片
⚠️ 图片过大 (12MB)，已自动压缩至 2048x1536 (1.8MB)
```

### 10.6 配置项

```yaml
# config/global.yaml

cli:
  multimodal:
    enabled: true                      # 是否启用多模态输入
    max_image_size_mb: 4               # 单张图片最大大小 (MB)
    max_dimension: 2048                # 图片最大边长 (超过自动压缩)
    auto_compress: true                # 是否自动压缩超大图片
    allowed_sources:                   # 允许的图片来源
      - clipboard
      - file
      - url
    allowed_formats:                   # 允许的图片格式
      - png
      - jpg
      - jpeg
      - gif
      - webp
```

### 10.7 依赖管理

需要在 `pyproject.toml` 中添加以下依赖：

```toml
[project.optional-dependencies]
multimodal = [
    "Pillow>=10.0.0",     # 图片处理
    "pyobjc-framework-Cocoa>=10.0; sys_platform == 'darwin'",  # macOS 剪贴板
]
```

### 10.8 安全考量

1. **文件路径安全**：
   - 验证文件路径不包含目录遍历攻击 (`../`)
   - 限制可访问的目录范围（可配置）

2. **图片内容安全**：
   - 使用 Pillow 验证图片格式有效性（防止恶意文件）
   - 限制图片大小防止内存溢出

3. **URL 安全**：
   - 仅允许 `https://` 协议
   - 可配置域名白名单

### 10.9 测试计划

| 测试场景 | 验证内容 | 优先级 |
|----------|----------|--------|
| 剪贴板读取 | macOS/Linux/Windows 兼容性 | P0 |
| 语法解析 | `@paste`, `@image:`, `@url:` 正确解析 | P0 |
| 图片压缩 | 超大图片自动压缩 | P1 |
| 多图片输入 | 单条消息多个 `@paste` | P1 |
| 错误处理 | 剪贴板为空、文件不存在等 | P0 |
| 格式验证 | 拒绝不支持的图片格式 | P1 |

## 12. 附录 (Appendix)

### 12.1 参考资料

- [OpenAI Vision API 文档](https://platform.openai.com/docs/guides/vision)
- [Claude Vision 文档](https://docs.anthropic.com/claude/docs/vision)
- [Gemini Multimodal 文档](https://ai.google.dev/gemini-api/docs/vision)

### 12.2 术语表

| 术语 | 定义 |
|------|------|
| Content Block | `content` 列表中的单个元素，如 `{"type": "text", ...}` |
| Vision Model | 支持图片输入的模型，如 GPT-4o, Claude 3.5 Sonnet |
| Atomic Drop | 多模态消息压缩时整条丢弃而非部分截断的策略 |
| Multimodal Adapter | 负责不同 LLM API 格式转换的适配器接口 |
