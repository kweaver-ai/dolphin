#!/usr/bin/env python3
"""
Multi-Tool Calls Integration Test Validator

This script validates the integration test configuration without running actual LLM calls.
It checks:
1. Test configuration files exist and are valid JSON
2. Dolphin script files exist
3. Feature flags are properly configured
4. Test case structure is correct
"""

import json
import os
import sys
from pathlib import Path

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

def print_success(msg):
    print(f"{Colors.GREEN}✓{Colors.END} {msg}")

def print_error(msg):
    print(f"{Colors.RED}✗{Colors.END} {msg}")

def print_warning(msg):
    print(f"{Colors.YELLOW}⚠{Colors.END} {msg}")

def print_info(msg):
    print(f"{Colors.BLUE}ℹ{Colors.END} {msg}")

def validate_test_config(config_path):
    """Validate test configuration file"""
    print(f"\n{Colors.BLUE}Validating test configuration:{Colors.END} {config_path}")
    
    if not os.path.exists(config_path):
        print_error(f"Config file not found: {config_path}")
        return False
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print_error(f"Invalid JSON: {e}")
        return False
    
    print_success("JSON format is valid")
    
    # Check test suite metadata
    if 'testSuite' not in config:
        print_error("Missing 'testSuite' key")
        return False
    
    print_success(f"Test Suite: {config['testSuite'].get('name', 'Unknown')}")
    
    # Check test cases
    if 'testCases' not in config:
        print_error("Missing 'testCases' key")
        return False
    
    test_cases = config['testCases']
    print_info(f"Found {len(test_cases)} test cases")
    
    all_valid = True
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n  Test Case {i}: {test_case.get('name', 'Unknown')}")
        
        # Check required fields
        required_fields = ['name', 'description', 'parameters', 'dolphinLangPath', 'expectedResult']
        for field in required_fields:
            if field not in test_case:
                print_error(f"    Missing required field: {field}")
                all_valid = False
            else:
                print_success(f"    Has {field}")
        
        # Check dolphin script file
        if 'dolphinLangPath' in test_case:
            script_path = os.path.join(
                os.path.dirname(config_path),
                '..',
                test_case['dolphinLangPath']
            )
            if os.path.exists(script_path):
                print_success(f"    Dolphin script exists: {test_case['dolphinLangPath']}")
            else:
                print_error(f"    Dolphin script not found: {script_path}")
                all_valid = False
        
        # Check feature flags
        if 'parameters' in test_case and 'variables' in test_case['parameters']:
            variables = test_case['parameters']['variables']
            flags = {k: v for k, v in variables.items() if k.startswith('enable_') or k.startswith('disable_')}
            if flags:
                print_info(f"    Feature flags: {flags}")
            else:
                print_warning("    No feature flags configured")
        
        # Check expected result
        if 'expectedResult' in test_case:
            expected = test_case['expectedResult']
            if 'tools' in expected and expected['tools']:
                print_info(f"    Expected tools: {expected['tools']}")
            if 'contentKeywords' in expected and expected['contentKeywords']:
                print_info(f"    Expected keywords: {expected['contentKeywords']}")
    
    return all_valid

def validate_dolphin_scripts(base_dir):
    """Validate dolphin script files"""
    print(f"\n{Colors.BLUE}Validating Dolphin scripts:{Colors.END}")
    
    dolphins_dir = os.path.join(base_dir, 'dolphins')
    if not os.path.exists(dolphins_dir):
        print_error(f"Dolphins directory not found: {dolphins_dir}")
        return False
    
    scripts = [
        'multi_tool_calls_basic.dph',
        'multi_tool_calls_two_tools.dph',
        'multi_tool_calls_error_handling.dph',
        'multi_tool_calls_backward_compat.dph'
    ]
    
    all_valid = True
    for script in scripts:
        script_path = os.path.join(dolphins_dir, script)
        if os.path.exists(script_path):
            print_success(f"Found: {script}")
            
            # Check file content
            with open(script_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    print_info(f"  Content preview: {content[:80]}...")
                else:
                    print_warning(f"  File is empty")
                    all_valid = False
        else:
            print_error(f"Missing: {script}")
            all_valid = False
    
    return all_valid

def check_dependencies():
    """Check if required dependencies are available"""
    print(f"\n{Colors.BLUE}Checking dependencies:{Colors.END}")
    
    try:
        import dolphin
        print_success("dolphin package is installed")
    except ImportError:
        print_error("dolphin package not found. Run: pip install -e .")
        return False
    
    try:
        from dolphin.core import flags
        print_success("dolphin.core.flags module is available")
        
        # Check if ENABLE_PARALLEL_TOOL_CALLS flag exists
        if hasattr(flags, 'ENABLE_PARALLEL_TOOL_CALLS'):
            print_success(f"ENABLE_PARALLEL_TOOL_CALLS flag exists: {flags.ENABLE_PARALLEL_TOOL_CALLS}")
        else:
            print_error("ENABLE_PARALLEL_TOOL_CALLS flag not found")
            return False
    except ImportError as e:
        print_error(f"Failed to import flags module: {e}")
        return False
    
    return True

def main():
    """Main validation function"""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BLUE}Multi-Tool Calls Integration Test Validator{Colors.END}")
    print(f"{Colors.BLUE}{'='*60}{Colors.END}")
    
    # Get script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.join(script_dir, '..')
    
    # Validate test configuration
    config_path = os.path.join(script_dir, 'multi_tool_calls_cases.json')
    config_valid = validate_test_config(config_path)
    
    # Validate dolphin scripts
    scripts_valid = validate_dolphin_scripts(base_dir)
    
    # Check dependencies
    deps_valid = check_dependencies()
    
    # Summary
    print(f"\n{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BLUE}Validation Summary:{Colors.END}")
    print(f"{Colors.BLUE}{'='*60}{Colors.END}")
    
    if config_valid:
        print_success("Test configuration is valid")
    else:
        print_error("Test configuration has errors")
    
    if scripts_valid:
        print_success("Dolphin scripts are valid")
    else:
        print_error("Dolphin scripts have errors")
    
    if deps_valid:
        print_success("Dependencies are satisfied")
    else:
        print_error("Dependencies are missing")
    
    all_valid = config_valid and scripts_valid and deps_valid
    
    if all_valid:
        print(f"\n{Colors.GREEN}✓ All validations passed!{Colors.END}")
        print(f"\n{Colors.BLUE}Next steps:{Colors.END}")
        print("  1. Configure your LLM API in config/global.yaml")
        print("  2. Run tests: python test_runner.py --config testcases/multi_tool_calls_cases.json")
        return 0
    else:
        print(f"\n{Colors.RED}✗ Some validations failed. Please fix the errors above.{Colors.END}")
        return 1

if __name__ == '__main__':
    sys.exit(main())
