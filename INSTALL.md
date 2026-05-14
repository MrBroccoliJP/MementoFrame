# MementoFrame — Installation Guide

Official setup guide for Raspberry Pi OS Lite.

The recommended setup is the one-command installer. It creates/uses the `mementoframe` Linux user, installs the runtime app to `/home/mementoframe/mementoframe`, creates separate systemd services for each runtime process, configures kiosk display settings, and prepares the updater.

---

## Tested Hardware

| Component | Version |
|---|---|
| Raspberry Pi | 3B+ |
| OS | Raspberry Pi OS Lite 13 (trixie) 32-bit |
| Python | System Python from Raspberry Pi OS, tested with Python 3.13 on Trixie |
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
- WebP image conversion/thumbnails through Pillow with system WebP libraries

---

## Recommended One-Command Install

From a fresh Raspberry Pi OS install, download the installer from the latest GitHub Release and run it:

```bash
cd ~
curl -fL https://github.com/MrBroccoliJP/MementoFrame/releases/latest/download/install.sh -o install.sh
sudo bash install.sh
```

The installer must be run with `sudo` because it installs apt packages, creates users, writes systemd services, edits boot display config, and configures limited sudo permissions for Wi-Fi/update/reboot actions.

By default, `install.sh` downloads and installs the latest stable GitHub Release. It does **not** install from the moving `main` branch. At the end of a normal install it reboots automatically so boot, HDMI, X11, and service settings take effect. For development/testing, skip the final reboot with `SKIP_REBOOT=1`.

Install a specific release tag:

```bash
sudo INSTALL_TAG=v1.25.22.21.21.13 bash install.sh
```

Install the newest non-draft pre-release/release instead of only the latest stable release:

```bash
sudo INSTALL_CHANNEL=pre-release bash install.sh
```

Run the installer without rebooting at the end, useful while testing installer changes:

```bash
sudo SKIP_REBOOT=1 bash install.sh
```

Install from a fork or different repository:

```bash
sudo INSTALL_REPO=owner/repository bash install.sh
```

Developer-only local checkout override:

```bash
sudo SRC_DIR="$(pwd)" bash install.sh
```

`SRC_DIR` must point to the repository root, the directory containing the inner `mementoframe/` folder.

The runtime app is installed to:

```text
/home/mementoframe/mementoframe
```

The Pi runtime does not run from the installer location or from a full Git checkout.

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
4. Stops any existing MementoFrame split services early, before touching Wi-Fi/NetworkManager, so a previous install cannot interfere.
5. Installs system dependencies, including Chromium, NetworkManager, X/Openbox, GPIO support, and WebP image support.
6. Enables NetworkManager, disables/masks `dhcpcd` if present, unblocks Wi-Fi with `rfkill`, and enables the Wi-Fi radio with `nmcli`.
7. Configures display boot settings in `/boot/firmware/config.txt`.
8. Configures quiet boot arguments in `/boot/firmware/cmdline.txt` while preserving the single-line format.
9. Configures X permissions in `/etc/X11/Xwrapper.config` and masks `getty@tty1.service` to prevent login text flashing before Chromium starts.
10. Downloads the selected GitHub Release, then copies the inner app folder to `/home/mementoframe/mementoframe`.
11. Runs `python3 updater.py install` as the `mementoframe` user.
12. Forces update settings in `config.json` so auto-update is enabled and the repository/channel match the installer selection.
13. Creates `/usr/local/bin/mementoframe-kiosk.sh` with DPMS/screen blanking disabled and Raspberry Pi Chromium flags.
14. Creates the split systemd services.
15. Creates `/etc/sudoers.d/mementoframe-updater` with only the limited permissions required by Wi-Fi setup, updater restarts, and reboot.
16. Enables and starts the services.
17. Reboots automatically unless `SKIP_REBOOT=1` is set.

---

## Directories

| Path | Purpose |
|---|---|
| `/home/mementoframe/mementoframe` | Runtime app root. |
| `/tmp/mementoframe-install-src` | Temporary extracted GitHub Release source used during install. |
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

It also ensures `/boot/firmware/cmdline.txt` remains a single line. It removes earlier/undesired tokens such as `console=tty1`, `fsck.mode=skip`, `systemd.show_status=...`, `rd.systemd.show_status=...`, and `plymouth.ignore-serial-consoles`, then ensures these values:

```text
console=tty3 quiet splash loglevel=1 logo.nologo vt.global_cursor_default=0 consoleblank=0
```

`fsck.repair=yes` is preserved when already present. The installer does not add `fsck.mode=skip`, because skipping filesystem checks is less safe for Raspberry Pi devices that may lose power.

And it writes `/etc/X11/Xwrapper.config`:

```ini
allowed_users=anybody
needs_root_rights=yes
```

It also disables and masks the tty1 login prompt:

```bash
systemctl disable --now getty@tty1.service
systemctl mask getty@tty1.service
```

---

## Configure `.env` and Spotify

The installer runs `updater.py install`, which creates `.env` if missing.

You can edit it manually:

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

Spotify can also be configured from the web configuration portal. Create an app in the Spotify Developer Dashboard, add this redirect URI to that Spotify app, then paste the Client ID and Client Secret into the Spotify section of the portal:

```text
https://httpbin.org/anything
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

The kiosk launcher disables X screen saver/DPMS every time X starts. This prevents HDMI from going to “No Signal” after the default 10-minute X timeout. It also hides the cursor with `unclutter`, sets the X root background black, stores Chromium cache in `/dev/shm`, and uses GPU/compositing flags for smoother image fades.

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

Check Wi-Fi radio state:

```bash
nmcli radio wifi
nmcli device status
```

After the kiosk starts, verify X screen blanking is disabled:

```bash
DISPLAY=:0 xset q
```

Expected values include `timeout: 0` under Screen Saver and `DPMS is Disabled`.

---

## Updating

Updates are handled by `updater.py` and GitHub Releases.

Each GitHub Release should include `install.sh` as a release asset so first-time users can install the latest tested release without cloning the repository.

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
  network-manager wireless-tools iw iproute2 rfkill curl ca-certificates \
  chromium unclutter xserver-xorg xinit openbox x11-xserver-utils \
  libjpeg-dev zlib1g-dev libwebp-dev webp python3-rpi.gpio

sudo adduser --disabled-password --gecos "MementoFrame" mementoframe || true
sudo usermod -aG video,input,gpio,netdev mementoframe

cd /tmp
curl -fL https://github.com/MrBroccoliJP/MementoFrame/releases/latest/download/install.sh -o install.sh
# If the one-command installer itself failed after dependencies, rerun it:
sudo bash install.sh

# Or manually use a full release/source checkout that contains the inner mementoframe folder:
# cp -a /path/to/release-or-checkout/mementoframe /home/mementoframe/mementoframe
sudo chown -R mementoframe:mementoframe /home/mementoframe/mementoframe

cd /home/mementoframe/mementoframe
sudo -u mementoframe python3 updater.py install
```

Then create the services and sudoers as described above.

---

## Development/Release Notes on Windows

If editing on Windows, Git may not preserve Unix executable bits automatically. Mark shell scripts executable in Git before releasing:

```bash
git update-index --chmod=+x install.sh
# or, if the installer lives inside the inner app folder in your repo:
# git update-index --chmod=+x mementoframe/install.sh
```
---

## License

Creative Commons Attribution-NonCommercial 4.0 International

[http://creativecommons.org/licenses/by-nc/4.0/](http://creativecommons.org/licenses/by-nc/4.0/)
