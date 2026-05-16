#!/usr/bin/env bash
set -euo pipefail

# MementoFrame service repair helper.
# This script is intended to be run as root via sudo by updater.py.

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: repair_services.sh must run as root" >&2
  exit 1
fi

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
APP_USER="${APP_USER:-$(stat -c '%U' "${APP_DIR}" 2>/dev/null || echo mementoframe)}"
KIOSK_SCRIPT="/usr/local/bin/mementoframe-kiosk.sh"

CONFIG_SERVICE="/etc/systemd/system/mementoframe-config.service"
DISPLAY_SERVICE="/etc/systemd/system/mementoframe-display.service"
NETWORK_SERVICE="/etc/systemd/system/mementoframe-network.service"
UPDATER_SERVICE="/etc/systemd/system/mementoframe-updater.service"
UPDATER_TIMER="/etc/systemd/system/mementoframe-updater.timer"
KIOSK_SERVICE="/etc/systemd/system/mementoframe-kiosk.service"

if [[ ! -d "${APP_DIR}" ]]; then
  echo "ERROR: APP_DIR does not exist: ${APP_DIR}" >&2
  exit 1
fi

if [[ ! -x "${APP_DIR}/venv/bin/python3" ]]; then
  echo "ERROR: app virtualenv python not found: ${APP_DIR}/venv/bin/python3" >&2
  exit 1
fi

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


cat > "${UPDATER_SERVICE}" <<EOF_UPDATER_SERVICE
[Unit]
Description=MementoFrame automatic update check/install
After=network-online.target NetworkManager.service
Wants=network-online.target

[Service]
Type=oneshot
User=${APP_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python3 ${APP_DIR}/updater.py autoupdate
Environment=PYTHONUNBUFFERED=1
EOF_UPDATER_SERVICE

cat > "${UPDATER_TIMER}" <<EOF_UPDATER_TIMER
[Unit]
Description=Run MementoFrame updater hourly

[Timer]
OnBootSec=2min
OnUnitActiveSec=1h
Persistent=true
Unit=mementoframe-updater.service

[Install]
WantedBy=timers.target
EOF_UPDATER_TIMER

if [[ -x "${KIOSK_SCRIPT}" ]]; then
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
else
  echo "WARN: kiosk launcher not found/executable: ${KIOSK_SCRIPT}; keeping existing kiosk service if any" >&2
fi

systemctl daemon-reload
systemctl disable --now mementoframe-post-reboot.service >/dev/null 2>&1 || true
systemctl enable mementoframe-config.service >/dev/null
systemctl enable mementoframe-display.service >/dev/null
systemctl enable mementoframe-network.service >/dev/null
systemctl enable mementoframe-updater.timer >/dev/null
if [[ -f "${KIOSK_SERVICE}" ]]; then
  systemctl enable mementoframe-kiosk.service >/dev/null
fi
systemctl start mementoframe-updater.timer >/dev/null || true

echo "MementoFrame systemd services repaired for ${APP_DIR} (${APP_USER})"
