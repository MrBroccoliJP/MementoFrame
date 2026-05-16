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
# Weather data helper
# =============================================================================
def get_weather_data():
    """Fetch current weather, using cached data when fresh or when requests fail."""
    now = time.time()
    if "weather" in cache:
        cached_data, cached_time = cache["weather"]
        if now - cached_time < 600:  # 10 min cache
            return cached_data

    if not WEATHER_API_KEY:
        return {"error": "Weather API key not configured"}

    try:
        url = "https://api.weatherapi.com/v1/current.json"
        params = {"key": WEATHER_API_KEY, "q": WEATHER_LOCATION, "aqi": "no"}
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        weather_info = {
            "temperature": round(data["current"]["temp_c"], 1),
            "condition": data["current"]["condition"]["text"],
            "icon": "https:" + data["current"]["condition"]["icon"],
            "humidity": data["current"]["humidity"],
            "windSpeed": data["current"]["wind_kph"],
            "city": data["location"]["name"],
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
