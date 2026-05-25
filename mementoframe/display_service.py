#!/usr/bin/env python3
# MementoFrame - Raspberry Pi Smart Photo Frame
# Copyright (c) 2026 João Fernandes
#
# This work is licensed under the Creative Commons Attribution-NonCommercial
# 4.0 International License. To view a copy of this license, visit:
# http://creativecommons.org/licenses/by-nc/4.0/

"""
api_service.py

Brief:
    Local display API for MementoFrame frontend widgets and hardware controls.

Endpoints:
    GET  /                         - Render the photo-frame frontend.
    GET  /assets/<filename>        - Serve static project assets.
    GET  /userdata/<filename>      - Serve persistent user data files.
    GET  /config.json              - Serve saved frame configuration.
    GET  /spotify.json             - Return current Spotify playback metadata.
    GET  /weather.json             - Return current weather data.
    GET  /config_portal_pin.json   - Return active AP-mode PIN for local display UI.
    GET  /status.json              - Return Wi-Fi/AP mode, IP address, and uptime.
    GET  /health                   - Return service health status.
    GET  /get_ip                   - Return detected local IP address.
    GET  /versions                 - Return installed component versions.
    GET  /config/stream            - Server-Sent Events stream for config/photo reloads.
    POST /screen/on                - Turn the display output on.
    POST /screen/off               - Turn the display output off.

"""
import sys
import threading

from flask import Flask, jsonify, render_template, send_from_directory, Response
from flask_cors import CORS
import os, json, time, socket, threading, subprocess, requests
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import RPi.GPIO as GPIO
from updater import PROJECT_ROOT
from version_info import GLOBAL_APP_VERSION, VERSION_INFO


# =============================================================================
# Hardware setup
# =============================================================================
SCREEN_PIN = 26
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(SCREEN_PIN, GPIO.OUT, initial=GPIO.HIGH)

# =============================================================================
# Flask initialization
# =============================================================================
load_dotenv()
app = Flask(__name__, static_folder="static", static_url_path="/static")
CORS(app)

# =============================================================================
# Filesystem layout
# =============================================================================
CONFIG_FILE = "config.json"

USERDATA_DIR = "resources/userdata"
ASSETS_DIR = "resources/assets"
PHOTO_JSON = os.path.join(USERDATA_DIR, "Photos/photos.json")
SPOTIFY_CACHE = os.path.join(USERDATA_DIR, "cache/.cache_spotify")
RUNTIME_DIR = "runtime"
CONFIG_PORTAL_PIN_FILE = os.path.join(RUNTIME_DIR, "config_portal_pin.json")
UPDATE_STATE_FILE = os.path.join(RUNTIME_DIR, "update_state.json")

# =============================================================================
# Configuration loading
# =============================================================================
def load_config():
    """Load config.json for display-service runtime settings."""
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config.json: {e}")
        return {}


def load_update_state():
    """Return updater runtime state merged with config/update defaults for display UI."""
    state = {}
    try:
        with open(UPDATE_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        state = {}
    except Exception as e:
        state = {"last_error": f"Unable to read update state: {e}"}

    cfg = load_config()
    updates_cfg = cfg.get("updates", {}) if isinstance(cfg, dict) else {}
    state.setdefault("available", False)
    state.setdefault("pending_restart", False)
    state.setdefault("update_in_progress", False)
    state.setdefault("installed_version", GLOBAL_APP_VERSION)
    state["auto_update"] = bool(updates_cfg.get("auto_update", False))
    return state

config = load_config()

# =============================================================================
# Spotify client setup
# =============================================================================
def spotify_credentials_configured():
    """Return True when the display service has enough Spotify credentials to start OAuth."""
    return bool(os.getenv("SPOTIFY_CLIENT_ID") and os.getenv("SPOTIFY_CLIENT_SECRET"))


def create_spotify_client():
    """Create the Spotify client only when credentials are configured.

    Spotipy raises SpotifyOauthError at construction time when credentials are
    missing. The display service must still start without Spotify configured,
    so this returns None instead of failing the whole Flask service.
    """
    if not spotify_credentials_configured():
        return None

    try:
        return spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=os.getenv("SPOTIFY_CLIENT_ID"),
            client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
            redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "https://httpbin.org/anything"),
            scope="user-read-playback-state user-read-currently-playing user-library-read",
            cache_path=SPOTIFY_CACHE
        ))
    except Exception as e:
        print(f"⚠️ Spotify disabled: {e}")
        return None


