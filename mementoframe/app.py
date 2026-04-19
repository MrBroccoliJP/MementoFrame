# MementoFrame - Raspberry Pi Smart Photo Frame
# Copyright (c) 2026 João Fernandes
#
# This work is licensed under the Creative Commons Attribution-NonCommercial
# 4.0 International License. To view a copy of this license, visit:
# http://creativecommons.org/licenses/by-nc/4.0/

"""
app.py — Admin Dashboard & Configuration Backend (port 5000)

Serves the admin/configuration web interface (backend.html) and handles
all user-initiated actions: photo management, Wi-Fi configuration,
display settings, Spotify OAuth, and system settings. This service runs
alongside api_service.py (port 5001) on the Pi.

Responsibilities:
  - Serve the admin dashboard (backend.html) and static assets
  - Upload, process (resize → WebP), and delete photos
  - Maintain the photo index (photos.json + photos.js)
  - Save and load all user configuration (config.json)
  - Connect to Wi-Fi networks via NetworkManager (nmcli)
  - Authenticate Spotify via OAuth and cache the token
  - Control screen brightness via GPIO (hardware button simulation)

Endpoints:
  GET/POST /                          → Admin dashboard (backend.html)
  POST     /upload                    → Upload and process photo files
  POST     /delete_selected_photos    → Delete selected photos
  POST     /save_clock_settings       → Save clock timezone/label config
  POST     /save_display_settings     → Save brightness and apply via GPIO
  POST     /save_auto_power           → Save auto on/off schedule
  POST     /save_weather_api          → Save WeatherAPI key and region
  POST     /test_brightness           → Test brightness level via GPIO
  GET      /spotify/connect           → Redirect to Spotify OAuth
  POST     /spotify/manual            → Exchange OAuth code via pasted URL
  POST     /spotify/disconnect        → Remove cached Spotify token
  GET      /assets/<file>             → Static assets
  GET      /userdata/<file>           → User data files
  GET      /resources/Photos/full/<f> → Full-size photo files
  GET      /resources/Photos/thumbs/<f> → Thumbnail photo files

Dependencies:
  - Flask, Werkzeug
  - Pillow          (image processing: resize, EXIF, WebP conversion)
  - spotipy         (Spotify OAuth token exchange)
  - python-dotenv   (loads .env credentials)
  - RPi.GPIO        (brightness control via hardware GPIO pins)
  - NetworkManager  (nmcli, for Wi-Fi management)
"""

from flask import Flask, request, render_template, redirect, url_for, jsonify, send_from_directory
import subprocess, os, json, socket, threading, time, uuid, shlex
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from PIL import Image, ImageOps
import RPi.GPIO as GPIO
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from version_info import VERSIONS

# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

