#!/usr/bin/env bash
set -euo pipefail

# MementoFrame one-command installer for Raspberry Pi OS Bookworm/Trixie.
# Run with: sudo bash install.sh

APP_USER="${APP_USER:-mementoframe}"
APP_HOME="${APP_HOME:-/home/${APP_USER}}"
APP_DIR="${APP_DIR:-${APP_HOME}/mementoframe}"
SRC_DIR="${SRC_DIR:-}"
REPO_URL="${REPO_URL:-https://github.com/MrBroccoliJP/MementoFrame.git}"
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

OLD_SERVICES=(
  mementoframe.service
  mementoframe-ap.service
)

ALL_SERVICES=(
  mementoframe-kiosk.service
  mementoframe-post-reboot.service
  mementoframe-network.service
  mementoframe-display.service
  mementoframe-config.service
  mementoframe-ap.service
  mementoframe.service
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

  if [[ -f "$BOOT_CMDLINE" ]]; then
    cp -a "$BOOT_CMDLINE" "${BOOT_CMDLINE}.mementoframe.bak.$(date +%Y%m%d-%H%M%S)"
    ensure_cmdline_token "$BOOT_CMDLINE" "quiet"
    ensure_cmdline_token "$BOOT_CMDLINE" "splash"
    ensure_cmdline_token "$BOOT_CMDLINE" "console=tty3"
    ensure_cmdline_token "$BOOT_CMDLINE" "loglevel=0"
    ensure_cmdline_token "$BOOT_CMDLINE" "logo.nologo"
    ensure_cmdline_token "$BOOT_CMDLINE" "vt.global_cursor_default=0"
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
}

log "Creating/checking user: ${APP_USER}"
if ! id "${APP_USER}" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "MementoFrame" "${APP_USER}"
fi
usermod -aG video,input,gpio,netdev "${APP_USER}" || true
mkdir -p "${APP_HOME}"
chown "${APP_USER}:${APP_USER}" "${APP_HOME}"

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
  unclutter \
  xserver-xorg \
  xinit \
  openbox \
  x11-xserver-utils \
  libjpeg-dev \
  zlib1g-dev \
  python3-rpi.gpio

if ! command -v chromium-browser >/dev/null 2>&1 && ! command -v chromium >/dev/null 2>&1; then
  if ! apt install -y chromium-browser; then
    apt install -y chromium
  fi
fi

log "Enabling NetworkManager"
systemctl disable --now dhcpcd 2>/dev/null || true
systemctl mask dhcpcd 2>/dev/null || true
systemctl enable --now NetworkManager

configure_boot_and_x11

log "Preparing source"
rm -rf "${REPO_TMP}"
if [[ -n "${SRC_DIR}" ]]; then
  if [[ ! -d "${SRC_DIR}/mementoframe" ]]; then
    echo "ERROR: SRC_DIR must point to the repo root containing mementoframe/" >&2
    exit 1
  fi
  cp -a "${SRC_DIR}" "${REPO_TMP}"
elif [[ -d "$(pwd)/mementoframe" && -f "$(pwd)/mementoframe/updater.py" ]]; then
  cp -a "$(pwd)" "${REPO_TMP}"
else
  git clone "${REPO_URL}" "${REPO_TMP}"
fi

for required in updater.py version_info.py config_portal_service.py display_service.py network_manager_service.py requirements.txt; do
  if [[ ! -f "${REPO_TMP}/mementoframe/${required}" ]]; then
    echo "ERROR: source does not contain mementoframe/${required}" >&2
    echo "The split-service layout requires config_portal_service.py, display_service.py, and network_manager_service.py." >&2
    exit 1
  fi
done

log "Installing app to ${APP_DIR}"
for svc in "${ALL_SERVICES[@]}"; do
  stop_service_if_exists "$svc"
done

for svc in "${OLD_SERVICES[@]}"; do
  disable_service_if_exists "$svc"
done

if [[ -d "${APP_DIR}" ]]; then
  BACKUP="${APP_HOME}/mementoframe.preinstall.$(date +%Y%m%d-%H%M%S)"
  warn "Existing app directory found. Moving it to ${BACKUP}"
  mv "${APP_DIR}" "${BACKUP}"
fi
cp -a "${REPO_TMP}/mementoframe" "${APP_DIR}"
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

log "Running app bootstrap"
sudo -u "${APP_USER}" bash -lc "cd '${APP_DIR}' && python3 updater.py install"

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

xset -dpms || true
xset s off || true
xset s noblank || true

openbox-session &

if command -v chromium-browser >/dev/null 2>&1; then
  CHROME=chromium-browser
else
  CHROME=chromium
fi

exec "$CHROME" \
  --kiosk \
  --incognito \
  --disable-infobars \
  --no-first-run \
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

log "Cleaning old service files"
rm -f /etc/systemd/system/mementoframe.service /etc/systemd/system/mementoframe-ap.service

log "Enabling services"
systemctl daemon-reload
for svc in "${NEW_SERVICES[@]}"; do
  systemctl enable "$svc"
done
systemctl restart mementoframe-network.service
systemctl restart mementoframe-config.service
systemctl restart mementoframe-display.service
systemctl restart mementoframe-kiosk.service || warn "Kiosk service did not start. This can happen on headless/SSH-only setups; check journalctl."

log "Install complete"
echo "App root: ${APP_DIR}"
echo "Edit local secrets: sudo -u ${APP_USER} nano ${APP_DIR}/.env"
echo "Admin dashboard: http://<pi-ip>:5000"
echo "Logs: journalctl -u mementoframe-config.service -f"
