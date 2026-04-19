# MementoFrame - Raspberry Pi Smart Photo Frame
# Copyright (c) 2026 João Fernandes
#
# This work is licensed under the Creative Commons Attribution-NonCommercial
# 4.0 International License. To view a copy of this license, visit:
# http://creativecommons.org/licenses/by-nc/4.0/

"""
api_service.py — Display Frontend API Service (port 5001)

Serves the public-facing photo frame display (index.html) and exposes
JSON endpoints that the frontend JavaScript polls to update the UI in
real time. This service runs alongside app.py (port 5000) on the Pi.

Responsibilities:
  - Serve the display frontend (index.html) and static assets
  - Provide live Spotify playback data with caching and rate-limit handling
  - Provide current weather data with 10-minute caching
  - Report system network mode (AP vs client) and IP address
  - Stream config/photo change events to the frontend via SSE
  - Control the physical screen via GPIO (on/off)

Endpoints:
  GET  /                  → Renders index.html (the photo frame display)
  GET  /spotify.json      → Current Spotify playback state
  GET  /weather.json      → Current weather for configured location
  GET  /status.json       → Network mode (ap/client) and IP address
  GET  /health            → Health check (always returns ok)
  GET  /get_ip            → Local IP address
  GET  /config.json       → Serves config.json from project root
  GET  /config/stream     → SSE stream; emits "reload" on file changes
  POST /screen/on         → Turn screen on  (GPIO pin HIGH)
  POST /screen/off        → Turn screen off (GPIO pin LOW)
  GET  /assets/<file>     → Static assets from resources/assets/
  GET  /userdata/<file>   → User data files from resources/userdata/

Dependencies:
  - Flask, flask-cors
  - spotipy         (Spotify Web API client)
  - requests        (WeatherAPI HTTP calls)
  - python-dotenv   (loads .env for credentials)
  - RPi.GPIO        (Raspberry Pi GPIO for screen control)
"""

from flask import Flask, jsonify, render_template, send_from_directory, Response
from flask_cors import CORS
import os, json, time, socket, threading, subprocess, requests
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import RPi.GPIO as GPIO
from version_info import VERSIONS

# ---------------------------------------------------------------------------
# Hardware — Screen control
# ---------------------------------------------------------------------------

SCREEN_PIN = 26                    # BCM pin connected to the screen's power relay
GPIO.setmode(GPIO.BCM)             # Use BCM pin numbering throughout
GPIO.setup(SCREEN_PIN, GPIO.OUT, initial=GPIO.HIGH)  # Screen starts ON

# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

load_dotenv()                      # Load SPOTIFY_CLIENT_ID, SECRET, etc. from .env

app = Flask(__name__, static_folder="static", static_url_path="/static")
CORS(app)                          # Allow cross-origin requests (needed during dev)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CONFIG_FILE  = "config.json"

# Aligned with the project's resources/ directory structure
USERDATA_DIR = "resources/userdata"
ASSETS_DIR   = "resources/assets"
PHOTO_JSON   = os.path.join(USERDATA_DIR, "Photos/photos.json")  # Photo index file
SPOTIFY_CACHE = os.path.join(USERDATA_DIR, "cache/.cache_spotify")  # Spotipy token cache

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config():
    """
    Load config.json from the project root.

    Returns an empty dict if the file does not exist, and logs a warning
    if it exists but cannot be parsed.

    Returns:
        dict: Parsed config, or {} on missing/invalid file.
    """
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config.json: {e}")
        return {}

config = load_config()

# ---------------------------------------------------------------------------
# Spotify — client setup
# ---------------------------------------------------------------------------

# Initialised once at startup using cached credentials from SPOTIFY_CACHE.
# Scopes requested are read-only; no playback control is performed here.
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=os.getenv("SPOTIFY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
    redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "https://httpbin.org/anything"),
    scope="user-read-playback-state user-read-currently-playing user-library-read",
    cache_path=SPOTIFY_CACHE
))

# ---------------------------------------------------------------------------
# Weather — config
# ---------------------------------------------------------------------------

# Read from config.json so the user can change location via the dashboard
# without restarting this service.
WEATHER_API_KEY  = config.get("weather_api_key")
WEATHER_LOCATION = config.get("weather_region", "Porto")

# ---------------------------------------------------------------------------
# Shared cache + rate-limit cooldowns
# ---------------------------------------------------------------------------

cache     = {}   # { endpoint_key: (data, timestamp) }
cooldowns = {}   # { endpoint_key: resume_timestamp }  — set on HTTP 429
MAX_CACHE_AGE = 30  # seconds before a cached Spotify result is considered stale


