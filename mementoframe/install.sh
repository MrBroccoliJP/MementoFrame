#!/usr/bin/env bash
set -euo pipefail

# MementoFrame one-command installer for Raspberry Pi OS Bookworm.
# Run with: sudo bash install.sh

APP_USER="${APP_USER:-mementoframe}"
APP_HOME="${APP_HOME:-/home/${APP_USER}}"
APP_DIR="${APP_DIR:-${APP_HOME}/mementoframe}"
SRC_DIR="${SRC_DIR:-}"
REPO_URL="${REPO_URL:-https://github.com/MrBroccoliJP/MementoFrame.git}"
REPO_TMP="${REPO_TMP:-/tmp/mementoframe-install-src}"
KIOSK_SCRIPT="/usr/local/bin/mementoframe-kiosk.sh"
APP_SERVICE="/etc/systemd/system/mementoframe.service"
KIOSK_SERVICE="/etc/systemd/system/mementoframe-kiosk.service"
SUDOERS_FILE="/etc/sudoers.d/mementoframe-updater"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: run this installer with sudo: sudo bash install.sh" >&2
  exit 1
fi

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\n\033[1;33mWARN: %s\033[0m\n' "$*"; }

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

configure_boot_console() {
  log "Configuring quiet boot console"

  local cmdline="/boot/firmware/cmdline.txt"
  if [[ ! -f "$cmdline" ]]; then
    warn "$cmdline not found; skipping cmdline.txt changes"
  else
    cp -a "$cmdline" "${cmdline}.mementoframe.bak.$(date +%Y%m%d-%H%M%S)"

    # cmdline.txt must remain one single line.
    # Keep the existing root=, PARTUUID, serial console, rootwait, regdom, etc.
    # Remove tokens from earlier experiments that caused visible boot/login issues.
    remove_cmdline_token "$cmdline" "console=tty3"
    remove_cmdline_token "$cmdline" "fsck.mode=skip"
    remove_cmdline_key "$cmdline" "systemd.show_status"
    remove_cmdline_key "$cmdline" "rd.systemd.show_status"
    remove_cmdline_token "$cmdline" "plymouth.ignore-serial-consoles"

    # Ensure the known-good MementoFrame boot quieting tokens.
    ensure_cmdline_token "$cmdline" "quiet"
    ensure_cmdline_token "$cmdline" "splash"
    set_cmdline_key "$cmdline" "loglevel" "1"
    ensure_cmdline_token "$cmdline" "logo.nologo"
    set_cmdline_key "$cmdline" "vt.global_cursor_default" "0"
    set_cmdline_key "$cmdline" "consoleblank" "0"
  fi

  # Prevent tty1 login text from flashing before Chromium takes over.
  systemctl disable --now getty@tty1.service 2>/dev/null || true
  systemctl mask getty@tty1.service 2>/dev/null || true
}



log "Creating/checking user: ${APP_USER}"
if ! id "${APP_USER}" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "MementoFrame" "${APP_USER}"
fi
usermod -aG sudo,video,input,gpio,netdev "${APP_USER}" || true
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

if ! command -v chromium >/dev/null 2>&1; then
  apt install -y chromium
fi

log "Enabling NetworkManager"
systemctl disable --now dhcpcd 2>/dev/null || true
systemctl mask dhcpcd 2>/dev/null || true
systemctl enable --now NetworkManager

configure_boot_console

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

if [[ ! -f "${REPO_TMP}/mementoframe/updater.py" ]]; then
  echo "ERROR: source does not contain mementoframe/updater.py" >&2
  exit 1
fi

log "Installing app to ${APP_DIR}"
if [[ -d "${APP_DIR}" ]]; then
  BACKUP="${APP_HOME}/mementoframe.preinstall.$(date +%Y%m%d-%H%M%S)"
  warn "Existing app directory found. Moving it to ${BACKUP}"
  systemctl stop mementoframe.service 2>/dev/null || true
  systemctl stop mementoframe-kiosk.service 2>/dev/null || true
  mv "${APP_DIR}" "${BACKUP}"
fi
cp -a "${REPO_TMP}/mementoframe" "${APP_DIR}"
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

log "Running app bootstrap"
sudo -u "${APP_USER}" bash -lc "cd '${APP_DIR}' && python3 updater.py install"

log "Writing sudoers for updater/reboot"
cat > "${SUDOERS_FILE}" <<EOF_SUDOERS
${APP_USER} ALL=(root) NOPASSWD: \\
  /usr/bin/systemctl restart mementoframe.service, \\
  /usr/bin/systemctl restart mementoframe-kiosk.service, \\
  /usr/sbin/reboot, \\
  /sbin/reboot, \\
  /usr/bin/reboot
EOF_SUDOERS
chmod 0440 "${SUDOERS_FILE}"
visudo -cf "${SUDOERS_FILE}"

log "Writing systemd service: mementoframe.service"
cat > "${APP_SERVICE}" <<EOF_SERVICE
[Unit]
Description=MementoFrame Application Services
After=network-online.target NetworkManager.service
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
ExecStart=/bin/bash ${APP_DIR}/start_apps.sh
Restart=always
RestartSec=2
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF_SERVICE

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
After=mementoframe.service
Requires=mementoframe.service

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
systemctl enable mementoframe.service
systemctl enable mementoframe-kiosk.service
systemctl restart mementoframe.service
systemctl restart mementoframe-kiosk.service || warn "Kiosk service did not start. This can happen on headless/SSH-only setups; check journalctl."

log "Install complete"
echo "App root: ${APP_DIR}"
echo "Edit local secrets: sudo -u ${APP_USER} nano ${APP_DIR}/.env"
echo "Admin dashboard: http://<pi-ip>:5000"
echo "Logs: journalctl -u mementoframe.service -f"