sp = create_spotify_client()

# =============================================================================
# Weather configuration
# =============================================================================
WEATHER_API_KEY = config.get("weather_api_key")
WEATHER_LOCATION = config.get("weather_region", "Porto")

# =============================================================================
# Shared cache and rate-limit state
# =============================================================================
cache = {}
cooldowns = {}
MAX_CACHE_AGE = 30  # seconds

def safe_spotify_call(endpoint_key, func, *args, **kwargs):
    """Call Spotify with short cache support and graceful rate-limit handling."""
    now = time.time()

    if endpoint_key in cooldowns and now < cooldowns[endpoint_key]:
        if endpoint_key in cache:
            cached_data, cached_time = cache[endpoint_key]
            if now - cached_time < MAX_CACHE_AGE:
                return cached_data
        return None

    try:
        result = func(*args, **kwargs)
        cache[endpoint_key] = (result, now)
        return result
    except spotipy.exceptions.SpotifyException as e:
        if e.http_status == 429:
            retry_after = int(e.headers.get("Retry-After", 5))
            cooldowns[endpoint_key] = now + retry_after
            if endpoint_key in cache:
                cached_data, cached_time = cache[endpoint_key]
                if now - cached_time < MAX_CACHE_AGE:
                    return cached_data
            return None
        print(f"[{endpoint_key}] Spotify API error: {e}")
        return None
    except Exception as e:
        print(f"[{endpoint_key}] Unexpected error: {e}")
        return None


# =============================================================================
# Weather icon mapping and alert area filtering
# =============================================================================
METEOICON_BASE_URL = "/assets/Weather/meteoicons/fill"

MOON_PHASE_TO_METEOICON = {
    "new moon": "moon-new",
    "waxing crescent": "moon-waxing-crescent",
    "first quarter": "moon-first-quarter",
    "waxing gibbous": "moon-waxing-gibbous",
    "full moon": "moon-full",
    "waning gibbous": "moon-waning-gibbous",
    "last quarter": "moon-last-quarter",
    "waning crescent": "moon-waning-crescent",
}

WEATHER_CODE_TO_METEOICON = {
    1000: {"day": "clear-day", "night": "moon-phase"},
    1003: {"day": "partly-cloudy-day", "night": "partly-cloudy-night"},
    1006: "cloudy",
    1009: {"day": "overcast-day", "night": "overcast-night"},

    1030: {"day": "fog-day", "night": "fog-night"},
    1135: {"day": "fog-day", "night": "fog-night"},
    1147: {"day": "fog-day", "night": "fog-night"},

    1063: {"day": "partly-cloudy-day-rain", "night": "partly-cloudy-night-rain"},
    1180: {"day": "partly-cloudy-day-rain", "night": "partly-cloudy-night-rain"},
    1240: {"day": "partly-cloudy-day-rain", "night": "partly-cloudy-night-rain"},

    1072: "sleet",
    1150: "rain",
    1153: "rain",
    1168: "sleet",
    1171: "sleet",

    1183: "rain",
    1186: "rain",
    1189: "rain",
    1192: "extreme-rain",
    1195: "extreme-rain",
    1198: "rain",
    1201: "extreme-rain",
    1243: "rain",
    1246: "extreme-rain",

    1066: "snow",
    1114: "wind-snow",
    1117: "extreme-snow",
    1210: "snow",
    1213: "snow",
    1216: "snow",
    1219: "snow",
    1222: "extreme-snow",
    1225: "extreme-snow",
    1255: "snow",
    1258: "snow",

    1069: {"day": "partly-cloudy-day-sleet", "night": "partly-cloudy-night-sleet"},
    1204: "sleet",
    1207: "sleet",
    1249: "sleet",
    1252: "sleet",

    1237: "hail",
    1261: "hail",
    1264: "hail",

    1087: {"day": "thunderstorms-day", "night": "thunderstorms-night"},
    1273: {"day": "thunderstorms-day-rain", "night": "thunderstorms-night-rain"},
    1276: "thunderstorms-extreme-rain",
    1279: {"day": "thunderstorms-day-snow", "night": "thunderstorms-night-snow"},
    1282: "thunderstorms-extreme-snow",
}