load_dotenv()          # Load SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET from .env
app = Flask(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CONFIG_FILE = "config.json"

# User data — persistent across firmware updates; never overwrite these
USERDATA_DIR  = "resources/userdata"
PHOTO_DIR     = os.path.join(USERDATA_DIR, "Photos")
FULL_DIR      = os.path.join(PHOTO_DIR, "full")       # Full-size WebP images (max 1000px)
THUMB_DIR     = os.path.join(PHOTO_DIR, "thumbs")     # Thumbnail WebP images (max 250px)
PHOTO_JSON    = os.path.join(PHOTO_DIR, "photos.json") # Ordered list of photo filenames
PHOTO_JS      = os.path.join(PHOTO_DIR, "photos.js")  # Same list as a JS global (window.photos)
CACHE_DIR     = os.path.join(USERDATA_DIR, "cache")
SPOTIFY_CACHE = os.path.join(CACHE_DIR, ".cache_spotify")  # Spotipy OAuth token cache

# Static assets — safe to overwrite during firmware updates
ASSETS_DIR = "resources/assets"

# Create all directories on first run if they don't already exist
for d in [USERDATA_DIR, PHOTO_DIR, FULL_DIR, THUMB_DIR, CACHE_DIR, ASSETS_DIR]:
    os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------------------
# Hardware — Brightness control
# ---------------------------------------------------------------------------

# The display brightness is controlled by simulating button presses on the
# monitor's physical buttons via GPIO. Pin 21 is wired to brightness-down,
# pin 20 to brightness-up.
BRIGHTNESS_DOWN = 21
BRIGHTNESS_UP   = 20
PRESS_DURATION  = 5.5   # Seconds to hold the down button to reach minimum brightness
STEP_DELAY      = 0.5   # Seconds between each brightness-up press

GPIO.setmode(GPIO.BCM)
GPIO.setup(BRIGHTNESS_DOWN, GPIO.OUT, initial=GPIO.HIGH)  # HIGH = button released
GPIO.setup(BRIGHTNESS_UP,   GPIO.OUT, initial=GPIO.HIGH)
gpio_lock = threading.Lock()  # Prevents concurrent GPIO access from multiple threads


# ---------------------------------------------------------------------------
# Photo helpers
# ---------------------------------------------------------------------------

def build_photo_list():
    """
    Scan FULL_DIR and return a sorted list of all image filenames.

    Used as a fallback when photos.json is missing or empty. Only returns
    filenames, not full paths, as photos.json stores names relative to FULL_DIR.

    Returns:
        list[str]: Sorted list of image filenames (e.g. ["photo1.webp", ...]).
    """
    exts = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")
    return sorted([f for f in os.listdir(FULL_DIR) if f.lower().endswith(exts)])


def load_photos():
    """
    Load the ordered photo list from photos.json.

    Falls back to build_photo_list() if photos.json does not exist, is empty,
    or cannot be parsed. Saves the fallback list back to disk to keep state
    consistent.

    Returns:
        list[str]: Ordered list of photo filenames.
    """
    if not os.path.exists(PHOTO_JSON):
        photos = build_photo_list()
        save_photos(photos)
        return photos
    try:
        with open(PHOTO_JSON) as f:
            photos = json.load(f)
        if not photos:
            photos = build_photo_list()
            save_photos(photos)
        return photos
    except Exception:
        photos = build_photo_list()
        save_photos(photos)
        return photos


def save_photos(photos):
    """
    Persist the photo list to photos.json and sync photos.js.

    Always calls sync_photo_js after writing so both files stay in sync.
    The frontend can load either — photos.js as a script tag, or
    photos.json via fetch.

    Args:
        photos (list[str]): Ordered list of photo filenames to save.
    """
    with open(PHOTO_JSON, "w") as f:
        json.dump(photos, f, indent=2)
    sync_photo_js(photos)


def sync_photo_js(photos=None):
    """
    Write the photo list to photos.js as a JavaScript global variable.

    Generates: window.photos = [ ... ];
    This allows the frontend to include photos.js as a <script> tag and
    access the photo list without an async fetch, which is useful during
    initial page load.

    Args:
        photos (list[str] | None): Photo list to write. If None, loads
                                   from photos.json first.
    """
    if photos is None:
        photos = load_photos()
    js_content = "window.photos = " + json.dumps(photos, indent=2) + ";"
    with open(PHOTO_JS, "w") as f:
        f.write(js_content)


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

def _run(cmd):
    """
    Run a shell command and return (returncode, stdout, stderr).

    Used for nmcli calls where the return code and output need to be
    inspected, unlike the fire-and-forget run() in ap_mode_manager.py.

    Args:
        cmd (list[str]): Command and arguments.

    Returns:
        tuple: (returncode: int, stdout: str, stderr: str)
    """
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def connect_wifi_sudo(ssid, psk, ifname="wlan0", stop_ap=True, timeout=10):
    """
    Connect to a Wi-Fi network using NetworkManager via nmcli.

    Steps:
      1. Optionally stops hostapd/dnsmasq if AP mode is running.
      2. Deletes any existing NM connection with the same SSID name.
      3. Creates a new WPA-PSK connection profile and sets autoconnect.
      4. Brings the connection up and waits up to `timeout` seconds.
      5. Checks NM device state to confirm connection success.

    Args:
        ssid    (str):  Target network SSID.
        psk     (str):  WPA passphrase.
        ifname  (str):  Wireless interface name (default "wlan0").
        stop_ap (bool): Whether to stop AP services before connecting.
        timeout (int):  Seconds to wait for connection (clamped 1–30).

    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        if stop_ap:
            _run(["sudo", "systemctl", "stop", "hostapd"])
            _run(["sudo", "systemctl", "stop", "dnsmasq"])

        # Remove stale connection profile with same name to avoid conflicts
        _run(["sudo", "nmcli", "connection", "delete", ssid])

        rc, out, err = _run([
            "sudo", "nmcli", "connection", "add",
            "type", "wifi", "ifname", ifname,
            "con-name", ssid, "ssid", ssid, "autoconnect", "no"
        ])
        if rc != 0:
            return False, f"failed to add connection: {err or out}"

        # Apply WPA-PSK security settings
        _run(["sudo", "nmcli", "connection", "modify", ssid,
              "802-11-wireless-security.key-mgmt", "wpa-psk"])
        _run(["sudo", "nmcli", "connection", "modify", ssid,
              "802-11-wireless-security.psk", psk])

        # Enable autoconnect so the Pi reconnects after reboots
        _run(["sudo", "nmcli", "connection", "modify", ssid,
              "connection.autoconnect", "yes"])

        _run(["sudo", "nmcli", "connection", "up", ssid])
        _run(["sudo", "nmcli", "device", "connect", ifname])

        time.sleep(min(max(timeout, 1), 30))

        rc, out, _ = _run(["nmcli", "-t", "-f", "DEVICE,STATE", "device", "status"])
        if f"{ifname}:connected" in out:
            return True, f"Connected to {ssid}"
        return True, f"Connection attempt OK; verify network state"

    except Exception as e:
        return False, f"exception: {e}"


def get_local_ip():
    """
    Return the device's current local IP address.

    Uses a temporary UDP socket to determine the outbound interface IP
    without sending any data. Falls back to 192.168.4.1 (AP gateway) on error.

    Returns:
        str: Local IP address string.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "192.168.4.1"


def get_mode():
    """
    Determine the current network mode via nmcli.

    Checks whether NetworkManager reports any device in AP state.

    Returns:
        str: "ap" if in hotspot mode, "wifi" otherwise.
    """
    try:
        result = subprocess.check_output(
            ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "d"]
        ).decode()
        if "ap" in result and "connected" in result:
            return "ap"
    except Exception:
        pass
    return "wifi"


