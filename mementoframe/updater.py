#!/usr/bin/env python3
# MementoFrame - Raspberry Pi Smart Photo Frame
# Updater / installer helper

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
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

UPDATER_BUILD = "2026-05-14-split-services-v2"

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_FILE = PROJECT_ROOT / "config.json"
RUNTIME_DIR = PROJECT_ROOT / "runtime"
STATE_FILE = RUNTIME_DIR / "update_state.json"
BACKUP_ROOT = PROJECT_ROOT.parent / "mementoframe_backups"
DEFAULT_UPDATE_TIME = "05:00"
DEFAULT_PRESERVE = ["config.json", ".env", "resources/userdata", "runtime"]
DEFAULT_SERVICES = [
    "mementoframe-config.service",
    "mementoframe-display.service",
    "mementoframe-network.service",
    "mementoframe-kiosk.service",
]
HEALTH_URLS = ["http://127.0.0.1:5000/health", "http://127.0.0.1:5001/health"]
APP_SUBDIR = "mementoframe"

EXCLUDE_DURING_COPY = {
    ".git",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "runtime",
}
SPECIAL_FILE_CLEANUP_SKIP = {
    ".git",
    "venv",
    "node_modules",
    "resources/userdata",
    "runtime",
}


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


def load_dotenv() -> None:
    for env_path in [PROJECT_ROOT / ".env", PROJECT_ROOT.parent / ".env"]:
        if not env_path.exists():
            continue
        try:
            for lineno, raw in enumerate(env_path.read_text(encoding="utf-8").splitlines(), 1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    print(f"⚠️ .env line {lineno}: ignored malformed entry: {line!r}", file=sys.stderr)
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except Exception:
            pass


def ensure_env_file() -> bool:
    """Create a starter .env if missing. Existing files are never overwritten."""
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        return False
    repo_hint = os.getenv("MEMENTOFRAME_UPDATE_REPO", "MrBroccoliJP/MementoFrame")
    env_path.write_text(
        "# MementoFrame local secrets and optional update settings\n"
        "# Leave Spotify values blank to keep Spotify disconnected.\n"
        "SPOTIFY_CLIENT_ID=\n"
        "SPOTIFY_CLIENT_SECRET=\n"
        "SPOTIFY_REDIRECT_URI=https://httpbin.org/anything\n"
        "\n"
        "# Optional. Needed for private GitHub repositories or higher API limits.\n"
        "GITHUB_TOKEN=\n"
        "\n"
        "# Optional. Overrides config.json updates.repo when set.\n"
        f"MEMENTOFRAME_UPDATE_REPO={repo_hint}\n",
        encoding="utf-8",
    )
    try:
        env_path.chmod(0o600)
    except Exception:
        pass
    return True


def installed_version() -> str:
    """Read the generated composite version from version_info.py without import cache."""
    version_file = PROJECT_ROOT / "version_info.py"
    try:
        data = runpy.run_path(str(version_file))
        version = data.get("GLOBAL_APP_VERSION")
        if version:
            return str(version)
    except Exception:
        pass
    return "0.0.0.0.0.0"


def base_state(**updates: Any) -> dict[str, Any]:
    state = {
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
        "applied_update": False,
        "last_error": None,
    }
    state.update(updates)
    return state


def replace_state(**updates: Any) -> dict[str, Any]:
    state = base_state(**updates)
    atomic_write_json(STATE_FILE, state)
    return state


def write_state(**updates: Any) -> dict[str, Any]:
    state = read_json(STATE_FILE, {})
    state.update({"updater_build": UPDATER_BUILD, "installed_version": installed_version()})
    state.update(updates)
    state.setdefault("latest_version", None)
    state.setdefault("available", False)
    state.setdefault("pending_restart", False)
    state.setdefault("reboot_requested", False)
    state.setdefault("update_in_progress", False)
    state.setdefault("applied_update", False)
    state.setdefault("last_error", None)
    atomic_write_json(STATE_FILE, state)
    return state


def load_config() -> dict[str, Any]:
    load_dotenv()
    cfg = read_json(CONFIG_FILE, {})
    cfg.setdefault("updates", {})
    updates = cfg["updates"]
    updates.setdefault("auto_update", True)
    updates.setdefault("repo", os.getenv("MEMENTOFRAME_UPDATE_REPO", "MrBroccoliJP/MementoFrame"))
    if os.getenv("MEMENTOFRAME_UPDATE_REPO"):
        updates["repo"] = os.getenv("MEMENTOFRAME_UPDATE_REPO", "")
    updates.setdefault("channel", "stable")
    updates.setdefault("preserve", DEFAULT_PRESERVE)
    updates["service_names"] = DEFAULT_SERVICES
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    atomic_write_json(CONFIG_FILE, cfg)


def parse_version(v: str) -> tuple[int, ...]:
    """Parse all numeric segments of tags like v1.25.22.21.21.13."""
    parts = re.findall(r"\d+", str(v).strip().lstrip("vV"))
    return tuple(int(p) for p in parts) or (0,)


def version_newer(latest: str, current: str) -> bool:
    a = parse_version(latest)
    b = parse_version(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def http_json(url: str, timeout: int = 15) -> Any:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "MementoFrame-Updater"}
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def github_latest_release(repo: str, channel: str = "stable") -> dict[str, Any]:
    if not repo or "/" not in repo:
        raise RuntimeError("Update repo is not configured. Set updates.repo or MEMENTOFRAME_UPDATE_REPO.")
    if channel in {"pre-release", "prerelease", "pre_release"}:
        releases = http_json(f"https://api.github.com/repos/{repo}/releases?per_page=30")
        if not isinstance(releases, list) or not releases:
            raise RuntimeError("No GitHub releases found.")
        candidates = [r for r in releases if not r.get("draft") and r.get("tag_name")]
        if not candidates:
            raise RuntimeError("No non-draft releases found.")
        return max(candidates, key=lambda r: parse_version(str(r.get("tag_name") or "")))
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
            release_assets=release.get("assets") or [],
            available=available,
            checked_at=now_ts(),
            last_error=None,
        )
    except Exception as exc:
        return replace_state(installed_version=current, checked_at=now_ts(), available=False, last_error=str(exc))