ALERT_EVENT_ICON_RULES = [
    ("avalanche", "alert-avalanche-danger"),
    ("rock|landslide|debris", "alert-falling-rocks"),
    ("tornado", "tornado"),
    ("hurricane|cyclone|typhoon", "hurricane"),
    ("thunder|lightning|storm", "thunderstorms-extreme-rain"),
    ("rain|shower|flood|precip|coastal|marine|surf", "extreme-rain"),
    ("snow|blizzard", "extreme-snow"),
    ("ice|freez|sleet", "sleet"),
    ("hail", "hail"),
    ("wind|gale|gust", "wind-alert"),
    ("fog|mist", "fog-day"),
    ("heat|hot|high temperature", "thermometer-warmer"),
    ("cold|frost|low temperature", "thermometer-colder"),
]

ALERT_SEVERITY_FALLBACK_ICON = {
    "extreme": "thunderstorms-extreme",
    "severe": "wind-alert",
    "moderate": "wind-alert",
    "minor": "wind-alert",
}


def meteocon_url(icon_name):
    """Return a browser URL for a bundled Meteoicons SVG."""
    clean = str(icon_name or "not-available").strip().replace(".svg", "")
    return f"{METEOICON_BASE_URL}/{clean}.svg"


def normalize_moon_phase(phase):
    return str(phase or "").strip().lower()


def resolve_moon_phase_icon(moon_phase):
    return MOON_PHASE_TO_METEOICON.get(normalize_moon_phase(moon_phase), "moon-new")


def resolve_uv_icon_name(uv_value):
    """Use UV-specific icons only for clear daytime sky when UV is 5 or above."""
    try:
        rounded = int(round(float(uv_value)))
    except (TypeError, ValueError):
        return "clear-day"

    if rounded < 5:
        return "clear-day"
    if rounded >= 12:
        return "uv-index-11-plus"
    if rounded == 11:
        return "uv-index-11"
    return f"uv-index-{max(1, min(10, rounded))}"


def resolve_weather_icon(condition_code, is_day=True, moon_phase=None, uv_value=None):
    """Map WeatherAPI condition code + day/night state to a bundled Meteoicon URL."""
    try:
        code = int(condition_code or 0)
    except (TypeError, ValueError):
        code = 0

    if code == 1000 and bool(is_day):
        return meteocon_url(resolve_uv_icon_name(uv_value))

    entry = WEATHER_CODE_TO_METEOICON.get(code, "not-available")

    if isinstance(entry, dict):
        icon_name = entry["day"] if bool(is_day) else entry["night"]
    else:
        icon_name = entry

    if icon_name == "moon-phase":
        icon_name = resolve_moon_phase_icon(moon_phase)

    return meteocon_url(icon_name)


def resolve_alert_icon(alert):
    """Map WeatherAPI alert text/severity to one of the bundled alert icons."""
    import re

    text = " ".join(str(alert.get(key, "")) for key in [
        "event", "headline", "desc", "instruction", "category", "severity"
    ]).lower()

    for pattern, icon_name in ALERT_EVENT_ICON_RULES:
        if re.search(pattern, text, re.IGNORECASE):
            return meteocon_url(icon_name)

    severity = str(alert.get("severity", "")).strip().lower()
    return meteocon_url(ALERT_SEVERITY_FALLBACK_ICON.get(severity, "wind-alert"))


def normalize_area_text(value):
    """Normalize area names for fuzzy but safe alert matching."""
    import re
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def area_words(value):
    return {
        word
        for word in normalize_area_text(value).split()
        if len(word) >= 3
    }


def alert_area_candidates(configured_location, api_location):
    candidates = []

    for part in str(configured_location or "").replace(";", ",").split(","):
        part = part.strip()
        if part:
            candidates.append(part)

    if isinstance(api_location, dict):
        for key in ("name", "region", "country"):
            value = str(api_location.get(key) or "").strip()
            if value:
                candidates.append(value)

    seen = set()
    clean = []
    for candidate in candidates:
        normalized = normalize_area_text(candidate)
        if normalized and normalized not in seen:
            seen.add(normalized)
            clean.append(candidate)

    return clean


