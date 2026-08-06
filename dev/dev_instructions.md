# MementoFrame Mock Apps

The `dev` folder provides a desktop development environment for the
MementoFrame frontend and configuration portal. It mirrors the production
routes closely enough to develop UI changes and test application states without
a Raspberry Pi, GPIO hardware, systemd, NetworkManager, or a connected display.

## Requirements

- Python 3.11 or later
- The MementoFrame repository
- A browser
- Internet access only when testing real Spotify, WeatherAPI, or GitHub calls

The mock services use these Python packages:

- Flask
- Flask-CORS
- Pillow
- python-dotenv
- Requests
- Spotipy
- Werkzeug

Create a virtual environment from the repository root.

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install Flask flask-cors Pillow python-dotenv requests spotipy Werkzeug
```

### Linux or macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install Flask flask-cors Pillow python-dotenv requests spotipy Werkzeug
```

The mock environment does not import `RPi.GPIO`, so that package is not
required for desktop development.

## Running the Mocks

Start both services from the repository root:

```bash
python dev/run_mocks.py
```

On Windows, this is also valid:

```powershell
py dev/run_mocks.py
```

The launcher starts both processes and prints their URLs:

| Interface | URL | Purpose |
|---|---|---|
| Configuration portal | `http://localhost:5000` | Develop and test the admin/configuration UI. |
| Display UI | `http://localhost:5001` | Render the kiosk frontend against mock APIs. |
| Mock controls | `http://localhost:5001/mock` | Change simulated device, weather, Spotify, time, PIN, and update state. |
| Forced-time JSON | `http://localhost:5001/mock/time.json` | Inspect the active browser-time override. |

Press `Ctrl+C` in the terminal to stop both services.

If port 5000 or 5001 is already in use, stop the conflicting process before
starting the mocks.

## Mock Components

| File | Role |
|---|---|
| `dev/run_mocks.py` | Starts and stops both mock web services. |
| `dev/mock_config_portal_service.py` | Endpoint-compatible configuration portal on port 5000. |
| `dev/mock_display_service.py` | Display frontend, widget APIs, and mock control panel on port 5001. |
| `dev/mock_shared.py` | Shared state, payload builders, photo helpers, external-service helpers, and runtime paths. |
| `dev/mock_updater.py` | Safe command-line interface for testing updater states. |
| `dev/runtime/` | Mock-only state, PIN, update state, and Spotify cache. Created automatically. |

## What Can Be Tested

The control panel at `http://localhost:5001/mock` supports:

- Client Wi-Fi, fallback AP, and unknown network modes [simulated only, no network control on the host]
- Simulated IP addresses, SSIDs, and known networks
- Screen on/off state [simulated, logs available on the frontend console]
- Configuration PIN creation and expiration
- Fixed or ticking browser time
- Mock Spotify playback, tracks, connection state, and progress
- Mock weather, forecast, astronomy, and alert data
- No-weather and current-weather-only layouts
- Photo upload, deletion, ordering, and reload behavior
- Server-Sent Events frontend reloads
- Available-update, installing, and automatic-update UI states

Most frontend work can use the built-in mock Spotify and weather data without
API credentials.

## Mock State and Project Data

Mock-only runtime state is written to:

```text
dev/runtime/
├── mock_state.json
├── update_state.json
├── config_portal_pin.json
└── .cache_spotify
```

The mock applications intentionally render the real files under
`mementoframe/templates`, `mementoframe/static`, and
`mementoframe/resources/assets`. Changes to those frontend files are visible
after refreshing the browser.

The configuration portal also uses the project's real local development data:

- `mementoframe/config.json`
- `mementoframe/.env`, when present
- `mementoframe/resources/userdata/Photos/`
- `mementoframe/resources/userdata/cache/`

As a result, configuration edits, credential changes, and photo operations made
through the mock portal can modify those local files. Use development data and
do not enter production secrets into a shared working tree.

## Testing Time-Dependent UI

Open the mock controls and configure the Forced time section. The display
service injects `/mock/time-override.js` into the frame page before the
frontend runs.

You can set:

- A fixed ISO datetime
- Whether simulated time continues ticking
- Whether the override is enabled

This is useful for testing clock layouts, date changes, schedules, nighttime
styles, and other time-dependent behavior without changing the computer clock.

## Testing Spotify and Weather

Both integrations support `mock` and `real` data sources.

Mock mode is the default and requires no credentials. Use the control panel to
change tracks, playback state, weather conditions, day/night state, forecasts,
and alerts.

Real integration testing may use values stored in `mementoframe/.env`:

```dotenv
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REDIRECT_URI=
WEATHER_API_KEY=
```

The weather API key can also be saved through the mock configuration portal.
Real integrations require network access and are no longer fully isolated
tests.

## Testing Updates Safely

The mock updater simulates update states but never installs project files or
reboots the computer.

Use the mock control panel for UI testing, or run:

```bash
python dev/mock_updater.py status
python dev/mock_updater.py pending-on
python dev/mock_updater.py pending-off
python dev/mock_updater.py check
python dev/mock_updater.py install
python dev/mock_updater.py autoupdate
python dev/mock_updater.py diagnose
```

A simulated installation remains in progress for 90 seconds by default. Change
the duration for a test session with:

```bash
MEMENTOFRAME_MOCK_INSTALL_SECONDS=10 python dev/run_mocks.py
```

In PowerShell:

```powershell
$env:MEMENTOFRAME_MOCK_INSTALL_SECONDS = "10"
python dev/run_mocks.py
```

## Troubleshooting

### A dependency is missing

Activate the virtual environment and reinstall the mock dependencies:

```bash
python -m pip install Flask flask-cors Pillow python-dotenv requests spotipy Werkzeug
```

### The UI does not reflect frontend changes

Refresh the display page. For state or photo changes, use the portal's reload
action or restart the mock launcher.

### Mock state needs to be reset

Stop the services, then remove only the generated files inside `dev/runtime`.
They will be recreated with defaults the next time the mocks start.

### A service exits immediately

Run it directly to see its complete error:

```bash
python dev/mock_config_portal_service.py
python dev/mock_display_service.py
```

Run individual services from the repository root so the real
`mementoframe` templates and assets can be resolved correctly.
