

# MementoFrame — Installation Guide

Official setup guide for Raspberry Pi OS Bookworm.

---

## Important Notes

Current versions of MementoFrame use:

- `NetworkManager`
- `nmcli`
- NetworkManager-managed AP profiles

---

## Tested Hardware

| Component | Version |
|---|---|
| Raspberry Pi | 3B+ |
| OS | Raspberry Pi OS Bookworm |
| Python | 3.11 |
| Display | GeekPi 7" HDMI |

---

## Install Dependencies

```bash
sudo apt update
sudo apt upgrade -y

sudo apt install -y \
  python3 \
  python3-pip \
  python3-venv \
  git \
  network-manager \
  chromium-browser \
  unclutter \
  xserver-xorg \
  xinit \
  openbox
````

---

## Clone Repository

```bash
cd ~
git clone <YOUR_REPO_URL> mementoframe
cd mementoframe
```

---

## Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

---

## Install Python Dependencies

```bash
pip install \
  flask \
  flask-cors \
  pillow \
  python-dotenv \
  requests \
  spotipy \
  RPi.GPIO
```

---

## Configure Spotify

Create `.env`:

```bash
nano .env
```

Example:

```env
SPOTIFY_CLIENT_ID=YOUR_CLIENT_ID
SPOTIFY_CLIENT_SECRET=YOUR_CLIENT_SECRET
SPOTIFY_REDIRECT_URI=https://httpbin.org/anything
```

---

## Enable NetworkManager

Disable conflicting networking systems:

```bash
sudo systemctl disable --now dhcpcd
sudo systemctl mask dhcpcd
```

Enable NetworkManager:

```bash
sudo systemctl enable --now NetworkManager
```

---

## AP Mode Notes

`ap_mode_manager.py` automatically:

* creates the AP profile
* switches between Wi‑Fi and AP mode
* manages reconnect probes
* enables AP fallback

No manual AP configuration is required.

The AP profile created automatically is:

| Setting | Value          |
| ------- | -------------- |
| Profile | `MementoAP`    |
| SSID    | `MementoFrame` |
| Gateway | `192.168.4.1`  |

---

## Create systemd Service — AP Manager

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
ExecStart=/home/pi/mementoframe/venv/bin/python /home/pi/mementoframe/ap_mode_manager.py
Restart=always
RestartSec=5
User=root
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now apmode.service
```

---

## Create Flask Service

```bash
chmod +x start_apps.sh
```

```bash
sudo nano /etc/systemd/system/mementoframe.service
```

```ini
[Unit]
Description=MementoFrame Services
After=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/mementoframe
ExecStart=/bin/bash /home/pi/mementoframe/start_apps.sh
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mementoframe.service
```

---

## Chromium Kiosk

Create launcher:

```bash
sudo nano /usr/local/bin/kiosk.sh
```

```bash
#!/bin/bash
export DISPLAY=:0

xset -dpms
xset s off
xset s noblank

openbox-session &

chromium-browser \
  --kiosk \
  --incognito \
  --disable-infobars \
  --no-first-run \
  http://127.0.0.1:5001
```

Make executable:

```bash
sudo chmod +x /usr/local/bin/kiosk.sh
```

---

## Create Kiosk Service

```bash
sudo nano /etc/systemd/system/kiosk.service
```

```ini
[Unit]
Description=MementoFrame Kiosk
After=mementoframe.service

[Service]
User=pi
Environment=DISPLAY=:0
ExecStart=/usr/bin/startx /usr/local/bin/kiosk.sh -- :0
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now kiosk.service
```

---

## Verify Services

```bash
systemctl status mementoframe.service
systemctl status apmode.service
systemctl status kiosk.service
```

---

## Useful Logs

```bash
journalctl -u mementoframe.service -f
journalctl -u apmode.service -f
journalctl -u kiosk.service -f
```

---

## Ports

| Port | Purpose              |
| ---- | -------------------- |
| 5000 | Admin dashboard      |
| 5001 | Frontend display API |

---

## First Boot Flow

```text
Boot Raspberry Pi
        │
        ▼
Start Flask services
        │
        ▼
Start kiosk frontend
        │
        ▼
Check Wi‑Fi connectivity
        │
        ├── Connected → Client mode
        │
        └── Offline → AP fallback mode
```

---

## Updating

```bash
cd ~/mementoframe
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart mementoframe.service
```

---

## License

Creative Commons Attribution-NonCommercial 4.0 International

[http://creativecommons.org/licenses/by-nc/4.0/](http://creativecommons.org/licenses/by-nc/4.0/)

```
```
