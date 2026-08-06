# MementoFrame — Installation Guide

Official setup guide for Raspberry Pi OS Lite.

The recommended setup is the automated `install.sh` installer. A manual path is also documented for troubleshooting and advanced installations. After either method, use the web configuration dashboard to add the WeatherAPI and optional Spotify credentials, connect Spotify users, configure the display, and upload photos.

## Installation overview

1. Choose the [automatic installation](#automatic-installation-recommended) or [manual installation](#manual-installation-advanced).
2. Reboot the Raspberry Pi and [verify the installation](#verify-install).
3. Open the [configuration dashboard](#post-install-configuration).
4. Configure WeatherAPI first, then Spotify if wanted, followed by the remaining display and frame settings.

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
- I²C and the Raspberry Pi RTC overlay for a DS3231 hardware clock, with `hwclock` from `util-linux-extra`
- `updater.py` for first-time app bootstrap and future GitHub Release updates
- Separate systemd services for config, display, network, kiosk, and post-reboot update validation
- WebP image conversion/thumbnails through Pillow with system WebP libraries

---

## Automatic Installation (Recommended)

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

## Manual Installation (Advanced)

Use this path when the automatic installer cannot complete or when you need to perform and diagnose each stage yourself. The automatic and manual methods are alternatives; do not run both for a normal installation.

Install the operating-system dependencies and create the dedicated runtime user:

```bash
sudo apt update
sudo apt install -y \
  python3 python3-pip python3-venv git \
  network-manager wireless-tools iw iproute2 rfkill curl ca-certificates \
  chromium unclutter xserver-xorg xinit openbox x11-xserver-utils \
  libjpeg-dev zlib1g-dev libwebp-dev webp util-linux-extra python3-rpi.gpio

sudo adduser --disabled-password --gecos "MementoFrame" mementoframe || true
sudo usermod -aG video,input,gpio,netdev mementoframe
```

Copy the repository's inner `mementoframe/` directory to the runtime location, then initialize it:

```bash
sudo mkdir -p /home/mementoframe/mementoframe
sudo cp -a /path/to/release-or-checkout/mementoframe/. /home/mementoframe/mementoframe/
sudo chown -R mementoframe:mementoframe /home/mementoframe/mementoframe

cd /home/mementoframe/mementoframe
sudo -u mementoframe python3 updater.py install
```

Replace `/path/to/release-or-checkout` with the extracted release or checkout root. The source must contain the inner `mementoframe/` application folder.

Complete the same system integration performed by `install.sh`:

1. Apply the settings in [Boot Display Configuration](#boot-display-configuration), preserving unrelated Raspberry Pi settings.
2. Configure NetworkManager and disable conflicting `dhcpcd` management if it is present.
3. Create the five units listed under [Services](#services).
4. Add the limited permissions described in [Update/Reboot/Wi-Fi Permissions](#updaterebootwi-fi-permissions).
5. Enable the services and reboot.

For the RTC, ensure these directives are present under `[all]` in `/boot/firmware/config.txt`:

```ini
[all]
dtparam=i2c_arm=on
dtoverlay=i2c-rtc,ds3231
```

After rebooting, confirm that Raspberry Pi OS created the RTC device:

```bash
ls -l /dev/rtc*
sudo hwclock --show
```

If the automatic installer failed only because packages were missing, install the dependencies above and rerun `sudo bash install.sh` instead of continuing with the fully manual path.

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
5. Installs system dependencies, including Chromium, NetworkManager, X/Openbox, GPIO and WebP support, and `util-linux-extra` for the `hwclock` RTC utility.
6. Enables NetworkManager, disables/masks `dhcpcd` if present, unblocks Wi-Fi with `rfkill`, and enables the Wi-Fi radio with `nmcli`.
7. Configures display settings and enables the DS3231 RTC in `/boot/firmware/config.txt`.
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

The installer does not replace `/boot/firmware/config.txt`. It creates a timestamped backup first, then preserves the existing Raspberry Pi settings and only ensures the MementoFrame display and DS3231 RTC keys.

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

Inside the `[all]` section, it enables the I²C controller, selects the DS3231 RTC overlay, and ensures the values for the tested 1024×600 HDMI display and GPIO screen-enable pin:

```ini
[all]
dtparam=i2c_arm=on
dtoverlay=i2c-rtc,ds3231
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

The installer updates an existing `i2c_arm` or `i2c-rtc` directive when necessary and preserves unrelated `dtparam` and `dtoverlay` entries. It also installs `util-linux-extra`, which provides the `hwclock` command on Raspberry Pi OS Bookworm and Trixie. After the reboot, the overlay makes the DS3231 available to Raspberry Pi OS through the kernel RTC driver, normally as `/dev/rtc0`. `util-linux-extra` supplies the userspace RTC utility; no separate RTC kernel module package is required.

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

## Post-Install Configuration

After the Pi reboots, open the MementoFrame configuration dashboard:

- While connected to the MementoFrame setup hotspot: `http://192.168.4.1:5000`
- After the frame joins your network: `http://mementoframe.local:5000` or `http://<frame-ip>:5000` [only if you added the wifi credentials on the official Raspberry Pi Imager configuration]

Configure the integrations in this order: **WeatherAPI key**, **Spotify app credentials**, and then the **Spotify user connection**. Spotify is optional; all other dashboard settings can be configured independently.

This guide uses two kinds of configuration pages:

| Page | Where it runs | Purpose |
|---|---|---|
| **External service dashboard** | A public website such as WeatherAPI.com or Spotify for Developers | Create accounts, API keys, app credentials, redirect URIs, and permitted Spotify users. |
| **MementoFrame dashboard** | On the Raspberry Pi at port `5000` | Give the frame the credentials created by the external services and configure its local behavior. |

The external dashboards do not configure the frame directly. You first create or configure a value on the external website, then copy that value into the MementoFrame dashboard.

### 1. WeatherAPI

The weather setup begins on the external WeatherAPI website and finishes on the frame:

```text
WeatherAPI.com account → API key and response fields → MementoFrame dashboard
```

#### External: WeatherAPI Website

1. Create an account at [WeatherAPI.com](https://www.weatherapi.com/).
2. Open the WeatherAPI dashboard and copy your API key. Keep this browser tab available; the key will be pasted into MementoFrame later.
3. Still in the WeatherAPI dashboard, open **API > API Response Fields** and select the fields listed below. Leaving unused fields disabled reduces the response size while preserving everything MementoFrame displays.

![WeatherAPI dashboard API menu](docs/Instructions/WeatherApiDashboardExample.png)

Select these response fields:

| Group | Fields |
|---|---|
| Current Weather | `last_updated`, `temp_c`, `is_day`, `text`, `icon`, `code`, `wind_kph`, `precip_mm`, `humidity`, `feelslike_c`, `uv`, `heatindex_c`, `dewpoint_c` |
| Forecast Day | `date` |
| Forecast Day > Day | `maxtemp_c`, `mintemp_c`, `avgtemp_c`, `totalprecip_mm`, `avghumidity`, `text`, `icon`, `code`, `uv`, `avgwetbulb_c`, `avgwetbulb_f`, `maxwetbulb_c`, `maxwetbulb_f` |
| Forecast Day > Astro | `sunrise`, `sunset`, `moon_phase`, `is_sun_up` |
| Forecast Day > Hour | `time`, `temp_c`, `is_day`, `text`, `icon`, `code`, `wind_kph`, `precip_mm`, `humidity`, `feelslike_c`, `heatindex_c`, `dewpoint_c`, `chance_of_rain`, `uv`, `wetbulb_c`, `wetbulb_f` |

#### Internal: MementoFrame Dashboard

Return to the local MementoFrame dashboard at port `5000`. Under **Weather Configuration**:

1. Paste the API key copied from WeatherAPI.com into **WeatherAPI.com Key**.
2. Enter the weather location as `City,Country`, for example `Aveiro,Portugal`.
3. Select **Save Weather Settings**.

The API key comes from WeatherAPI.com, but the location is configured on MementoFrame itself.

![MementoFrame weather configuration](docs/Instructions/MementoFrameConfiguration-WeatherConfiguration.png)

### 2. Spotify App Credentials (Optional)

Spotify playback data requires your own Spotify developer app. This setup also begins on an external website and finishes on the frame:

```text
Spotify Developer Dashboard → Client ID, secret, redirect URI, and users → MementoFrame dashboard
```

#### External: Spotify Developer Dashboard

Create an app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard), then open its settings and configure the values shown below.

| Spotify app setting | Value |
|---|---|
| App name | `MementoFrame` (or another name of your choice) |
| App description | `MementoFrame` |
| Redirect URI | `https://httpbin.org/anything` |
| Additional redirect URI shown in the example | `http://127.0.0.1:8080/callback` |
| APIs used | Web API and Web Playback SDK |

The HTTPBin redirect URI is required for the dashboard connection flow. Copy it exactly, including `https://` and `/anything`.

![Spotify developer dashboard](docs/Instructions/SpotifyDevDashboard.png)

![Spotify app settings](docs/Instructions/SpotifyDevDashboardCreateApp.png)

> **Spotify development-mode requirement (2026):** every Spotify account that will connect to MementoFrame must first be explicitly added to the developer app's user allowlist. In February 2026 Spotify changed Development Mode to require a Premium account for the app owner and limit each app to five authorized users. Previously, development apps allowed broader user access. See Spotify's [Development Mode documentation](https://developer.spotify.com/documentation/web-api/concepts/quota-modes) and [February 2026 announcement](https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security).

While still on the external Spotify dashboard, open the app's **User Management** tab. Add each intended user with the full name and email address associated with that user's Spotify account. An unregistered user may appear to sign in, but Spotify will reject that user's API requests.

![Spotify user management](docs/Instructions/SpotifyDevDashboardUserManagement.png)

Before leaving Spotify's dashboard, copy the app's **Client ID** and reveal and copy its **Client Secret**. Treat the secret like a password.

#### Internal: MementoFrame Dashboard

Return to the local MementoFrame dashboard at port `5000`. Under **Spotify App Settings**:

1. Paste the **Client ID** copied from Spotify.
2. Paste the **Client Secret** copied from Spotify.
3. Enter `https://httpbin.org/anything` as the **Redirect URI**.
4. Select **Save Spotify App Settings**.

The status will say that the credentials are saved but the account is not connected. This is expected until the user authorization in the next section is completed.

![Spotify credentials saved but not connected](docs/Instructions/MementoFrameConfiguration-SpotifyCredentialsSavedNotConfigured.png)

### 3. Connect a Spotify User (Optional)

This stage moves between the internal dashboard, Spotify, HTTPBin, and back to the internal dashboard:

```text
MementoFrame dashboard → Spotify authorization → HTTPBin redirect → MementoFrame dashboard
```

After saving the app credentials and allowlisting the user:

1. **MementoFrame dashboard:** select **Connect to Spotify**.
2. **External Spotify page:** sign in with an allowlisted Spotify account and approve access.
3. **External HTTPBin page:** after Spotify redirects the browser, copy the **entire URL from the browser address bar**, including the `?code=...` query string. Nothing needs to be entered on the HTTPBin page itself.
4. **Return to the MementoFrame dashboard:** switch back to its existing browser tab, use the browser's **Back** button, or open the dashboard again at `http://mementoframe.local:5000` or `http://192.168.4.1:5000` while connected to the setup hotspot. Do not paste the URL into HTTPBin or Spotify.
5. If you returned with the browser's **Back** button, refresh the MementoFrame dashboard before continuing. This ensures the page is ready to receive the authorization response.
6. **MementoFrame dashboard:** paste the copied HTTPBin URL into **Paste full redirect URL here**, then select **Submit Spotify Redirect URL**. The internal dashboard should show **Connected as _user_**.

The authorization code is temporary and can only be used once, so submit the copied URL promptly. If it expires or fails, start again with **Connect to Spotify**.

![HTTPBin redirect URL example](docs/Instructions/MementoFrameConfiguration-HTTPBinConfigurationExample.png)

![Spotify connected](docs/Instructions/MementoFrameConfiguration-SpotifyConfigured.png)

### 4. Remaining Internal Dashboard Settings

The following settings exist only in the MementoFrame dashboard; they do not require another external service dashboard. Once the integrations are working, configure them to suit the installation.

#### Wi-Fi and Frame Controls

Choose a network, enter its password, and select **Connect**. The controls at the top of the page can reload the display, restart the frame, or turn the screen on.

![Wi-Fi and frame controls](docs/Instructions/MementoFrameConfiguration-Wi-Fi.png)

#### Clocks

Set the primary clock's timezone and label. A second clock can be enabled with a separate timezone and label.

![Clock configuration](docs/Instructions/MementoFrameConfiguration-Clock.png)

#### Display and Power Schedule

Set the display brightness and optionally enable an automatic off/on schedule. Save the schedule after changing its times.

![Display settings](docs/Instructions/MementoFrameConfiguration-DisplaySettings.png)

#### Photos

Upload the photos shown by the frame, monitor upload progress, and select existing photos for deletion.

![Photo configuration](docs/Instructions/MementoFrameConfiguration-PhotoConfiguration.png)

#### Updates

Choose the update repository and stable or pre-release channel, enable or disable automatic updates, check for a newer release, and install it from the dashboard.

When **Automatically install updates** is enabled, MementoFrame checks for updates hourly but only installs an available update during a one-hour installation window:

- If the automatic display power schedule is enabled, the window begins at the configured **screen-on time**. For example, an on time of `07:00` permits installation between `07:00` and `07:59`.
- If the automatic display power schedule is disabled, the default installation window is `07:00`–`07:59` in the Raspberry Pi's local time.

After successfully installing an automatic update, MementoFrame requests a reboot so the new version can start. The dashboard's **Install Update Now** action does not wait for this scheduled window.

![Update configuration](docs/Instructions/MementoFrameConfiguration-UpdateConfiguration.png)

### Advanced `.env` Configuration

The installer runs `updater.py install`, which creates `.env` if it is missing. The dashboard is the recommended place to save WeatherAPI and Spotify settings, but administrators can edit the environment file directly:

```bash
sudo -u mementoframe nano /home/mementoframe/mementoframe/.env
```

```env
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REDIRECT_URI=https://httpbin.org/anything
GITHUB_TOKEN=
MEMENTOFRAME_UPDATE_REPO=MrBroccoliJP/MementoFrame
```

Private GitHub repository updates require `GITHUB_TOKEN`. Never commit `.env` or share the Spotify client secret or WeatherAPI key.

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

The updater checks hourly. If auto-updates are enabled, an available update is installed during the one-hour window beginning at the configured display **on time**, which is the end of the overnight/off period. If no automatic display schedule is enabled, the installation window defaults to `07:00`–`07:59` in the Raspberry Pi's local time.

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
