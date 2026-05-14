#!/usr/bin/env bash
set -euo pipefail

# MementoFrame one-command installer for Raspberry Pi OS Bookworm/Trixie.
# Run with: sudo bash install.sh

APP_USER="${APP_USER:-mementoframe}"
APP_HOME="${APP_HOME:-/home/${APP_USER}}"
APP_DIR="${APP_DIR:-${APP_HOME}/mementoframe}"
SRC_DIR="${SRC_DIR:-}"
INSTALL_REPO="${INSTALL_REPO:-MrBroccoliJP/MementoFrame}"
INSTALL_CHANNEL="${INSTALL_CHANNEL:-stable}"
INSTALL_TAG="${INSTALL_TAG:-}"
REPO_TMP="${REPO_TMP:-/tmp/mementoframe-install-src}"
KIOSK_SCRIPT="/usr/local/bin/mementoframe-kiosk.sh"
CONFIG_SERVICE="/etc/systemd/system/mementoframe-config.service"
DISPLAY_SERVICE="/etc/systemd/system/mementoframe-display.service"
NETWORK_SERVICE="/etc/systemd/system/mementoframe-network.service"
KIOSK_SERVICE="/etc/systemd/system/mementoframe-kiosk.service"
POST_REBOOT_SERVICE="/etc/systemd/system/mementoframe-post-reboot.service"
SUDOERS_FILE="/etc/sudoers.d/mementoframe-updater"
BOOT_CONFIG="/boot/firmware/config.txt"
BOOT_CMDLINE="/boot/firmware/cmdline.txt"
XWRAPPER_CONFIG="/etc/X11/Xwrapper.config"

ALL_SERVICES=(
  mementoframe-kiosk.service
  mementoframe-post-reboot.service
  mementoframe-network.service
  mementoframe-display.service
  mementoframe-config.service
)

NEW_SERVICES=(
  mementoframe-config.service
  mementoframe-display.service
  mementoframe-network.service
  mementoframe-kiosk.service
  mementoframe-post-reboot.service
)

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: run this installer with sudo: sudo bash install.sh" >&2
  exit 1
fi