def scan_networks():
    """
    Scan for available Wi-Fi networks and return a deduplicated SSID list.

    Triggers an active scan (nmcli dev wifi rescan), waits 2 seconds for
    results, then reads the list. Duplicate SSIDs are removed while
    preserving order.

    Returns:
        list[str]: Available SSIDs, or [] if the scan fails.
    """
    try:
        subprocess.run(["nmcli", "dev", "wifi", "rescan"], check=True)
        time.sleep(2)
        result = subprocess.check_output(
            ["nmcli", "-t", "-f", "SSID", "dev", "wifi", "list"]
        ).decode()
        ssids = [line for line in result.splitlines() if line.strip()]
        return list(dict.fromkeys(ssids))  # Remove duplicates, preserve order
    except subprocess.CalledProcessError:
        return []


# ---------------------------------------------------------------------------
# Spotify
# ---------------------------------------------------------------------------

def get_spotify_oauth():
    """
    Build and return a SpotifyOAuth object using credentials from .env.

    A new instance is created each call so it always reflects the current
    environment and uses the correct cache path.

    Returns:
        SpotifyOAuth: Configured OAuth manager.
    """
    return SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri="https://httpbin.org/anything",
        scope="user-read-playback-state user-read-currently-playing user-library-read",
        cache_path=SPOTIFY_CACHE
    )


def get_spotify_user():
    """
    Return the currently authenticated Spotify user, or None if not connected.

    Reads the cached token from SPOTIFY_CACHE. If no valid token exists,
    returns None without triggering any OAuth flow (connection is
    initiated manually via the dashboard).

    Returns:
        dict | None: Spotify user object, or None if unauthenticated.
    """
    try:
        oauth = get_spotify_oauth()
        token_info = oauth.get_cached_token()
        if not token_info:
            return None
        sp = spotipy.Spotify(auth=token_info["access_token"])
        return sp.current_user()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config():
    """
    Load config.json and merge with default values.

    Any key present in `default` but missing from config.json is added
    automatically, so new config fields are backwards-compatible without
    requiring a manual edit.

    Returns:
        dict: Merged configuration dict.
    """
    default = {
        "clock1":      {"label": "Lisbon",   "timezone": "Europe/Lisbon"},
        "clock2":      {"label": "Shanghai", "timezone": "Asia/Shanghai", "enabled": True},
        "weather_api_key": "",
        "weather_region":  "",
        "brightness":  80,
        "auto_power":  {"enabled": False, "off_time": "23:00", "on_time": "07:00"},
    }
    if not os.path.exists(CONFIG_FILE):
        return default
    try:
        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)
        for key, val in default.items():
            cfg.setdefault(key, val)
        return cfg
    except Exception as e:
        print(f"⚠️ Error loading config.json: {e}")
        return default


