# 安装指南

本文档将指导您完成 Dolphin Language SDK 的安装和配置。

## 系统要求

- Python 3.10 或更高版本
- uv (推荐) 或 pip
- Git

## 安装方式

### 方式一：使用 uv (推荐)

```bash
# 1. 克隆仓库
git clone https://github.com/kweaver-ai/dolphin.git
cd dolphin-language

# 2. 设置开发环境
make dev-setup

# 3. 验证安装
make test
```

### 方式二：使用 pip

```bash
# 1. 克隆仓库
git clone https://github.com/kweaver-ai/dolphin.git
cd dolphin-language

# 2. 安装依赖
pip install -e ".[dev]"

# 3. 验证安装
python -m pytest tests/
```

## 验证安装

创建一个简单的测试文件：

```python
# test_installation.py
from DolphinLanguageSDK import DolphinLanguage

# 创建一个简单的程序
dolphin = DolphinLanguage()
print("Dolphin Language SDK 安装成功！")
```

运行测试：

```bash
python test_installation.py
```

## 下一步

- [快速入门](quickstart.md) - 学习基本用法
- [基础概念](basics.md) - 了解核心概念
