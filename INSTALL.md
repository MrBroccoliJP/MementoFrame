# MementoFrame — Install Guide

Step-by-step setup for **Raspberry Pi OS Lite (32-bit)** on a **Raspberry Pi 3B+**.

---

## Assumptions

| Item | Value |
|---|---|
| User account | `mementoframe` |
| Wi-Fi interface | `wlan0` |
| Admin dashboard | `http://<device-ip>:5000` |
| Display (kiosk) | `http://127.0.0.1:5001` |
| AP fallback SSID | `MementoFrame` |
| AP fallback IP | `192.168.4.1` |

---

## 1. System packages

```bash
sudo apt update && sudo apt upgrade -y

# GUI / kiosk stack
sudo apt install -y \
  xserver-xorg x11-xserver-utils xinit \
  openbox matchbox-window-manager \
  chromium \
  unclutter

# App + networking
sudo apt install -y \
  python3-pip python3-dev python3-venv git \
  i2c-tools python3-smbus \
  network-manager hostapd dnsmasq

# Pillow build dependencies
sudo apt install -y \
  libjpeg-dev zlib1g-dev libopenjp2-7-dev libtiff5-dev \
  libfreetype6-dev liblcms2-dev libwebp-dev \
  libharfbuzz-dev libfribidi-dev libxcb1-dev
```

---

## 2. Get the project code

**Option A — git clone (recommended)**

```bash
cd ~
git clone <GIT_REPO_URL> mementoframe
```

**Option B — download ZIP**

```bash
cd ~
wget -O mementoframe.zip <GIT_ZIP_URL>
unzip mementoframe.zip
mv mementoframe-* mementoframe
```

---

## 3. Python venv + dependencies

```bash
cd ~/mementoframe
python3 -m venv venv
source venv/bin/activate

pip install \
  flask flask-cors python-dotenv pillow spotipy requests RPi.GPIO
```

---

## 4. Create the `.env` file

The `.env` file holds your Spotify app credentials. It is created once manually and stays in place — the servers read it on startup but never overwrite it. All other settings (weather API key, clock config, power schedule) are saved automatically by the admin dashboard to `config.json`.

```bash
nano ~/mementoframe/.env
```

Paste and fill in:

```env
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
SPOTIFY_REDIRECT_URI=https://httpbin.org/anything
```

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`).

> **Getting Spotify credentials:**
> 1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and create an app.
> 2. Add `https://httpbin.org/anything` as a redirect URI in the app settings.
> 3. Copy the Client ID and Client Secret into `.env`.

---

## 5. Enable I2C for the RTC module (DS3231)

```bash
sudo raspi-config
# Interface Options → I2C → Enable
```

Verify the RTC is detected:

```bash
sudo i2cdetect -y 1
# Should show 0x68
```

---

## 6. Allow time setting without sudo password (optional)

```bash
sudo visudo
```

Add at the end:

```
mementoframe ALL=(ALL) NOPASSWD: /bin/date
```

---

## 7. Allow Wi-Fi management without sudo (polkit for NetworkManager)

```bash
sudo nano /etc/polkit-1/rules.d/90-nmcli.rules
```

Paste:

```javascript
polkit.addRule(function(action, subject) {
    if (action.id.indexOf("org.freedesktop.NetworkManager") == 0 &&
        subject.user == "mementoframe") {
        return polkit.Result.YES;
    }
});
```

---

## 8. Disable dhcpcd, enable NetworkManager

NetworkManager and dhcpcd conflict — disable dhcpcd completely.

```bash
sudo systemctl disable --now dhcpcd
sudo systemctl mask dhcpcd

sudo systemctl enable --now NetworkManager
```

---

## 9. Configure hostapd + dnsmasq (AP fallback mode)

### hostapd

```bash
sudo nano /etc/hostapd/hostapd.conf
```

```
country_code=PT
interface=wlan0
ssid=MementoFrame
hw_mode=g
channel=6
wmm_enabled=0

auth_algs=1
wpa=2
wpa_passphrase=your_ap_password
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
```

> Change `country_code` and `wpa_passphrase` as needed.

### dnsmasq

```bash
sudo nano /etc/dnsmasq.conf
```

```
interface=wlan0
dhcp-range=192.168.4.10,192.168.4.100,255.255.255.0,24h
dhcp-option=3,192.168.4.1
dhcp-option=6,192.168.4.1
server=1.1.1.1
```

> **Important:** Do not enable hostapd or dnsmasq as services yourself. `ap_mode_manager.py` starts and stops them programmatically as the network state changes.

```bash
sudo systemctl unmask hostapd
sudo systemctl disable hostapd
sudo systemctl disable dnsmasq
```

---

## 10. AP mode manager service

```bash
sudo nano /etc/systemd/system/apmode.service
```

