#!/usr/bin/env python3
"""
测试 verbose 参数集成功能

这个测试脚本验证：
1. Context 类正确存储和获取 verbose 状态
2. DolphinExecutor 正确传递 verbose 参数给 Context
3. console 函数正确响应 verbose 参数
4. 整个集成链条工作正常
"""

import shutil

from dolphin.core.context.context import Context
from dolphin.core.executor.dolphin_executor import DolphinExecutor
from dolphin.core.logging.logger import console, console_skill_call, console_block_start


def test_context_verbose():
    """测试 Context 类的 verbose 功能"""
    print("=== 测试 Context verbose 功能 ===")

    # 测试启用 verbose
    context_verbose = Context(verbose=True)
    assert context_verbose.is_verbose() == True, "启用 verbose 失败"
    assert context_verbose.get_verbose() == True, "获取 verbose 状态失败"
    print("✓ 启用 verbose 测试通过")

    # 测试禁用 verbose
    context_no_verbose = Context(verbose=False)
    assert context_no_verbose.is_verbose() == False, "禁用 verbose 失败"
    assert context_no_verbose.get_verbose() == False, "获取 verbose 状态失败"
    print("✓ 禁用 verbose 测试通过")

    # 测试设置 verbose
    context_no_verbose.set_verbose(True)
    assert context_no_verbose.is_verbose() == True, "动态设置 verbose 失败"
    print("✓ 动态设置 verbose 测试通过")

    # 测试 copy 功能
    copied_context = context_verbose.copy()
    assert copied_context.is_verbose() == True, "copy 功能未保留 verbose 设置"
    print("✓ copy 功能测试通过")


def test_dolphin_executor_verbose():
    """测试 DolphinExecutor 的 verbose 功能"""
    print("\n=== 测试 DolphinExecutor verbose 功能 ===")

    # 测试启用 verbose
    executor_verbose = DolphinExecutor(verbose=True)
    assert executor_verbose.context.is_verbose() == True, (
        "DolphinExecutor 未正确传递 verbose 给 Context"
    )
    print("✓ DolphinExecutor 启用 verbose 测试通过")

    # 测试禁用 verbose
    executor_no_verbose = DolphinExecutor(verbose=False)
    assert executor_no_verbose.context.is_verbose() == False, (
        "DolphinExecutor 未正确传递 verbose 给 Context"
    )
    print("✓ DolphinExecutor 禁用 verbose 测试通过")


def test_console_functions_verbose():
    """测试 console 函数的 verbose 功能"""
    print("\n=== 测试 console 函数 verbose 功能 ===")

    # 测试 console 函数
    print("测试 console 函数（应该显示）:")
    console("这是 verbose=True 的消息", verbose=True)

    print("测试 console 函数（不应该显示）:")
    console("这是 verbose=False 的消息", verbose=False)

    # 测试 console_skill_call 函数
    print("\n测试 console_skill_call 函数:")
    console_skill_call("test_skill", {"param": "value"}, verbose=True)
    console_skill_call("test_skill", {"param": "value"}, verbose=False)

    # 测试 console_block_start 函数
    print("\n测试 console_block_start 函数:")
    console_block_start("explore", "output_var", "测试内容", verbose=True)
    console_block_start("explore", "output_var", "测试内容", verbose=False)


def test_verbose_integration_chain():
    """测试 verbose 参数的完整集成链"""
    print("\n=== 测试 verbose 参数完整集成链 ===")

    # 1. 创建 DolphinExecutor 时传入 verbose=True
    executor = DolphinExecutor(verbose=True)

    # 2. 验证 Context 获取到正确的 verbose 状态
    assert executor.context.is_verbose() == True, (
        "集成链断裂：Context 未获取到正确的 verbose 状态"
    )

    # 3. 在业务代码中使用 verbose 状态
    is_verbose = executor.context.is_verbose()

    # 4. 传递给 console 函数
    print("以下是集成链测试输出（verbose=True 时应该显示）：")
    console("集成链测试消息", verbose=is_verbose)
    console_skill_call("chain_test_skill", {"integration": "test"}, verbose=is_verbose)
    console_block_start("chain_test", "output", "集成测试", verbose=is_verbose)

    print("✓ verbose 参数完整集成链测试通过")


def test_backward_compatibility():
    """测试向后兼容性"""
    print("\n=== 测试向后兼容性 ===")

    # 测试不传入 verbose 参数时的默认行为
    context = Context()  # 默认 verbose=False
    assert context.is_verbose() == False, "默认 verbose 值不正确"

    executor = DolphinExecutor()  # 默认 verbose=False
    assert executor.context.is_verbose() == False, "默认 verbose 值不正确"

    # 测试 console 函数的向后兼容性
    print("测试向后兼容性（应该显示，因为使用默认行为）：")
    console("这是向后兼容性测试消息")  # 不传入 verbose 参数，使用默认行为

    print("✓ 向后兼容性测试通过")


def cleanup_test_files():
    """清理测试文件"""
    # 清理可能的临时文件
    temp_dirs = ["temp_test", "log"]
    for dir_name in temp_dirs:
        if os.path.exists(dir_name):
            if os.path.isdir(dir_name):
                shutil.rmtree(dir_name)
            else:
                os.remove(dir_name)


def main():
    """运行所有测试"""
    print("开始测试 verbose 参数集成功能...\n")

    try:
        # 清理之前的测试文件
        cleanup_test_files()

        # 运行所有测试
        test_context_verbose()
        test_dolphin_executor_verbose()
        test_console_functions_verbose()
        test_verbose_integration_chain()
        test_backward_compatibility()

        print("\n" + "=" * 60)
        print("🎉 所有测试通过！verbose 参数集成功能正常工作。")
        print("=" * 60)

        print("\n使用说明:")
        print("1. 在 bin/dolphin 脚本中使用 --verbose 参数启用详细输出")
        print("2. 在代码中通过 context.is_verbose() 获取 verbose 状态")
        print("3. 将 verbose 状态传递给 console_* 函数控制输出")
        print("4. 旧代码仍然可以正常工作，保持向后兼容")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    finally:
        # 清理测试文件
        cleanup_test_files()


if __name__ == "__main__":
    main()
