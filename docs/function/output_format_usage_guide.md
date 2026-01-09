# OutputFormat 输出格式使用指南

## 概述

`OutputFormat` 是 Dolphin Language SDK 中的输出格式约束系统，用于控制和解析 LLM 的输出格式。系统支持三种主要格式：JSON、JSONL 和对象类型（ObjectType）。

## 功能特性

1. **格式约束**：自动向 LLM 添加格式约束提示词
2. **结果解析**：将 LLM 响应解析为对应的数据结构
3. **类型安全**：基于预定义的对象类型进行约束和验证
4. **Function Call 支持**：为对象类型自动生成 OpenAI function call 工具定义
5. **自动类型加载**：DolphinExecutor 可自动加载类型定义文件

## 支持的格式类型

### 1. JSON 格式

将 LLM 输出约束为标准 JSON 对象格式。

```dolphin
/prompt/(output="json") 请生成一个用户信息 -> user_info
```

**输出示例：**
```json
{
  "name": "张三",
  "age": 30,
  "city": "北京"
}
```

**解析结果：** Python 字典 `dict`

### 2. JSONL 格式

将 LLM 输出约束为 JSON Lines 格式，每行一个 JSON 对象。

```dolphin
/prompt/(output="jsonl") 请生成三个用户信息 -> users_list
```

**输出示例：**
```
{"name": "张三", "age": 30}
{"name": "李四", "age": 25}
{"name": "王五", "age": 35}
```

**解析结果：** Python 列表 `List[dict]`

### 3. 对象类型格式

基于预定义的对象类型进行约束，支持复杂的结构化数据。

```dolphin
/prompt/(output="obj/UserProfile") 请生成一个用户档案 -> user_profile
```

**前提条件：** 需要在 `global_types` 中定义 `UserProfile` 类型

## 对象类型定义与加载

### 类型定义文件格式

对象类型需要在 `.type` 文件中定义，使用标准的 JSON Schema 格式。

**示例类型定义文件：`UserProfile.type`**

```json
{
  "title": "UserProfile",
  "description": "用户档案信息",
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "用户姓名"
    },
    "age": {
      "type": "integer", 
      "description": "用户年龄"
    },
    "email": {
      "type": "string",
      "description": "用户邮箱"
    },
    "skills": {
      "type": "array",
      "description": "用户技能列表"
    },
    "address": {
      "type": "object",
      "description": "用户地址信息",
      "properties": {
        "street": {"type": "string", "description": "街道"},
        "city": {"type": "string", "description": "城市"},
        "zipcode": {"type": "string", "description": "邮政编码"}
      }
    }
  },
  "required": ["name", "age"]
}
```

### DolphinExecutor 类型加载功能

`DolphinExecutor` 提供了多种方式来加载对象类型定义：

#### 1. 自动加载（推荐）

DolphinExecutor 在初始化时会自动从以下目录加载 `.type` 文件：

- `./examples/types/` - 项目示例类型目录
- `./types/` - 根目录类型目录
- `./src/types/` - 源码类型目录

```python
from DolphinLanguageSDK.dolphin_language import DolphinExecutor

# 自动加载默认目录中的所有 .type 文件
executor = DolphinExecutor()
```

#### 2. 指定文件夹加载

```python
# 指定单个文件夹
executor = DolphinExecutor(type_folders="./my_types")

# 指定多个文件夹
executor = DolphinExecutor(type_folders=["./types", "./custom_types"])
```

#### 3. 手动加载单个文件

```python
# 从文件加载类型定义
executor.load_type_from_file("./types/UserProfile.type")
```

#### 4. 从 JSON 数据加载

```python
# 从 JSON 字典加载类型定义
type_definition = {
    "title": "Product",
    "description": "产品信息",
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "产品名称"},
        "price": {"type": "number", "description": "产品价格", "minimum": 0}
    },
    "required": ["name", "price"]
}

executor.load_type(type_definition)
```

#### 5. 运行时动态加载

```python
async def main():
    executor = DolphinExecutor()
    
    # 运行时加载新的类型定义
    executor.load_type_from_file("./new_type.type")
    
    # 现在可以使用新类型
    content = '/prompt/(output="obj/NewType") 生成数据 -> result'
    async for result in executor.run(content):
        print(result)
```

## 使用方法

### 在 Dolphin Language 文件中使用