def alert_matches_configured_area(alert, configured_location, api_location):
    """Return True if the alert area appears to cover the configured weather area.

    WeatherAPI alert areas are often broader than a city. So "Aveiro,Portugal"
    should match an alert for "Aveiro", the API-resolved region, or "Portugal".
    Alerts with no area value are kept because WeatherAPI already returned them
    for the requested location and there is no safer filter.
    """
    raw_areas = str(alert.get("areas") or "").strip()
    if not raw_areas:
        return True

    normalized_areas = normalize_area_text(raw_areas)
    if not normalized_areas:
        return True

    candidates = alert_area_candidates(configured_location, api_location)
    area_word_set = area_words(raw_areas)

    for candidate in candidates:
        normalized_candidate = normalize_area_text(candidate)
        if not normalized_candidate:
            continue

        if normalized_candidate in normalized_areas:
            return True

        candidate_words = area_words(candidate)
        if candidate_words and any(word in area_word_set for word in candidate_words):
            return True

    broad_markers = [
        "all areas",
        "entire country",
        "whole country",
        "countrywide",
        "nationwide",
        "all districts",
        "mainland",
    ]
    return any(marker in normalized_areas for marker in broad_markers)


def normalize_weather_alerts(data, configured_location=None):
    alerts = data.get("alerts", {}).get("alert", []) or []
    api_location = data.get("location", {}) or {}
    normalized = []

    for alert in alerts:
        if not alert_matches_configured_area(alert, configured_location, api_location):
            continue

        item = {
            "headline": alert.get("headline", ""),
            "event": alert.get("event", ""),
            "severity": alert.get("severity", ""),
            "urgency": alert.get("urgency", ""),
            "areas": alert.get("areas", ""),
            "category": alert.get("category", ""),
            "certainty": alert.get("certainty", ""),
            "effective": alert.get("effective", ""),
            "expires": alert.get("expires", ""),
            "desc": alert.get("desc", ""),
            "instruction": alert.get("instruction", ""),
        }
        item["icon"] = resolve_alert_icon(item)
        normalized.append(item)

    return normalized


# =============================================================================
# Weather data helper
# =============================================================================
def get_weather_data():
    """Fetch current weather + 3-day forecast from WeatherAPI.com free tier.

    Uses forecast.json so current conditions, forecast, astronomy/moon phase,
    UV index, and alerts are available from the same API response.
    """
    now = time.time()
    if "weather" in cache:
        cached_data, cached_time = cache["weather"]
        if now - cached_time < 600:  # 10 min cache
            return cached_data

    if not WEATHER_API_KEY:
        return {"error": "Weather API key not configured"}

    try:
        url = "https://api.weatherapi.com/v1/forecast.json"
        params = {
            "key": WEATHER_API_KEY,
            "q": WEATHER_LOCATION,
            "days": 3,
            "aqi": "no",
            "alerts": "yes",
        }
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        forecast_days = data.get("forecast", {}).get("forecastday", [])
        today_forecast = forecast_days[0] if forecast_days else {}
        moon_phase = today_forecast.get("astro", {}).get("moon_phase", "")

        current = data["current"]
        current_condition = current["condition"]
        current_code = current_condition.get("code")
        current_is_day = bool(current.get("is_day", 1))
        current_uv = current.get("uv")

        # ── Current conditions ────────────────────────────────────────────
        weather_info = {
            "temperature": round(current["temp_c"], 1),
            "condition": current_condition.get("text", ""),
            "conditionCode": current_code,
            "isDay": current_is_day,
            "uv": current_uv,
            "moonPhase": moon_phase,
            "icon": resolve_weather_icon(
                current_code,
                is_day=current_is_day,
                moon_phase=moon_phase,
                uv_value=current_uv,
            ),
            "humidity": current["humidity"],
            "windSpeed": current["wind_kph"],
            "city": data["location"]["name"],
            "alerts": normalize_weather_alerts(data, WEATHER_LOCATION),
        }

        # ── Hourly forecast: next 5 whole hours from now ──────────────────
        current_hour = int(time.strftime("%H"))  # local server hour 0-23
        hourly_slots = []
        today_str = forecast_days[0]["date"] if forecast_days else ""

        for day_fc in forecast_days:
            day_moon_phase = day_fc.get("astro", {}).get("moon_phase") or moon_phase
            for hour_fc in day_fc.get("hour", []):
                slot_hour = int(hour_fc["time"].split(" ")[1].split(":")[0])
                slot_date = hour_fc["time"].split(" ")[0]

                if slot_date == today_str and slot_hour <= current_hour:
                    continue

                condition = hour_fc["condition"]
                condition_code = condition.get("code")
                is_day = bool(hour_fc.get("is_day", 1))

                hourly_slots.append({
                    "time": hour_fc["time"].split(" ")[1][:5],
                    "icon": resolve_weather_icon(
                        condition_code,
                        is_day=is_day,
                        moon_phase=day_moon_phase,
                        uv_value=hour_fc.get("uv"),
                    ),
                    "conditionCode": condition_code,
                    "isDay": is_day,
                    "moonPhase": day_moon_phase,
                    "uv": hour_fc.get("uv"),
                    "temp": f"{round(hour_fc['temp_c'])}°C",
                    "condition": condition.get("text", ""),
                })

                if len(hourly_slots) == 5:
                    break

            if len(hourly_slots) == 5:
                break

        # ── Daily forecast: today + next 2 days (3 days free plan max) ────
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        daily_slots = []

        for day_fc in forecast_days:
            import datetime
            date_obj = datetime.date.fromisoformat(day_fc["date"])
            label = "Today" if date_obj == datetime.date.today() else day_names[date_obj.weekday()]
            day_data = day_fc["day"]
            condition = day_data["condition"]
            condition_code = condition.get("code")
            uv_value = day_data.get("uv")
            day_moon_phase = day_fc.get("astro", {}).get("moon_phase", "")

            daily_slots.append({
                "label": label,
                "icon": resolve_weather_icon(
                    condition_code,
                    is_day=True,
                    moon_phase=day_moon_phase,
                    uv_value=uv_value,
                ),
                "conditionCode": condition_code,
                "isDay": True,
                "moonPhase": day_moon_phase,
                "uv": uv_value,
                "high": f"{round(day_data['maxtemp_c'])}°C",
                "low": f"{round(day_data['mintemp_c'])}°C",
                "condition": condition.get("text", ""),
            })

        weather_info["forecast"] = {
            "hourly": hourly_slots,
            "daily": daily_slots,
        }

        cache["weather"] = (weather_info, now)
        return weather_info

    except requests.exceptions.RequestException as e:
        if "weather" in cache:
            return cache["weather"][0]
        return {"error": f"Weather request failed: {e}"}
    except Exception as e:
        return {"error": f"Unexpected error: {e}"}


