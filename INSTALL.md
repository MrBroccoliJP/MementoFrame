# MementoFrame — Installation Guide

Official setup guide for Raspberry Pi OS Lite.

The recommended setup is the one-command installer. It creates/uses the `mementoframe` Linux user, installs the runtime app to `/home/mementoframe/mementoframe`, creates separate systemd services for each runtime process, configures kiosk display settings, and prepares the updater.

---

## Tested Hardware

| Component | Version |
|---|---|
| Raspberry Pi | 3B+ |
| OS | Raspberry Pi OS Lite 13 (trixie) 32-bit |
| Python | 3.11 |
| Display | GeekPi 7" HDMI, 1024×600 |

---

## What MementoFrame Uses

- NetworkManager and `nmcli` for Wi-Fi/client/AP mode
- Flask config portal on port `5000`
- Flask display service on port `5001`
- Chromium kiosk mode for the physical display
- GPIO pins for display power and brightness pulses
- `updater.py` for first-time app bootstrap and future GitHub Release updates
- Separate systemd services for config, display, network, kiosk, and post-reboot update validation

---

## Recommended One-Command Install

From a fresh Raspberry Pi OS install:

```bash
cd ~
git clone https://github.com/MrBroccoliJP/MementoFrame.git
cd MementoFrame
sudo bash install.sh
```

The installer must be run with `sudo` because it installs apt packages, creates users, writes systemd services, edits boot display config, and configures limited sudo permissions for Wi-Fi/update/reboot actions.

You can also install from a local checkout by setting `SRC_DIR`:

```bash
sudo SRC_DIR="$(pwd)" bash install.sh
```

`SRC_DIR` must point to the repository root, the directory containing the inner `mementoframe/` folder.

The runtime app is installed to:

```text
/home/mementoframe/mementoframe
```

The full Git checkout is only used as install source. The Pi runtime does not run from the repository root.

---

## Runtime Files

The installed runtime app folder contains the split-service layout:

| File | Purpose |
|---|---|
| `config_portal_service.py` | Admin/configuration portal on port `5000`. |
| `display_service.py` | Local display/frontend API on port `5001`. |
| `network_manager_service.py` | NetworkManager Wi-Fi/AP fallback watchdog. |
| `updater.py` | Installer/update/post-reboot helper. |
| `version_info.py` | Composite release/component version metadata. |
| `requirements.txt` | Python dependencies. |
| `config.json` | User configuration. |
| `.env` | Local secrets and optional GitHub token. Created by `updater.py install` if missing. |
| `resources/userdata/` | Persistent photos, thumbnails, cache, and generated user files. |
| `runtime/` | Runtime state such as update state and temporary PIN data. |

---

## What the Installer Does

`install.sh` performs these steps:

1. Requires root/sudo.
2. Creates the `mementoframe` user if it does not already exist.
3. Adds the user to only the required hardware groups: `video`, `input`, `gpio`, and `netdev`.
4. Installs system dependencies.
5. Enables NetworkManager and disables/masks `dhcpcd` if present.
6. Configures display boot settings in `/boot/firmware/config.txt`.
7. Configures quiet boot arguments in `/boot/firmware/cmdline.txt` while preserving the single-line format.
8. Configures X permissions in `/etc/X11/Xwrapper.config`.
9. Copies the inner app folder to `/home/mementoframe/mementoframe`.
10. Runs `python3 updater.py install` as the `mementoframe` user.
11. Creates `/usr/local/bin/mementoframe-kiosk.sh`.
12. Creates the split systemd services.
13. Creates `/etc/sudoers.d/mementoframe-updater` with only the limited permissions required by Wi-Fi setup, updater restarts, and reboot.
14. Enables and starts the services.

---

## Directories

| Path | Purpose |
|---|---|
| `/home/mementoframe/mementoframe` | Runtime app root. |
| `/tmp/mementoframe-install-src` | Default temporary full repo checkout used during install. |
| `/home/mementoframe/mementoframe/resources/userdata` | Persistent user data. Preserved by updates. |
| `/home/mementoframe/mementoframe/runtime` | Runtime update/config state. Preserved by updates. |
| `/home/mementoframe/mementoframe/.env` | Local secrets and optional GitHub token. Preserved by updates. |
| `/home/mementoframe/mementoframe_backups` | Update backups. |

