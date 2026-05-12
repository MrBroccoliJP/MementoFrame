#!/usr/bin/env python3
# MementoFrame - Raspberry Pi Smart Photo Frame
# Updater / installer helper

"""
updater.py

Usage:
    python3 updater.py install
    python3 updater.py status
    python3 updater.py check
    python3 updater.py update
    python3 updater.py update --no-reboot
    python3 updater.py autoupdate
    python3 updater.py autoupdate --no-reboot
    python3 updater.py post-reboot-check

Configuration:
    Add this to config.json, or set MEMENTOFRAME_UPDATE_REPO in .env:

    {
      "updates": {
        "auto_update": false,
        "repo": "your-github-user/mementoframe",
        "channel": "stable",
        "preserve": ["config.json", ".env", "resources/userdata", "runtime"],
        "service_names": [
          "mementoframe-dashboard.service",
          "mementoframe-display.service",
          "mementoframe-ap.service"
        ]
      }
    }

Notes:
    - GitHub release tags should match version_info.GLOBAL_APP_VERSION, usually vX.Y.Z.
    - Release archives are downloaded from GitHub's zipball_url.
    - The updater preserves config/user data, writes runtime/update_state.json,
      and reboots after a successful update.
"""

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_FILE = PROJECT_ROOT / "config.json"
RUNTIME_DIR = PROJECT_ROOT / "runtime"
STATE_FILE = RUNTIME_DIR / "update_state.json"
BACKUP_ROOT = PROJECT_ROOT.parent / "mementoframe_backups"
DEFAULT_UPDATE_TIME = "05:00"
DEFAULT_PRESERVE = ["config.json", ".env", "resources/userdata", "runtime"]
DEFAULT_SERVICES = [
    "mementoframe-dashboard.service",
    "mementoframe-display.service",
    "mementoframe-ap.service",
]
HEALTH_URLS = ["http://127.0.0.1:5000/health", "http://127.0.0.1:5001/health"]

EXCLUDE_DURING_COPY = {
    ".git",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "runtime",
    "resources/userdata",
}
APP_SUBDIR = "mementoframe"

def now_ts() -> int:
    return int(time.time())


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    fallback = fallback or {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fallback.copy()
    except Exception as exc:
        return {**fallback, "_read_error": str(exc)}


def write_state(**updates: Any) -> dict[str, Any]:
    state = read_json(STATE_FILE, {})
    state.update(updates)
    state.setdefault("checked_at", None)
    state.setdefault("installed_version", installed_version())
    state.setdefault("latest_version", None)
    state.setdefault("available", False)
    state.setdefault("pending_restart", False)
    state.setdefault("update_in_progress", False)
    state.setdefault("last_error", None)
    atomic_write_json(STATE_FILE, state)
    return state


def installed_version() -> str:
    """Read version from the import-cached module. Use _read_version_from_file()
    after a file copy to avoid getting a stale cached value."""
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from version_info import GLOBAL_APP_VERSION, VERSIONS  # type: ignore
        return str(GLOBAL_APP_VERSION or VERSIONS.get("MementoFrame") or VERSIONS.get("Global App Version") or "0.0.0")
    except Exception:
        return "0.0.0"


def _read_version_from_file() -> str:
    """Read GLOBAL_APP_VERSION directly from version_info.py without importing it.

    Used post-copy so we always get the new file's version, bypassing Python's
    module cache which would otherwise return the pre-update value.
    """
    try:
        text = (PROJECT_ROOT / "version_info.py").read_text(encoding="utf-8")
        m = re.search(r'^GLOBAL_APP_VERSION\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        return m.group(1) if m else "0.0.0"
    except Exception:
        return "0.0.0"


def load_config() -> dict[str, Any]:
    cfg = read_json(CONFIG_FILE, {})
    cfg.setdefault("updates", {})
    updates = cfg["updates"]
    updates.setdefault("auto_update", False)
    updates.setdefault("repo", os.getenv("MEMENTOFRAME_UPDATE_REPO", ""))
    updates.setdefault("channel", "stable")
    updates.setdefault("preserve", DEFAULT_PRESERVE)
    updates.setdefault("service_names", DEFAULT_SERVICES)
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    atomic_write_json(CONFIG_FILE, cfg)


def parse_version(v: str) -> tuple[int, ...]:
    v = str(v).strip().lstrip("vV")
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts[:4]) or (0,)


def version_newer(latest: str, current: str) -> bool:
    a = parse_version(latest)
    b = parse_version(current)
    max_len = max(len(a), len(b))
    a += (0,) * (max_len - len(a))
    b += (0,) * (max_len - len(b))
    return a > b


def http_json(url: str, timeout: int = 15, retries: int = 3) -> dict[str, Any]:
    """Fetch JSON from a URL with simple exponential-backoff retry.

    Retries up to `retries` times on any exception (network error, timeout,
    bad status). Waits 1 s then 2 s between attempts. Re-raises on final failure.
    """
    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "MementoFrame-Updater",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return json.loads(res.read().decode("utf-8"))
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)  # 1 s, 2 s
    raise last_exc


