"""
Test tool interrupt handling with multiple arun calls

This test simulates the executor service pattern where each interrupt
triggers a new arun() call, which can expose performance issues.

Issue: @tool syntax interrupt response time regression
Related Commits: 42736d9, 08c22c9
"""

import asyncio
import pytest
import time
from typing import Dict, Any

from dolphin.sdk import DolphinAgent
from dolphin.core.config.global_config import GlobalConfig


class MockToolWithInterrupt:
    """Mock tool that requires confirmation"""
    
    def __init__(self, name: str, delay_ms: int = 100):
        self.tool_name = name
        self.name = name
        self.description = f"Test tool: {name}"
        self.delay_ms = delay_ms
        self.call_count = 0
        
        # Interrupt configuration
        self.interrupt_config = {
            "requires_confirmation": True,
            "confirmation_message": f"Confirm execution of {name}?"
        }
        
        self.parameters = {
            "type": "object",
            "properties": {
                "param": {
                    "type": "string",
                    "description": "Test parameter"
                }
            },
            "required": ["param"]
        }
        
        self.inputs = {
            "param": {
                "type": "string",
                "description": "Test parameter",
                "required": True
            }
        }
        
        self.outputs = {
            "result": {
                "type": "string",
                "description": "Tool execution result"
            }
        }
        
        # Result process strategy (required by TriditionalToolkit)
        self.result_process_strategy_cfg = [
            {"strategy": "default", "category": "app"},
            {"strategy": "default", "category": "llm"}
        ]
    
    async def arun_stream(self, **kwargs):
        """Async stream execution"""
        self.call_count += 1
        await asyncio.sleep(self.delay_ms / 1000)
        
        tool_input = kwargs.get("tool_input", {})
        if isinstance(tool_input, dict) and tool_input:
            params = tool_input
        else:
            params = {k: v for k, v in kwargs.items() if k not in ["tool_input", "props", "gvp"]}
        
        param = params.get("param", "unknown")
        result = f"Tool {self.name} executed with param={param}, call_count={self.call_count}"
        yield result
    
    def get_tool_json(self):
        return {
            "name": self.tool_name,
            "description": self.description,
            "parameters": self.parameters
        }
    
    def get_function_name(self) -> str:
        return self.name


@pytest.mark.asyncio
async def test_tool_interrupt_single_arun_baseline():
    """Baseline test: single arun with inline interrupt handling"""
    from dolphin.sdk.tool.traditional_toolkit import TriditionalToolkit
    
    # Create tool
    tool = MockToolWithInterrupt("test_tool", delay_ms=50)
    tools = {"test_tool": tool}
    toolkit = TriditionalToolkit.buildFromTooldict(tools)
    
    # Simple dolphin script - just call the tool
    dolphin_content = '@test_tool(param="test_value") -> result'
    
    global_config = GlobalConfig()
    agent = DolphinAgent(
        content=dolphin_content,
        global_config=global_config,
        skillkit=toolkit,
        verbose=False
    )
    
    await agent.initialize()
    
    # Test with inline interrupt handling (original test script pattern)
    interrupt_count = 0
    start_time = time.time()
    interrupt_response_times = []
    completed = False
    
    # Need to keep iterating after resume in single arun mode
    while not completed:
        async for result in agent.arun(stream_variables=True):
            if isinstance(result, dict):
                if result.get("status") == "interrupted":
                    interrupt_count += 1
                    response_time = (time.time() - start_time) * 1000
                    interrupt_response_times.append(response_time)
                    
                    # Inline resume (same arun) - continue without breaking
                    await agent.resume(updates={
                        "tool": {
                            "tool_name": "test_tool",
                            "tool_args": [{"key": "param", "value": "test_value"}],
                            "action": "confirm"
                        }
                    })
                    # After resume, break and restart arun loop to continue execution
                    break
                elif result.get("_status") == "completed":
                    completed = True
                    break
        
        # Check if agent completed
        from dolphin.core.agent.agent_state import AgentState
        if agent.state == AgentState.COMPLETED:
            completed = True
    
    total_time = (time.time() - start_time) * 1000
    
    # Assertions
    assert interrupt_count == 1, f"Should have exactly 1 interrupt, got {interrupt_count}"
    assert tool.call_count == 1, f"Tool should be called once, got {tool.call_count}"
    
    # Performance should be good (no multiple arun overhead)
    if interrupt_response_times:
        avg_response_time = sum(interrupt_response_times) / len(interrupt_response_times)
        print(f"\nBaseline - Avg interrupt response time: {avg_response_time:.2f} ms")
        print(f"Baseline - Total time: {total_time:.2f} ms")
        assert avg_response_time < 200, f"Baseline response time too slow: {avg_response_time}ms"