---

## Boot Display Configuration

The installer does not replace `/boot/firmware/config.txt`. It creates a timestamped backup first, then preserves the existing Raspberry Pi settings and only ensures the MementoFrame display keys.

Backup examples:

```text
/boot/firmware/config.txt.mementoframe.bak.YYYYMMDD-HHMMSS
/boot/firmware/cmdline.txt.mementoframe.bak.YYYYMMDD-HHMMSS
/etc/X11/Xwrapper.config.mementoframe.bak.YYYYMMDD-HHMMSS
```

The installer ensures this global setting exists before section blocks such as `[cm4]`, `[cm5]`, or `[all]`:

```ini
dtoverlay=vc4-fkms-v3d
```

Inside the `[all]` section, it ensures these values for the tested 1024×600 HDMI display and GPIO screen-enable pin:

```ini
[all]
enable_uart=1
disable_splash=1
avoid_warnings=1
gpu_mem=185
gpio=26=op,dh
hdmi_force_hotplug=1
hdmi_group=2
hdmi_mode=87
hdmi_cvt=1024 600 60 6 0 0 0
config_hdmi_boost=7
```

It also ensures `/boot/firmware/cmdline.txt` remains a single line and includes these tokens only if missing:

```text
quiet splash console=tty3 loglevel=0 logo.nologo vt.global_cursor_default=0
```

And it writes `/etc/X11/Xwrapper.config`:

```ini
allowed_users=anybody
needs_root_rights=yes
```

---

## Configure `.env`

The installer runs `updater.py install`, which creates `.env` if missing.

Edit it after install:

```bash
sudo -u mementoframe nano /home/mementoframe/mementoframe/.env
```

Example:

```env
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REDIRECT_URI=https://httpbin.org/anything
GITHUB_TOKEN=
MEMENTOFRAME_UPDATE_REPO=MrBroccoliJP/MementoFrame
```

Spotify remains disconnected until credentials are configured. Private GitHub repository updates require `GITHUB_TOKEN`.

---

## Services

### `mementoframe-config.service`

Runs the admin/configuration portal.

```text
/etc/systemd/system/mementoframe-config.service
```

Important values:

```ini
User=mementoframe
WorkingDirectory=/home/mementoframe/mementoframe
ExecStart=/home/mementoframe/mementoframe/venv/bin/python3 /home/mementoframe/mementoframe/config_portal_service.py
```

Port:

```text
5000
```

### `mementoframe-display.service`

Runs the local display/frontend API.

```text
/etc/systemd/system/mementoframe-display.service
```

Important values:

```ini
User=mementoframe
WorkingDirectory=/home/mementoframe/mementoframe
ExecStart=/home/mementoframe/mementoframe/venv/bin/python3 /home/mementoframe/mementoframe/display_service.py
```

Port:

```text
5001
```

### `mementoframe-network.service`

Runs the NetworkManager Wi-Fi/AP fallback watchdog.

```text
/etc/systemd/system/mementoframe-network.service
```

Important values:

```ini
User=root
WorkingDirectory=/home/mementoframe/mementoframe
ExecStart=/home/mementoframe/mementoframe/venv/bin/python3 /home/mementoframe/mementoframe/network_manager_service.py
```

This service runs as root so the existing NetworkManager commands can manage AP/client mode reliably.

### `mementoframe-kiosk.service`

Runs Chromium in kiosk mode.

```text
/etc/systemd/system/mementoframe-kiosk.service
```

Important values:

```ini
User=mementoframe
Environment=DISPLAY=:0
ExecStart=/usr/bin/startx /usr/local/bin/mementoframe-kiosk.sh -- :0
After=mementoframe-display.service
Requires=mementoframe-display.service
```

### `mementoframe-post-reboot.service`

Runs the update lifecycle health check after boot.

```text
/etc/systemd/system/mementoframe-post-reboot.service
```

It polls:

