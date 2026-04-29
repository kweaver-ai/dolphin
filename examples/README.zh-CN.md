# Dolphin Language 示例

English | **中文文档**

---

一组示例项目，展示 Dolphin Language SDK 的能力。

## 快速开始

在运行任何示例之前，请确保：

1. 安装所有必需的依赖：
   ```bash
   uv sync
   ```

2. 在相应的 `config/global.yaml` 文件中配置您的 API 密钥（从 `global.template.yaml` 复制）

---

## 可用示例

| 示例 | 描述 | 主要特性 |
|------|------|----------|
| [deepsearch](#deepsearch) | 多智能体深度研究系统 | 网络搜索、认知思考、多视角分析 |
| [tabular_analyst](#tabular_analyst) | 智能数据文件分析器 | Python 执行、数据分析、多格式支持 |
| [resource_skill](#resource_skill) | 技能引导助手 | Claude Skill 格式、渐进式加载、专家方法论 |

---

## resource_skill

一个技能引导助手，展示如何使用 Claude Skill 格式的资源（SKILL.md）为各种任务提供专家指导。

### 特性

- **Claude Skill 格式**：使用 SKILL.md 文件进行结构化指导（兼容 HuggingFace Skills）
- **渐进式加载**：三级加载（元数据 → 内容 → 资源）
- **自包含**：所有技能都打包在示例目录中
- **专家方法论**：技能提供框架和方法论，而不仅仅是指令

### 可用技能

| 技能 | 描述 |
|------|------|
| `brainstorming` | 通过协作式提问将想法转化为完整的设计 |
| `cto-advisor` | 技术领导力指导：技术债务、团队扩展、架构决策 |

### 使用方法

```bash
# 头脑风暴一个新产品想法
./examples/resource_skill/bin/skill_guided_coding.sh "我有一个新的移动应用想法，帮我头脑风暴"

# 获取关于技术债务的 CTO 建议
./examples/resource_skill/bin/skill_guided_coding.sh "作为 CTO，我应该如何评估我们的技术债务？"

# 设计一个新功能
./examples/resource_skill/bin/skill_guided_coding.sh "帮我设计一个应用的通知系统"
```

或手动运行：

```bash
dolphin run --folder examples/resource_skill/ \
    --agent skill_guided_assistant \
    --config examples/resource_skill/config/global.yaml \
    --query "帮我头脑风暴一个新功能"
```

### 目录结构

```
resource_skill/
├── bin/
│   └── skill_guided_coding.sh   # 便捷启动脚本
├── config/
│   ├── global.yaml              # 配置文件（从模板创建）
│   └── global.template.yaml     # 配置模板
├── skill_guided_assistant.dph   # 主技能引导智能体
└── skills/                      # 自包含技能目录
    ├── brainstorming/
    │   └── SKILL.md             # 头脑风暴方法论
    └── cto-advisor/
        └── SKILL.md             # CTO 咨询框架
```

### 工作原理

1. **列出技能**：智能体发现可用的资源技能
2. **分析请求**：识别哪个技能最符合用户的需求
3. **加载技能**：加载完整的 SKILL.md 方法论
4. **应用框架**：按照技能的结构化方法帮助用户

---

## deepsearch

一个智能深度研究系统，结合网络搜索和认知推理，提供全面且经过验证的答案。

### 特性

- 🔍 **多视角研究**：生成多种研究方法，进行全面分析
- 🌐 **网络搜索集成**：实时网络搜索获取最新信息
- 🧠 **认知推理**：使用结构化思考工具进行验证
- 📊 **结果综合**：整合不同方法的研究发现

### 智能体

| 智能体 | 描述 |
|--------|------|
| `deepsearch` | 主入口 - 协调探索和验证的研究流程 |
| `deepersearch` | 增强版 - 使用头脑风暴生成多种研究方法 |
| `web_search` | 将查询扩展为多个搜索词并综合结果 |
| `web_query` | 直接网络查询智能体，带完整性验证 |

### 使用方法

```bash
# 运行主 deepsearch 智能体
./examples/deepsearch/bin/deepsearch.sh "您的研究问题"
```

或手动运行：

```bash
dolphin run --folder examples/deepsearch/ \
    --agent deepsearch \
    --config examples/deepsearch/config/global.yaml \
    --query "AI 智能体的最新发展是什么？"
```

### 目录结构

```
deepsearch/
├── bin/
│   └── deepsearch.sh        # 便捷启动脚本
├── config/
│   ├── global.yaml          # 配置文件（从模板创建）
│   └── global.template.yaml # 配置模板
├── deepsearch.dph           # 主研究智能体
├── deepersearch.dph         # 多视角研究智能体
├── web_search.dph           # 带查询扩展的网络搜索
└── web_query.dph            # 直接网络查询智能体
```

---

## tabular_analyst

一个智能数据分析智能体，可以使用 Python 执行来读取、理解和分析表格数据文件。

### 特性

- 📁 **多格式支持**：CSV、XLSX、XLS、JSON、Parquet
- 🐍 **有状态 Python 执行**：变量在多次代码执行之间持久保存
- 📈 **智能分析**：自动模式检测和多维度洞察
- 🔧 **自定义技能包**：可通过领域特定技能扩展

### 支持的文件格式

| 格式 | 扩展名 |
|------|--------|
| CSV | `.csv` |
| Excel | `.xlsx`, `.xls` |
| JSON | `.json` |
| Parquet | `.parquet` |

### 使用方法

```bash
# 使用便捷脚本运行
./examples/tabular_analyst/bin/tabular_analyst.sh /path/to/your/data.xlsx
```

或手动运行：

```bash
dolphin run --folder examples/tabular_analyst/ \
    --agent tabular_analyst \
    --config examples/tabular_analyst/config/global.yaml \
    --skill_folder examples/tabular_analyst/skillkits/ \
    --query "/path/to/your/data.csv"
```

### 目录结构

```
tabular_analyst/
├── bin/
│   └── tabular_analyst.sh   # 带验证的便捷启动脚本
├── config/
│   ├── global.yaml          # 配置文件（从模板创建）
│   └── global.template.yaml # 配置模板
├── skillkits/               # 数据分析自定义技能包
└── tabular_analyst.dph      # 主分析智能体
```

### Python 会话特性

表格分析器使用有状态的 Python 执行，这意味着：

- **变量持久化**：DataFrame 和计算结果在调用之间持久保存
- **自动恢复**：模块导入会尝试自动恢复
- **分步分析**：可以逐步执行分析，充分利用状态持久化的优势

---

## 配置

每个示例都有自己的配置目录，包含：

- `global.template.yaml`：带占位符值的模板
- `global.yaml`：您的实际配置（已加入 gitignore）

### 配置设置

```bash
# 复制模板创建您的配置
cp examples/deepsearch/config/global.template.yaml examples/deepsearch/config/global.yaml

# 编辑您的 API 密钥和偏好设置
vim examples/deepsearch/config/global.yaml
```

### 常用配置选项

| 选项 | 描述 |
|------|------|
| `model_name` | 使用的 LLM 模型（例如 `gpt-4`、`deepseek-chat`） |
| `api_key` | 您的 API 密钥 |
| `api_base` | API 端点 URL |

---

## 创建您自己的示例

1. 在 `examples/` 下创建新目录：
   ```bash
   mkdir -p examples/my_example/{bin,config}
   ```

2. 创建您的智能体文件：
   ```bash
   touch examples/my_example/my_agent.dph
   ```

3. 复制并配置配置模板：
   ```bash
   cp examples/deepsearch/config/global.template.yaml examples/my_example/config/
   ```

4. 创建便捷启动脚本：
   ```bash
   touch examples/my_example/bin/my_example.sh
   chmod +x examples/my_example/bin/my_example.sh
   ```

---

## 注意事项

1. **API 密钥**：永远不要提交包含真实 API 密钥的 `global.yaml` 文件
2. **工作目录**：从项目根目录运行脚本
3. **依赖**：某些示例可能需要额外的 Python 包
4. **交互模式**：大多数示例支持 `-i` 或 `--interactive` 进行持续对话

---

## 故障排除

### 常见问题

| 问题 | 解决方案 |
|------|----------|
| 找不到配置文件 | 从 `global.template.yaml` 复制并配置 |
| API 密钥无效 | 检查您的 `global.yaml` 配置 |
| 找不到模块 | 运行 `uv sync` 安装依赖 |
| 文件权限被拒绝 | 使用 `chmod +r` 检查文件权限 |

### 获取帮助

```bash
# 查看详细日志
dolphin run --agent <agent> --folder <folder> --verbose

# 更详细的调试输出
dolphin run --agent <agent> --folder <folder> --vv
```