def github_latest_release(repo: str) -> dict[str, Any]:
    if not repo or "/" not in repo:
        raise RuntimeError("Update repo is not configured. Set updates.repo or MEMENTOFRAME_UPDATE_REPO.")
    return http_json(f"https://api.github.com/repos/{repo}/releases/latest")


def download_file(url: str, dest: Path, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "MementoFrame-Updater"})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=timeout) as res, dest.open("wb") as f:
        while True:
            chunk = res.read(1024 * 256)
            if not chunk:
                break
            h.update(chunk)
            f.write(chunk)
    return h.hexdigest()


def check_for_update() -> dict[str, Any]:
    cfg = load_config()
    repo = cfg.get("updates", {}).get("repo", "")
    current = installed_version()
    try:
        release = github_latest_release(repo)
        latest = str(release.get("tag_name") or "").lstrip("v")
        available = bool(latest and version_newer(latest, current))
        state = write_state(
            installed_version=current,
            latest_version=latest or None,
            latest_tag=release.get("tag_name"),
            release_name=release.get("name"),
            release_notes=release.get("body") or "",
            release_url=release.get("html_url"),
            zipball_url=release.get("zipball_url"),
            available=available,
            checked_at=now_ts(),
            last_error=None,
        )
        return state
    except Exception as exc:
        return write_state(
            installed_version=current,
            checked_at=now_ts(),
            available=False,
            last_error=str(exc),
        )


def should_preserve(rel: str, preserve: list[str]) -> bool:
    rel = rel.strip("/")
    return any(rel == p.strip("/") or rel.startswith(p.strip("/") + "/") for p in preserve)