```text
http://127.0.0.1:5000/health
http://127.0.0.1:5001/health
```

and clears `pending_restart` in `runtime/update_state.json` once both services respond.

---

## Service Commands

Restart everything:

```bash
sudo systemctl restart mementoframe-network.service
sudo systemctl restart mementoframe-config.service
sudo systemctl restart mementoframe-display.service
sudo systemctl restart mementoframe-kiosk.service
```

Check status:

```bash
systemctl status mementoframe-config.service
systemctl status mementoframe-display.service
systemctl status mementoframe-network.service
systemctl status mementoframe-kiosk.service
systemctl status mementoframe-post-reboot.service
```

Useful logs:

```bash
journalctl -u mementoframe-config.service -f
journalctl -u mementoframe-display.service -f
journalctl -u mementoframe-network.service -f
journalctl -u mementoframe-kiosk.service -f
```

---

## Update/Reboot/Wi-Fi Permissions

The installer creates:

```text
/etc/sudoers.d/mementoframe-updater
```

With limited permissions for the app user:

```sudoers
mementoframe ALL=(root) NOPASSWD: \
  /usr/bin/systemctl restart mementoframe-config.service, \
  /usr/bin/systemctl restart mementoframe-display.service, \
  /usr/bin/systemctl restart mementoframe-network.service, \
  /usr/bin/systemctl restart mementoframe-kiosk.service, \
  /usr/bin/systemctl stop hostapd, \
  /usr/bin/systemctl stop dnsmasq, \
  /usr/bin/nmcli, \
  /usr/sbin/reboot, \
  /sbin/reboot, \
  /usr/bin/reboot
```

The `mementoframe` user is not granted unrestricted root access.

---

## Verify Install

```bash
curl http://127.0.0.1:5000/health
curl http://127.0.0.1:5001/health
curl http://127.0.0.1:5000/versions
curl http://127.0.0.1:5001/versions
```

Then check services:

```bash
systemctl status mementoframe-config.service
systemctl status mementoframe-display.service
systemctl status mementoframe-network.service
systemctl status mementoframe-kiosk.service
```

---

## Updating

Updates are handled by `updater.py` and GitHub Releases.

GitHub release tags should use the composite version from `version_info.py`:

```text
v<release>.<frontend>.<config>.<display>.<network>.<updater>
```

Example:

```text
v1.25.22.21.21.13
```

Manual terminal update:

```bash
cd /home/mementoframe/mementoframe
python3 updater.py check
python3 updater.py update
```

Test update without reboot:

```bash
python3 updater.py update --no-reboot
```

If auto-updates are enabled, the updater runs near the end of the configured night/off period, or around `05:00` if no display schedule is configured.

---

## Manual Install Fallback

Use this only if the one-command installer fails.

```bash
sudo apt update
sudo apt install -y \
  python3 python3-pip python3-venv git \
  network-manager wireless-tools iw iproute2 \
  chromium-browser unclutter xserver-xorg xinit openbox x11-xserver-utils \
  libjpeg-dev zlib1g-dev python3-rpi.gpio

sudo adduser --disabled-password --gecos "MementoFrame" mementoframe || true
sudo usermod -aG video,input,gpio,netdev mementoframe

cd /home/mementoframe
git clone https://github.com/MrBroccoliJP/MementoFrame.git MementoFrame-src
rm -rf /home/mementoframe/mementoframe
cp -a /home/mementoframe/MementoFrame-src/mementoframe /home/mementoframe/mementoframe
sudo chown -R mementoframe:mementoframe /home/mementoframe/mementoframe

cd /home/mementoframe/mementoframe
sudo -u mementoframe python3 updater.py install
```

Then create the services and sudoers as described above.

---

## Development/Release Notes on Windows

If editing on Windows, Git may not preserve Unix executable bits automatically. Mark shell scripts executable in Git before releasing:

```bash
git update-index --chmod=+x mementoframe/install.sh
```
---

## License

Creative Commons Attribution-NonCommercial 4.0 International

[http://creativecommons.org/licenses/by-nc/4.0/](http://creativecommons.org/licenses/by-nc/4.0/)
