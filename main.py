"""
main.py - Controlled Execution Sandbox - Entry Point
=====================================================
Wires together validator.py, executor.py, and monitor.py into a complete
sandbox pipeline. Provides:

    1. run_sandbox(code) - The main public API used by any caller.
    2. A full attack simulation test suite (ran by default).
    3. An optional --interactive CLI mode for manual testing.

Usage:
    python main.py                     # Run all attack simulation tests
    python main.py --interactive       # Start interactive prompt
    python main.py --code "print(42)"  # Run a single snippet

Author: Controlled Execution Sandbox
"""

import argparse
import json
import sys
import time
from typing import Any


import validator
import executor
import monitor


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def run_sandbox(code: str) -> dict[str, Any]:
    """
    Full sandbox pipeline: validate -> execute -> log -> return result.

    Args:
        code: Raw Python code snippet from the user (untrusted).

    Returns:
        Structured response dict:
            {
                "status":  "allowed" | "blocked" | "error" | "timeout",
                "output":  "<stdout captured from print() calls>",
                "reason":  "<human-readable explanation>",
            }
    """
    t_start = time.monotonic()

    # -- Layer 1: Static AST validation -----------------------------------
    validation = validator.validate(code)

    if not validation["valid"]:
        result: dict[str, Any] = {
            "status": "blocked",
            "output": "",
            "reason": validation["reason"],
        }
        elapsed_ms = (time.monotonic() - t_start) * 1000
        monitor.log_execution(code, result, elapsed_ms)
        return result

    # -- Layer 2 + 3 + 4: Sandboxed execution (timeout + resource limits) -
    result = executor.execute(code)

    elapsed_ms = (time.monotonic() - t_start) * 1000

    # -- Layer 5: Log everything ------------------------------------------
    monitor.log_execution(code, result, elapsed_ms)

    return result


# ---------------------------------------------------------------------------
# Attack simulation test suite
# ---------------------------------------------------------------------------

# Each test case is a tuple of:
#   (description, code_snippet, expected_status)
ATTACK_TEST_CASES: list[tuple[str, str, str]] = [

    # ---- Safe code -------------------------------------------------------
    (
        "[OK] Safe: sum of range",
        "result = sum(range(1, 101))\nprint(f'Sum 1..100 = {result}')",
        "allowed",
    ),
    (
        "[OK] Safe: list comprehension",
        "squares = [x**2 for x in range(10)]\nprint(squares)",
        "allowed",
    ),
    (
        "[OK] Safe: fibonacci loop",
        (
            "a, b = 0, 1\n"
            "for _ in range(10):\n"
            "    print(a, end=' ')\n"
            "    a, b = b, a + b"
        ),
        "allowed",
    ),

    # ---- Import attacks --------------------------------------------------
    (
        "[!!] Import: import os",
        "import os\nos.system('whoami')",
        "blocked",
    ),
    (
        "[!!] Import: from subprocess import run",
        "from subprocess import run\nrun(['cat', '/etc/passwd'])",
        "blocked",
    ),
    (
        "[!!] Import: __import__ builtin call",
        "__import__('os').system('dir')",
        "blocked",
    ),
    (
        "[!!] Import: importlib string in literal",
        "s = '__import__(\"os\")'\nprint(s)",
        "blocked",
    ),

    # ---- File system attacks ---------------------------------------------
    (
        "[!!] File access: open() direct call",
        "f = open('/etc/passwd', 'r')\nprint(f.read())",
        "blocked",
    ),

    # ---- Dunder / MRO escape attacks ------------------------------------
    (
        "[!!] Dunder: __subclasses__() chain",
        "().__class__.__bases__[0].__subclasses__()",
        "blocked",
    ),
    (
        "[!!] Dunder: __globals__ via function",
        "def f(): pass\nprint(f.__globals__)",
        "blocked",
    ),
    (
        "[!!] Dunder: __class__ access",
        "x = ().__class__\nprint(x)",
        "blocked",
    ),

    # ---- Builtin abuse --------------------------------------------------
    (
        "[!!] Builtin: eval() call",
        "eval('1 + 1')",
        "blocked",
    ),
    (
        "[!!] Builtin: exec() call",
        "exec('print(42)')",
        "blocked",
    ),
    (
        "[!!] Builtin: getattr() call",
        "getattr(list, 'append')",
        "blocked",
    ),

    # ---- Resource exhaustion --------------------------------------------
    (
        "[TT] Timeout: infinite loop",
        "while True:\n    pass",
        "timeout",
    ),
    (
        "[WW] Error: infinite recursion",
        "def boom():\n    return boom()\nboom()",
        "error",   # RecursionError fires fast due to low recursion limit
    ),
    (
        "[WW] Memory: large list allocation (system-dependent)",
        "x = [0] * (10 ** 8)\nprint(len(x))",
        "allowed",  # Outcome is system-dependent: MemoryError on Linux with
                    # setrlimit, allowed on Windows (large virtual address space).
                    # Either is a valid sandbox response.
    ),

    # ---- Runtime errors -------------------------------------------------
    (
        "[WW] Error: division by zero",
        "print(1 / 0)",
        "error",
    ),
    (
        "[WW] Error: missing dict key",
        "d = {}\nprint(d['missing'])",
        "error",
    ),

    # ---- Creative bypass attempts ---------------------------------------
    (
        "[!!] Bypass: string-encoded __import__ for eval",
        "s = '__import__(\"os\")'\nx = eval(s)",
        "blocked",
    ),
    (
        "[!!] Bypass: class MRO attribute chain",
        "x = ().__class__.__bases__\nprint(x)",
        "blocked",
    ),
]