def save_config(cfg):
    """
    Write the config dict to config.json.

    api_service.py watches this file via SSE and notifies connected
    frontends to reload when it changes.

    Args:
        cfg (dict): Configuration dict to persist.
    """
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# ---------------------------------------------------------------------------
# Brightness control
# ---------------------------------------------------------------------------

def press(pin, duration=PRESS_DURATION):
    """
    Simulate a physical button press by pulsing a GPIO pin LOW then HIGH.

    The monitor interprets a sustained LOW signal as a held button press.
    After the pulse, the pin is cleaned up to release it.

    Args:
        pin      (int):   BCM pin number to pulse.
        duration (float): How long to hold the pin LOW, in seconds.
    """
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)
    GPIO.output(pin, GPIO.LOW)
    time.sleep(duration)
    GPIO.output(pin, GPIO.HIGH)
    GPIO.cleanup(pin)


def set_brightness(level):
    """
    Set the screen brightness by simulating button presses.

    The monitor has no direct brightness register, so brightness is set
    by:
      1. Holding BRIGHTNESS_DOWN for PRESS_DURATION seconds to reach
         the minimum brightness level.
      2. Pressing BRIGHTNESS_UP `level` times (0–100), once per step,
         to reach the target level.

    This function is always run in a background thread (it can take
    several seconds to complete).

    Args:
        level (int): Target brightness level, 0–100.
    """
    level = max(0, min(100, int(level)))

    # Drive brightness to zero first for a known baseline
    press(BRIGHTNESS_DOWN, PRESS_DURATION)
    GPIO.cleanup(BRIGHTNESS_DOWN)
    time.sleep(0.5)

    # Step up to target level
    for _ in range(level):
        press(BRIGHTNESS_UP, 0.5)
        time.sleep(STEP_DELAY - 0.1)


# ---------------------------------------------------------------------------
# Routes — Dashboard
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET", "POST"])
def dashboard():
    """
    Render the admin dashboard (backend.html).

    On GET:  Gathers all state (mode, IP, photos, networks, Spotify user,
             config) and renders the template.
    On POST: Handles the Wi-Fi connect form (ssid + psk fields), calls
             connect_wifi_sudo, and redirects with a status message.

    Template variables:
        mode         (str):        "ap" or "wifi"
        ip           (str):        Current local IP
        networks     (list[str]):  Available SSIDs
        photos       (list[str]):  Ordered photo filenames
        spotify_user (dict|None):  Authenticated Spotify user or None
        spotify_msg  (str|None):   Flash message from Spotify OAuth flow
        config       (dict):       Current configuration
    """
    mode         = get_mode()
    ip           = get_local_ip()
    photos       = load_photos()
    networks     = scan_networks()
    spotify_user = get_spotify_user()
    spotify_msg  = request.args.get("msg")
    config       = load_config()

    if request.method == "POST" and "ssid" in request.form:
        ssid = request.form["ssid"].strip()
        psk  = request.form.get("psk", "").strip()
        success, msg = connect_wifi_sudo(ssid, psk)
        return redirect(url_for("dashboard", msg=msg))

    return render_template(
        "backend.html",
        mode=mode,
        ip=ip,
        networks=networks,
        photos=photos,
        spotify_user=spotify_user,
        spotify_msg=spotify_msg,
        config=config,
    )


# ---------------------------------------------------------------------------
# Routes — Static serving
# ---------------------------------------------------------------------------

@app.route("/assets/<path:filename>")
def serve_assets(filename):
    """Serve static assets (JS, CSS, icons) from resources/assets/."""
    return send_from_directory(ASSETS_DIR, filename)


@app.route("/userdata/<path:filename>")
def serve_userdata(filename):
    """Serve user data files (photos.json, photos.js) from resources/userdata/."""
    return send_from_directory(USERDATA_DIR, filename)


@app.route("/resources/Photos/full/<path:filename>")
def serve_full(filename):
    """Serve full-size photo files from resources/userdata/Photos/full/."""
    return send_from_directory(FULL_DIR, filename)


@app.route("/resources/Photos/thumbs/<path:filename>")
def serve_thumb(filename):
    """Serve thumbnail photo files from resources/userdata/Photos/thumbs/."""
    return send_from_directory(THUMB_DIR, filename)


# ---------------------------------------------------------------------------
# Routes — Photo management
# ---------------------------------------------------------------------------