def safe_spotify_call(endpoint_key, func, *args, **kwargs):
    """
    Execute a Spotify API call with in-memory caching and 429 rate-limit handling.

    If the endpoint is currently in a cooldown period (from a previous 429),
    returns the most recent cached value if it is still within MAX_CACHE_AGE,
    otherwise returns None.

    On a successful call the result is stored in the cache. On a 429 error,
    the cooldown is set to Retry-After seconds and the cache is checked again
    as a fallback. Any other SpotifyException is logged and returns None.

    Args:
        endpoint_key (str): A unique string identifying the endpoint,
                            used as the cache and cooldown key.
        func (callable):    The spotipy method to call (e.g. sp.current_playback).
        *args:              Positional arguments forwarded to func.
        **kwargs:           Keyword arguments forwarded to func.

    Returns:
        Any: The API result, a cached result, or None if unavailable.
    """
    now = time.time()

    # If we are in a cooldown, return cached data if fresh enough
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
            # Respect the Retry-After header; default to 5 seconds
            retry_after = int(e.headers.get("Retry-After", 5))
            cooldowns[endpoint_key] = now + retry_after
            # Serve stale cache rather than returning nothing
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


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

def get_weather_data():
    """
    Fetch current weather from WeatherAPI.com with a 10-minute cache.

    Caches the result in the shared `cache` dict under the key "weather".
    On a network error, returns the last successful result if available,
    otherwise returns an error dict.

    Returns:
        dict: Weather info with keys: temperature, condition, icon,
              humidity, windSpeed, city.
              On error: {"error": "<reason>"}.
    """
    now = time.time()

    # Return cached result if it is less than 10 minutes old
    if "weather" in cache:
        cached_data, cached_time = cache["weather"]
        if now - cached_time < 600:
            return cached_data

    if not WEATHER_API_KEY:
        return {"error": "Weather API key not configured"}

    try:
        url    = "https://api.weatherapi.com/v1/current.json"
        params = {"key": WEATHER_API_KEY, "q": WEATHER_LOCATION, "aqi": "no"}
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        weather_info = {
            "temperature": round(data["current"]["temp_c"], 1),
            "condition":   data["current"]["condition"]["text"],
            "icon":        "https:" + data["current"]["condition"]["icon"],
            "humidity":    data["current"]["humidity"],
            "windSpeed":   data["current"]["wind_kph"],
            "city":        data["location"]["name"],
        }

        cache["weather"] = (weather_info, now)
        return weather_info

    except requests.exceptions.RequestException as e:
        # Network failure — serve stale cache rather than showing an error
        if "weather" in cache:
            return cache["weather"][0]
        return {"error": f"Weather request failed: {e}"}

    except Exception as e:
        return {"error": f"Unexpected error: {e}"}


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def get_local_ip():
    """
    Determine the device's current local IP address.

    Opens a temporary UDP socket towards 8.8.8.8 (no data is sent) to let
    the OS pick the correct outbound interface, then reads the local address.

    Returns:
        str: Local IP address, or "192.168.4.1" if detection fails
             (which is the AP mode gateway address).
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "192.168.4.1"


# ---------------------------------------------------------------------------
# Routes — Static / Template
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    """Render the photo frame display (index.html)."""
    return render_template("index.html")


@app.route("/assets/<path:filename>")
def serve_assets(filename):
    """Serve static assets (fonts, icons, JS, CSS) from resources/assets/."""
    return send_from_directory(ASSETS_DIR, filename)


@app.route("/userdata/<path:filename>")
def serve_userdata(filename):
    """Serve user data files (photos, photos.json, photos.js) from resources/userdata/."""
    return send_from_directory(USERDATA_DIR, filename)


@app.route("/config.json")
def serve_config():
    """Serve config.json directly from the project root."""
    return send_from_directory(".", "config.json")


# ---------------------------------------------------------------------------
# Routes — Spotify
# ---------------------------------------------------------------------------

@app.route("/spotify.json")
def spotify_status():
    """
    Return the current Spotify playback state as JSON.

    Calls the Spotify Web API via safe_spotify_call (cached + rate-limited).
    Also checks whether the current track is saved in the user's library.

    Response keys:
        isPlaying (bool):   Whether a track is currently playing.
        track     (str):    Track name.
        artist    (str):    Comma-separated artist names.
        albumArt  (str):    URL of the album art image (largest available).
        progress  (int):    Playback position in milliseconds.
        duration  (int):    Track duration in milliseconds.
        liked     (bool):   Whether the track is in the user's Liked Songs.
        trackId   (str):    Spotify track ID.

    Returns {"isPlaying": False} if nothing is playing or the call fails.
    """
    data = safe_spotify_call("playback", sp.current_playback)
    if not data or not data.get("item"):
        return jsonify({"isPlaying": False})

    track    = data["item"]["name"]
    artist   = ", ".join(a["name"] for a in data["item"]["artists"])
    albumArt = data["item"]["album"]["images"][0]["url"] if data["item"]["album"]["images"] else None
    isPlaying = data.get("is_playing", False)
    progress  = data.get("progress_ms", 0)
    duration  = data["item"].get("duration_ms", 0)
    trackId   = data["item"]["id"]

    # Check liked status separately; failure defaults to False (non-critical)
    liked = False
    liked_result = safe_spotify_call("liked", sp.current_user_saved_tracks_contains, [trackId])
    if liked_result:
        liked = liked_result[0]

    return jsonify({
        "track":    track,
        "artist":   artist,
        "albumArt": albumArt,
        "isPlaying": isPlaying,
        "progress": progress,
        "duration": duration,
        "liked":    liked,
        "trackId":  trackId,
    })


# ---------------------------------------------------------------------------
# Routes — Weather
# ---------------------------------------------------------------------------

@app.route("/weather.json")
def weather_status():
    """
    Return current weather data as JSON.

    Delegates to get_weather_data() which handles caching and error recovery.
    Returns 503 only if the result is None (should not normally occur).
    """
    weather_data = get_weather_data()
    if not weather_data:
        return jsonify({"error": "Unable to fetch weather data"}), 503
    return jsonify(weather_data)


# ---------------------------------------------------------------------------
# Routes — System
# ---------------------------------------------------------------------------

@app.route("/status.json")
def system_status():
    """
    Return the current network mode and IP address.

    Inspects the wlan0 interface using `ip addr show`. Determines mode by
    checking whether the assigned IP is the AP gateway (192.168.4.1) or a
    regular DHCP address.

    Response keys:
        mode   (str):   "ap", "client", or "unknown"
        ip     (str):   Current IP address, or None if unavailable
        uptime (float): Current Unix timestamp (used by frontend as a
                        lightweight liveness indicator)
    """
    try:
        result = subprocess.run(
            ["ip", "addr", "show", "wlan0"], capture_output=True, text=True
        )
        ip = None
        for line in result.stdout.splitlines():
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
        ip   = None

    return jsonify({"mode": mode, "ip": ip, "uptime": time.time()})


@app.route("/health")
def health_check():
    """
    Lightweight health check endpoint.

    Used by monitoring scripts and the frontend to confirm the service
    is alive. Always returns {"status": "ok"}.
    """
    return jsonify({"status": "ok", "timestamp": time.time()})


@app.route("/get_ip")
def get_ip():
    """Return the device's current local IP address."""
    return jsonify({"ip": get_local_ip()})