```ini
[Unit]
Description=MementoFrame AP Mode Manager
After=NetworkManager.service network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/mementoframe/mementoframe/ap_mode_manager.py
Restart=always
RestartSec=5
User=root
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable apmode
sudo systemctl start apmode

# Check logs
journalctl -u apmode -f
```

---

## 11. Flask apps service

```bash
# Make sure the startup script is executable
chmod +x /home/mementoframe/mementoframe/start_apps.sh
```

```bash
sudo nano /etc/systemd/system/mementoframe.service
```

```ini
[Unit]
Description=MementoFrame Flask Services
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=mementoframe
WorkingDirectory=/home/mementoframe/mementoframe
ExecStart=/bin/bash /home/mementoframe/mementoframe/start_apps.sh
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mementoframe.service

# Check logs
journalctl -u mementoframe.service -f
```

---

## 12. Boot config (`/boot/firmware/config.txt`)

```bash
sudo nano /boot/firmware/config.txt
```

Add or ensure the following are set:

```
dtoverlay=vc4-fkms-v3d
disable_splash=1
avoid_warnings=1
gpu_mem=185

# GPIO 26: screen enable pin — HIGH at boot so screen is on before Python starts
gpio=26=op,dh
```

---

## 13. Boot cmdline (`/boot/firmware/cmdline.txt`)

Edit the file — it must remain a **single line**:

```bash
sudo nano /boot/firmware/cmdline.txt
```

Add these parameters to the existing line (do not start a new line):

```
quiet splash console=tty3 loglevel=0 logo.nologo vt.global_cursor_default=0
```

---

## 14. X permissions

```bash
sudo nano /etc/X11/Xwrapper.config
```

```
allowed_users=anybody
needs_root_rights=yes
```

---

## 15. Kiosk launcher script

```bash
sudo nano /usr/local/bin/kiosk.sh
```

```bash
#!/bin/bash
set -e

export DISPLAY=:0

xset -dpms
xset s off
xset s noblank

echo "Waiting for backend..."
until curl -sf http://127.0.0.1:5001/health > /dev/null; do
  sleep 1
done

echo "Backend ready — launching browser"

openbox-session &

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
  http://127.0.0.1:5001
```

```bash
sudo chmod +x /usr/local/bin/kiosk.sh
```

---

## 16. Kiosk systemd service

```bash
sudo nano /etc/systemd/system/kiosk.service
```

```ini
[Unit]
Description=Chromium Kiosk on tty1
After=mementoframe.service network-online.target
Requires=mementoframe.service
Wants=network-online.target

[Service]
User=mementoframe

TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=yes
StandardInput=tty
StandardOutput=journal
StandardError=journal
PAMName=login

Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/mementoframe/.Xauthority
WorkingDirectory=/home/mementoframe

ExecStart=/usr/bin/startx /usr/local/bin/kiosk.sh -- :0 vt1 -keeptty -nolisten tcp -nocursor
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable kiosk.service
sudo systemctl start kiosk.service

# Check logs
journalctl -u kiosk.service -f
```

Remove the login prompt on tty1 (so the screen goes straight to kiosk):

```bash
sudo systemctl disable --now getty@tty1.service
sudo systemctl mask getty@tty1.service
```

---

## 17. Spotify authorisation (first run)

Do this once after the services are running:

1. Open the admin dashboard at `http://<pi-ip>:5000` from any device on the same network.
2. Go to the **Spotify** section and click the authorisation link.
3. Log in to Spotify and approve access.
4. You will be redirected to `https://httpbin.org/anything` — copy the full URL from your browser's address bar.
5. Paste it into the field in the admin dashboard and submit.

The token is saved to `resources/userdata/cache/.cache_spotify` and refreshes automatically.

---

## 18. Upload your first photos

1. Open the admin dashboard at `http://<pi-ip>:5000`.
2. Go to the **Photos** section and upload your images.
3. Photos are automatically converted to WebP, resized, and registered in the slideshow.

The display will show a blank frame until at least one photo has been uploaded.

---

## Sanity checklist

### Service status

```bash
systemctl status mementoframe.service
systemctl status kiosk.service
systemctl status apmode.service
```

### Ports open

```bash
ss -lntp | grep -E ':(5000|5001)\s'
```

### AP mode

If not connected to a known Wi-Fi network:
- `wlan0` should have IP `192.168.4.1`
- SSID `MementoFrame` should be visible on nearby devices
- Admin dashboard should be reachable at `http://192.168.4.1:5000`

---

## Useful log commands

```bash
journalctl -u mementoframe.service -f   # Flask apps
journalctl -u kiosk.service -f          # Chromium kiosk
journalctl -u apmode.service -f         # Wi-Fi daemon

# Restart after code changes
sudo systemctl restart mementoframe.service
```