def should_preserve(rel: str, preserve: list[str]) -> bool:
    rel = rel.strip("/")
    return any(rel == p.strip("/") or rel.startswith(p.strip("/") + "/") for p in preserve if p.strip("/"))


def is_excluded(rel: str) -> bool:
    rel = rel.strip("/")
    return any(rel == p or rel.startswith(p + "/") for p in EXCLUDE_DURING_COPY)


def is_special_file(path: Path) -> bool:
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return True
    return not (stat.S_ISDIR(mode) or stat.S_ISREG(mode) or stat.S_ISLNK(mode))


def cleanup_special_files(root: Path = PROJECT_ROOT) -> list[str]:
    removed: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        try:
            rel_dir = str(current.relative_to(root)).strip(".")
        except Exception:
            rel_dir = ""
        keep_dirs = []
        for d in dirnames:
            rel = f"{rel_dir}/{d}".strip("/") if rel_dir else d
            if any(rel == skip or rel.startswith(skip + "/") for skip in SPECIAL_FILE_CLEANUP_SKIP):
                continue
            keep_dirs.append(d)
        dirnames[:] = keep_dirs
        for name in filenames:
            path = current / name
            try:
                if is_special_file(path):
                    rel = str(path.relative_to(root))
                    path.unlink()
                    removed.append(rel)
            except Exception as exc:
                removed.append(f"{path}: failed to remove ({exc})")
    return removed


def copy_one(src: Path, dst: Path, rel: str, preserve: list[str], copied_top: set[str]) -> None:
    rel = rel.strip("/")
    if not rel or should_preserve(rel, preserve) or is_excluded(rel):
        return
    if is_special_file(src):
        return
    top = rel.split("/", 1)[0]
    copied_top.add(top)
    if src.is_dir() and not src.is_symlink():
        dst.mkdir(parents=True, exist_ok=True)
        for child in src.iterdir():
            copy_one(child, dst / child.name, f"{rel}/{child.name}", preserve, copied_top)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.is_dir():
        shutil.rmtree(dst)
    shutil.copy2(src, dst, follow_symlinks=False)


