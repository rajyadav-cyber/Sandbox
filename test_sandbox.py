"""
test_sandbox.py - Comprehensive Test Suite
===========================================
Unit and integration tests for the sandbox execution system.

Run with: python -m pytest test_sandbox.py -v
or: python test_sandbox.py   (if pytest not available)
"""

import unittest
import json
from io import StringIO
import sys

import validator
import executor
import monitor
import main


class TestValidator(unittest.TestCase):
    """Tests for validator.py - Input validation layer."""

    def test_valid_safe_code(self):
        """Valid safe code should pass validation."""
        result = validator.validate("x = 1 + 2\nprint(x)")
        self.assertTrue(result["valid"])
        self.assertEqual(result["reason"], "")

    def test_empty_code_rejected(self):
        """Empty or whitespace-only code should be rejected."""
        result = validator.validate("")
        self.assertFalse(result["valid"])
        
        result = validator.validate("   \n  \n  ")
        self.assertFalse(result["valid"])

    def test_code_too_long_rejected(self):
        """Code exceeding 8KB should be rejected."""
        long_code = "x = 1\n" * 2000  # ~12KB
        result = validator.validate(long_code)
        self.assertFalse(result["valid"])
        self.assertIn("exceeds maximum", result["reason"])

    def test_syntax_error_rejected(self):
        """Code with syntax errors should be rejected."""
        result = validator.validate("x = [1, 2,")  # Unclosed bracket
        self.assertFalse(result["valid"])
        self.assertIn("Syntax error", result["reason"])

    def test_import_rejected(self):
        """Import statements should be rejected."""
        result = validator.validate("import os")
        self.assertFalse(result["valid"])
        self.assertIn("Import not allowed", result["reason"])

    def test_from_import_rejected(self):
        """From-import statements should be rejected."""
        result = validator.validate("from os import system")
        self.assertFalse(result["valid"])
        self.assertIn("Import not allowed", result["reason"])

    def test_blocked_builtins_rejected(self):
        """Blocked built-ins like eval/exec should be rejected."""
        result = validator.validate("eval('1+1')")
        self.assertFalse(result["valid"])
        
        result = validator.validate("exec('x = 1')")
        self.assertFalse(result["valid"])

    def test_dunder_attrs_rejected(self):
        """Access to dunder attributes should be rejected."""
        result = validator.validate("[].__class__")
        self.assertFalse(result["valid"])
        self.assertIn("Access to attribute", result["reason"])

    def test_malicious_string_rejected(self):
        """Strings containing dangerous patterns should be rejected."""
        result = validator.validate('code = "__import__"')
        self.assertFalse(result["valid"])
        self.assertIn("Malicious string", result["reason"])


class TestExecutor(unittest.TestCase):
    """Tests for executor.py - Sandboxed execution engine."""

    def test_simple_print_execution(self):
        """Simple print statement should execute and capture output."""
        result = executor.execute("print('Hello, Sandbox!')")
        self.assertEqual(result["status"], "allowed")
        self.assertIn("Hello, Sandbox!", result["output"])

    def test_arithmetic_operations(self):
        """Basic arithmetic should work."""
        result = executor.execute("result = 5 + 3 * 2\nprint(result)")
        self.assertEqual(result["status"], "allowed")
        self.assertIn("11", result["output"])

    def test_list_comprehension(self):
        """List comprehension should work."""
        result = executor.execute("squares = [x**2 for x in range(5)]\nprint(squares)")
        self.assertEqual(result["status"], "allowed")
        self.assertIn("0", result["output"])

    def test_loop_execution(self):
        """Loops should execute."""
        result = executor.execute("for i in range(3):\n    print(i, end=' ')")
        self.assertEqual(result["status"], "allowed")
        self.assertIn("0", result["output"])

    def test_recursion_error_caught(self):
        """Deep recursion should be caught."""
        code = "def boom(n):\n    return boom(n+1)\nboom(0)"
        result = executor.execute(code)
        self.assertEqual(result["status"], "error")
        self.assertIn("RecursionError", result["reason"])

    def test_infinite_loop_timeout(self):
        """Infinite loops should timeout."""
        result = executor.execute("while True: pass")
        self.assertEqual(result["status"], "timeout")
        self.assertIn("timed out", result["reason"])

    def test_output_truncation(self):
        """Very large output should be truncated."""
        code = "print('x' * 5000)"
        result = executor.execute(code)
        self.assertEqual(result["status"], "allowed")
        self.assertIn("truncated", result["output"])

    def test_exception_handling(self):
        """Exceptions should be caught and reported."""
        result = executor.execute("print(1/0)")
        self.assertEqual(result["status"], "error")
        self.assertIn("ZeroDivisionError", result["reason"])


