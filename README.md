<p align="center">
  <img src="docs/logo.png" alt="MementoFrame logo" width="800"/>
</p>

<h1 align="center">MementoFrame</h1>

<p align="center">
  Smart Raspberry Pi photo frame with automatic Wi‑Fi/AP fallback, live Spotify integration, weather widgets, GPIO-controlled display power, and a fully web-based management portal.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg" alt="License"/>
  <img src="https://img.shields.io/badge/platform-Raspberry%20Pi%203B%2B-red" alt="Platform"/>
  <img src="https://img.shields.io/badge/python-3.11-blue" alt="Python"/>
  <img src="https://img.shields.io/badge/NetworkManager-managed-success" alt="NetworkManager"/>
</p>

---

## Overview

MementoFrame is a self-contained smart photo frame platform built around a Raspberry Pi.

The project combines:

- Full-screen slideshow frontend
- Local Flask API service
- Web-based administration dashboard
- Automatic Wi‑Fi ↔ AP fallback switching
- GPIO display power + brightness control
- Spotify playback integration
- Weather + timezone widgets
- Server-Sent Events (SSE) live config reloading

The system is designed to boot directly into a kiosk interface while remaining remotely configurable from any device on the same network.

---

## Current Component Versions

Versions are exposed live through `/versions` and defined in `version_info.py`.

| Component | Notes |
|---|---|
| Frontend | All frontend related files (html, css, js) |
| App | app.py |
| API Service | api_service.py |
| AP Mode Manager | ap_mode_manager.py |

---

## Main Services

| Service | Port | Purpose | Notes |
|---|---|---|---|
| `app.py` | `5000` | Admin/configuration dashboard | Acessible on AP network or IP, protected by a pin generated on access and shown on device |
| `api_service.py` | `5001` | Frontend display API + live data | Only acessible on device for security purposes |
| `ap_mode_manager.py` | — | Wi‑Fi/AP watchdog daemon | |

---

## Architecture

```text
                        ┌────────────────────┐
                        │   Browser / Kiosk  │
                        │  Chromium Frontend │
                        └─────────┬──────────┘
                                  │
                    Requests JSON │
                                  ▼
                    ┌─────────────────────┐
                    │   api_service.py    │
                    │   Port 5001         │
                    │ Frontend API Layer  │
                    └─────────┬───────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
    Spotify API         WeatherAPI         GPIO Control


                    ┌─────────────────────┐
                    │       app.py        │
                    │      Port 5000      │
                    │ Admin Dashboard     │
                    └─────────┬───────────┘
                              │
                              ▼
                   Photo uploads + config


                    ┌─────────────────────┐
                    │ ap_mode_manager.py  │
                    │ Network watchdog    │
                    └─────────┬───────────┘
                              │
               Wi‑Fi connected / AP fallback
````

---

## Features

### Photo Management

* Multi-file photo uploads
* Automatic EXIF rotation handling
* Automatic WebP conversion
* Thumbnail generation
* Persistent slideshow ordering
* Dynamic frontend photo reloads via SSE

### Network Management

* Fully managed by NetworkManager
* Automatic fallback AP mode
* SSID: `MementoFrame`
* AP gateway: `192.168.4.1`
* Automatic reconnect probing
* Runtime-only configuration PIN protection

### Display Features

* Fullscreen Chromium kiosk mode
* GPIO-controlled display power
* GPIO brightness pulse control
* Auto on/off schedules
* Dual timezone clocks
* Weather widget
* Spotify album art + playback state

### Security

* Runtime-generated Flask secret key
* Session-based config portal unlock
* Short-lived AP PIN authentication
* PIN auto-expiration

---

## Access Point (AP) Mode

When no known Wi‑Fi network is available, MementoFrame automatically enables a local configuration hotspot.

| Setting   | Value                     |
| --------- | ------------------------- |
| SSID      | `MementoFrame`            |
| Gateway   | `192.168.4.1`             |
| Dashboard | `http://192.168.4.1:5000` |

### AP Flow

```text
No Wi‑Fi detected
        │
        ▼
Enable NetworkManager AP profile
        │
        ▼
Generate temporary config PIN
        │
        ▼
User connects to MementoFrame AP
        │
        ▼
Enter PIN on dashboard
        │
        ▼
Configure Wi‑Fi credentials
        │
        ▼
Reconnect to client network
```

---

## GPIO Usage