print_license_banner() {
  cat <<'EOF_LICENSE'
MementoFrame - Raspberry Pi Smart Photo Frame
Copyright (c) 2026 João Fernandes

This work is licensed under the Creative Commons Attribution-NonCommercial
4.0 International License. To view a copy of this license, visit:
http://creativecommons.org/licenses/by-nc/4.0/
EOF_LICENSE
}

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\n\033[1;33mWARN: %s\033[0m\n' "$*"; }

service_exists() {
  systemctl list-unit-files "$1" >/dev/null 2>&1 || [[ -f "/etc/systemd/system/$1" ]]
}

stop_service_if_exists() {
  local svc="$1"
  if service_exists "$svc"; then
    systemctl stop "$svc" 2>/dev/null || true
  fi
}

disable_service_if_exists() {
  local svc="$1"
  if service_exists "$svc"; then
    systemctl disable --now "$svc" 2>/dev/null || true
  fi
}

ensure_cmdline_token() {
  local file="$1"
  local token="$2"
  touch "$file"
  local line
  line="$(tr '\n' ' ' < "$file" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')"
  if [[ " $line " != *" $token "* ]]; then
    line="${line} ${token}"
  fi
  printf '%s\n' "$(echo "$line" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')" > "$file"
}

remove_cmdline_token() {
  local file="$1"
  local token="$2"
  touch "$file"
  local line
  line="$(tr '\n' ' ' < "$file" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')"
  line=" ${line} "
  line="${line// ${token} / }"
  printf '%s\n' "$(echo "$line" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')" > "$file"
}

remove_cmdline_key() {
  local file="$1"
  local key="$2"
  touch "$file"
  local token
  local line=""
  for token in $(tr '\n' ' ' < "$file"); do
    if [[ "$token" != "${key}="* ]]; then
      line="${line} ${token}"
    fi
  done
  printf '%s\n' "$(echo "$line" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')" > "$file"
}

set_cmdline_key() {
  local file="$1"
  local key="$2"
  local value="$3"
  remove_cmdline_key "$file" "$key"
  ensure_cmdline_token "$file" "${key}=${value}"
}

configure_boot_and_x11() {
  log "Configuring boot display settings"

  if [[ -f "$BOOT_CONFIG" ]]; then
    cp -a "$BOOT_CONFIG" "${BOOT_CONFIG}.mementoframe.bak.$(date +%Y%m%d-%H%M%S)"
    BOOT_CONFIG="$BOOT_CONFIG" python3 - <<'PY_BOOT_CONFIG'
from pathlib import Path
import os

path = Path(os.environ["BOOT_CONFIG"])
text = path.read_text(encoding="utf-8")
lines = text.splitlines()

global_settings = {"dtoverlay": "vc4-fkms-v3d"}
all_settings = {
    "enable_uart": "1",
    "disable_splash": "1",
    "avoid_warnings": "1",
    "gpu_mem": "185",
    "gpio": "26=op,dh",
    "hdmi_force_hotplug": "1",
    "hdmi_group": "2",
    "hdmi_mode": "87",
    "hdmi_cvt": "1024 600 60 6 0 0 0",
    "config_hdmi_boost": "7",
}

section_re = lambda line: line.strip().startswith("[") and line.strip().endswith("]")

def section_name(line: str) -> str | None:
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return stripped[1:-1].strip().lower()
    return None

first_section = next((i for i, line in enumerate(lines) if section_re(line)), len(lines))
for key, value in global_settings.items():
    found = False
    for i in range(first_section):
        raw = lines[i].strip()
        if raw.startswith("#") or "=" not in raw:
            continue
        if raw.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        insert_at = first_section
        if insert_at > 0 and lines[insert_at - 1].strip():
            lines.insert(insert_at, "")
            insert_at += 1
        lines.insert(insert_at, f"{key}={value}")
        first_section += 1

all_start = None
for i, line in enumerate(lines):
    if section_name(line) == "all":
        all_start = i
        break
if all_start is None:
    if lines and lines[-1].strip():
        lines.append("")
    lines.append("[all]")
    all_start = len(lines) - 1

all_end = len(lines)
for i in range(all_start + 1, len(lines)):
    if section_re(lines[i]):
        all_end = i
        break

for key, value in all_settings.items():
    found = False
    for i in range(all_start + 1, all_end):
        raw = lines[i].strip()
        if raw.startswith("#") or "=" not in raw:
            continue
        if raw.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.insert(all_end, f"{key}={value}")
        all_end += 1

path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
PY_BOOT_CONFIG
  else
    warn "$BOOT_CONFIG not found; skipping boot config.txt changes"
  fi

  log "Configuring quiet boot console"
  if [[ -f "$BOOT_CMDLINE" ]]; then
    cp -a "$BOOT_CMDLINE" "${BOOT_CMDLINE}.mementoframe.bak.$(date +%Y%m%d-%H%M%S)"
    remove_cmdline_token "$BOOT_CMDLINE" "console=tty1"
    remove_cmdline_token "$BOOT_CMDLINE" "fsck.mode=skip"
    remove_cmdline_key "$BOOT_CMDLINE" "systemd.show_status"
    remove_cmdline_key "$BOOT_CMDLINE" "rd.systemd.show_status"
    remove_cmdline_token "$BOOT_CMDLINE" "plymouth.ignore-serial-consoles"
    ensure_cmdline_token "$BOOT_CMDLINE" "console=tty3"
    ensure_cmdline_token "$BOOT_CMDLINE" "quiet"
    ensure_cmdline_token "$BOOT_CMDLINE" "splash"
    set_cmdline_key "$BOOT_CMDLINE" "loglevel" "1"
    ensure_cmdline_token "$BOOT_CMDLINE" "logo.nologo"
    set_cmdline_key "$BOOT_CMDLINE" "vt.global_cursor_default" "0"
    set_cmdline_key "$BOOT_CMDLINE" "consoleblank" "0"
  else
    warn "$BOOT_CMDLINE not found; skipping cmdline.txt changes"
  fi

  log "Configuring X permissions"
  mkdir -p "$(dirname "$XWRAPPER_CONFIG")"
  if [[ -f "$XWRAPPER_CONFIG" ]]; then
    cp -a "$XWRAPPER_CONFIG" "${XWRAPPER_CONFIG}.mementoframe.bak.$(date +%Y%m%d-%H%M%S)"
  fi
  cat > "$XWRAPPER_CONFIG" <<'EOF_XWRAPPER'
allowed_users=anybody
needs_root_rights=yes
EOF_XWRAPPER

  # Prevent tty1 login text from flashing before Chromium takes over.
  systemctl disable --now getty@tty1.service 2>/dev/null || true
  systemctl mask getty@tty1.service 2>/dev/null || true
}

enable_wifi_radio() {
  log "Enabling Wi-Fi radio"

  rfkill unblock wifi 2>/dev/null || true
  nmcli radio wifi on 2>/dev/null || true

  systemctl restart NetworkManager
  sleep 3

  if command -v nmcli >/dev/null 2>&1; then
    WIFI_STATE="$(nmcli -t -f WIFI radio 2>/dev/null || true)"
    if [[ "${WIFI_STATE}" != "enabled" ]]; then
      warn "Wi-Fi radio is not enabled yet. Current state: ${WIFI_STATE:-unknown}"
      warn "Check rfkill with: rfkill list"
    fi
    nmcli radio wifi || true
    nmcli device status || true
  fi
}

print_license_banner

log "Creating/checking user: ${APP_USER}"
if ! id "${APP_USER}" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "MementoFrame" "${APP_USER}"
fi
usermod -aG video,input,gpio,netdev "${APP_USER}" || true
mkdir -p "${APP_HOME}"
chown "${APP_USER}:${APP_USER}" "${APP_HOME}"

log "Stopping existing MementoFrame services"
systemctl daemon-reload || true
for svc in "${ALL_SERVICES[@]}"; do
  stop_service_if_exists "$svc"
done

log "Installing system dependencies"
apt update
apt install -y \
  python3 \
  python3-pip \
  python3-venv \
  git \
  network-manager \
  wireless-tools \
  iw \
  iproute2 \
  rfkill \
  curl \
  ca-certificates \
  unclutter \
  xserver-xorg \
  xinit \
  openbox \
  x11-xserver-utils \
  libjpeg-dev \
  zlib1g-dev \
  libwebp-dev \
  webp \
  python3-rpi.gpio

if ! command -v chromium >/dev/null 2>&1; then
  apt install -y chromium
fi

log "Enabling NetworkManager"
systemctl disable --now dhcpcd 2>/dev/null || true
systemctl mask dhcpcd 2>/dev/null || true
systemctl enable --now NetworkManager

enable_wifi_radio
configure_boot_and_x11

log "Preparing source"
rm -rf "${REPO_TMP}"
mkdir -p "${REPO_TMP}"

if [[ -n "${SRC_DIR}" ]]; then
  log "Using local source from SRC_DIR=${SRC_DIR}"
  if [[ ! -d "${SRC_DIR}/mementoframe" ]]; then
    echo "ERROR: SRC_DIR must point to the repo root containing mementoframe/" >&2
    exit 1
  fi
  cp -a "${SRC_DIR}" "${REPO_TMP}/repo"
else
  log "Downloading MementoFrame release from GitHub"
  INSTALL_REPO="${INSTALL_REPO}" \
  INSTALL_CHANNEL="${INSTALL_CHANNEL}" \
  INSTALL_TAG="${INSTALL_TAG}" \
  REPO_TMP="${REPO_TMP}" \
  GITHUB_TOKEN="${GITHUB_TOKEN:-}" \
  python3 - <<'PY_RELEASE_DOWNLOAD'
from __future__ import annotations

import json
import os
import re
import shutil
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

repo = os.environ.get("INSTALL_REPO", "").strip()
channel = os.environ.get("INSTALL_CHANNEL", "stable").strip().lower()
tag = os.environ.get("INSTALL_TAG", "").strip()
repo_tmp = Path(os.environ["REPO_TMP"])
token = os.environ.get("GITHUB_TOKEN", "").strip()

if not repo or "/" not in repo:
    raise SystemExit("ERROR: INSTALL_REPO must be owner/repository, for example MrBroccoliJP/MementoFrame")

headers = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "MementoFrame-Installer",
}
if token:
    headers["Authorization"] = f"Bearer {token}"


def http_json(url: str):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8"))


def parse_version(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(value).strip().lstrip("vV"))
    return tuple(int(p) for p in parts) or (0,)

if tag:
    encoded_tag = urllib.parse.quote(tag, safe="")
    release = http_json(f"https://api.github.com/repos/{repo}/releases/tags/{encoded_tag}")
elif channel in {"pre-release", "prerelease", "pre_release"}:
    releases = http_json(f"https://api.github.com/repos/{repo}/releases?per_page=30")
    candidates = [r for r in releases if not r.get("draft") and r.get("tag_name")]
    if not candidates:
        raise SystemExit("ERROR: no non-draft GitHub releases found")
    release = max(candidates, key=lambda r: parse_version(r.get("tag_name") or ""))
else:
    release = http_json(f"https://api.github.com/repos/{repo}/releases/latest")

zipball_url = release.get("zipball_url")
if not zipball_url:
    raise SystemExit("ERROR: selected GitHub release does not include a zipball_url")

print(f"Selected release: {release.get('tag_name') or release.get('name')}")
archive = repo_tmp / "release.zip"
zip_headers = {"User-Agent": "MementoFrame-Installer"}
if token:
    zip_headers["Authorization"] = f"Bearer {token}"
req = urllib.request.Request(zipball_url, headers=zip_headers)
with urllib.request.urlopen(req, timeout=120) as res, archive.open("wb") as f:
    shutil.copyfileobj(res, f)

extract_dir = repo_tmp / "extract"
extract_dir.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive) as zf:
    bad = zf.testzip()
    if bad:
        raise SystemExit(f"ERROR: corrupt release archive member: {bad}")
    zf.extractall(extract_dir)

