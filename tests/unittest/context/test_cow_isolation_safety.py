
import pytest
import threading
from dolphin.core.context.context import Context
from dolphin.core.context.cow_context import COWContext

def test_cow_uncopyable_object_fail_fast():
    """Verify that uncopyable objects (like threading.Lock) raise TypeError (fail-fast)."""
    # 1. Create parent Context and set an uncopyable object
    parent = Context()
    lock = threading.Lock()
    parent.set_variable("my_lock", lock)
    
    # 2. Create COW sub-context
    cow = COWContext(parent, "subtask_1")
    
    # 3. Read variable, expect TypeError
    with pytest.raises(TypeError) as excinfo:
        cow.get_variable("my_lock")
    
    assert "not deepcopyable" in str(excinfo.value)
    print("\n[V] Successfully verified fail-fast behavior for uncopyable objects in COWContext.")

def test_cow_mutable_isolation():
    # 验证常规 mutable 对象 (list) 的深度隔离
    parent = Context()
    parent.set_variable("data", [1, 2, 3])
    
    cow = COWContext(parent, "subtask_1")
    sub_data = cow.get_var_value("data")
    sub_data.append(4) 
    cow.set_variable("data", sub_data) # 必须显式写回
    
    assert parent.get_var_value("data") == [1, 2, 3] # 父上下文依然不受影响
    assert cow.get_var_value("data") == [1, 2, 3, 4] # 子上下文读取到了更新
    print("[V] Mutable list isolation and explicit write-back verified.")