def copy_tree_contents(src: Path, dst: Path, preserve: list[str]) -> list[str]:
    copied_top: set[str] = set()
    for item in src.iterdir():
        copy_one(item, dst / item.name, item.name, preserve, copied_top)
    return sorted(copied_top)


def backup_ignore(directory: str, names: list[str]) -> set[str]:
    ignored = set(shutil.ignore_patterns(
        "venv", "__pycache__", ".git", ".pytest_cache", "node_modules", "runtime/update_state.json",
    )(directory, names))
    for name in names:
        if name in ignored:
            continue
        path = Path(directory) / name
        if is_special_file(path):
            ignored.add(name)
    return ignored


def backup_current() -> Path:
    cleanup_special_files(PROJECT_ROOT)
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_ROOT / f"mementoframe-{installed_version()}-{stamp}"
    shutil.copytree(PROJECT_ROOT, dest, ignore=backup_ignore, ignore_dangling_symlinks=True)
    return dest


def restore_preserved_from_backup(backup: Path, preserve: list[str]) -> list[str]:
    restored: list[str] = []
    for rel in preserve:
        rel = rel.strip("/")
        if not rel:
            continue
        src = backup / rel
        dst = PROJECT_ROOT / rel
        if not src.exists() and not src.is_symlink():
            continue
        if dst.exists() or dst.is_symlink():
            if dst.is_dir() and not dst.is_symlink():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir() and not src.is_symlink():
            shutil.copytree(src, dst, symlinks=True, ignore_dangling_symlinks=True)
        else:
            shutil.copy2(src, dst, follow_symlinks=False)
        restored.append(rel)
    return restored


def find_release_app_root(extract_dir: Path) -> Path:
    candidates: list[Path] = []
    for root, _dirs, files in os.walk(extract_dir):
        p = Path(root)
        if "config_portal_service.py" in files and "display_service.py" in files:
            candidates.append(p)
    if not candidates:
        raise RuntimeError("Could not find config_portal_service.py + display_service.py inside release archive.")
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


def download_file(url: str, dest: Path, timeout: int = 60, expected_sha256: str | None = None) -> str:
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
    digest = h.hexdigest()
    if expected_sha256 and digest != expected_sha256.lower():
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 mismatch: expected {expected_sha256.lower()!r}, got {digest!r}")
    return digest


def fetch_release_checksum(release_assets: list[dict[str, Any]], filename: str) -> str | None:
    for asset in release_assets:
        name = str(asset.get("name") or "").lower()
        if name in {"checksums.txt", "sha256sums.txt", "checksums.sha256"}:
            url = asset.get("browser_download_url") or asset.get("url")
            if not url:
                continue
            try:
                headers = {"User-Agent": "MementoFrame-Updater"}
                token = os.getenv("GITHUB_TOKEN", "").strip()
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as res:
                    text = res.read().decode("utf-8", errors="replace")
                for line in text.splitlines():
                    parts = line.split()
                    if len(parts) == 2 and parts[1].lstrip("*") == filename:
                        return parts[0].lower()
            except Exception:
                pass
    return None