@pytest.mark.asyncio
async def test_tool_interrupt_multiple_arun_pattern():
    """Test multiple arun pattern (executor service style) - reproduces the issue"""
    from dolphin.sdk.tool.traditional_toolkit import TriditionalToolkit
    
    # Create tool
    tool = MockToolWithInterrupt("test_tool", delay_ms=50)
    tools = {"test_tool": tool}
    toolkit = TriditionalToolkit.buildFromTooldict(tools)
    
    # Simple dolphin script - just call the tool
    dolphin_content = '@test_tool(param="test_value") -> result'
    
    global_config = GlobalConfig()
    agent = DolphinAgent(
        content=dolphin_content,
        global_config=global_config,
        skillkit=toolkit,
        verbose=False
    )
    
    await agent.initialize()
    
    # Test with multiple arun pattern (executor service pattern)
    interrupt_count = 0
    arun_call_count = 0
    interrupt_response_times = []
    
    while True:
        interrupted = False
        saved_handle = None
        
        # Each iteration is a new arun call (like executor service)
        arun_call_count += 1
        arun_start_time = time.time()
        
        print(f"\n[TEST] Starting arun call #{arun_call_count}")
        
        async for result in agent.arun(stream_variables=True):
            if isinstance(result, dict) and result.get("status") == "interrupted":
                interrupt_count += 1
                response_time = (time.time() - arun_start_time) * 1000
                interrupt_response_times.append(response_time)
                
                print(f"[TEST] Interrupt #{interrupt_count}, response time: {response_time:.2f} ms")
                
                interrupted = True
                saved_handle = result.get("handle")
                
                # Break to exit current arun (executor pattern)
                break
        
        if interrupted:
            # Resume outside of arun loop (executor pattern)
            print(f"[TEST] Calling resume()")
            await agent.resume(updates={
                "tool": {
                    "tool_name": "test_tool",
                    "tool_args": [{"key": "param", "value": "test_value"}],
                    "action": "confirm"
                }
            }, resume_handle=saved_handle)
            
            # Continue to next arun call
            continue
        
        # Check if completed
        from dolphin.core.agent.agent_state import AgentState
        if agent.state == AgentState.COMPLETED:
            print(f"[TEST] Agent completed")
            break
    
    # Assertions
    assert interrupt_count == 1, "Should have exactly 1 interrupt"
    assert tool.call_count == 1, "Tool should be called once"
    assert arun_call_count >= 2, "Should have at least 2 arun calls (initial + after resume)"
    
    # Performance check - with fix, should be fast
    if interrupt_response_times:
        avg_response_time = sum(interrupt_response_times) / len(interrupt_response_times)
        max_response_time = max(interrupt_response_times)
        
        print(f"\nMultiple arun pattern:")
        print(f"  - Total arun calls: {arun_call_count}")
        print(f"  - Interrupt count: {interrupt_count}")
        print(f"  - Avg response time: {avg_response_time:.2f} ms")
        print(f"  - Max response time: {max_response_time:.2f} ms")
        
        # With the fix, response time should be < 50ms
        # Without the fix, it would be 100-150ms (due to 0.1s timeout)
        assert avg_response_time < 100, \
            f"Response time too slow: {avg_response_time}ms (expected <100ms with fix)"
        
        # More strict check: should ideally be < 50ms
        if avg_response_time < 50:
            print(f"  [OK] Response time is excellent (<50ms)")
        else:
            print(f"  [WARN] Response time is acceptable but could be better ({avg_response_time:.2f}ms)")


@pytest.mark.asyncio
async def test_interrupt_response_time_regression():
    """Regression test to ensure interrupt response time stays below threshold"""
    from dolphin.sdk.tool.traditional_toolkit import TriditionalToolkit
    
    # Create tool
    tool = MockToolWithInterrupt("fast_tool", delay_ms=10)
    tools = {"fast_tool": tool}
    toolkit = TriditionalToolkit.buildFromTooldict(tools)
    
    # Simple dolphin script
    dolphin_content = '@fast_tool(param="test") -> result'
    
    global_config = GlobalConfig()
    agent = DolphinAgent(
        content=dolphin_content,
        global_config=global_config,
        skillkit=toolkit,
        verbose=False
    )
    
    await agent.initialize()
    
    # Measure interrupt response time with multiple arun pattern
    arun_start_time = time.time()
    interrupt_detected = False
    
    async for result in agent.arun(stream_variables=True):
        if isinstance(result, dict) and result.get("status") == "interrupted":
            response_time = (time.time() - arun_start_time) * 1000
            interrupt_detected = True
            
            print(f"\nInterrupt response time: {response_time:.2f} ms")
            
            # Strict performance requirement
            # With fix: should be < 20ms
            # Without fix: would be 100-150ms
            assert response_time < 50, \
                f"REGRESSION: Interrupt response time {response_time:.2f}ms exceeds threshold of 50ms"
            
            if response_time < 20:
                print("  [OK] Excellent performance (<20ms)")
            elif response_time < 50:
                print("  [OK] Good performance (<50ms)")
            
            break
    
    assert interrupt_detected, "Should detect interrupt"


if __name__ == "__main__":
    # Run tests
    import sys
    pytest.main([__file__, "-v", "-s"] + sys.argv[1:])
