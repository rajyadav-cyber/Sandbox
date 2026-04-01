"""
executor.py — Sandboxed Python Execution Engine
================================================
This module is the heart of the sandbox. It takes code that has already
been approved by validator.py and executes it in the most restricted
Python environment that can be constructed inside a single process.

Defence layers applied here (in order):
    1. Restricted __builtins__ dict  — limits what names are visible
    2. Isolated globals namespace    — no access to real module state
    3. stdout capture                — collect print() output safely
    4. Threading timeout (2 s)       — kills hanging / infinite-loop code
    5. setrlimit (Linux only)        — hard OS-level memory & CPU cap
    6. Output truncation             — prevent megabyte-sized outputs

Limitations (documented honestly):
    - Python threads cannot be truly killed; a timed-out thread continues
      consuming resources until the GIL yields or the thread finishes.
      The process-level resource limits (layer 5) mitigate this on Linux.
    - True isolation requires running in a subprocess inside a seccomp
      jail, container, or VM. This module is the first line of defence,
      not the only line.

Author: Controlled Execution Sandbox
"""

import io
import sys
import threading
import time
import traceback
from typing import Any

# ---------------------------------------------------------------------------
# Try to import 'resource' (Linux/macOS only). Gracefully degrade on Windows.
# ---------------------------------------------------------------------------
try:
    import resource as _resource
    _RESOURCE_AVAILABLE = True
except ImportError:
    _RESOURCE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------
EXECUTION_TIMEOUT_SECS  = 2          # Wall-clock timeout
MAX_OUTPUT_CHARS        = 4_096      # Truncate captured stdout beyond this
MEMORY_LIMIT_BYTES      = 256 * 1024 * 1024   # 256 MB virtual address space
CPU_LIMIT_SECS          = 5          # CPU-time hard limit (setrlimit)
MAX_RECURSION_DEPTH     = 100        # Prevent recursive bombs

# ---------------------------------------------------------------------------
# Safe built-ins whitelist
# ONLY these names are visible to sandboxed code.
# Every other built-in is stripped from the execution namespace.
# ---------------------------------------------------------------------------
_SAFE_BUILTINS: dict[str, Any] = {
    # Output
    "print":      print,
    # Numeric
    "abs":        abs,
    "divmod":     divmod,
    "max":        max,
    "min":        min,
    "pow":        pow,
    "round":      round,
    "sum":        sum,
    # Iteration helpers
    "range":      range,
    "enumerate":  enumerate,
    "zip":        zip,
    "map":        map,
    "filter":     filter,
    "sorted":     sorted,
    "reversed":   reversed,
    "len":        len,
    "next":       next,
    "iter":       iter,
    # Type constructors (safe subset)
    "int":        int,
    "float":      float,
    "str":        str,
    "bool":       bool,
    "list":       list,
    "dict":       dict,
    "tuple":      tuple,
    "set":        set,
    "frozenset":  frozenset,
    # Inspection (limited)
    "isinstance": isinstance,
    "repr":       repr,
    "hash":       hash,
    "id":         id,
    # Exceptions — allow code to raise/catch standard errors
    "Exception":          Exception,
    "ValueError":         ValueError,
    "TypeError":          TypeError,
    "IndexError":         IndexError,
    "KeyError":           KeyError,
    "ZeroDivisionError":  ZeroDivisionError,
    "StopIteration":      StopIteration,
    "RuntimeError":       RuntimeError,
    "OverflowError":      OverflowError,
    "MemoryError":        MemoryError,
    "RecursionError":     RecursionError,
    "NotImplementedError": NotImplementedError,
    "ArithmeticError":    ArithmeticError,
    "AssertionError":     AssertionError,
    # Boolean constants
    "True":   True,
    "False":  False,
    "None":   None,
}


# ---------------------------------------------------------------------------
# Resource limiter (Linux/macOS only)
# ---------------------------------------------------------------------------

def _apply_resource_limits() -> None:
    """Apply OS-level resource limits (Linux/macOS only)."""
    if not _RESOURCE_AVAILABLE:
        return

    def _set_limit(limit_type: int, value: int) -> bool:
        try:
            _resource.setrlimit(limit_type, (value, value))
            return True
        except (ValueError, _resource.error) as exc:
            # Log but don't fail — limit may already be lower
            import sys as _sys
            print(f"[Sandbox] Resource limit {limit_type} not enforced: {exc}", file=_sys.stderr)
            return False

    _set_limit(_resource.RLIMIT_AS, MEMORY_LIMIT_BYTES)
    _set_limit(_resource.RLIMIT_CPU, CPU_LIMIT_SECS)