```dolphin
# JSON 格式示例
/prompt/(output="json", model="gpt-4") 
  根据以下信息生成用户数据：姓名张三，年龄30岁，城市北京
-> json_result

# JSONL 格式示例  
/prompt/(output="jsonl", model="gpt-4")
  生成5个不同的用户信息，包含姓名、年龄、城市
-> jsonl_result

# 对象类型格式示例
/prompt/(output="obj/UserProfile", model="gpt-4")
  生成一个完整的用户档案，包含所有必需字段
-> profile_result
```

### 在 Python 代码中使用

```python
from DolphinLanguageSDK.dolphin_language import DolphinExecutor
from DolphinLanguageSDK.type.output_format import OutputFormatFactory

# 创建 DolphinExecutor（自动加载类型定义）
executor = DolphinExecutor()

# 直接使用 OutputFormat（需要手动管理类型）
from DolphinLanguageSDK.type.object_type import ObjectTypeFactory

global_types = ObjectTypeFactory()
global_types.load('./types/UserProfile.type')

# 解析输出格式
output_format = OutputFormatFactory.parseFromString("obj/UserProfile", global_types)

# 添加格式约束到消息
from DolphinLanguageSDK.common import Messages
messages = Messages()
messages.append_message(MessageRole.USER, "生成用户档案")
output_format.addFormatConstraintToMessages(messages)

# 解析响应结果
response = '{"name": "张三", "age": 30, "email": "zhang@example.com"}'
parsed_result = output_format.parseResponse(response)
print(parsed_result)  # Python dict
```

## 高级功能

### Function Call 集成

对象类型格式自动支持 OpenAI function call，可以生成相应的工具定义：

```python
from DolphinLanguageSDK.type.output_format import ObjectTypeOutputFormat

# 创建对象类型输出格式
obj_format = ObjectTypeOutputFormat("UserProfile", type_definition)
tools = obj_format.generateFunctionCallTools()

# 生成的工具定义可直接用于 LLM function call
llm_params = {
    "messages": messages,
    "tools": tools,
    "tool_choice": "auto"
}
```

**生成的工具定义示例：**
```python
[{
    "type": "function",
    "function": {
        "name": "UserProfile",
        "description": "用户档案信息",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "用户姓名"},
                "age": {"type": "integer", "description": "用户年龄"}
            },
            "required": ["name", "age"]
        }
    }
}]
```

### 错误处理

系统提供完整的错误处理机制：

```python
from DolphinLanguageSDK.type.output_format import OutputFormatFactory

try:
    # 格式解析错误处理
    output_format = OutputFormatFactory.parseFromString("obj/UnknownType", global_types)
except ValueError as e:
    print(f"格式解析失败: {e}")

try:
    # 响应解析错误处理
    parsed_result = output_format.parseResponse(invalid_response)
except ValueError as e:
    print(f"响应解析失败: {e}")
```

## 实际使用示例

### 完整的使用流程

```python
from DolphinLanguageSDK.dolphin_language import DolphinExecutor

async def example_usage():
    # 1. 创建执行器并自动加载类型定义
    executor = DolphinExecutor()
    
    # 2. 可选：手动加载特定类型
    product_type = {
        "title": "Product",
        "description": "产品信息",
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "产品名称"},
            "price": {"type": "number", "description": "产品价格"}
        },
        "required": ["name", "price"]
    }
    executor.load_type(product_type)
    
    # 3. 使用不同的输出格式
    
    # JSON 格式
    json_content = '/prompt/(output="json") 生成一个用户信息 -> user'
    async for result in executor.run(json_content):
        user_data = result.get('user', {}).get('value')
        print("JSON 结果:", user_data)
    
    # JSONL 格式
    jsonl_content = '/prompt/(output="jsonl") 生成3个产品信息 -> products'
    async for result in executor.run(jsonl_content):
        products_data = result.get('products', {}).get('value')
        print("JSONL 结果:", products_data)
    
    # 对象类型格式
    obj_content = '/prompt/(output="obj/Product") 生成一个产品信息 -> product'
    async for result in executor.run(obj_content):
        product_data = result.get('product', {}).get('value')
        print("对象类型结果:", product_data)

# 运行示例
import asyncio
asyncio.run(example_usage())
```

## 最佳实践

### 1. 类型定义规范

- **完整的描述信息**：为每个属性提供清晰的 `description`
- **正确的 required 字段**：明确哪些字段是必需的
- **标准的 JSON Schema 类型**：使用 `string`、`number`、`integer`、`boolean`、`array`、`object`
- **嵌套结构支持**：可以定义复杂的嵌套对象结构
- **约束条件**：使用 `minimum`、`maximum`、`pattern` 等约束

