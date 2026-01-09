#!/bin/bash

# Dolphin Language Test Runner (UV Enhanced)
# 用于运行integration_test或unittest的脚本，使用uv进行包管理

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Default values
TEST_TYPE=""
FILTER=""
VERBOSE=false
CONFIG=""
COVERAGE=false
PARALLEL=false
PYTHON_VERSION=""
FAIL_FAST=false

# Function to print usage
print_usage() {
    echo "用法: $0 <test_type> [options]"
    echo ""
    echo "Test Types:"
    echo "  integration   - 运行集成测试 (integration tests)"
    echo "  unit         - 运行单元测试 (unit tests)"
    echo "  all          - 运行所有测试 (all tests)"
    echo ""
    echo "Options:"
    echo "  -f, --filter <pattern>      过滤测试用例 (仅对integration tests有效)"
    echo "  -c, --config <file>         指定配置文件 (仅对integration tests有效)"
    echo "  -v, --verbose              详细输出"
    echo "  --agent-only               仅运行agent调用测试"
    echo "  --regular-only             仅运行常规集成测试"
    echo "  --coverage                生成覆盖率报告"
    echo "  --parallel                并行运行测试"
    echo "  --python <version>         指定Python版本 (如3.10, 3.11)"
    echo "  --fail-fast               遇到第一个失败就停止"
    echo "  -h, --help                显示帮助信息"
    echo ""
    echo "UV Specific Options:"
    echo "  --sync                    同步依赖环境"
    echo "  --clean                   清理并重新创建环境"
    echo ""
    echo "Examples:"
    echo "  $0 integration                    # 运行所有集成测试"
    echo "  $0 integration -f poem            # 运行包含'poem'的集成测试"
    echo "  $0 integration --agent-only       # 仅运行agent调用测试"
    echo "  $0 integration --coverage        # 运行集成测试并生成覆盖率"
    echo "  $0 unit --parallel               # 并行运行单元测试"
    echo "  $0 all --coverage                # 运行所有测试并生成覆盖率"
    echo "  $0 integration --python 3.11      # 使用Python 3.11运行测试"
}

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_step() {
    echo -e "${CYAN}[STEP]${NC} $1"
}

print_uv() {
    echo -e "${PURPLE}[UV]${NC} $1"
}

# Function to calculate duration (fallback if bc not available)
calculate_duration() {
    if command -v bc &> /dev/null; then
        echo "$1" | bc -l 2>/dev/null || echo "$1"
    else
        # Simple fallback: use Python for calculation
        uv run python -c "print($1)" 2>/dev/null || echo "0.0"
    fi
}

# Function to check if uv is available
check_uv() {
    if ! command -v uv &> /dev/null; then
        print_error "uv is not installed. Please install uv first:"
        print_info "curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
}

# Function to setup uv environment
setup_uv_env() {
    print_step "Setting up UV environment..."

    # Check if .venv exists
    if [ ! -d ".venv" ]; then
        print_uv "Creating virtual environment..."
        uv venv
    fi

    # Install dependencies if needed
    if [ "$SYNC" = true ]; then
        print_uv "Syncing dependencies (groups: dev, test)..."
        uv sync --all-extras --group dev --group test
    fi
}

# Function to run integration tests
run_integration_tests() {
    print_step "Running integration tests..."

    local cmd="uv run python -m tests.integration_test.test_runner"

    # Add coverage if requested
    if [ "$COVERAGE" = true ]; then
        cmd="uv run coverage run --source=src -m tests.integration_test.test_runner"
    fi

    if [ ! -z "$CONFIG" ]; then
        cmd="$cmd --config $CONFIG"
    fi

    if [ ! -z "$FILTER" ]; then
        cmd="$cmd --filter $FILTER"
    fi

    if [ "$VERBOSE" = true ]; then
        cmd="$cmd --verbose"
    fi

    if [ "$FAIL_FAST" = true ]; then
        cmd="$cmd --fail-fast"
    fi

    print_info "Executing: $cmd"
    print_info "Working directory: $(pwd)"

    start_time=$(date +%s.%N)

    if eval $cmd; then
        end_time=$(date +%s.%N)
        duration=$(calculate_duration "$end_time - $start_time")
        print_success "Integration tests completed successfully (${duration}s)"

        # Generate coverage report if requested
        if [ "$COVERAGE" = true ]; then
            mv .coverage .coverage.integration
            print_step "Generating coverage report..."
            uv run coverage report --show-missing
            uv run coverage html -d htmlcov/integration
            print_success "Coverage report generated: htmlcov/integration/index.html"
        fi

        return 0
    else
        end_time=$(date +%s.%N)
        duration=$(calculate_duration "$end_time - $start_time")
        print_error "Integration tests failed (${duration}s)"
        return 1
    fi
}