# ---------------------------------------------------------------------------
# Core execution function (runs inside a thread)
# ---------------------------------------------------------------------------

def _run_code(
    code: str,
    result_container: list,
    stdout_buffer: io.StringIO,
) -> None:
    """
    Execute `code` in a fully restricted environment.
    Stores a result dict in result_container[0].
    This function is designed to run inside a daemon thread.
    """
    # Apply OS-level limits first (no-op on Windows)
    _apply_resource_limits()

    # Lower recursion limit to prevent stack-overflow bombs
    old_recursion_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(MAX_RECURSION_DEPTH)

    # Redirect stdout so print() output is captured
    old_stdout = sys.stdout
    sys.stdout = stdout_buffer

    try:
        # Build the sandbox namespace:
        #   __builtins__ → our safe whitelist dict (not the real builtins module)
        #   __name__     → indicates we're in a sandboxed context
        sandbox_globals: dict[str, Any] = {
            "__builtins__": _SAFE_BUILTINS,
            "__name__":     "__sandbox__",
        }

        # Execute the code. exec() is what we're protecting against externally;
        # here it is used intentionally under full control.
        exec(code, sandbox_globals)  # noqa: S102 — intentional sandboxed use

        output = _truncate_output(stdout_buffer.getvalue())
        result_container[0] = {
            "status": "allowed",
            "output": output,
            "reason": "Code executed successfully",
        }

    except MemoryError:
        result_container[0] = {
            "status": "error",
            "output": "",
            "reason": "MemoryError: Code attempted to allocate too much memory",
        }
    except RecursionError:
        result_container[0] = {
            "status": "error",
            "output": "",
            "reason": "RecursionError: Maximum recursion depth exceeded (recursive bomb?)",
        }
    except Exception as exc:  # noqa: BLE001 — intentional broad catch
        # Capture the error type and message but NOT the full traceback
        # (tracebacks can leak internal sandbox structure)
        exc_type = type(exc).__name__
        result_container[0] = {
            "status": "error",
            "output": _truncate_output(stdout_buffer.getvalue()),
            "reason": f"{exc_type}: {exc}",
        }
    finally:
        # Always restore stdout and recursion limit, even if the thread
        # survives past a timeout (it will continue in the background)
        sys.stdout = old_stdout
        sys.setrecursionlimit(old_recursion_limit)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute(code: str) -> dict[str, Any]:
    """
    Execute a pre-validated Python code snippet in a sandboxed environment.

    Args:
        code: Python source code. MUST have already passed validator.validate().
              Calling this on unvalidated code is a security violation.

    Returns:
        A structured response dict:
            {
                "status":  "allowed" | "error" | "timeout",
                "output":  "<captured stdout>",
                "reason":  "<human-readable explanation>",
            }
    """
    stdout_buffer = io.StringIO()
    result_container: list[dict] = [{}]  # Mutable container for thread result

    # Launch execution in a daemon thread so the main process is never blocked
    exec_thread = threading.Thread(
        target=_run_code,
        args=(code, result_container, stdout_buffer),
        daemon=True,   # Thread dies with the process if main exits
        name="sandbox-exec",
    )

    start_time = time.monotonic()
    exec_thread.start()
    exec_thread.join(timeout=EXECUTION_TIMEOUT_SECS)
    elapsed = time.monotonic() - start_time

    # ── Timeout path ──────────────────────────────────────────────────────
    if exec_thread.is_alive():
        # Thread is still running — we abandon it and report a timeout.
        # WARNING: Abandoned thread continues consuming resources.
        # This is a known limitation of in-process sandboxing.
        import sys as _sys
        print(
            f"[Sandbox WARN] Thread abandoned after timeout: {exec_thread.name}",
            file=_sys.stderr,
        )
        return {
            "status": "timeout",
            "output": "",
            "reason": (
                f"Execution timed out after {EXECUTION_TIMEOUT_SECS}s. "
                "Possible infinite loop or excessively long-running computation."
            ),
        }

    # ── Normal completion path ────────────────────────────────────────────
    result = result_container[0]

    # Safety guard: if the thread somehow exited without storing a result
    if not result:
        import sys as _sys
        print(
            "[Sandbox ERROR] Thread exited without result (possible exception in finally block)",
            file=_sys.stderr,
        )
        return {
            "status": "error",
            "output": "",
            "reason": "Internal sandbox error: execution thread produced no result",
        }

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate_output(text: str) -> str:
    """Prevent excessively large outputs from being returned."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    overflow = len(text) - MAX_OUTPUT_CHARS
    return (
        text[:MAX_OUTPUT_CHARS]
        + f"\n... [{overflow} characters truncated — output limit reached]"
    )
