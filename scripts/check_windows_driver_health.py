#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.reports import save_json
from devmgmt_runtime.status import status_exit_code


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "windows-driver-health.final.json"
DEFAULT_INTEL_INSTALLER = Path.home() / "Downloads" / "drivers" / "intel-arc-101.8735" / "gfx_win_101.8735.exe"
DEFAULT_TARGET_INTEL_VERSION = "32.0.101.8735"
INTEL_ARC_DEVICE_MARKERS = ("Intel(R) Arc", "Intel® Arc", "Intel Arc")


def run_command(args: list[str]) -> str:
    completed = subprocess.run(args, check=True, text=True, capture_output=True)
    return completed.stdout


def is_admin() -> bool:
    command = (
        "$identity=[Security.Principal.WindowsIdentity]::GetCurrent(); "
        "$principal=[Security.Principal.WindowsPrincipal]$identity; "
        "$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)"
    )
    try:
        return run_command(["powershell", "-NoProfile", "-NonInteractive", "-Command", command]).strip().lower() == "true"
    except (OSError, subprocess.CalledProcessError):
        return False


def running_installer_processes(process_name: str) -> list[dict[str, Any]]:
    command = (
        "$rows = Get-Process -Name '"
        + process_name
        + "' -ErrorAction SilentlyContinue | "
        "Select-Object Id,ProcessName,Path,StartTime; "
        "$rows | ConvertTo-Json -Depth 3"
    )
    try:
        payload = run_command(["powershell", "-NoProfile", "-NonInteractive", "-Command", command]).strip()
    except (OSError, subprocess.CalledProcessError):
        return []
    if not payload:
        return []
    parsed = json.loads(payload)
    rows = parsed if isinstance(parsed, list) else [parsed]
    return [row for row in rows if isinstance(row, dict)]


def parse_driver_version(value: str) -> str:
    match = re.search(r"(?P<version>\d+\.\d+\.\d+\.\d+)", value)
    return match.group("version") if match else ""


def parse_driver_date(value: str) -> str:
    match = re.search(r"(?P<date>\d{2}/\d{2}/\d{4})", value)
    return match.group("date") if match else ""


