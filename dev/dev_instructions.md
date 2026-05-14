# MementoFrame Mock Apps

Local development environment for MementoFrame without requiring Raspberry Pi hardware.

The mock environment mirrors the real application structure and APIs closely so frontend development and testing can happen entirely on a desktop machine.

---

# Features

The mock environment supports:

* Frontend/UI development
* AP/client mode simulation
* Configuration PIN flow testing
* Spotify widget testing
* Real Spotify integration
* Weather widget testing
* SSE reload testing
* Local photo upload/delete
* Device state simulation
* Frontend design iteration

---

# Repository Structure

```txt
root/
├── mementoframe/
│   ├── app.py
│   ├── api_service.py
│   ├── ap_mode_manager.py
│   ├── resources/
│   ├── runtime/
│   ├── static/
│   ├── templates/
│   └── ...
│
├── dev/
│   ├── mock_app.py
│   ├── mock_api_service.py
│   ├── mock_shared.py
│   ├── run_mocks.py
│   └── runtime/
│
└── .gitignore
```

---

# Mock Services

## `mock_app.py`

Runs on:

```txt
http://localhost:5000
```

Replacement for:

```txt
mementoframe/app.py
```

Provides:

* Admin dashboard
* Photo uploads
* Photo deletion
* Config portal PIN flow
* Brightness settings
* Auto power settings
* Weather settings
* Spotify controls
* Mock device controls

---

## `mock_api_service.py`

Runs on:

```txt
http://localhost:5001
```

Replacement for:

```txt
mementoframe/api_service.py
```

Provides:

* Spotify API
* Weather API
* Device status API
* PIN JSON endpoints
* SSE reload stream
* AP/client mode state
* Mock management UI

---

## `mock_shared.py`

Shared state manager used by both mock services.

Handles:

* Shared runtime state
* Shared Spotify state
* Shared weather state
* Shared AP/client state
* Shared PIN state

Runtime files are stored in:

```txt
dev/runtime/
```

---

# Installation

Install dependencies:

```bash
pip install flask flask-cors pillow python-dotenv werkzeug spotipy
```

---

# Running the Mock Environment

From the repository root:

```bash
py dev/run_mocks.py
```

Expected output:

```txt
MementoFrame mock environment running
Admin dashboard : http://localhost:5000
Frontend API    : http://localhost:5001
Mock controls   : http://localhost:5001/mock
```

---

# URLs

## Admin Dashboard

```txt
http://localhost:5000
```

Main local development dashboard.

---

## Frontend API

```txt
http://localhost:5001
```

Used by the frontend/display UI.

---

## Mock Controls

```txt
http://localhost:5001/mock
```

Allows changing:

* AP/client mode
* Weather state
* Spotify state
* PIN state
* Screen state
* Device status

---

# Spotify Modes

The mock environment supports both mock and real Spotify playback.

---

## Mock Spotify Mode

Uses built-in fake playback data.

Good for:

* frontend testing
* screenshots
* UI development
* development without Spotify OAuth

Configuration:

```python
state["spotify"]["source"] = "mock"
```

---

## Real Spotify Mode

Uses your real Spotify playback data locally.

Spotify credentials and cache are intended to remain local only and should never be committed.

Create a local `.env` file:

```env
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
```

Spotify cache location:

```txt
dev/runtime/.cache_spotify
```

Enable real Spotify mode:

```python
state["spotify"]["source"] = "real"
```

---

# Configuration PIN Flow

The mock environment mirrors the real configuration PIN system.

Protected routes require unlocking with a temporary PIN.

PIN endpoint:

```txt
/config_portal_pin.json
```

Compatibility aliases:

```txt
/config_pin.json
/frame_pin.json
/ap_pin.json
```

PINs:

* expire automatically
* are stored only in `dev/runtime`
* are never committed to git

---

# SSE Reload Stream

The mock API provides:

```txt
/config/stream
```

The frontend reloads automatically when:

* `photos.json` changes
* `config.json` changes

---

# Runtime Files

Generated files are stored in:

```txt
dev/runtime/
```

Examples:

```txt
mock_state.json
config_portal_pin.json
.cache_spotify
```

These files should not be committed.

---

# Recommended `.gitignore`

```gitignore
# Python
__pycache__/
*.pyc

# Environment
.env
.env.*

# Runtime
mementoframe/runtime/*
dev/runtime/*
!mementoframe/runtime/.gitkeep
!dev/runtime/.gitkeep

# Spotify
.cache_spotify

# Photos
mementoframe/resources/userdata/Photos/full/*
mementoframe/resources/userdata/Photos/thumbs/*
!mementoframe/resources/userdata/Photos/full/.gitkeep
!mementoframe/resources/userdata/Photos/thumbs/.gitkeep
```

---

# Demo Photos

Demo photos included in the repository are intended only for:

* development
* testing
* screenshots
* frontend previews

Photo attributions are listed in:

```txt
mementoframe/resources/demo/ATTRIBUTIONS.md
```

---

# Notes

The mock environment intentionally:

* does NOT use GPIO
* does NOT modify Wi‑Fi state
* does NOT use `nmcli`
* does NOT require Raspberry Pi hardware

The mock environment exists purely for:

* frontend iteration
* local testing
* contributor onboarding
* UI development
* API simulation

---

# Troubleshooting

## Templates not loading

Verify repository structure:

```txt
root/
├── mementoframe/
└── dev/
```

---

## Static/CSS not loading

Run the mocks from the repository root:

```bash
py dev/run_mocks.py
```

---

## Spotify not working

Install Spotipy:

```bash
pip install spotipy
```

Verify `.env` contains:

```txt
SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET
```

---

## PIN flow stuck

Delete:

```txt
dev/runtime/config_portal_pin.json
```

Then restart the mock environment.

---

# Mock update styling flag

The mock environment includes a safe UI-testing flag for update styling.

In the mock management UI:

```txt
http://localhost:5001/mock
```

Enable:

```txt
Software updates → Mock pending update
```

When enabled, the mock update status endpoints return `available: true` and `mock_pending_update: true` so the frontend update badge/rounded div is shown. This does not install updates, set a real pending restart, or reboot.

Relevant endpoints:

```txt
GET  /update_status.json       # display/frontend read-only status
GET  /update/status            # dashboard read-only status
POST /update/check             # checks GitHub releases if repo is configured
POST /update/install           # mock no-op; always blocked
POST /mock/update/pending      # toggles the mock pending update flag
```