@app.route("/upload", methods=["POST"])
def upload_photo():
    """
    Receive, process, and store uploaded photo files.

    Processing pipeline for each file:
      1. Sanitise the filename with secure_filename.
      2. Find a collision-safe .webp output name (appends _1, _2, etc.).
      3. Save the raw upload to a temp file in FULL_DIR.
      4. Open with Pillow: apply EXIF rotation, convert to RGB.
      5. Save full-size copy (max 1000×1000, WebP quality 100).
      6. Save thumbnail copy (max 250×250, WebP quality 80).
      7. Remove the temp file and add the webp name to the photo list.
      8. On any PIL error, fall back to saving the original file as-is.

    After all files are processed, saves photos.json and photos.js.
    Redirects back to the dashboard on completion.
    """
    files = request.files.getlist("photos")
    if not files or all(f.filename == "" for f in files):
        return "No file", 400

    photos = load_photos()

    for file in files:
        filename = secure_filename(file.filename)
        if not filename:
            continue

        name, ext = os.path.splitext(filename)
        ext = ext.lower()

        # Find a unique output name to avoid overwriting existing photos
        base_name = name
        counter = 1
        while True:
            webp_name  = f"{base_name}.webp"
            full_path  = os.path.join(FULL_DIR, webp_name)
            thumb_path = os.path.join(THUMB_DIR, webp_name)
            if not os.path.exists(full_path):
                break
            base_name = f"{name}_{counter}"
            counter += 1

        # Write to a temp file first in case PIL processing fails midway
        temp_path = os.path.join(FULL_DIR, f"temp_{uuid.uuid4().hex[:6]}{ext}")
        file.save(temp_path)

        try:
            with Image.open(temp_path) as img:
                # Correct orientation from EXIF metadata (e.g. rotated phone photos)
                img = ImageOps.exif_transpose(img).convert("RGB")

                # Full-size — thumbnail mutates in place, so copy first
                img.thumbnail((1000, 1000))
                img.save(full_path, format="WEBP", quality=100, method=6)

                # Thumbnail from the already-resized full image
                thumb = img.copy()
                thumb.thumbnail((250, 250))
                thumb.save(thumb_path, format="WEBP", quality=80, method=6)

            os.remove(temp_path)
            photos.append(webp_name)

        except Exception as e:
            print(f"Error processing {filename}: {e}")
            # Keep the original file so the upload is not silently lost
            fallback_full = os.path.join(FULL_DIR, filename)
            os.rename(temp_path, fallback_full)
            if filename not in photos:
                photos.append(filename)

    save_photos(photos)
    return redirect(url_for("dashboard"))


@app.route("/delete_selected_photos", methods=["POST"])
def delete_selected_photos():
    """
    Delete the selected photos from disk and remove them from the photo list.

    Expects a form field "selected_photos" containing one or more filenames.
    Deletes the full-size and thumbnail versions of each file, then updates
    photos.json and photos.js. Redirects back to the dashboard.
    """
    selected = request.form.getlist("selected_photos")
    for name in selected:
        filename = secure_filename(name)
        for path in [os.path.join(FULL_DIR, filename),
                     os.path.join(THUMB_DIR, filename)]:
            if os.path.exists(path):
                os.remove(path)
    photos = [p for p in load_photos() if p not in selected]
    save_photos(photos)
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Routes — Settings
# ---------------------------------------------------------------------------

@app.route("/test_brightness", methods=["POST"])
def test_brightness():
    """
    Apply a brightness level immediately for live preview.

    Accepts JSON: {"level": 0–100}. Runs set_brightness in a daemon thread
    so the HTTP response is not held while GPIO pulses are executing.

    Returns:
        JSON: {"status": "started", "level": <int>}
    """
    data = request.get_json() or {}
    level = data.get("level", 80)
    try:
        level = int(level)
        level = max(0, min(100, level))
    except ValueError:
        return jsonify({"error": "Invalid level"}), 400
    threading.Thread(target=set_brightness, args=(level,), daemon=True).start()
    return jsonify({"status": "started", "level": level})


@app.route("/save_clock_settings", methods=["POST"])
def save_clock_settings():
    """
    Save clock label and timezone settings for both clocks to config.json.

    Form fields expected:
        clock1_label, clock1_tz
        clock2_label, clock2_tz
        enable_clock2 (checkbox — presence means enabled)
    """
    config = load_config()

    def make_clock(prefix):
        return {
            "label":    request.form.get(f"{prefix}_label", prefix.title()),
            "timezone": request.form.get(f"{prefix}_tz", "UTC"),
        }

    config["clock1"] = make_clock("clock1")
    config["clock2"] = make_clock("clock2")
    config["clock2"]["enabled"] = "enable_clock2" in request.form

    save_config(config)
    return redirect(url_for("dashboard"))