def repair_runtime_permissions() -> list[str]:
    fixed: list[str] = []
    for rel in ["updater.py", "network_manager_service.py", "config_portal_service.py", "display_service.py"]:
        path = PROJECT_ROOT / rel
        if not path.exists():
            continue
        try:
            path.chmod(path.stat().st_mode | 0o755)
            fixed.append(rel)
        except Exception as exc:
            fixed.append(f"{rel}: failed to chmod ({exc})")
    return fixed


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
    preserve = list(cfg.get("updates", {}).get("preserve") or DEFAULT_PRESERVE)
    state = read_json(STATE_FILE, {})
    if not state.get("zipball_url") or not state.get("available"):
        state = check_for_update()
    if not state.get("available"):
        return write_state(update_in_progress=False, applied_update=False)

    latest = state.get("latest_version") or state.get("latest_tag") or "unknown"
    write_state(update_in_progress=True, update_started_at=now_ts(), last_error=None)

    backup: Path | None = None
    sha256 = ""
    release_root_str = None
    copied: list[str] = []
    restored_preserved: list[str] = []
    fixed_permissions: list[str] = []
    removed_special_files: list[str] = []

    try:
        with tempfile.TemporaryDirectory(prefix="mementoframe-update-") as td:
            tmp = Path(td)
            archive = tmp / "release.zip"
            release_assets: list[dict[str, Any]] = state.get("release_assets") or []
            expected_sha256 = fetch_release_checksum(release_assets, "release.zip")
            sha256 = download_file(str(state["zipball_url"]), archive, expected_sha256=expected_sha256)
            extract_dir = tmp / "extract"
            extract_dir.mkdir()
            with zipfile.ZipFile(archive) as zf:
                bad = zf.testzip()
                if bad:
                    raise RuntimeError(f"Corrupted zip file: {bad}")
                zf.extractall(extract_dir)

            release_root = find_release_app_root(extract_dir)
            release_root_str = str(release_root)
            removed_special_files = cleanup_special_files(PROJECT_ROOT)
            backup = backup_current()
            copied = copy_tree_contents(release_root, PROJECT_ROOT, preserve)
            restored_preserved = restore_preserved_from_backup(backup, preserve)
            fixed_permissions = repair_runtime_permissions()
            install_requirements()

        return write_state(
            installed_version=installed_version(),
            latest_version=str(latest).lstrip("v"),
            available=False,
            update_in_progress=False,
            pending_restart=True,
            reboot_requested=True,
            applied_update=True,
            updated_at=now_ts(),
            downloaded_sha256=sha256,
            backup_path=str(backup) if backup else None,
            release_root=release_root_str,
            copied_top_level=copied,
            restored_preserved=restored_preserved,
            removed_special_files=removed_special_files,
            fixed_permissions=fixed_permissions,
            last_error=None,
        )
    except Exception as exc:
        write_state(update_in_progress=False, last_error=str(exc))
        raise


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
    env_created = ensure_env_file()
    # reload after creating .env so diagnose/check can see values immediately if present
    load_dotenv()
    venv = PROJECT_ROOT / "venv"
    if not venv.exists():
        run([sys.executable, "-m", "venv", str(venv)], check=True, timeout=300)
    removed_special_files = cleanup_special_files(PROJECT_ROOT)
    fixed_permissions = repair_runtime_permissions()
    install_requirements()
    return replace_state(
        installed_version=installed_version(),
        installed_at=now_ts(),
        env_created=env_created,
        removed_special_files=removed_special_files,
        fixed_permissions=fixed_permissions,
        last_error=None,
    )


def diagnose() -> dict[str, Any]:
    cfg = load_config()
    updates = cfg.get("updates", {})
    repo = updates.get("repo", "")
    channel = updates.get("channel", "stable")
    url = (
        f"https://api.github.com/repos/{repo}/releases?per_page=10"
        if str(channel).startswith("pre")
        else f"https://api.github.com/repos/{repo}/releases/latest"
    )
    out: dict[str, Any] = {
        "updater_build": UPDATER_BUILD,
        "project_root": str(PROJECT_ROOT),
        "installed_version": installed_version(),
        "repo": repo,
        "channel": channel,
        "url": url,
        "github_token_loaded": bool(os.getenv("GITHUB_TOKEN", "").strip()),
        "env_exists": (PROJECT_ROOT / ".env").exists(),
        "service_files_exist": {
            "config_portal_service.py": (PROJECT_ROOT / "config_portal_service.py").exists(),
            "display_service.py": (PROJECT_ROOT / "display_service.py").exists(),
            "network_manager_service.py": (PROJECT_ROOT / "network_manager_service.py").exists(),
        },
        "services": DEFAULT_SERVICES,
        "version_schema": "release.frontend.config.display.network.updater",
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
