from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def load_first_report(reports_root: Path, candidates: list[str]) -> tuple[dict[str, Any], str, bool]:
    for candidate in candidates:
        path = reports_root / candidate
        if path.exists():
            payload = load_json(path, default={})
            return (payload if isinstance(payload, dict) else {}, str(path), False)
    return ({}, str(reports_root / candidates[0]), True)
