from flask import Flask, jsonify, render_template, send_from_directory, Response
from flask_cors import CORS
import os, json, time, socket, threading, subprocess, requests
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import RPi.GPIO as GPIO

# ---------- Hardware ----------
SCREEN_PIN = 26
GPIO.setmode(GPIO.BCM)
GPIO.setup(SCREEN_PIN, GPIO.OUT, initial=GPIO.HIGH)

# ---------- Initialization ----------
load_dotenv()
app = Flask(__name__, static_folder="static", static_url_path="/static")
CORS(app)

# ---------- Paths ----------
CONFIG_FILE = "config.json"

# Align with new project structure
USERDATA_DIR = "resources/userdata"
ASSETS_DIR = "resources/assets"
PHOTO_JSON = os.path.join(USERDATA_DIR, "Photos/photos.json")
SPOTIFY_CACHE = os.path.join(USERDATA_DIR, "cache/.cache_spotify")

# ---------- Load config ----------
def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config.json: {e}")
        return {}

config = load_config()

# ---------- Spotify setup ----------
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=os.getenv("SPOTIFY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
    redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "https://httpbin.org/anything"),
    scope="user-read-playback-state user-read-currently-playing user-library-read",
    cache_path=SPOTIFY_CACHE
))

# ---------- Weather config ----------
WEATHER_API_KEY = config.get("weather_api_key")
WEATHER_LOCATION = config.get("weather_region", "Porto")

# ---------- Cache + rate-limiting ----------
cache = {}
cooldowns = {}
MAX_CACHE_AGE = 30  # seconds

def safe_spotify_call(endpoint_key, func, *args, **kwargs):
    """Run a Spotify API call with caching and 429-rate-limit handling."""
    now = time.time()

    # Cooldown (rate-limited)
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

# ---------- Weather API ----------
def get_weather_data():
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

# ---------- Utility ----------
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "192.168.4.1"

# ---------- Routes ----------
@app.route("/")
def home():
    return render_template("index.html")

# Serve restructured resources
@app.route("/assets/<path:filename>")
def serve_assets(filename):
    return send_from_directory(ASSETS_DIR, filename)

@app.route("/userdata/<path:filename>")
def serve_userdata(filename):
    return send_from_directory(USERDATA_DIR, filename)

@app.route("/config.json")
def serve_config():
    return send_from_directory(".", "config.json")


# ---------- Spotify / Weather ----------
@app.route("/spotify.json")
def spotify_status():
    data = safe_spotify_call("playback", sp.current_playback)
    if not data or not data.get("item"):
        return jsonify({"isPlaying": False})

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
    weather_data = get_weather_data()
    if not weather_data:
        return jsonify({"error": "Unable to fetch weather data"}), 503
    return jsonify(weather_data)

# ---------- System ----------
@app.route("/status.json")
def system_status():
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
    return jsonify({"status": "ok", "timestamp": time.time()})

@app.route("/get_ip")
def get_ip():
    return jsonify({"ip": get_local_ip()})

# ---------- Config Stream (SSE) ----------
@app.route("/config/stream")
def config_stream():
    """Stream config and photo changes to frontend."""
    CONFIG_FILES = [CONFIG_FILE, PHOTO_JSON]

    def event_stream():
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

# ---------- Screen Control ----------
from threading import Thread

@app.route("/screen/on", methods=["POST"])
def screen_on():
    def do_on():
        GPIO.output(SCREEN_PIN, GPIO.HIGH)
    Thread(target=do_on, daemon=True).start()
    return jsonify({"status": "on"})

@app.route("/screen/off", methods=["POST"])
def screen_off():
    def do_off():
        GPIO.output(SCREEN_PIN, GPIO.LOW)
    Thread(target=do_off, daemon=True).start()
    return jsonify({"status": "off"})
# ---------- Run ----------
if __name__ == "__main__":
    if not os.getenv("SPOTIFY_CLIENT_ID") or not os.getenv("SPOTIFY_CLIENT_SECRET"):
        print("⚠️  Spotify credentials missing — endpoints disabled.")
    else:
        print("✅ Spotify credentials loaded.")

    if not WEATHER_API_KEY:
        print("⚠️  WeatherAPI key not found — weather data unavailable.")
    else:
        print(f"🌤️  Weather configured for: {WEATHER_LOCATION}")

    app.run(host="0.0.0.0", port=5001, debug=False)