# ---------------------------------------------------------------------------
# Routes — Server-Sent Events (SSE)
# ---------------------------------------------------------------------------

@app.route("/config/stream")
def config_stream():
    """
    Stream file-change notifications to the frontend via Server-Sent Events.

    Watches config.json and photos.json for modification time changes.
    Sends "data: reload\\n\\n" whenever either file is updated, prompting
    the frontend to re-fetch its data without a full page refresh.
    Sends a heartbeat comment every second to keep the connection alive
    through proxies and load balancers.

    Events emitted:
        data: ready   — sent once on connection to confirm the stream is live
        data: reload  — sent when any watched file changes
        : heartbeat   — sent every second when no change is detected
    """
    CONFIG_FILES = [CONFIG_FILE, PHOTO_JSON]

    def event_stream():
        # Record current mtimes so we can detect changes
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
                    continue  # File deleted mid-run; ignore until it reappears
            if changed:
                yield "data: reload\n\n"
            else:
                yield ": heartbeat\n\n"

    print("📡 SSE client connected to /config/stream")
    return Response(event_stream(), mimetype="text/event-stream")


# ---------------------------------------------------------------------------
# Routes — Screen control
# ---------------------------------------------------------------------------

from threading import Thread

@app.route("/screen/on", methods=["POST"])
def screen_on():
    """
    Turn the screen on by driving the GPIO pin HIGH.

    Runs in a daemon thread to avoid blocking the Flask response.
    Returns {"status": "on"} immediately.
    """
    def do_on():
        GPIO.output(SCREEN_PIN, GPIO.HIGH)
    Thread(target=do_on, daemon=True).start()
    return jsonify({"status": "on"})


@app.route("/screen/off", methods=["POST"])
def screen_off():
    """
    Turn the screen off by driving the GPIO pin LOW.

    Runs in a daemon thread to avoid blocking the Flask response.
    Returns {"status": "off"} immediately.
    """
    def do_off():
        GPIO.output(SCREEN_PIN, GPIO.LOW)
    Thread(target=do_off, daemon=True).start()
    return jsonify({"status": "off"})

@app.route("/versions")
def versions():
    return jsonify(VERSIONS)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Warn on startup if credentials are missing so issues are caught early
    if not os.getenv("SPOTIFY_CLIENT_ID") or not os.getenv("SPOTIFY_CLIENT_SECRET"):
        print("⚠️  Spotify credentials missing — /spotify.json will return isPlaying: false.")
    else:
        print("✅ Spotify credentials loaded.")

    if not WEATHER_API_KEY:
        print("⚠️  WeatherAPI key not found — /weather.json will return an error.")
    else:
        print(f"🌤️  Weather configured for: {WEATHER_LOCATION}")

    # debug=False in production; the Pi runs this as a systemd service
    app.run(host="0.0.0.0", port=5001, debug=False)