def copy_tree_contents(src: Path, dst: Path, preserve: list[str]) -> None:
    for item in src.iterdir():
        name = item.name
        rel = name
        if name in EXCLUDE_DURING_COPY or should_preserve(rel, preserve):
            continue
        target = dst / name
        if item.is_dir():
            if target.exists() and not target.is_dir():
                target.unlink()
            shutil.copytree(item, target, dirs_exist_ok=True, ignore=ignore_patterns(preserve))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def ignore_patterns(preserve: list[str]):
    def _ignore(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        root = Path(directory)
        for name in names:
            if name in EXCLUDE_DURING_COPY:
                ignored.add(name)
                continue
            try:
                project_rel = str((root / name).relative_to(PROJECT_ROOT))
            except Exception:
                project_rel = name
            if should_preserve(project_rel, preserve):
                ignored.add(name)
        return ignored
    return _ignore


def find_app_root(tmpdir: Path) -> Path:
    """Find the mementoframe/ subfolder inside the GitHub-generated zip.
    
    GitHub wraps everything in a top-level folder like owner-repo-abc1234/,
    so we look one level deep for APP_SUBDIR rather than at the zip root.
    """
    # GitHub zip: tmpdir/owner-repo-sha/mementoframe/
    for child in tmpdir.iterdir():
        if child.is_dir():
            target = child / APP_SUBDIR
            if target.is_dir():
                return target
    # Fallback: mementoframe/ directly at zip root
    direct = tmpdir / APP_SUBDIR
    if direct.is_dir():
        return direct
    raise RuntimeError(
        f"Could not find '{APP_SUBDIR}/' in the release archive. "
        f"Expected structure: <repo-root>/{APP_SUBDIR}/..."
    )


def run(cmd: list[str], check: bool = False, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{proc.stderr or proc.stdout}")
    return proc


def systemctl(action: str, services: list[str]) -> None:
    for svc in services:
        proc = run(["sudo", "systemctl", action, svc], check=False, timeout=30)
        if proc.returncode != 0:
            print(f"⚠️ systemctl {action} {svc}: {proc.stderr.strip() or proc.stdout.strip()}")


def backup_current() -> Path:
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_ROOT / f"mementoframe-{installed_version()}-{stamp}"
    shutil.copytree(
        PROJECT_ROOT,
        dest,
        ignore=shutil.ignore_patterns("venv", "__pycache__", ".git", "runtime/update_state.json"),
    )
    return dest


def install_requirements() -> None:
    req = PROJECT_ROOT / "requirements.txt"
    if not req.exists():
        return
    pip = PROJECT_ROOT / "venv" / "bin" / "pip"
    if pip.exists():
        run([str(pip), "install", "-r", str(req)], check=True, timeout=600)
    else:
        run([sys.executable, "-m", "pip", "install", "-r", str(req)], check=True, timeout=600)


def apply_update() -> dict[str, Any]:
    cfg = load_config()
    updates_cfg = cfg.get("updates", {})
    preserve = list(updates_cfg.get("preserve") or DEFAULT_PRESERVE)
    services = list(updates_cfg.get("service_names") or DEFAULT_SERVICES)

    state = read_json(STATE_FILE, {})
    if not state.get("zipball_url") or not state.get("available"):
        state = check_for_update()
    if not state.get("available"):
        return write_state(update_in_progress=False, last_error=None)

    latest = state.get("latest_version") or state.get("latest_tag") or "unknown"
    write_state(update_in_progress=True, update_started_at=now_ts(), last_error=None)

    # FIX 1 + FIX 2: success flag + finally block so update_in_progress is
    # always cleared, even if write_state itself throws. On the success path
    # we also read the version from disk (not from the import cache) so we
    # get the newly-copied version_info.py rather than the pre-update value.
    success = False
    sha256 = ""
    backup: Path | None = None

    try:
        with tempfile.TemporaryDirectory(prefix="mementoframe-update-") as td:
            tmp = Path(td)
            archive = tmp / "release.zip"
            sha256 = download_file(str(state["zipball_url"]), archive)
            extract_dir = tmp / "extract"
            extract_dir.mkdir()
            with zipfile.ZipFile(archive) as zf:
                    bad = zf.testzip()
                    if bad:
                        raise RuntimeError(f"Corrupted zip file: {bad}")
                    zf.extractall(extract_dir)
            release_root = find_app_root(extract_dir)

            backup = backup_current()
            systemctl("stop", services)
            copy_tree_contents(release_root, PROJECT_ROOT, preserve)
            install_requirements()
            systemctl("start", services)

        # Read version from the freshly-copied file — bypasses Python's module
        # cache which would otherwise return the pre-update version string.
        new_version = _read_version_from_file()

        write_state(
            installed_version=new_version,
            latest_version=str(latest).lstrip("v"),
            available=False,
            update_in_progress=False,
            pending_restart=True,
            reboot_requested=True,
            updated_at=now_ts(),
            downloaded_sha256=sha256,
            backup_path=str(backup) if backup else None,
            last_error=None,
        )
        success = True
        return read_json(STATE_FILE, {})

    except Exception as exc:
        write_state(update_in_progress=False, last_error=str(exc))
        raise

    finally:
        # Last-resort safety net: if write_state threw on the success path
        # and left update_in_progress=True in the file, clear it now so the
        # display doesn't show the "Updating" overlay indefinitely.
        if not success:
            try:
                raw = read_json(STATE_FILE, {})
                if raw.get("update_in_progress"):
                    atomic_write_json(STATE_FILE, {**raw, "update_in_progress": False})
            except Exception:
                pass  # Nothing more we can do; don't mask the original error.


def request_reboot() -> None:
    write_state(pending_restart=True, reboot_requested=True)
    proc = run(["sudo", "reboot"], check=False, timeout=10)
    if proc.returncode != 0:
        print(f"⚠️ reboot failed: {proc.stderr.strip() or proc.stdout.strip()}")


def parse_hm(value: str) -> tuple[int, int]:
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(value or ""))
    if not m:
        return (5, 0)
    h, mi = int(m.group(1)), int(m.group(2))
    return max(0, min(23, h)), max(0, min(59, mi))


def current_minutes() -> int:
    n = datetime.now()
    return n.hour * 60 + n.minute


def auto_update_target_minute(cfg: dict[str, Any]) -> int:
    ap = cfg.get("auto_power") or {}
    if ap.get("enabled"):
        h, m = parse_hm(ap.get("on_time", DEFAULT_UPDATE_TIME))
        # Update shortly before the screen comes back on.
        return (h * 60 + m - 30) % (24 * 60)
    h, m = parse_hm(DEFAULT_UPDATE_TIME)
    return h * 60 + m


def in_auto_update_window(cfg: dict[str, Any], window_minutes: int = 20) -> bool:
    target = auto_update_target_minute(cfg)
    now = current_minutes()
    return 0 <= ((now - target) % (24 * 60)) < window_minutes


# FIX 4: autoupdate now accepts no_reboot so --no-reboot works from the CLI.
def autoupdate(no_reboot: bool = False) -> dict[str, Any]:
    cfg = load_config()
    if not cfg.get("updates", {}).get("auto_update"):
        return write_state(auto_update_skipped="disabled", last_autoupdate_check=now_ts())
    if not in_auto_update_window(cfg):
        return write_state(auto_update_skipped="outside_window", last_autoupdate_check=now_ts())

    state = check_for_update()
    if state.get("available"):
        result = apply_update()
        if not no_reboot:
            request_reboot()
        return result
    return state


def url_ok(url: str, timeout: int = 8) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as res:
            return 200 <= int(res.status) < 300
    except Exception:
        return False


def post_reboot_check() -> dict[str, Any]:
    state = read_json(STATE_FILE, {})
    if not state.get("pending_restart"):
        return write_state(post_reboot_checked_at=now_ts())

    # Give systemd/app startup a little time when this is run too early.
    deadline = time.time() + 90
    while time.time() < deadline:
        if all(url_ok(u) for u in HEALTH_URLS):
            return write_state(
                pending_restart=False,
                reboot_requested=False,
                post_reboot_checked_at=now_ts(),
                last_successful_boot_version=installed_version(),
                last_error=None,
            )
        time.sleep(3)

    return write_state(post_reboot_checked_at=now_ts(), last_error="Post-reboot health check failed")


def install() -> dict[str, Any]:
    cfg = load_config()
    for path in [
        PROJECT_ROOT / "resources/userdata/Photos/full",
        PROJECT_ROOT / "resources/userdata/Photos/thumbs",
        PROJECT_ROOT / "resources/userdata/cache",
        PROJECT_ROOT / "resources/assets",
        RUNTIME_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)

    if not CONFIG_FILE.exists():
        save_config(cfg)

    venv = PROJECT_ROOT / "venv"
    if not venv.exists():
        run([sys.executable, "-m", "venv", str(venv)], check=True, timeout=300)
    install_requirements()

    state = write_state(installed_version=installed_version(), installed_at=now_ts(), last_error=None)
    return state


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="MementoFrame updater")
    parser.add_argument(
        "command",
        choices=["install", "status", "check", "update", "autoupdate", "post-reboot-check", "reboot"],
    )
    parser.add_argument(
        "--no-reboot",
        action="store_true",
        # FIX 4: flag now applies to both `update` and `autoupdate`.
        help="Do not reboot after update (applies to both `update` and `autoupdate`)",
    )
    args = parser.parse_args()

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if args.command == "install":
            print_json(install())
        elif args.command == "status":
            state = read_json(STATE_FILE, {})
            state.setdefault("installed_version", installed_version())
            print_json(state)
        elif args.command == "check":
            print_json(check_for_update())
        elif args.command == "update":
            result = apply_update()
            print_json(result)
            if not args.no_reboot and result.get("pending_restart"):
                request_reboot()
        elif args.command == "autoupdate":
            # FIX 4: pass the flag through so autoupdate respects --no-reboot.
            print_json(autoupdate(no_reboot=args.no_reboot))
        elif args.command == "post-reboot-check":
            print_json(post_reboot_check())
        elif args.command == "reboot":
            request_reboot()
            print_json(read_json(STATE_FILE, {}))
        return 0
    except Exception as exc:
        write_state(update_in_progress=False, last_error=str(exc))
        print_json(read_json(STATE_FILE, {}))
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())