# 使用 MkDocs 文档系统

本项目已集成 MkDocs 文档系统，提供美观的在线文档。

## 快速开始

### 1. 安装依赖

```bash
# 确保已安装 mkdocs 依赖
make dev-setup
# 或
uv sync --all-groups
```

### 2. 启动文档服务器

```bash
# 启动本地文档服务器
make docs-serve
```

### 3. 访问文档

打开浏览器访问：
- **本地访问**: http://localhost:30050
- **局域网访问**: http://你的IP地址:30050

## 可用命令

### 启动开发服务器
```bash
make docs-serve
```

### 构建静态文档
```bash
make docs-build
```

### 清理构建产物
```bash
make docs-clean
```

## 文档结构

```
docs/
├── index.md                 # 文档首页
├── getting-started/         # 快速开始
│   ├── installation.md
│   ├── quickstart.md
│   └── basics.md
├── language/               # 语言规范
│   ├── code_blocks.md
│   └── variables.md
├── core/                   # 核心功能
│   ├── agents.md
│   ├── skills.md
│   ├── context.md
│   ├── memory.md
│   └── feature_flags.md
├── dev/                    # 开发指南
│   ├── custom-skills.md
│   ├── extensions.md
│   ├── debugging.md
│   └── performance.md
├── architecture/           # 架构设计
│   ├── overview.md
│   ├── coroutine.md
│   └── experiments.md
├── examples/               # 示例
│   └── index.md
├── api/                    # API 参考
│   └── index.md
└── faq/                    # 常见问题
    ├── troubleshooting.md
    └── faq.md
```

## 编辑文档

### 添加新页面

1. 在相应目录创建 `.md` 文件
2. 在 `mkdocs.yml` 的 `nav` 部分添加导航链接
3. 重启文档服务器查看更改

### 示例：创建新页面

```markdown
# 标题

这里是内容...

## 子标题

更多内容...
```

### Markdown 扩展功能

- **代码高亮**: 使用 ` ```python ` 包围代码
- **提示框**: 使用 ` !!! note ` 创建提示
- **标签页**: 使用 ` === "标签1" ` 创建标签页
- **图标**: 使用 `:material-icon:` 语法

示例：
```markdown
!!! note "提示"
    这是一个提示框。

=== "Python"
    ```python
    print("Hello")
    ```

=== "JavaScript"
    ```javascript
    console.log("Hello");
    ```
```

## 自定义主题

编辑 `mkdocs.yml` 文件自定义主题：

```yaml
theme:
  name: material
  language: zh
  features:
    - navigation.tabs
    - search.suggest
    - content.code.copy
```

## 部署文档

### GitHub Pages

```bash
# 构建文档
make docs-build

# 推送到 gh-pages 分支
cd site
git init
git add -A
git commit -m 'Deploy docs'
git push -f git@github.com:your-org/dolphin-language.git main:gh-pages
```

### 其他平台

- Netlify: 连接 Git 仓库自动部署
- Vercel: 支持 MkDocs 部署
- AWS S3: 静态网站托管

## 技巧与提示

1. **实时预览**: 文档服务器支持热重载，修改文件后自动刷新
2. **搜索功能**: 集成 MkDocs 内置搜索，支持中文
3. **代码复制**: 点击代码块右上角复制按钮
4. **响应式设计**: 文档支持移动端访问
5. **暗色模式**: 点击右上角切换明暗主题

## 故障排除

### 问题：端口被占用
```bash
# 使用不同端口
uv run mkdocs serve --dev-addr=0.0.0.0:30051
```

### 问题：依赖缺失
```bash
# 重新安装依赖
uv sync --all-groups
```

### 问题：文档不显示
```bash
# 检查 mkdocs.yml 语法
uv run mkdocs build --strict
```

## 参考资源

- [MkDocs 官方文档](https://www.mkdocs.org/)
- [Material 主题](https://squidfunk.github.io/mkdocs-material/)
- [Markdown 指南](https://www.markdownguide.org/)
