"""
monitor.py — Behaviour Monitoring & Audit Logging
==================================================
Records every execution attempt in a structured JSONL audit log and detects
suspicious usage patterns within a session (e.g. repeated blocked attempts
that may indicate an attacker probing for vulnerabilities).

Design decisions:
  - JSONL format (one JSON object per line) is chosen for log files because
    it is human-readable, grep-friendly, and trivially parseable by log
    aggregators (Splunk, ELK, etc.).
  - Session-level counters are kept in memory; they reset when the process
    restarts. A production system would persist these in Redis or a DB.
  - The monitor is intentionally NOT responsible for blocking — it only
    observes and reports. Enforcement is the validator's and executor's job.

Author: Controlled Execution Sandbox
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LOG_FILE          = Path("sandbox_executions.log")
MAX_CODE_LOG_LEN  = 500          # Truncate long snippets in the log
SUSPICIOUS_THRESHOLD = 10        # Blocked attempts per session before warning (reduced false positives)

# ---------------------------------------------------------------------------
# Python stdlib logger (separate from the JSONL audit log) for internal
# warnings about suspicious behaviour. Writes to both stderr and a file.
# ---------------------------------------------------------------------------
_internal_logger = logging.getLogger("sandbox.monitor")
_internal_logger.setLevel(logging.DEBUG)

# Handler: internal_sandbox.log (structured warnings for ops teams)
_fh = logging.FileHandler("internal_sandbox.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
))
_internal_logger.addHandler(_fh)
# NOTE: No console handler is added intentionally — warnings go only to
# the internal log file so they do not pollute the test output table.

# ---------------------------------------------------------------------------
# Session-level state (thread-safe via a lock)
# ---------------------------------------------------------------------------
_state_lock        = threading.Lock()
_session_stats: dict[str, int] = {
    "total":   0,
    "allowed": 0,
    "blocked": 0,
    "error":   0,
    "timeout": 0,
}
_session_start_time = time.time()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def log_execution(
    code: str,
    result: dict[str, Any],
    elapsed_ms: float,
) -> None:
    """
    Write a structured log entry for a single sandbox execution.

    Args:
        code        : Original code snippet (will be truncated in the log).
        result      : The structured response dict from the sandbox.
        elapsed_ms  : Wall-clock time the execution took, in milliseconds.
    """
    status = result.get("status", "unknown")

    # ── Build the JSONL record ────────────────────────────────────────────
    record: dict[str, Any] = {
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "status":      status,
        "elapsed_ms":  round(elapsed_ms, 2),
        "code":        _truncate(code, MAX_CODE_LOG_LEN),
        "output":      result.get("output", ""),
        "reason":      result.get("reason", ""),
    }

    # ── Write to JSONL audit log ──────────────────────────────────────────
    try:
        json_str = json.dumps(record)  # Serialize separately to catch type errors
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json_str + "\n")
    except (OSError, TypeError, ValueError) as exc:
        # Catch both file errors AND JSON serialization errors
        _internal_logger.error("Failed to write audit log entry: %s", exc)

    # ── Update session counters (thread-safe) ─────────────────────────────
    with _state_lock:
        _session_stats["total"] += 1
        if status in _session_stats:
            _session_stats[status] += 1

    # ── Suspicious behaviour check ──────────────────────────────────────────
    # Add alert to result if suspicious activity detected
    is_suspicious = _check_suspicious(code, status)
    if is_suspicious:
        result["security_alert"] = f"Suspicious activity detected ({_session_stats['blocked']} blocked attempts in session)"


def get_session_stats() -> dict[str, Any]:
    """Return a snapshot of current session statistics."""
    with _state_lock:
        uptime_secs = round(time.time() - _session_start_time, 1)
        return {
            **_session_stats,
            "uptime_seconds": uptime_secs,
        }


def print_session_summary() -> None:
    """Print a human-readable session summary to stdout."""
    stats = get_session_stats()
    print("\n" + "=" * 60)
    print("  SESSION SUMMARY")
    print("=" * 60)
    print(f"  Uptime         : {stats['uptime_seconds']}s")
    print(f"  Total runs     : {stats['total']}")
    print(f"  [OK]  Allowed  : {stats['allowed']}")
    print(f"  [!!]  Blocked  : {stats['blocked']}")
    print(f"  [WW]  Errors   : {stats['error']}")
    print(f"  [TT]  Timeouts : {stats['timeout']}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int) -> str:
    """Truncate a string and append truncation notice."""
    remaining = len(text) - max_len
    return text[:max_len] + f"... [{remaining} chars truncated]" if remaining > 0 else text


def _check_suspicious(code: str, status: str) -> bool:
    """
    Detect suspicious usage patterns and emit a warning.
    Returns True if suspicious activity detected.

    Currently detects: more than SUSPICIOUS_THRESHOLD blocked attempts per
    session, which may indicate an attacker probing the sandbox.
    """
    with _state_lock:
        blocked_count = _session_stats["blocked"]

    if status == "blocked" and blocked_count >= SUSPICIOUS_THRESHOLD:
        try:
            _internal_logger.warning(
                "[SUSPICIOUS ACTIVITY] %d blocked attempt(s) in this session. "
                "Last payload (truncated): %s",
                blocked_count,
                _truncate(code, 120),
            )
            return True
        except Exception as exc:
            _internal_logger.error("Failed to log suspicious activity: %s", exc)
            return True  # Assume suspicious even if logging failed
    
    return False