candidates = []
for path in extract_dir.rglob("mementoframe"):
    if path.is_dir() and (path / "updater.py").is_file():
        candidates.append(path.parent)

if not candidates:
    raise SystemExit("ERROR: release archive does not contain mementoframe/updater.py")

source_root = sorted(candidates, key=lambda p: len(p.parts))[0]
shutil.copytree(source_root, repo_tmp / "repo")
PY_RELEASE_DOWNLOAD
fi

for required in updater.py version_info.py config_portal_service.py display_service.py network_manager_service.py requirements.txt; do
  if [[ ! -f "${REPO_TMP}/repo/mementoframe/${required}" ]]; then
    echo "ERROR: source does not contain mementoframe/${required}" >&2
    echo "The split-service layout requires config_portal_service.py, display_service.py, and network_manager_service.py." >&2
    exit 1
  fi
done

log "Installing app to ${APP_DIR}"

if [[ -d "${APP_DIR}" ]]; then
  BACKUP="${APP_HOME}/mementoframe.preinstall.$(date +%Y%m%d-%H%M%S)"
  warn "Existing app directory found. Moving it to ${BACKUP}"
  mv "${APP_DIR}" "${BACKUP}"
fi
cp -a "${REPO_TMP}/repo/mementoframe" "${APP_DIR}"
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