@app.route("/save_display_settings", methods=["POST"])
def save_display_settings():
    """
    Save the brightness level to config.json and apply it via GPIO.

    Runs set_brightness in a background thread so the response
    is not delayed by GPIO timing.

    Form fields expected:
        brightness (int, 0–100)
    """
    config = load_config()
    try:
        level = int(request.form.get("brightness", 80))
        level = max(0, min(100, level))
    except ValueError:
        level = 80
    threading.Thread(target=set_brightness, args=(level,), daemon=True).start()
    config["brightness"] = level
    save_config(config)
    return redirect(url_for("dashboard"))


@app.route("/save_auto_power", methods=["POST"])
def save_auto_power():
    """
    Save the auto power schedule (on/off times) to config.json.

    Form fields expected:
        auto_power_enabled (checkbox)
        off_time (HH:MM string)
        on_time  (HH:MM string)
    """
    config = load_config()
    config["auto_power"]["enabled"]  = "auto_power_enabled" in request.form
    config["auto_power"]["off_time"] = request.form.get("off_time", "23:00")
    config["auto_power"]["on_time"]  = request.form.get("on_time",  "07:00")
    save_config(config)
    return redirect(url_for("dashboard"))


@app.route("/save_weather_api", methods=["POST"])
def save_weather_api():
    """
    Save the WeatherAPI key and location region to config.json.

    Form fields expected:
        weather_api_key (str)
        weather_region  (str, e.g. "Porto" or "London")
    """
    config = load_config()
    config["weather_api_key"] = request.form.get("weather_api_key", "")
    config["weather_region"]  = request.form.get("weather_region",  "")
    save_config(config)
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Routes — Spotify OAuth
# ---------------------------------------------------------------------------

@app.route("/spotify/connect")
def spotify_connect():
    """
    Redirect the browser to Spotify's OAuth authorisation page.

    Because the Pi has no browser, the redirect_uri points to httpbin.org
    which echoes the full callback URL. The user copies that URL and pastes
    it into /spotify/manual to complete the flow.
    """
    oauth = get_spotify_oauth()
    return redirect(oauth.get_authorize_url())


@app.route("/spotify/manual", methods=["POST"])
def spotify_manual():
    """
    Complete Spotify OAuth by extracting the code from a pasted callback URL.

    The user pastes the full URL they were redirected to (via httpbin.org)
    after authorising the app. This endpoint extracts the `code` query
    parameter and exchanges it for an access token, which is cached in
    SPOTIFY_CACHE for use by api_service.py.

    Form fields expected:
        spotify_url (str): Full callback URL containing the `code` parameter.
    """
    pasted_url = request.form.get("spotify_url")
    if not pasted_url:
        return redirect(url_for("dashboard", msg="No URL provided"))

    from urllib.parse import urlparse, parse_qs
    try:
        query = urlparse(pasted_url).query
        code  = parse_qs(query).get("code", [None])[0]
    except Exception:
        code = None

    if not code:
        return redirect(url_for("dashboard", msg="Invalid URL – code not found"))

    try:
        oauth = get_spotify_oauth()
        oauth.get_access_token(code)
        user = get_spotify_user()
        if user:
            name = user.get("display_name", user.get("id"))
            return redirect(url_for("dashboard", msg=f"Connected as {name}"))
        return redirect(url_for("dashboard", msg="Spotify connected."))
    except Exception as e:
        return redirect(url_for("dashboard", msg=f"Spotify error: {e}"))


@app.route("/spotify/disconnect", methods=["POST"])
def spotify_disconnect():
    """
    Disconnect Spotify by deleting the cached token file.

    After this, get_spotify_user() will return None and api_service.py
    will return isPlaying: false from /spotify.json.
    """
    if os.path.exists(SPOTIFY_CACHE):
        os.remove(SPOTIFY_CACHE)
    return redirect(url_for("dashboard", msg="Spotify disconnected."))

@app.route("/versions")
def versions():
    return jsonify(VERSIONS)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Ensure photos.json and photos.js are in sync before serving
    photos = load_photos()
    sync_photo_js(photos)
    app.run(host="0.0.0.0", port=5000)