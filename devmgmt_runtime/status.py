from __future__ import annotations


VALID_STATUSES = {"PASS", "WARN", "BLOCKED", "FAIL", "WAIVED"}


def normalize_status(value: object, default: str = "WARN") -> str:
    text = str(value or "").strip().upper()
    return text if text in VALID_STATUSES else default


def collapse_status(values: list[str]) -> str:
    items = [normalize_status(value, default="") for value in values if str(value or "").strip()]
    if any(value in {"BLOCKED", "FAIL"} for value in items):
        return "BLOCKED"
    if any(value == "WARN" for value in items):
        return "WARN"
    return "PASS"


def status_exit_code(status: str) -> int:
    normalized = normalize_status(status)
    if normalized in {"PASS", "WAIVED"}:
        return 0
    if normalized == "WARN":
        return 1
    return 2