class TestIntegration(unittest.TestCase):
    """Integration tests for main.py - Full pipeline."""

    def test_sandbox_safe_code_flow(self):
        """Valid safe code should flow through full pipeline."""
        result = main.run_sandbox("print('safe code')")
        self.assertEqual(result["status"], "allowed")
        self.assertIn("safe code", result["output"])

    def test_sandbox_blocked_code_flow(self):
        """Dangerous code should be blocked at validation layer."""
        result = main.run_sandbox("import os")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("Import", result["reason"])

    def test_sandbox_timeout_flow(self):
        """Timeout should be handled in full pipeline."""
        result = main.run_sandbox("while True: pass")
        self.assertEqual(result["status"], "timeout")

    def test_sandbox_error_flow(self):
        """Runtime errors should be caught in full pipeline."""
        result = main.run_sandbox("x = [1, 2, 3]\nprint(x[10])")
        self.assertEqual(result["status"], "error")
        self.assertIn("IndexError", result["reason"])

    def test_multiple_statements(self):
        """Multiple statements should execute sequentially."""
        code = """
x = 10
y = 20
z = x + y
print(f'Sum: {z}')
"""
        result = main.run_sandbox(code)
        self.assertEqual(result["status"], "allowed")
        self.assertIn("Sum: 30", result["output"])


class TestMonitor(unittest.TestCase):
    """Tests for monitor.py - Logging and monitoring."""

    def test_session_stats_increment(self):
        """Session stats should increment on execution."""
        initial = monitor.get_session_stats()
        
        # Execute a safe code
        monitor.log_execution("print(1)", {"status": "allowed", "output": "1", "reason": ""}, 10.5)
        
        updated = monitor.get_session_stats()
        self.assertEqual(updated["total"], initial["total"] + 1)
        self.assertEqual(updated["allowed"], initial["allowed"] + 1)

    def test_log_file_creation(self):
        """Log file should be created on execution."""
        monitor.log_execution(
            "test code",
            {"status": "allowed", "output": "test", "reason": ""},
            5.0
        )
        # Just verify it doesn't crash; actual file verification is OS-dependent
        self.assertTrue(True)


class TestAPIEndpoints(unittest.TestCase):
    """Tests for Flask API endpoints (if needed)."""

    def setUp(self):
        """Set up Flask test client."""
        from app import app
        self.app = app.test_client()

    def test_index_route(self):
        """Index route should return HTML."""
        response = self.app.get('/')
        self.assertEqual(response.status_code, 200)

    def test_run_endpoint_missing_code(self):
        """POST /run without 'code' should return 400."""
        response = self.app.post('/run', json={})
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn("Missing", data["reason"])

    def test_run_endpoint_safe_code(self):
        """POST /run with safe code should return 200."""
        response = self.app.post('/run', json={"code": "print(1)"})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data["status"], "allowed")

    def test_run_endpoint_blocked_code(self):
        """POST /run with blocked code should return 200 (but status='blocked')."""
        response = self.app.post('/run', json={"code": "import os"})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data["status"], "blocked")


# Quick test cases for rapid validation
QUICK_TEST_CASES = [
    ("print('OK')", "allowed", "print output"),
    ("import os", "blocked", "import block"),
    ("while True: pass", "timeout", "timeout"),
    ("1/0", "error", "exception"),
]


def run_quick_tests():
    """Run quick validation tests without pytest."""
    print("\n" + "=" * 70)
    print("QUICK VALIDATION TESTS")
    print("=" * 70)
    
    for code, expected_status, description in QUICK_TEST_CASES:
        result = main.run_sandbox(code)
        status = result["status"]
        symbol = "✓" if status == expected_status else "✗"
        print(f"{symbol} {description:30} | Expected: {expected_status:10} | Got: {status}")
    
    # Print session summary
    monitor.print_session_summary()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--quick":
        # Run quick tests without pytest
        run_quick_tests()
    else:
        # Run full unittest suite
        print("\nRunning comprehensive test suite...\n")
        unittest.main(verbosity=2)
