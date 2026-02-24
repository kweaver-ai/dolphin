.PHONY: clean install-dev install-prod build build-only dev-setup test test-unit test-integration test-integration-filter help lint format uv-sync uv-clean docs-serve docs-build

clean:
	rm -rf dist
	rm -rf build
	rm -rf *.spec
	rm -rf *.pyc
	rm -rf **/*.pyc
	rm -rf **/**/*.pyc
	rm -rf **/**/**/*.pyc
	rm -rf **/**/**/**/*.pyc
	rm -rf *.egg-info;
	rm -rf **/*.egg-info;
	rm -rf **/**/*.egg-info;
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +

# 开发模式安装 - 推荐用于开发环境
install-dev: clean
	uv pip install -e ".[dev,test]"
	@echo "✅ 开发环境安装完成 (editable mode)"
	@echo "💡 现在您可以直接修改代码，无需重新安装包"

# 生产模式安装
install-prod: clean
	uv pip install .
	@echo "✅ 生产环境安装完成"

dev-setup: uv-sync
	@echo "🚀 开发环境设置完成"
	@echo "🧪 运行 'make test' 来验证环境"

build-only:
	uv run python -m build

build: clean build-only

# 使用改进的测试脚本
test:
	bash tests/run_tests.sh all

test-unit:
	bash tests/run_tests.sh unit --parallel

test-integration:
	bash tests/run_tests.sh integration

test-integration-filter:
	@echo "使用方法: make test-integration-filter FILTER=<pattern>"
	@echo "示例: make test-integration-filter FILTER=poem"
	bash tests/run_tests.sh integration -f $(FILTER)

test-verbose:
	bash tests/run_tests.sh all -v

# 检查代码质量（如果有相关工具）
lint:
	@echo "🔍 检查代码质量..."
	@if uv run which ruff >/dev/null 2>&1; then \
		uv run ruff check --fix src tests; \
		uv run ruff format src tests; \
	else \
		echo "⚠️  ruff 未安装，跳过代码检查"; \
	fi

# 格式化代码（如果有相关工具）
format:
	@echo "🎨 格式化代码..."
	@if uv run which ruff >/dev/null 2>&1; then \
		uv run ruff format src tests; \
	else \
		echo "⚠️  black 未安装，跳过代码格式化"; \
	fi

# UV 特定操作
uv-sync:
	uv sync --all-groups
	@echo "✅ UV 环境同步完成"

uv-clean:
	uv cache clean
	rm -rf .venv
	@echo "✅ UV 缓存清理完成"

# 文档相关命令
docs-serve:
	@echo "📖 启动文档服务器..."
	@echo "🌐 访问地址: http://0.0.0.0:30050"
	@echo "💡 按 Ctrl+C 停止服务器"
	@echo ""
	uv run mkdocs serve --dev-addr=0.0.0.0:30050

docs-build:
	@echo "📦 构建文档..."
	uv run mkdocs build
	@echo "✅ 文档构建完成，输出到 site/ 目录"

docs-clean:
	rm -rf site/
	@echo "✅ 文档构建产物清理完成"

help:
	@echo "🐬 Dolphin Language SDK - Makefile 帮助"
	@echo ""
	@echo "🔧 安装:"
	@echo "  dev-setup            - 设置开发环境 (推荐)"
	@echo "  install-dev          - 以开发模式安装包"
	@echo "  install-prod         - 以生产模式安装包"
	@echo ""
	@echo "🏗️  构建:"
	@echo "  clean                - 清理构建产物和缓存文件"
	@echo "  build-only           - 仅构建wheel包"
	@echo "  build                - 清理 + 构建wheel包"
	@echo ""
	@echo "🧪 测试:"
	@echo "  test                 - 运行所有测试"
	@echo "  test-unit            - 仅运行单元测试"
	@echo "  test-integration     - 仅运行集成测试"
	@echo "  test-integration-filter FILTER=<pattern> - 过滤集成测试"
	@echo "  test-verbose         - 详细模式运行所有测试"
	@echo ""
	@echo "🎨 代码质量:"
	@echo "  lint                 - 检查代码质量"
	@echo "  format               - 格式化代码"
	@echo ""
	@echo "🚀 UV 特定:"
	@echo "  uv-sync              - 同步 UV 环境依赖"
	@echo "  uv-clean             - 清理 UV 缓存和虚拟环境"
	@echo ""
	@echo "📖 文档:"
	@echo "  docs-serve           - 启动文档服务器 (http://0.0.0.0:30050)"
	@echo "  docs-build           - 构建文档到 site/ 目录"
	@echo "  docs-clean           - 清理文档构建产物"
	@echo ""
	@echo "📖 示例用法:"
	@echo "  make dev-setup                    # 设置开发环境"
	@echo "  make test                         # 运行所有测试"
	@echo "  make docs-serve                   # 启动文档服务器"
	@echo "  make test-integration-filter FILTER=poem  # 过滤测试"