# Function to run unit tests
run_unit_tests() {
    print_step "Running unit tests..."

    local cmd="uv run pytest tests/unittest"

    # Add coverage if requested
    if [ "$COVERAGE" = true ]; then
        cmd="uv run coverage run --source=src -m pytest tests/unittest"
        mv .coverage .coverage.unit
    fi

    if [ "$VERBOSE" = true ]; then
        cmd="$cmd -v"
    fi

    if [ "$PARALLEL" = true ]; then
        cmd="$cmd -n auto"
    fi

    if [ "$FAIL_FAST" = true ]; then
        cmd="$cmd --tb=short --maxfail=1"
    fi

    # Add color output
    cmd="$cmd --color=yes"

    print_info "Executing: $cmd"

    start_time=$(date +%s.%N)

    if eval $cmd; then
        end_time=$(date +%s.%N)
        duration=$(calculate_duration "$end_time - $start_time")
        print_success "Unit tests completed successfully (${duration}s)"

        # Generate coverage report if requested
        if [ "$COVERAGE" = true ]; then
            print_step "Generating coverage report..."
            uv run coverage report --show-missing
            uv run coverage html -d htmlcov/unit
            print_success "Coverage report generated: htmlcov/unit/index.html"
        fi

        return 0
    else
        end_time=$(date +%s.%N)
        duration=$(echo "$end_time - $start_time" | bc -l)
        print_error "Unit tests failed (${duration}s)"
        return 1
    fi
}

# Function to check Python version
check_python_version() {
    if [ ! -z "$PYTHON_VERSION" ]; then
        print_step "Checking Python version..."
        current_version=$(uv run python --version | grep -oP '\d+\.\d+')
        target_version=$(echo $PYTHON_VERSION | grep -oP '\d+\.\d+')

        if [ "$current_version" != "$target_version" ]; then
            print_uv "Switching to Python $PYTHON_VERSION..."
            uv python install $PYTHON_VERSION
            uv venv --python $PYTHON_VERSION
        fi
    fi
}

# Parse command line arguments
if [ $# -eq 0 ]; then
    print_error "No test type specified"
    print_usage
    exit 1
fi

# Check for help first
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    print_usage
    exit 0
fi

TEST_TYPE="$1"
shift

SYNC=false
CLEAN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -f|--filter)
            FILTER="$2"
            shift 2
            ;;
        -c|--config)
            CONFIG="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        --agent-only)
            FILTER="agent"
            shift
            ;;
        --regular-only)
            FILTER="prompt|judge|explore|variable"
            shift
            ;;
        --coverage)
            COVERAGE=true
            shift
            ;;
        --parallel)
            PARALLEL=true
            shift
            ;;
        --python)
            PYTHON_VERSION="$2"
            shift 2
            ;;
        --fail-fast)
            FAIL_FAST=true
            shift
            ;;
        --sync)
            SYNC=true
            shift
            ;;
        --clean)
            CLEAN=true
            shift
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            print_usage
            exit 1
            ;;
    esac
done

# Check if uv is available
check_uv

# Setup environment
setup_uv_env

# Check Python version if specified
check_python_version

# Clean if requested
if [ "$CLEAN" = true ]; then
    print_step "Cleaning environment..."
    rm -rf .venv
    rm -rf htmlcov/
    rm -rf .coverage
    rm -rf .pytest_cache/
    rm -rf .ruff_cache/
    uv venv
    print_uv "Clean environment created"
fi

# Main execution
print_step "Dolphin Language Test Runner (UV Enhanced)"
print_info "Current directory: $(pwd)"
print_info "Test type: $TEST_TYPE"
print_info "Python version: $(uv run python --version)"
print_info "UV version: $(uv --version)"

case $TEST_TYPE in
    integration)
        run_integration_tests
        exit $?
        ;;
    unit)
        if [ ! -z "$FILTER" ] || [ ! -z "$CONFIG" ]; then
            print_warning "Filter and config options are ignored for unit tests"
        fi
        run_unit_tests
        exit $?
        ;;
    all)
        print_step "Running all tests..."
        unit_result=0
        integration_result=0
        all_start_time=$(date +%s.%N)

        # Create coverage combined directory
        if [ "$COVERAGE" = true ]; then
            mkdir -p htmlcov
            rm -f .coverage
        fi

        # Run unit tests first
        if ! run_unit_tests; then
            unit_result=1
        fi

        echo ""

        # Run integration tests
        if ! run_integration_tests; then
            integration_result=1
        fi

        # Merge coverage if both tests ran and coverage is enabled
        if [ "$COVERAGE" = true ] && [ -f ".coverage" ]; then
            if [ -f ".coverage.unit" ]; then
                mv .coverage .coverage.integration
                mv .coverage.unit .coverage
                print_step "Combining coverage reports..."
                uv run coverage combine .coverage.integration .coverage.unit
            fi
            uv run coverage report --show-missing
            uv run coverage html -d htmlcov/combined
            print_success "Combined coverage report generated: htmlcov/combined/index.html"
        fi

        # Summary
        all_end_time=$(date +%s.%N)
        all_duration=$(calculate_duration "$all_end_time - $all_start_time")

        echo ""
        print_step "=== Test Summary ==="
        if [ $unit_result -eq 0 ]; then
            print_success "Unit tests: PASSED"
        else
            print_error "Unit tests: FAILED"
        fi

        if [ $integration_result -eq 0 ]; then
            print_success "Integration tests: PASSED"
        else
            print_error "Integration tests: FAILED"
        fi

        print_info "Total execution time: ${all_duration}s"

        if [ $unit_result -eq 0 ] && [ $integration_result -eq 0 ]; then
            print_success "All tests passed!"
            exit 0
        else
            print_error "Some tests failed!"
            exit 1
        fi
        ;;
    *)
        print_error "Invalid test type: $TEST_TYPE"
        print_usage
        exit 1
        ;;
esac 