# =============================================================================
# Utility helpers
# =============================================================================
def get_local_ip():
    """Detect the current outbound local IP address, falling back to the AP gateway."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "192.168.4.1"

# =============================================================================
# Flask routes: frontend, assets, data APIs, system status, and screen control
# =============================================================================
@app.route("/")
def home():
    """Render the main photo-frame frontend."""
    return render_template("kiosk_display.html")

@app.route("/assets/<path:filename>")
def serve_assets(filename):
    """Serve static assets used by the frontend."""
    return send_from_directory(ASSETS_DIR, filename)

@app.route("/userdata/<path:filename>")
def serve_userdata(filename):
    """Serve persistent user data used by the frontend."""
    return send_from_directory(USERDATA_DIR, filename)

@app.route("/config.json")
def serve_config():
    """Serve the current config.json file to the frontend."""
    return send_from_directory(".", "config.json")


@app.route("/spotify.json")
def spotify_status():
    """Return current playback metadata and liked-state information."""
    if sp is None:
        return jsonify({"isPlaying": False, "spotifyConfigured": False})

    data = safe_spotify_call("playback", sp.current_playback)
    if not data or not data.get("item"):
        return jsonify({"isPlaying": False, "spotifyConfigured": True})

    track = data["item"]["name"]
    artist = ", ".join(a["name"] for a in data["item"]["artists"])
    albumArt = data["item"]["album"]["images"][0]["url"] if data["item"]["album"]["images"] else None
    isPlaying = data.get("is_playing", False)
    progress = data.get("progress_ms", 0)
    duration = data["item"].get("duration_ms", 0)
    trackId = data["item"]["id"]

    liked = False
    liked_result = safe_spotify_call("liked", sp.current_user_saved_tracks_contains, [trackId])
    if liked_result:
        liked = liked_result[0]

    return jsonify({
        "track": track,
        "artist": artist,
        "albumArt": albumArt,
        "isPlaying": isPlaying,
        "progress": progress,
        "duration": duration,
        "liked": liked,
        "trackId": trackId
    })

@app.route("/weather.json")
def weather_status():
    """Return current weather information or an error response."""
    weather_data = get_weather_data()
    if not weather_data:
        return jsonify({"error": "Unable to fetch weather data"}), 503
    return jsonify(weather_data)

@app.route("/config_portal_pin.json")
def config_portal_pin_json():
    """Expose the active short-lived configuration PIN to the local display UI."""
    try:
        with open(CONFIG_PORTAL_PIN_FILE, "r", encoding="utf-8") as f:
            record = json.load(f)
    except FileNotFoundError:
        return jsonify({"pin": None, "active": False})
    except Exception:
        return jsonify({"pin": None, "active": False}), 500

    now = time.time()
    expires_at = float(record.get("expires_at") or 0)
    pin = str(record.get("pin") or "").strip()

    if not pin or not expires_at or now >= expires_at:
        try:
            os.remove(CONFIG_PORTAL_PIN_FILE)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"⚠️ Could not remove expired config portal PIN: {e}")
        return jsonify({"pin": None, "active": False})

    return jsonify({
        "pin": pin,
        "active": True,
        "expires_at": expires_at,
        "seconds_remaining": max(0, int(expires_at - now)),
    })


@app.route("/status.json")
def system_status():
    """Return detected Wi-Fi/AP mode, current IP address, and service timestamp."""
    try:
        result = subprocess.run(["ip", "addr", "show", "wlan0"], capture_output=True, text=True)
        output = result.stdout
        ip = None

        for line in output.splitlines():
            if line.strip().startswith("inet "):
                ip = line.split()[1].split("/")[0]
                break

        if ip == "192.168.4.1":
            mode = "ap"
        elif ip:
            mode = "client"
        else:
            mode = "unknown"

    except Exception as e:
        print(f"Error determining mode: {e}")
        mode = "unknown"
        ip = None

    return jsonify({"mode": mode, "ip": ip, "uptime": time.time()})

@app.route("/health")
def health_check():
    """Return a basic health-check response."""
    return jsonify({"status": "ok", "timestamp": time.time()})

@app.route("/get_ip")
def get_ip():
    """Return the detected local IP address as JSON."""
    return jsonify({"ip": get_local_ip()})

@app.route("/versions")
def versions():
    """Return component version information as JSON."""
    return jsonify(VERSION_INFO)


@app.route("/update_status.json")
def update_status_json():
    """Return read-only software update state for the display UI."""
    return jsonify(load_update_state())

@app.route("/config/stream")
def config_stream():
    """Open an SSE stream that notifies clients when config or photo metadata changes."""
    CONFIG_FILES = [CONFIG_FILE, PHOTO_JSON]

    def event_stream():
        """Yield SSE heartbeat and reload messages when watched files change."""
        mtimes = {f: os.path.getmtime(f) if os.path.exists(f) else 0 for f in CONFIG_FILES}
        yield "data: ready\n\n"
        while True:
            time.sleep(1)
            changed = False
            for f in CONFIG_FILES:
                try:
                    mtime = os.path.getmtime(f)
                    if mtime != mtimes[f]:
                        mtimes[f] = mtime
                        changed = True
                        print(f"🔄 {f} changed — notifying clients")
                except FileNotFoundError:
                    continue
            if changed:
                yield "data: reload\n\n"
            else:
                yield ": heartbeat\n\n"

    print("📡 SSE client connected to /config/stream")
    return Response(event_stream(), mimetype="text/event-stream")

@app.route("/screen/on", methods=["POST"])
def screen_on():
    """Set the display GPIO pin high."""
    GPIO.output(SCREEN_PIN, GPIO.HIGH)
    return jsonify({"status": "on"})

@app.route("/screen/off", methods=["POST"])
def screen_off():
    """Set the display GPIO pin low."""
    GPIO.output(SCREEN_PIN, GPIO.LOW)
    return jsonify({"status": "off"})

if __name__ == "__main__":
    if sp is None:
        print("⚠️  Spotify credentials missing or invalid — Spotify endpoint will return disconnected state.")
    else:
        print("✅ Spotify credentials loaded.")

    if not WEATHER_API_KEY:
        print("⚠️  WeatherAPI key not found — weather data unavailable.")
    else:
        print(f"🌤️  Weather configured for: {WEATHER_LOCATION}")

    app.run(host="127.0.0.1", port=5001, debug=False)
