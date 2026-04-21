from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUARANTINE = ROOT / "quarantine"


class QuarantineHostileAuditTests(unittest.TestCase):
    def test_quarantine_contains_no_executable_files(self) -> None:
        offenders = []
        for path in QUARANTINE.rglob("*"):
            if not path.is_file():
                continue
            try:
                if path.stat().st_mode & 0o111:
                    offenders.append(str(path))
            except OSError:
                offenders.append(str(path))
        self.assertEqual(offenders, [])

    def test_quarantine_contains_no_shebang_or_script_extensions(self) -> None:
        offenders = []
        for path in QUARANTINE.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in {".py", ".sh", ".ps1"}:
                offenders.append(str(path))
                continue
            try:
                first_line = path.read_text(encoding="utf-8", errors="ignore").splitlines()[:1]
            except OSError:
                offenders.append(str(path))
                continue
            if first_line and first_line[0].startswith("#!"):
                offenders.append(str(path))
        self.assertEqual(offenders, [])

    def test_active_quarantine_evidence_roots_have_manifests(self) -> None:
        expected = [
            QUARANTINE / "2026-04-16" / "MANIFEST.json",
            QUARANTINE / "artifact-hygiene" / "20260421-102140" / "MANIFEST.json",
        ]
        missing = [str(path) for path in expected if not path.exists()]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