| GPIO    | Purpose               |
| ------- | --------------------- |
| GPIO 20 | Brightness UP pulse   |
| GPIO 21 | Brightness DOWN pulse |
| GPIO 26 | Screen power enable   |

---

## Project Structure

```text
mementoframe/
├── app.py
├── api_service.py
├── ap_mode_manager.py
├── start_apps.sh
├── version_info.py
├── config.json
├── runtime/
├── resources/
│   ├── assets/
│   └── userdata/
│       ├── Photos/
│       └── cache/
├── static/
├── templates/
└── docs/
```

---

## API Endpoints

### app.py (Admin Dashboard)

| Endpoint                  | Description                   |
| ------------------------- | ----------------------------- |
| `/`                       | Main dashboard                |
| `/upload`                 | Upload photos                 |
| `/delete_selected_photos` | Remove photos                 |
| `/save_clock_settings`    | Save clock configuration      |
| `/save_display_settings`  | Save brightness settings      |
| `/save_auto_power`        | Save power schedule           |
| `/save_weather_api`       | Save WeatherAPI configuration |
| `/spotify/connect`        | Start Spotify OAuth           |
| `/spotify/manual`         | Finish Spotify OAuth          |
| `/versions`               | Return component versions     |

### api_service.py (Display API)

| Endpoint         | Description               |
| ---------------- | ------------------------- |
| `/spotify.json`  | Spotify playback metadata |
| `/weather.json`  | Current weather           |
| `/status.json`   | Network mode + IP         |
| `/config/stream` | SSE reload stream         |
| `/screen/on`     | Enable screen GPIO        |
| `/screen/off`    | Disable screen GPIO       |
| `/versions`      | Return component versions |

---

## Runtime Data

| Path                                      | Purpose                    |
| ----------------------------------------- | -------------------------- |
| `resources/userdata/Photos/full/`         | Full-size converted photos |
| `resources/userdata/Photos/thumbs/`       | Generated thumbnails       |
| `resources/userdata/cache/.cache_spotify` | Spotify OAuth cache        |
| `runtime/config_portal_pin.json`          | Temporary AP-mode PIN      |
| `config.json`                             | User configuration         |

---

## Requirements

### Hardware

* Raspberry Pi 3B+
* HDMI display
* DS3231 RTC (optional)
* GPIO-connected brightness/display circuitry

### Software

* Raspberry Pi OS Bookworm
* Python 3.11+
* NetworkManager
* Chromium

---

## Installation

Full setup instructions are available in:

```text
INSTALL.md
```

---

## License

Creative Commons Attribution-NonCommercial 4.0 International

[http://creativecommons.org/licenses/by-nc/4.0/](http://creativecommons.org/licenses/by-nc/4.0/)



## Author

João Fernandes — 2026


---
---

# Demo Image Attributions

These images are included only as demo/development placeholders for MementoFrame.

Images sourced from Unsplash under the Unsplash License:
https://unsplash.com/license

## Included Images

- `erik-jan-leusink-IbPxGLgJiMI-unsplash.jpg`
  Photo by Erik-Jan Leusink
  https://unsplash.com/@erikjanl

- `kate-stone-matheson-uy5t-CJuIK4-unsplash.jpg`
  Photo by Kate Stone Matheson
  https://unsplash.com/@kstonematheson

- `ryoji-iwata-X53e51WfjIE-unsplash.jpg`
  Photo by Ryoji Iwata
  https://unsplash.com/@ryoji__iwata

- `ray-hennessy-MH_psben7HE-unsplash.jpg`
  Photo by Ray Hennessy
  https://unsplash.com/@rayhennessy

- `tanya-barrow-AobgShFe_ks-unsplash.jpg`
  Photo by Tanya Barrow
  https://unsplash.com/@tanyabarrow

- `bin-thieu-ILEzY3D9jbQ-unsplash.jpg`
  Photo by Bin Thieu
  https://unsplash.com/@binthieu

- `brooke-balentine-ta4hTTz7ipw-unsplash.jpg`
  Photo by Brooke Balentine
  https://unsplash.com/@brookebalentine

- `microsoft-copilot-o2MBk6J-qc-unsplash.jpg`
  Photo by Microsoft 365
  https://unsplash.com/@microsoft365

- `jason-leung-TxhDR5I-sUg-unsplash.jpg`
  Photo by Jason Leung
  https://unsplash.com/@ninjason