### 2. 文件组织建议

```
project/
├── types/                 # 类型定义目录
│   ├── User.type         # 用户类型
│   ├── Product.type      # 产品类型
│   └── Order.type        # 订单类型
├── dolphins/             # Dolphin 脚本目录
│   ├── user_profile.dph
│   └── product_catalog.dph
└── config/
    └── global.yaml
```

### 3. 格式选择建议

- **JSON**: 单个结构化对象，简单的数据结构
- **JSONL**: 多个对象列表，批量数据处理
- **ObjectType**: 复杂结构化数据，需要类型验证和 Function Call 支持

### 4. 错误处理策略

```python
# 推荐的错误处理模式
try:
    executor = DolphinExecutor()
    executor.load_type_from_file("./types/CustomType.type")
except FileNotFoundError:
    print("类型文件未找到，使用默认类型")
except ValueError as e:
    print(f"类型定义格式错误: {e}")
```

### 5. 性能优化

- **批量加载**：使用 `type_folders` 参数一次性加载多个类型
- **延迟加载**：只在需要时加载特定类型
- **缓存复用**：DolphinExecutor 会缓存已加载的类型定义

## 示例项目

完整的使用示例可以参考：

- `tests/unittest/test_output_format.py` - 单元测试示例
- `tests/integration_test/testcases/output_format_cases.json` - 集成测试用例
- `tests/integration_test/dolphins/output_format_*.dph` - Dolphin Language 使用示例
- `examples/types/Product.type` - 实际类型定义示例

## 注意事项

1. **类型定义加载顺序**：
   - 自动加载在 DolphinExecutor 初始化时执行
   - 手动加载可以在运行时任意时刻执行
   - 后加载的同名类型会覆盖先加载的类型

2. **LLM 兼容性**：
   - 某些 LLM 可能对格式约束的遵循程度不同
   - Function Call 功能需要 LLM 支持工具调用
   - 复杂的对象类型可能需要多次尝试才能获得正确格式

3. **内存管理**：
   - 类型定义会加载到内存中并持续保存
   - 大量复杂类型定义可能影响内存使用

4. **文件路径**：
   - 支持相对路径和绝对路径
   - 类型文件必须使用 `.type` 扩展名
   - 建议使用项目相对路径以提高可移植性

## 故障排除

### 常见问题与解决方案

#### Q: 如何处理 LLM 不遵循格式约束的情况？

A: 系统会尽力解析响应，如果解析失败会保留原始响应并记录警告。建议：
- 在提示词中明确说明输出格式要求
- 使用更严格的约束条件
- 在应用层添加额外的验证逻辑

#### Q: 对象类型格式没有生效怎么办？

A: 检查以下几点：
1. 确认类型定义已正确加载：`executor.global_types.getTypes(['TypeName'])`
2. 检查类型定义文件格式是否符合 JSON Schema 规范
3. 确认在 `/prompt/` 块中正确使用了 `output="obj/TypeName"` 格式

#### Q: 可以自定义格式类型吗？

A: 可以通过继承 `OutputFormat` 基类来实现自定义格式处理器：

```python
from DolphinLanguageSDK.type.output_format import OutputFormat, OutputFormatType

class CustomOutputFormat(OutputFormat):
    def __init__(self):
        super().__init__(OutputFormatType.JSON)  # 或自定义类型
    
    def addFormatConstraintToMessages(self, messages):
        # 实现自定义约束逻辑
        pass
    
    def parseResponse(self, responseStr):
        # 实现自定义解析逻辑
        pass
    
    def getFormatDescription(self):
        return "自定义输出格式"
```

#### Q: 对象类型支持嵌套结构吗？

A: 完全支持，可以在类型定义中使用嵌套的 `object` 类型：

```json
{
  "title": "User",
  "type": "object",
  "properties": {
    "profile": {
      "type": "object",
      "properties": {
        "address": {
          "type": "object",
          "properties": {
            "street": {"type": "string"},
            "city": {"type": "string"}
          }
        }
      }
    }
  }
}
```

#### Q: 如何调试类型加载问题？

A: 启用日志记录来查看详细信息：

```python
import logging
logging.basicConfig(level=logging.INFO)

executor = DolphinExecutor()
# 查看加载的类型
loaded_types = executor.global_types.getTypes()
print(f"已加载的类型: {[t.title for t in loaded_types]}")
```

---

更多信息请参考 [Dolphin Language SDK 文档](../index.md)。 