"""
validator.py — Static AST-based Input Validation Layer
=======================================================
Performs deep static analysis of user-submitted Python code BEFORE any
execution takes place. Uses Python's built-in `ast` module to walk the
Abstract Syntax Tree — this is far more robust than regex or keyword
matching, because an attacker cannot hide an import behind a comment or
a creative string concatenation that slips past a regex.

Security philosophy:
    "If it can't be proven safe, it is rejected."

Author: Controlled Execution Sandbox
"""

import ast
import re
from typing import Any


# ---------------------------------------------------------------------------
# Blocked module names — any import of these is instantly rejected.
# ---------------------------------------------------------------------------
BLOCKED_MODULES: frozenset[str] = frozenset({
    "os", "sys", "subprocess", "socket", "shutil", "pathlib",
    "ctypes", "builtins", "io", "pickle", "marshal", "shelve",
    "importlib", "importlib.util", "importlib.machinery",
    "multiprocessing", "threading", "concurrent", "signal",
    "resource", "mmap", "struct", "gc", "weakref",
    "inspect", "dis", "code", "codeop", "compileall",
    "ast", "tokenize", "keyword", "symtable", "py_compile",
    "site", "sysconfig", "platform", "pwd", "grp",
    "fcntl", "termios", "pty", "tty",
    "ftplib", "http", "urllib", "requests", "httpx",
    "email", "smtplib", "ssl", "hashlib", "hmac",
    "secrets", "random", "uuid",  # blocked: uuid uses os
    "tempfile", "glob", "fnmatch", "linecache", "fileinput",
    "zipfile", "tarfile", "gzip", "bz2", "lzma",
    "json", "csv", "xml", "html", "configparser",
    "logging", "warnings", "traceback", "pdb",
    "pprint", "textwrap",
})

# ---------------------------------------------------------------------------
# Blocked built-in function / attribute names. These are checked whenever
# the AST contains a Name node or an Attribute node.
# ---------------------------------------------------------------------------
BLOCKED_BUILTINS: frozenset[str] = frozenset({
    "open", "exec", "eval", "compile", "input",
    "__import__", "breakpoint", "help",
    "getattr", "setattr", "delattr",
    "vars", "dir", "globals", "locals",
    "staticmethod", "classmethod", "property",
    "super",  # can be used to escape MRO
    "object",  # ().__class__.__bases__[0] etc.
    "type",    # type('', (object,), {}) class factory
    "memoryview", "bytearray", "bytes",  # low-level memory
})

# ---------------------------------------------------------------------------
# Blocked dunder / magic attribute names.
# These are the classic Python sandbox-escape vectors.
# ---------------------------------------------------------------------------
BLOCKED_ATTRS: frozenset[str] = frozenset({
    "__class__", "__bases__", "__subclasses__",
    "__globals__", "__builtins__", "__code__",
    "__dict__", "__doc__", "__file__", "__spec__",
    "__loader__", "__package__", "__path__",
    "__import__", "__init__", "__new__", "__del__",
    "__reduce__", "__reduce_ex__", "__getstate__",
    "__setstate__", "__getnewargs__",
    "__module__", "__qualname__", "__name__",
    "__mro__", "__abstractmethods__",
    "mro", "func_globals",  # older Python names
    "__func__", "__self__",
    "__wrapped__",
})

# ---------------------------------------------------------------------------
# Patterns that are too dangerous even as string literals.
# These catch eval('__import__("os")') style attacks.
# ---------------------------------------------------------------------------
BLOCKED_STRING_PATTERNS: list[tuple[str, str]] = [
    (r'__import__',          "String literal contains __import__"),
    (r'importlib',           "String literal references importlib"),
    (r'subprocess',          "String literal references subprocess"),
    (r'__subclasses__',      "String literal references __subclasses__"),
    (r'__globals__',         "String literal references __globals__"),
    (r'__builtins__',        "String literal references __builtins__"),
]


# ---------------------------------------------------------------------------
# AST Visitor — walks every node and raises on dangerous constructs.
# ---------------------------------------------------------------------------
class _SecurityVisitor(ast.NodeVisitor):
    """
    Walks the AST and raises ValueError with a descriptive message the
    moment a forbidden construct is encountered.
    """

    def visit_Import(self, node: ast.Import) -> None:
        """Block all import statements."""
        raise ValueError(f"Import not allowed: {', '.join(a.name for a in node.names)}")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Block all from-import statements."""
        raise ValueError(f"Import not allowed: from {node.module or '?'} import ...")

    def visit_Name(self, node: ast.Name) -> None:
        """Block references to dangerous built-in names."""
        if node.id in BLOCKED_BUILTINS:
            raise ValueError(
                f"Use of built-in '{node.id}' is not permitted in the sandbox"
            )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """
        Block access to any blocked attribute name.
        e.g.  ().__class__.__bases__[0].__subclasses__()
        """
        if node.attr in BLOCKED_ATTRS:
            raise ValueError(
                f"Access to attribute '{node.attr}' is not permitted "
                f"(potential sandbox escape vector)"
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """
        Extra check: catch __import__('os') style calls where the function
        is expressed as a Name node.
        """
        if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_BUILTINS:
            raise ValueError(
                f"Call to '{node.func.id}' is not permitted in the sandbox"
            )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        """
        Inspect string constants for dangerous content.
        Prevents tricks like: exec('__import__("os").system("whoami")')
        """
        if isinstance(node.value, str):
            for pattern, reason in BLOCKED_STRING_PATTERNS:
                if re.search(pattern, node.value, re.IGNORECASE):
                    raise ValueError(f"Malicious string constant detected: {reason}")
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate(code: str) -> dict[str, Any]:
    """
    Validate a Python code snippet for safety.

    Args:
        code: Raw Python source code string submitted by the user.

    Returns:
        A dict with keys:
            - "valid"  (bool)  : True if code is safe to attempt execution.
            - "reason" (str)   : Empty string on success; error message on failure.

    Never raises — all errors are caught and returned in the result dict.
    """

    # ── Guard 1: Empty / whitespace only input ────────────────────────────
    if not code or not code.strip():
        return {"valid": False, "reason": "Empty code submission"}

    # ── Guard 2: Maximum input length (prevent parser DoS) ────────────────
    MAX_CODE_LENGTH = 8_192  # 8 KB
    if len(code) > MAX_CODE_LENGTH:
        return {
            "valid": False,
            "reason": (
                f"Code exceeds maximum allowed length of {MAX_CODE_LENGTH} characters "
                f"(submitted {len(code)} characters)"
            ),
        }

    # ── Guard 3: Parse and validate AST ──────────────────────────────
    try:
        tree = ast.parse(code, mode="exec")
        _SecurityVisitor().visit(tree)
    except SyntaxError as exc:
        return {"valid": False, "reason": f"Syntax error: {exc}"}
    except ValueError as exc:
        return {"valid": False, "reason": str(exc)}

    # ── All checks passed ─────────────────────────────────────────────────
    return {"valid": True, "reason": ""}