def parse_display_device_drivers(text: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    entry: dict[str, str] | None = None

    def finish_entry() -> None:
        nonlocal entry
        if current is not None and entry:
            current.setdefault("driver_entries", []).append(entry)
        entry = None

    def finish_device() -> None:
        nonlocal current
        finish_entry()
        if current:
            records.append(current)
        current = None

    for raw_line in text.splitlines():
        nested_driver_line = raw_line[:1].isspace()
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Instance ID:"):
            finish_device()
            current = {
                "instance_id": line.split(":", 1)[1].strip(),
                "driver_entries": [],
            }
            continue
        if current is None:
            continue
        if line.startswith("Device Description:"):
            current["device_description"] = line.split(":", 1)[1].strip()
        elif line.startswith("Driver Name:") and not nested_driver_line:
            current["active_driver_name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Driver Name:"):
            finish_entry()
            value = line.split(":", 1)[1].strip()
            entry = {"driver_name": value}
        elif line.startswith("Provider Name:") and entry is not None:
            entry["provider_name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Class Name:"):
            value = line.split(":", 1)[1].strip()
            if entry is not None:
                entry["class_name"] = value
            else:
                current["class_name"] = value
        elif line.startswith("Driver Version:") and entry is not None:
            value = line.split(":", 1)[1].strip()
            entry["driver_version_raw"] = value
            entry["driver_version"] = parse_driver_version(value)
            entry["driver_date"] = parse_driver_date(value)
    finish_device()

    for record in records:
        active_name = str(record.get("active_driver_name") or "")
        active_entry = next(
            (
                item
                for item in record.get("driver_entries", [])
                if item.get("driver_name") == active_name and item.get("class_name", "").lower() == "display"
            ),
            None,
        )
        if active_entry:
            record["active_driver_version"] = active_entry.get("driver_version", "")
            record["active_driver_date"] = active_entry.get("driver_date", "")
    return {"devices": records}


def parse_driver_store(text: str) -> list[dict[str, str]]:
    drivers: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                drivers.append(current)
                current = {}
            continue
        if ":" not in line:
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        normalized = key.lower().replace(" ", "_")
        current[normalized] = value
        if normalized == "driver_version":
            current["version"] = parse_driver_version(value)
            current["date"] = parse_driver_date(value)
    if current:
        drivers.append(current)
    return drivers


def intel_display_devices(parsed_devices: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        device
        for device in parsed_devices.get("devices", [])
        if any(marker.lower() in str(device.get("device_description", "")).lower() for marker in INTEL_ARC_DEVICE_MARKERS)
    ]


def evaluate_driver_state(
    *,
    display_devices: list[dict[str, Any]],
    driver_store: list[dict[str, str]],
    target_version: str,
    installer_path: Path,
    installer_processes: list[dict[str, Any]],
    admin: bool,
) -> dict[str, Any]:
    warnings: list[str] = []
    blockers: list[str] = []
    actions: list[str] = []
    active_versions = sorted({str(device.get("active_driver_version") or "") for device in display_devices if device.get("active_driver_version")})
    staged_versions = sorted({driver.get("version", "") for driver in driver_store if driver.get("version")})
    target_staged = target_version in staged_versions
    target_active = target_version in active_versions

    if not display_devices:
        blockers.append("Intel Arc display device was not detected by pnputil.")
    elif target_active:
        pass
    else:
        blockers.append(f"target Intel graphics driver is not active: {target_version}")
        actions.append("Run the Intel or OEM graphics installer from an elevated Windows session, then reboot.")

    if not target_staged:
        blockers.append(f"target Intel graphics driver is not staged in the driver store: {target_version}")
    if active_versions and target_version not in active_versions:
        warnings.append("active Intel graphics driver differs from the target version: " + ", ".join(active_versions))
    if staged_versions and not target_staged:
        warnings.append("newer staged Intel driver exists but it is not the target version: " + ", ".join(staged_versions[-3:]))
    if not installer_path.exists():
        warnings.append(f"target Intel installer file is missing: {installer_path}")
        actions.append("Download the Intel graphics installer again from Intel or Lenovo support.")
    if not installer_processes:
        warnings.append("target Intel graphics installer is not currently running")
    if not admin:
        blockers.append("current shell is not elevated; driver installation and pnputil driver changes can be blocked")
        actions.append("Use Run as administrator for the installer or Device Manager driver update.")
    if not target_active:
        actions.extend(
            [
                "If Windows Update rolls the driver back, retry Intel's non-clean custom install path first.",
                "Prefer Lenovo's model-specific package when the Intel generic installer refuses OEM-customized systems.",
                "Avoid DDU or driver-store deletion unless you intentionally accept downtime and have a restore point.",
            ]
        )

    status = "BLOCKED" if blockers else "WARN" if warnings else "PASS"
    return {
        "status": status,
        "target_version": target_version,
        "target_active": target_active,
        "target_staged": target_staged,
        "active_versions": active_versions,
        "staged_versions": staged_versions,
        "installer_path": str(installer_path),
        "installer_exists": installer_path.exists(),
        "installer_processes": installer_processes,
        "is_admin": admin,
        "warnings": warnings,
        "blockers": blockers,
        "recommended_actions": list(dict.fromkeys(actions)),
    }


def collect_report(target_version: str, installer_path: Path) -> dict[str, Any]:
    display_text = run_command(["pnputil", "/enum-devices", "/class", "Display", "/drivers"])
    store_text = run_command(["pnputil", "/enum-drivers"])
    parsed_devices = parse_display_device_drivers(display_text)
    store = parse_driver_store(store_text)
    installer_process_name = installer_path.stem
    devices = intel_display_devices(parsed_devices)
    state = evaluate_driver_state(
        display_devices=devices,
        driver_store=store,
        target_version=target_version,
        installer_path=installer_path,
        installer_processes=running_installer_processes(installer_process_name),
        admin=is_admin(),
    )
    return {
        "status": state["status"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "driver_state": state,
        "intel_display_devices": devices,
        "driver_store_matches": [
            driver
            for driver in store
            if "intel" in driver.get("provider_name", "").lower()
            and driver.get("version")
            and driver.get("class_name", "").lower() in {"display", "extension", "media"}
        ],
        "sources": [
            "https://www.intel.com/content/www/us/en/support/articles/000056629/graphics.html",
            "https://www.intel.com/content/www/us/en/support/articles/000087834/graphics.html",
            "https://pcsupport.lenovo.com/us/en/products/laptops-and-netbooks/yoga-series/yoga-7-2-in-1-14ill10/83jq/downloads",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Windows Intel graphics driver install/staging health.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--target-version", default=DEFAULT_TARGET_INTEL_VERSION)
    parser.add_argument("--installer-path", default=str(DEFAULT_INTEL_INSTALLER))
    args = parser.parse_args()

    report = collect_report(args.target_version, Path(args.installer_path).expanduser())
    output_path = Path(args.output_file).expanduser().resolve()
    save_json(output_path, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        state = report["driver_state"]
        print(f"{report['status']}: active={state['active_versions']} target={state['target_version']}")
    return status_exit_code(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
