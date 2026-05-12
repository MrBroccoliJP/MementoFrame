#!/usr/bin/env python3
# MementoFrame - Raspberry Pi Smart Photo Frame
# Updater / installer helper

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

UPDATER_BUILD = "2026-05-12-preserve-userdata-v9"

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_FILE = PROJECT_ROOT / "config.json"
RUNTIME_DIR = PROJECT_ROOT / "runtime"
STATE_FILE = RUNTIME_DIR / "update_state.json"
BACKUP_ROOT = PROJECT_ROOT.parent / "mementoframe_backups"
DEFAULT_UPDATE_TIME = "05:00"
DEFAULT_PRESERVE = ["config.json", ".env", "resources/userdata", "runtime"]
DEFAULT_SERVICES = ["mementoframe.service", "kiosk.service"]
HEALTH_URLS = ["http://127.0.0.1:5000/health", "http://127.0.0.1:5001/health"]
APP_SUBDIR = "mementoframe"

EXCLUDE_DURING_COPY = {
    ".git",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "runtime",
    "resources/userdata",
}


def now_ts() -> int:
    return int(time.time())


def load_dotenv() -> None:
    for env_path in [PROJECT_ROOT / ".env", PROJECT_ROOT.parent / ".env"]:
        if not env_path.exists():
            continue
        try:
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except Exception:
            pass


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


def base_state(**updates: Any) -> dict[str, Any]:
    data = {
        "updater_build": UPDATER_BUILD,
        "installed_version": installed_version(),
        "latest_version": None,
        "latest_tag": None,
        "release_name": None,
        "release_notes": "",
        "release_url": None,
        "zipball_url": None,
        "available": False,
        "checked_at": None,
        "pending_restart": False,
        "reboot_requested": False,
        "update_in_progress": False,
        "last_error": None,
    }
    data.update(updates)
    return data


def write_state(**updates: Any) -> dict[str, Any]:
    state = read_json(STATE_FILE, {})
    state.update({"updater_build": UPDATER_BUILD, "installed_version": installed_version()})
    state.update(updates)
    state.setdefault("latest_version", None)
    state.setdefault("available", False)
    state.setdefault("pending_restart", False)
    state.setdefault("reboot_requested", False)
    state.setdefault("update_in_progress", False)
    state.setdefault("last_error", None)
    atomic_write_json(STATE_FILE, state)
    return state


def replace_state(**updates: Any) -> dict[str, Any]:
    state = base_state(**updates)
    atomic_write_json(STATE_FILE, state)
    return state