log "Running app bootstrap"
sudo -u "${APP_USER}" bash -lc "cd '${APP_DIR}' && python3 updater.py install"

log "Forcing update settings"
sudo -u "${APP_USER}" APP_DIR="${APP_DIR}" INSTALL_REPO="${INSTALL_REPO}" INSTALL_CHANNEL="${INSTALL_CHANNEL}" python3 - <<'PY_UPDATE_CONFIG'
import json
import os
from pathlib import Path

app_dir = Path(os.environ["APP_DIR"])
config_path = app_dir / "config.json"
try:
    config = json.loads(config_path.read_text(encoding="utf-8"))
except FileNotFoundError:
    config = {}
updates = config.setdefault("updates", {})
updates["auto_update"] = True
updates["repo"] = os.environ.get("INSTALL_REPO", "MrBroccoliJP/MementoFrame") or "MrBroccoliJP/MementoFrame"
updates["channel"] = os.environ.get("INSTALL_CHANNEL", "stable") or "stable"
updates["preserve"] = ["config.json", ".env", "resources/userdata", "runtime"]
updates["service_names"] = [
    "mementoframe-config.service",
    "mementoframe-display.service",
    "mementoframe-network.service",
    "mementoframe-kiosk.service",
]
config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
PY_UPDATE_CONFIG

log "Writing sudoers for updater, Wi-Fi, and reboot"
cat > "${SUDOERS_FILE}" <<EOF_SUDOERS
${APP_USER} ALL=(root) NOPASSWD: \\
  /usr/bin/systemctl restart mementoframe-config.service, \\
  /usr/bin/systemctl restart mementoframe-display.service, \\
  /usr/bin/systemctl restart mementoframe-network.service, \\
  /usr/bin/systemctl restart mementoframe-kiosk.service, \\
  /usr/bin/systemctl stop hostapd, \\
  /usr/bin/systemctl stop dnsmasq, \\
  /usr/bin/nmcli, \\
  /usr/sbin/reboot, \\
  /sbin/reboot, \\
  /usr/bin/reboot