def run_attack_simulations() -> None:
    """Run all attack test cases and print a formatted results table."""
    SEP  = "=" * 82
    DASH = "-" * 82

    print("\n" + SEP)
    print("  CONTROLLED EXECUTION SANDBOX -- ATTACK SIMULATION SUITE")
    print(SEP)
    print(f"  {'#':<3}  {'SCENARIO':<40}  {'EXPECTED':<9}  {'ACTUAL':<9}  PASS?")
    print(DASH)

    pass_count = 0
    fail_count = 0
    total = len(ATTACK_TEST_CASES)

    for idx, (description, code, expected_status) in enumerate(ATTACK_TEST_CASES, 1):
        result = run_sandbox(code)
        actual_status = result["status"]
        passed = (actual_status == expected_status)

        if passed:
            pass_count += 1
            mark = "PASS"
        else:
            fail_count += 1
            mark = "FAIL"

        # Truncate description to fit column width
        desc_col = description[:40].ljust(40)
        print(
            f"  {idx:<3}  {desc_col}  "
            f"{expected_status:<9}  {actual_status:<9}  {mark}",
            flush=True,
        )

        # Print the reason summarised on an indented line
        reason = result.get("reason", "")
        if reason:
            print(f"       |-> {reason[:72]}", flush=True)
        sys.stdout.flush()

    print(DASH)
    print(f"  Results: {pass_count}/{total} passed  |  {fail_count} failed")
    print(SEP)

    monitor.print_session_summary()


# ---------------------------------------------------------------------------
# Interactive REPL
# ---------------------------------------------------------------------------

def run_interactive() -> None:
    """Start an interactive sandbox prompt."""
    SEP = "=" * 62
    print("\n" + SEP)
    print("  SANDBOX INTERACTIVE MODE")
    print("  Enter Python code. Blank line = execute. 'exit' = quit.")
    print(SEP + "\n")

    while True:
        lines: list[str] = []
        try:
            print(">>> ", end="", flush=True)
            while True:
                line = input()
                if line.strip().lower() in ("exit", "quit"):
                    print("Goodbye.")
                    monitor.print_session_summary()
                    return
                if line == "" and lines:
                    break
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            print("\nInterrupted.")
            monitor.print_session_summary()
            return

        code = "\n".join(lines)
        result = run_sandbox(code)

        print("\n" + json.dumps(result, indent=2) + "\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Controlled Execution Sandbox - safe Python execution engine"
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Start an interactive sandbox REPL",
    )
    parser.add_argument(
        "--code", "-c",
        type=str,
        default=None,
        help="Execute a single code snippet and print the JSON result",
    )
    args = parser.parse_args()

    if args.code:
        result = run_sandbox(args.code)
        print(json.dumps(result, indent=2))
    elif args.interactive:
        run_interactive()
    else:
        run_attack_simulations()


if __name__ == "__main__":
    main()