def installed_version() -> str:
    # Read from file directly to avoid Python import cache after updates.
    version_file = PROJECT_ROOT / "version_info.py"
    try:
        text = version_file.read_text(encoding="utf-8")
        m = re.search(r'^GLOBAL_APP_VERSION\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        if m:
            return m.group(1)
        m = re.search(r'["\'](?:MementoFrame|Global App Version)["\']\s*:\s*["\']([^"\']+)["\']', text)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "0.0.0"


def load_config() -> dict[str, Any]:
    load_dotenv()
    cfg = read_json(CONFIG_FILE, {})
    cfg.setdefault("updates", {})
    updates = cfg["updates"]
    updates.setdefault("auto_update", False)
    updates.setdefault("repo", os.getenv("MEMENTOFRAME_UPDATE_REPO", ""))
    updates.setdefault("channel", "stable")
    updates.setdefault("preserve", DEFAULT_PRESERVE)
    # Always use the project service names. Do not require config edits.
    updates["service_names"] = DEFAULT_SERVICES
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    atomic_write_json(CONFIG_FILE, cfg)


def parse_version(v: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(v).strip().lstrip("vV"))
    return tuple(int(p) for p in parts[:4]) or (0,)


def version_newer(latest: str, current: str) -> bool:
    a = parse_version(latest)
    b = parse_version(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def http_json(url: str, timeout: int = 15) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "MementoFrame-Updater",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def github_latest_release(repo: str, channel: str = "stable") -> dict[str, Any]:
    if not repo or "/" not in repo:
        raise RuntimeError("Update repo is not configured. Set updates.repo or MEMENTOFRAME_UPDATE_REPO.")

    # IMPORTANT: /releases/latest ignores pre-releases and can return 404 when
    # all releases are pre-releases. Your repo currently has pre-releases only.
    if channel in {"pre-release", "prerelease", "pre_release"}:
        releases = http_json(f"https://api.github.com/repos/{repo}/releases?per_page=10")
        if not isinstance(releases, list) or not releases:
            raise RuntimeError("No GitHub releases found.")
        for release in releases:
            if not release.get("draft"):
                return release
        raise RuntimeError("Only draft releases found.")

    return http_json(f"https://api.github.com/repos/{repo}/releases/latest")


def check_for_update() -> dict[str, Any]:
    cfg = load_config()
    updates = cfg.get("updates", {})
    repo = updates.get("repo", "")
    channel = updates.get("channel", "stable")
    current = installed_version()
    try:
        release = github_latest_release(repo, channel=channel)
        latest = str(release.get("tag_name") or "").lstrip("v")
        available = bool(latest and version_newer(latest, current))
        return replace_state(
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
    except Exception as exc:
        return replace_state(
            installed_version=current,
            checked_at=now_ts(),
            available=False,
            last_error=str(exc),
        )


def should_preserve(rel: str, preserve: list[str]) -> bool:
    rel = rel.strip("/")
    return any(rel == p.strip("/") or rel.startswith(p.strip("/") + "/") for p in preserve)


def copy_tree_contents(src: Path, dst: Path, preserve: list[str]) -> list[str]:
    """Copy release files into the live app tree without touching preserved paths.

    This is intentionally recursive instead of using shutil.copytree() with an
    ignore callback. The old implementation copied top-level folders such as
    resources/ with copytree(), but the ignore callback could not reliably map
    extracted-release paths back to project-relative paths. That allowed nested
    preserved folders like resources/userdata to be replaced by the release.

    The recursive copy below computes the project-relative path itself for every
    item before copying, so preserve entries such as resources/userdata, .env,
    config.json, and runtime are protected at every depth.
    """
    copied_top_level: list[str] = []

    def is_copyable(path: Path) -> bool:
        try:
            mode = os.lstat(path).st_mode
        except OSError:
            return False
        return stat.S_ISDIR(mode) or stat.S_ISREG(mode) or stat.S_ISLNK(mode)

    def copy_dir(src_dir: Path, dst_dir: Path, rel_prefix: str = "") -> None:
        for item in src_dir.iterdir():
            name = item.name
            rel = f"{rel_prefix}/{name}" if rel_prefix else name

            if name in EXCLUDE_DURING_COPY or should_preserve(rel, preserve):
                continue
            if not is_copyable(item):
                continue

            target = dst_dir / name

            if item.is_dir() and not item.is_symlink():
                if target.exists() and not target.is_dir():
                    target.unlink()
                target.mkdir(parents=True, exist_ok=True)
                copy_dir(item, target, rel)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and target.is_dir():
                    shutil.rmtree(target)
                shutil.copy2(item, target, follow_symlinks=False)

            if not rel_prefix and name not in copied_top_level:
                copied_top_level.append(name)

    copy_dir(src, dst)
    return copied_top_level


def restore_preserved_from_backup(backup: Path, dst: Path, preserve: list[str]) -> list[str]:
    """Restore critical preserved paths after copy as a second safety net.

    The copy routine should already skip these paths. This restore step makes the
    updater resilient against future copy logic mistakes or unexpected release
    structures. It intentionally restores only config/.env/userdata, not the
    whole runtime folder, because runtime/update_state.json is managed by the
    updater itself.
    """
    restored: list[str] = []
    critical = ["config.json", ".env", "resources/userdata"]
    for rel in critical:
        if not should_preserve(rel, preserve):
            continue
        src_path = backup / rel
        dst_path = dst / rel
        if not src_path.exists() and not src_path.is_symlink():
            continue
        if dst_path.exists() or dst_path.is_symlink():
            if dst_path.is_dir() and not dst_path.is_symlink():
                shutil.rmtree(dst_path)
            else:
                dst_path.unlink()
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if src_path.is_dir() and not src_path.is_symlink():
            shutil.copytree(src_path, dst_path, symlinks=True, ignore_dangling_symlinks=True)
        else:
            shutil.copy2(src_path, dst_path, follow_symlinks=False)
        restored.append(rel)
    return restored

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


def find_release_app_root(extract_dir: Path) -> Path:
    candidates: list[Path] = []
    for root, dirs, files in os.walk(extract_dir):
        p = Path(root)
        if "app.py" in files and "api_service.py" in files:
            candidates.append(p)
    if not candidates:
        raise RuntimeError("Could not find app.py + api_service.py inside release archive.")
    for candidate in candidates:
        if candidate.name == APP_SUBDIR:
            return candidate
    return sorted(candidates, key=lambda p: len(p.parts))[0]


def run(cmd: list[str], check: bool = False, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{proc.stderr or proc.stdout}")
    return proc


def sudo_cmd(*cmd: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return run(["sudo", "-n", *cmd], check=False, timeout=timeout)


def restart_services(services: list[str]) -> None:
    for svc in services:
        proc = sudo_cmd("systemctl", "restart", svc, timeout=30)
        if proc.returncode != 0:
            print(f"⚠️ systemctl restart {svc}: {proc.stderr.strip() or proc.stdout.strip()}")



def cleanup_special_files(root: Path) -> list[str]:
    """Remove special filesystem nodes that should never live in the app tree.

    Some desktop/file-sync/runtime tools can leave FIFOs/named pipes, sockets,
    or device nodes under the project directory. Python's shutil.copytree
    raises on these during backup. They are not source files and cannot be
    restored meaningfully, so delete them before backup/update.
    """
    removed: list[str] = []
    for path in root.rglob("*"):
        try:
            mode = os.lstat(path).st_mode
        except OSError:
            continue
        if stat.S_ISDIR(mode) or stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            continue
        try:
            path.unlink()
            removed.append(str(path.relative_to(root)))
        except Exception as exc:
            # If we cannot remove it, backup_ignore will still skip it. Keep
            # a trace in update_state for debugging without failing early.
            removed.append(f"FAILED:{path.relative_to(root)}:{exc}")
    return removed

def backup_ignore(directory: str, names: list[str]) -> set[str]:
    """Return names that should be skipped during backup.

    The updater must never fail because a runtime/tooling process created a
    special file in the project tree. This skips FIFOs/named pipes, sockets,
    block devices, character devices, and other non-regular filesystem nodes.
    It also skips heavy/runtime folders that are either regenerated or already
    preserved separately.
    """
    ignored = set(shutil.ignore_patterns(
        "venv",
        "__pycache__",
        ".git",
        ".pytest_cache",
        "node_modules",
        "runtime/update_state.json",
    )(directory, names))

    for name in names:
        if name in ignored:
            continue
        path = Path(directory) / name
        try:
            mode = os.lstat(path).st_mode
        except OSError:
            ignored.add(name)
            continue

        # Directories, normal files, and symlinks are safe for copytree with
        # ignore_dangling_symlinks=True. Everything else is a special file
        # and should not be part of an app backup.
        if stat.S_ISDIR(mode) or stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            continue

        ignored.add(name)

    return ignored


def backup_current() -> tuple[Path, list[str]]:
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    removed_special_files = cleanup_special_files(PROJECT_ROOT)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_ROOT / f"mementoframe-{installed_version()}-{stamp}"
    shutil.copytree(
        PROJECT_ROOT,
        dest,
        ignore=backup_ignore,
        ignore_dangling_symlinks=True,
    )
    return dest, removed_special_files


def download_file(url: str, dest: Path, timeout: int = 60) -> str:
    headers = {"User-Agent": "MementoFrame-Updater"}
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=timeout) as res, dest.open("wb") as f:
        while True:
            chunk = res.read(1024 * 256)
            if not chunk:
                break
            h.update(chunk)
            f.write(chunk)
    return h.hexdigest()


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
    updates = cfg.get("updates", {})
    preserve = list(updates.get("preserve") or DEFAULT_PRESERVE)
    services = list(updates.get("service_names") or DEFAULT_SERVICES)

    state = read_json(STATE_FILE, {})
    if not state.get("zipball_url") or not state.get("available"):
        state = check_for_update()
    if not state.get("available"):
        return write_state(update_in_progress=False, applied_update=False)

    latest = state.get("latest_version") or state.get("latest_tag") or "unknown"
    write_state(update_in_progress=True, update_started_at=now_ts(), last_error=None)

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

        release_root = find_release_app_root(extract_dir)
        backup, removed_special_files = backup_current()
        copied = copy_tree_contents(release_root, PROJECT_ROOT, preserve)
        restored_preserved = restore_preserved_from_backup(backup, PROJECT_ROOT, preserve)
        install_requirements()

    new_version = installed_version()
    return write_state(
        installed_version=new_version,
        latest_version=str(latest).lstrip("v"),
        available=False,
        update_in_progress=False,
        pending_restart=True,
        reboot_requested=True,
        applied_update=True,
        updated_at=now_ts(),
        downloaded_sha256=sha256,
        backup_path=str(backup),
        removed_special_files=removed_special_files,
        restored_preserved=restored_preserved,
        release_root=str(release_root),
        copied_top_level=copied,
        last_error=None,
    )


def request_reboot() -> None:
    write_state(pending_restart=True, reboot_requested=True)
    proc = sudo_cmd("reboot", timeout=10)
    if proc.returncode != 0:
        print(f"⚠️ reboot failed: {proc.stderr.strip() or proc.stdout.strip()}")


def parse_hm(value: str) -> tuple[int, int]:
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(value or ""))
    if not m:
        return (5, 0)
    return max(0, min(23, int(m.group(1)))), max(0, min(59, int(m.group(2))))


def current_minutes() -> int:
    n = datetime.now()
    return n.hour * 60 + n.minute


def auto_update_target_minute(cfg: dict[str, Any]) -> int:
    ap = cfg.get("auto_power") or {}
    if ap.get("enabled"):
        h, m = parse_hm(ap.get("on_time", DEFAULT_UPDATE_TIME))
        return (h * 60 + m - 30) % (24 * 60)
    h, m = parse_hm(DEFAULT_UPDATE_TIME)
    return h * 60 + m


def in_auto_update_window(cfg: dict[str, Any], window_minutes: int = 20) -> bool:
    target = auto_update_target_minute(cfg)
    now = current_minutes()
    return 0 <= ((now - target) % (24 * 60)) < window_minutes


def autoupdate(no_reboot: bool = False) -> dict[str, Any]:
    cfg = load_config()
    if not cfg.get("updates", {}).get("auto_update"):
        return write_state(auto_update_skipped="disabled", last_autoupdate_check=now_ts())
    if not in_auto_update_window(cfg):
        return write_state(auto_update_skipped="outside_window", last_autoupdate_check=now_ts())
    state = check_for_update()
    if state.get("available"):
        result = apply_update()
        if result.get("applied_update") and not no_reboot:
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
    return replace_state(installed_version=installed_version(), installed_at=now_ts(), last_error=None)


def diagnose() -> dict[str, Any]:
    cfg = load_config()
    updates = cfg.get("updates", {})
    repo = updates.get("repo", "")
    channel = updates.get("channel", "stable")
    url = f"https://api.github.com/repos/{repo}/releases?per_page=10" if channel.startswith("pre") else f"https://api.github.com/repos/{repo}/releases/latest"
    out = {
        "updater_build": UPDATER_BUILD,
        "project_root": str(PROJECT_ROOT),
        "installed_version": installed_version(),
        "repo": repo,
        "channel": channel,
        "url": url,
        "github_token_loaded": bool(os.getenv("GITHUB_TOKEN", "").strip()),
    }
    try:
        data = http_json(url)
        if isinstance(data, list):
            out["release_count"] = len(data)
            out["tags"] = [r.get("tag_name") for r in data]
        else:
            out["tag"] = data.get("tag_name")
    except Exception as exc:
        out["error"] = str(exc)
    return out


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="MementoFrame updater")
    parser.add_argument("command", choices=["install", "status", "check", "update", "autoupdate", "post-reboot-check", "reboot", "diagnose"])
    parser.add_argument("--no-reboot", action="store_true", help="Do not reboot after update/autoupdate")
    args = parser.parse_args()

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "install":
            print_json(install())
        elif args.command == "status":
            state = read_json(STATE_FILE, {})
            state.setdefault("updater_build", UPDATER_BUILD)
            state.setdefault("installed_version", installed_version())
            print_json(state)
        elif args.command == "diagnose":
            print_json(diagnose())
        elif args.command == "check":
            print_json(check_for_update())
        elif args.command == "update":
            result = apply_update()
            print_json(result)
            if result.get("applied_update") and not args.no_reboot:
                request_reboot()
        elif args.command == "autoupdate":
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