EOF_SUDOERS
chmod 0440 "${SUDOERS_FILE}"
visudo -cf "${SUDOERS_FILE}"

log "Writing systemd service: mementoframe-config.service"
cat > "${CONFIG_SERVICE}" <<EOF_CONFIG_SERVICE
[Unit]
Description=MementoFrame Config Portal Service
After=network-online.target NetworkManager.service
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python3 ${APP_DIR}/config_portal_service.py
Restart=always
RestartSec=2
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF_CONFIG_SERVICE

log "Writing systemd service: mementoframe-display.service"
cat > "${DISPLAY_SERVICE}" <<EOF_DISPLAY_SERVICE
[Unit]
Description=MementoFrame Display API Service
After=network-online.target NetworkManager.service
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python3 ${APP_DIR}/display_service.py
Restart=always
RestartSec=2
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF_DISPLAY_SERVICE

log "Writing systemd service: mementoframe-network.service"
cat > "${NETWORK_SERVICE}" <<EOF_NETWORK_SERVICE
[Unit]
Description=MementoFrame Network Manager Service
After=NetworkManager.service network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python3 ${APP_DIR}/network_manager_service.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF_NETWORK_SERVICE

log "Writing systemd service: mementoframe-post-reboot.service"
cat > "${POST_REBOOT_SERVICE}" <<EOF_POSTREBOOT
[Unit]
Description=MementoFrame post-reboot health check
After=mementoframe-config.service mementoframe-display.service
Requires=mementoframe-config.service mementoframe-display.service

[Service]
Type=oneshot
User=${APP_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python3 ${APP_DIR}/updater.py post-reboot-check

[Install]
WantedBy=multi-user.target
EOF_POSTREBOOT

log "Writing kiosk launcher"
cat > "${KIOSK_SCRIPT}" <<'EOF_KIOSK'
#!/usr/bin/env bash
export DISPLAY=:0

openbox-session &

sleep 1

xset -dpms || true
xset s off || true
xset s noblank || true
xsetroot -solid black || true

unclutter -idle 0.1 -root &

mkdir -p /dev/shm/chromium-cache 2>/dev/null || true

xset -dpms || true
xset s off || true
xset s noblank || true

exec chromium \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-translate \
  --disable-session-crashed-bubble \
  --disable-save-password-bubble \
  --no-first-run \
  --incognito \
  --password-store=basic \
  --disk-cache-dir=/dev/shm/chromium-cache \
  --disable-background-timer-throttling \
  --disable-backgrounding-occluded-windows \
  --enable-gpu-rasterization \
  --enable-zero-copy \
  --ignore-gpu-blocklist \
  --enable-native-gpu-memory-buffers \
  --enable-accelerated-2d-canvas \
  --enable-smooth-scrolling \
  --default-background-color=000000 \
  http://127.0.0.1:5001
EOF_KIOSK
chmod +x "${KIOSK_SCRIPT}"

log "Writing systemd service: mementoframe-kiosk.service"
cat > "${KIOSK_SERVICE}" <<EOF_KIOSK_SERVICE
[Unit]
Description=MementoFrame Chromium Kiosk
After=mementoframe-display.service
Requires=mementoframe-display.service

[Service]
User=${APP_USER}
Environment=DISPLAY=:0
ExecStart=/usr/bin/startx ${KIOSK_SCRIPT} -- :0
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF_KIOSK_SERVICE

log "Enabling services"
systemctl daemon-reload
for svc in "${NEW_SERVICES[@]}"; do
  systemctl enable "$svc"
done
systemctl restart mementoframe-network.service
systemctl restart mementoframe-config.service
systemctl restart mementoframe-display.service
systemctl restart mementoframe-kiosk.service || warn "Kiosk service did not start. This can happen before reboot; check journalctl -u mementoframe-kiosk.service."

log "Install complete"
echo "App root: ${APP_DIR}"
echo "Edit local secrets: sudo -u ${APP_USER} nano ${APP_DIR}/.env"
echo "Admin dashboard: http://<pi-ip>:5000"
echo "Logs: journalctl -u mementoframe-config.service -f"


if [[ "${SKIP_REBOOT:-0}" != "1" ]]; then
  log "Rebooting"
  echo "MementoFrame installation is complete. Rebooting now..."
  sleep 3
  systemctl reboot
else
  warn "Skipping reboot because SKIP_REBOOT=1"
fi