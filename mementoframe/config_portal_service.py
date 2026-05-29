#!/usr/bin/env python3
# MementoFrame - Raspberry Pi Smart Photo Frame
# Copyright (c) 2026 João Fernandes
#
# This work is licensed under the Creative Commons Attribution-NonCommercial
# 4.0 International License. To view a copy of this license, visit:
# http://creativecommons.org/licenses/by-nc/4.0/

"""
app.py

Brief:
    Flask configuration portal for MementoFrame.

Endpoints:
    GET|POST /                         - Dashboard and Wi-Fi connection form.
    GET      /assets/<filename>        - Serve static project assets.
    GET      /userdata/<filename>      - Serve persistent user data files.
    GET      /resources/Photos/full/<filename>   - Serve full-size uploaded photos.
    GET      /resources/Photos/thumbs/<filename> - Serve generated photo thumbnails.
    POST     /upload                   - Queue uploaded photos and process WebP images in background.
    GET      /upload/status            - Return current background photo-processing state.
    POST     /delete_selected_photos   - Delete selected uploaded photos.
    POST     /test_brightness          - Start a background brightness test.
    POST     /save_clock_settings      - Save dashboard clock settings.
    POST     /save_display_settings    - Save brightness/display settings.
    POST     /save_auto_power          - Save automatic screen power schedule.
    POST     /save_weather_api         - Save WeatherAPI key and region.
    GET      /versions                 - Return installed component versions.
    GET      /spotify/connect          - Begin Spotify OAuth authorization.
    POST     /spotify/manual           - Complete Spotify OAuth using pasted callback URL.
    POST     /spotify/disconnect       - Remove cached Spotify credentials.
    GET      /config-portal-pin        - Show PIN unlock page for AP configuration mode.
    POST     /config-portal-pin        - Validate submitted configuration portal PIN.

Flow chart:

    ┌────────────────────────┐
    │ Request enters Flask   │
    └──────┬─────────────────┘
           │
           ├── PIN locked ─────► Wake screen → create/read PIN → show PIN page
           │
           └── PIN unlocked ───► Dashboard/routes manage Wi-Fi, photos, settings,
                                  Spotify auth, brightness, and config persistence
"""
from flask import Flask, request, render_template, redirect, url_for, jsonify, send_from_directory, session
import subprocess, os, json, socket, threading, time, uuid, shlex, secrets, sys
from pathlib import Path
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from PIL import Image, ImageOps
import RPi.GPIO as GPIO
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from version_info import GLOBAL_APP_VERSION, VERSION_INFO

# =============================================================================
# Environment and Flask initialization
# =============================================================================
ENV_FILE = Path(".env")


def read_env_values():
    """Read simple KEY=value pairs from .env without exposing unrelated parsing complexity."""
    values = {}
    if not ENV_FILE.exists():
        return values

    try:
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    except Exception as e:
        print(f"⚠️ Could not read .env: {e}")

    return values


def write_env_values(updates):
    """Update or append selected .env values while preserving unrelated lines."""
    existing_lines = []
    seen = set()

    if ENV_FILE.exists():
        existing_lines = ENV_FILE.read_text(encoding="utf-8").splitlines()

    new_lines = []
    for raw in existing_lines:
        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
            new_lines.append(raw)
            continue

        key, _value = line.split("=", 1)
        key = key.strip()

        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            new_lines.append(raw)

    for key, value in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={value}")

    ENV_FILE.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
    try:
        ENV_FILE.chmod(0o600)
    except Exception:
        pass

    for key, value in updates.items():
        os.environ[key] = value


def spotify_credentials_configured():
    """Return True when Spotify app credentials are configured."""
    return bool(os.getenv("SPOTIFY_CLIENT_ID") and os.getenv("SPOTIFY_CLIENT_SECRET"))


def restart_runtime_services_after_env_change():
    """Restart services that need .env values reloaded.

    Use separate sudo calls because sudoers command matching is argument-specific.
    The config service restart is delayed so this HTTP response can finish first.
    """
    subprocess.Popen(
        ["sudo", "systemctl", "restart", "mementoframe-display.service"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.Popen(
        ["sh", "-c", "sleep 2; sudo systemctl restart mementoframe-config.service"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def ensure_flask_secret_key():
    """Return a stable Flask session secret, creating and saving one when missing."""
    key = os.getenv("FLASK_SECRET_KEY")
    if key:
        return key

    key = secrets.token_urlsafe(32)

    with open(ENV_FILE, "a", encoding="utf-8") as f:
        f.write(f"\nFLASK_SECRET_KEY={key}\n")

    os.environ["FLASK_SECRET_KEY"] = key
    print("🔐 Generated FLASK_SECRET_KEY and saved it to .env")
    return key


load_dotenv()
app = Flask(__name__)
app.secret_key = ensure_flask_secret_key()

# =============================================================================
# Filesystem layout
# =============================================================================
CONFIG_FILE = "config.json"

USERDATA_DIR = "resources/userdata"
PHOTO_DIR = os.path.join(USERDATA_DIR, "Photos")
FULL_DIR = os.path.join(PHOTO_DIR, "full")
THUMB_DIR = os.path.join(PHOTO_DIR, "thumbs")
PHOTO_TMP_DIR = os.path.join(PHOTO_DIR, "tmp_uploads")
PHOTO_JSON = os.path.join(PHOTO_DIR, "photos.json")
PHOTO_JS = os.path.join(PHOTO_DIR, "photos.js")
CACHE_DIR = os.path.join(USERDATA_DIR, "cache")
SPOTIFY_CACHE = os.path.join(CACHE_DIR, ".cache_spotify")

ASSETS_DIR = "resources/assets"

for d in [USERDATA_DIR, PHOTO_DIR, FULL_DIR, THUMB_DIR, PHOTO_TMP_DIR, CACHE_DIR, ASSETS_DIR]:
    os.makedirs(d, exist_ok=True)

# =============================================================================
# GPIO display and brightness controls
# =============================================================================
SCREEN_PIN = 26
BRIGHTNESS_DOWN = 21
BRIGHTNESS_UP = 20
PRESS_DURATION = 5.5
STEP_DELAY = 0.5

GPIO.setmode(GPIO.BCM)
GPIO.setup(SCREEN_PIN, GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(BRIGHTNESS_DOWN, GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(BRIGHTNESS_UP, GPIO.OUT, initial=GPIO.HIGH)
gpio_lock = threading.Lock()

# =============================================================================
# Configuration portal PIN gate
# =============================================================================
RUNTIME_DIR = "runtime"
os.makedirs(RUNTIME_DIR, exist_ok=True)

CONFIG_PORTAL_PIN_FILE = os.path.join(RUNTIME_DIR, "config_portal_pin.json")
UPDATE_STATE_FILE = os.path.join(RUNTIME_DIR, "update_state.json")
CONFIG_PORTAL_PIN_LENGTH = 6
CONFIG_PORTAL_PIN_TTL_SECONDS = 10 * 60

CONFIG_PORTAL_PIN_EXEMPT_ENDPOINTS = {
    "config_portal_pin_page",
    "config_portal_pin_submit",
    "static",
    "serve_assets",
    "health_check",
}


def _atomic_write_json(path, data):
    """Write JSON through a temporary file and atomically replace the target path."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def remove_config_portal_pin():
    """Delete the active configuration portal PIN file when it exists."""
    try:
        os.remove(CONFIG_PORTAL_PIN_FILE)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"⚠️ Could not remove config portal PIN: {e}")


def read_config_portal_pin_record():
    """Read and validate the short-lived configuration portal PIN record."""
    try:
        with open(CONFIG_PORTAL_PIN_FILE, "r", encoding="utf-8") as f:
            record = json.load(f)
    except FileNotFoundError:
        return None
    except Exception:
        remove_config_portal_pin()
        return None

    expires_at = float(record.get("expires_at") or 0)
    pin = str(record.get("pin") or "").strip()
    if not pin or not expires_at or time.time() >= expires_at:
        remove_config_portal_pin()
        return None
    return record


def create_config_portal_pin():
    """Create a new numeric PIN record and schedule automatic expiry cleanup."""
    now = time.time()
    pin = "".join(secrets.choice("0123456789") for _ in range(CONFIG_PORTAL_PIN_LENGTH))
    record = {
        "pin": pin,
        "created_at": now,
        "expires_at": now + CONFIG_PORTAL_PIN_TTL_SECONDS,
        "ttl_seconds": CONFIG_PORTAL_PIN_TTL_SECONDS,
    }
    _atomic_write_json(CONFIG_PORTAL_PIN_FILE, record)
    try:
        os.chmod(CONFIG_PORTAL_PIN_FILE, 0o600)
    except Exception:
        pass

    def expire_pin(expected_pin=pin, expected_expires_at=record["expires_at"]):
        """Remove the generated PIN after its TTL when it has not been replaced."""
        time.sleep(CONFIG_PORTAL_PIN_TTL_SECONDS)
        current = read_config_portal_pin_record()
        if current and current.get("pin") == expected_pin and current.get("expires_at") == expected_expires_at:
            remove_config_portal_pin()

    threading.Thread(target=expire_pin, daemon=True).start()
    return record


def get_or_create_config_portal_pin_record():
    """Return the active PIN record, creating one when none is valid."""
    return read_config_portal_pin_record() or create_config_portal_pin()


def config_portal_pin_gate_required():
    """Report whether the current session still needs PIN verification."""
    return session.get("config_unlocked") is not True


def wake_screen():
    """Set the screen GPIO pin high so the user can see the PIN prompt."""
    try:
        GPIO.setup(SCREEN_PIN, GPIO.OUT, initial=GPIO.HIGH)
        GPIO.output(SCREEN_PIN, GPIO.HIGH)
    except Exception as e:
        print(f"⚠️ Could not wake screen: {e}")


@app.before_request
def enforce_config_portal_pin_gate():
    """Redirect locked sessions to the PIN page before protected routes run."""
    if request.endpoint in CONFIG_PORTAL_PIN_EXEMPT_ENDPOINTS:
        return None
    if config_portal_pin_gate_required():
        wake_screen()
        get_or_create_config_portal_pin_record()
        return redirect(url_for("config_portal_pin_page"))
    return None


@app.route("/config-portal-pin", methods=["GET"])
def config_portal_pin_page():
    """Display the PIN entry page and ensure a valid PIN exists."""
    wake_screen()
    get_or_create_config_portal_pin_record()
    return render_template("pin.html", error=None)


@app.route("/config-portal-pin", methods=["POST"])
def config_portal_pin_submit():
    """Validate a submitted PIN and unlock the configuration portal session."""
    record = read_config_portal_pin_record()
    submitted = request.form.get("pin", "").strip()
    if record and submitted == record.get("pin"):
        session["config_unlocked"] = True
        remove_config_portal_pin()
        return redirect(url_for("dashboard"))

    wake_screen()
    get_or_create_config_portal_pin_record()
    return render_template("pin.html", error="Incorrect or expired PIN — try again.")

def clear_config_portal_pin():
    """Remove any stale PIN file during application startup or shutdown cleanup."""
    try:
        os.remove(CONFIG_PORTAL_PIN_FILE)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"⚠️ Could not clear config portal PIN: {e}")


# =============================================================================
# Photo metadata and image helpers
# =============================================================================
def build_photo_list():
    """Return sorted supported image filenames from the full-size photo directory."""
    exts = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")
    return sorted([f for f in os.listdir(FULL_DIR) if f.lower().endswith(exts)])

def load_photos():
    """Load the photo ordering file, rebuilding it from disk when missing or invalid."""
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
    """Persist the photo list and synchronize the browser-facing JavaScript file."""
    with open(PHOTO_JSON, "w") as f:
        json.dump(photos, f, indent=2)
    sync_photo_js(photos)

def sync_photo_js(photos=None):
    """Write the current photo list as a JavaScript global for the frame UI."""
    if photos is None:
        photos = load_photos()
    js_content = "window.photos = " + json.dumps(photos, indent=2) + ";"
    with open(PHOTO_JS, "w") as f:
        f.write(js_content)


photo_processing_lock = threading.Lock()
photo_processing_status_lock = threading.Lock()
photo_processing_status = {
    "active": False,
    "queued": 0,
    "processed": 0,
    "failed": 0,
    "last_batch_id": None,
    "last_error": None,
    "updated_at": None,
}


def update_photo_processing_status(**updates):
    """Update the in-memory photo-processing status exposed to the config portal."""
    with photo_processing_status_lock:
        photo_processing_status.update(updates)
        photo_processing_status["updated_at"] = time.time()


def get_photo_processing_status():
    """Return a copy of the current background photo-processing status."""
    with photo_processing_status_lock:
        return dict(photo_processing_status)


def unique_temp_upload_path(batch_dir, filename):
    """Return a collision-safe temporary upload path inside one batch directory."""
    name, ext = os.path.splitext(filename)
    counter = 1
    candidate = os.path.join(batch_dir, filename)
    while os.path.exists(candidate):
        candidate = os.path.join(batch_dir, f"{name}_{counter}{ext}")
        counter += 1
    return candidate


def unique_final_photo_name(original_filename, photos):
    """Return a collision-safe final filename for the processed photo."""
    name, ext = os.path.splitext(original_filename)
    if not name:
        name = f"photo_{uuid.uuid4().hex[:8]}"

    counter = 1
    webp_name = f"{name}.webp"
    while webp_name in photos or os.path.exists(os.path.join(FULL_DIR, webp_name)):
        webp_name = f"{name}_{counter}.webp"
        counter += 1
    return webp_name


def unique_fallback_photo_name(original_filename, photos):
    """Return a collision-safe fallback filename when image conversion fails."""
    name, ext = os.path.splitext(original_filename)
    ext = ext or ".bin"
    if not name:
        name = f"photo_{uuid.uuid4().hex[:8]}"

    candidate = f"{name}{ext}"
    counter = 1
    while candidate in photos or os.path.exists(os.path.join(FULL_DIR, candidate)):
        candidate = f"{name}_{counter}{ext}"
        counter += 1
    return candidate


def process_uploaded_photo_batch(batch_id, batch_dir):
    """Convert queued uploads to final WebP photos without blocking the request."""
    processed = 0
    failed = 0

    with photo_processing_lock:
        update_photo_processing_status(
            active=True,
            last_batch_id=batch_id,
            last_error=None,
        )

        try:
            temp_files = [
                os.path.join(batch_dir, name)
                for name in sorted(os.listdir(batch_dir))
                if os.path.isfile(os.path.join(batch_dir, name))
            ]
        except FileNotFoundError:
            update_photo_processing_status(active=False, last_error="Upload batch directory disappeared.")
            return

        photos = load_photos()

        for temp_path in temp_files:
            filename = os.path.basename(temp_path)
            webp_name = unique_final_photo_name(filename, photos)
            full_path = os.path.join(FULL_DIR, webp_name)
            thumb_path = os.path.join(THUMB_DIR, webp_name)

            try:
                with Image.open(temp_path) as img:
                    img = ImageOps.exif_transpose(img).convert("RGB")

                    full_img = img.copy()
                    full_img.thumbnail((1000, 1000))
                    full_img.save(full_path, format="WEBP", quality=100, method=6)

                    thumb = img.copy()
                    thumb.thumbnail((250, 250))
                    thumb.save(thumb_path, format="WEBP", quality=80, method=6)

                os.remove(temp_path)
                photos.append(webp_name)
                processed += 1
                update_photo_processing_status(processed=processed, failed=failed)

            except Exception as e:
                failed += 1
                update_photo_processing_status(processed=processed, failed=failed, last_error=str(e))
                print(f"Error processing queued upload {filename}: {e}")

                try:
                    fallback_name = unique_fallback_photo_name(filename, photos)
                    fallback_full = os.path.join(FULL_DIR, fallback_name)
                    os.replace(temp_path, fallback_full)
                    photos.append(fallback_name)
                except Exception as fallback_error:
                    print(f"Error saving fallback upload {filename}: {fallback_error}")
                    try:
                        os.remove(temp_path)
                    except FileNotFoundError:
                        pass

        save_photos(photos)

        try:
            os.rmdir(batch_dir)
        except OSError:
            pass

        update_photo_processing_status(
            active=False,
            queued=0,
            processed=processed,
            failed=failed,
        )

# =============================================================================
# Network helpers
# =============================================================================
def _run(cmd):
    """Run a subprocess command and return its status, stdout, and stderr."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

def connect_wifi_sudo(ssid, psk, ifname="wlan0", stop_ap=True, timeout=10):
    """Create/update a NetworkManager Wi-Fi profile and attempt to connect to it."""
    try:
        if stop_ap:
            _run(["sudo", "systemctl", "stop", "hostapd"])
            _run(["sudo", "systemctl", "stop", "dnsmasq"])
        _run(["sudo", "nmcli", "connection", "delete", ssid])
        rc, out, err = _run([
            "sudo", "nmcli", "connection", "add",
            "type", "wifi", "ifname", ifname,
            "con-name", ssid, "ssid", ssid, "autoconnect", "no"
        ])
        if rc != 0:
            return False, f"failed to add connection: {err or out}"
        _run(["sudo", "nmcli", "connection", "modify", ssid,
              "802-11-wireless-security.key-mgmt", "wpa-psk"])
        _run(["sudo", "nmcli", "connection", "modify", ssid,
              "802-11-wireless-security.psk", psk])
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
    """Detect the current outbound local IP address, falling back to the AP gateway."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "192.168.4.1"

def get_mode():
    """Infer whether the frame is in AP mode or Wi-Fi mode."""
    try:
        result = subprocess.check_output(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "d"]).decode()
        if "ap" in result and "connected" in result:
            return "ap"
    except Exception:
        pass
    return "wifi"

def scan_networks():
    """Rescan nearby Wi-Fi networks and return unique SSIDs."""
    try:
        subprocess.run(["sudo", "nmcli", "dev", "wifi", "rescan", "ifname", "wlan0"], check=True)
        time.sleep(2)
        result = subprocess.check_output(["nmcli", "-t", "-f", "SSID", "dev", "wifi", "list"]).decode()
        ssids = [line for line in result.splitlines() if line.strip()]
        return list(dict.fromkeys(ssids))
    except subprocess.CalledProcessError:
        return []

# =============================================================================
# Spotify helpers
# =============================================================================
def get_spotify_oauth():
    """Build the Spotify OAuth helper using environment credentials and cache path."""
    if not spotify_credentials_configured():
        return None

    return SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "https://httpbin.org/anything"),
        scope="user-read-playback-state user-read-currently-playing user-library-read",
        cache_path=SPOTIFY_CACHE
    )

def get_spotify_user():
    """Return the connected Spotify user profile when cached credentials are valid."""
    try:
        oauth = get_spotify_oauth()
        if not oauth:
            return None

        token_info = oauth.get_cached_token()
        if not token_info:
            return None

        sp = spotipy.Spotify(auth=token_info["access_token"])
        return sp.current_user()
    except Exception:
        return None

# =============================================================================
# Configuration persistence
# =============================================================================
def load_config():
    """Load frame configuration and merge any missing default keys."""
    default = {
        "clock1": {"label": "Lisbon", "timezone": "Europe/Lisbon"},
        "clock2": {"label": "Shanghai", "timezone": "Asia/Shanghai", "enabled": True},
        "weather_api_key": "",
        "weather_region": "",
        "brightness": 80,
        "auto_power": {"enabled": False, "off_time": "23:00", "on_time": "07:00"},
        "updates": {
            "auto_update": False,
            "repo": os.getenv("MEMENTOFRAME_UPDATE_REPO", ""),
            "channel": "stable",
            "last_checked": None,
            "available_version": None,
            "available": False,
        },
    }
    if not os.path.exists(CONFIG_FILE):
        return default
    try:
        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)
        for key, val in default.items():
            cfg.setdefault(key, val)
            if isinstance(val, dict) and isinstance(cfg.get(key), dict):
                for sub_key, sub_val in val.items():
                    cfg[key].setdefault(sub_key, sub_val)
        return cfg
    except Exception as e:
        print(f"⚠️ Error loading config.json: {e}")
        return default

def save_config(cfg):
    """Persist frame configuration to config.json."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def load_update_state():
    """Read updater runtime state and merge it with config/version defaults."""
    try:
        with open(UPDATE_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        state = {}
    except Exception as e:
        state = {"last_error": f"Unable to read update state: {e}"}

    cfg = load_config()
    updates_cfg = cfg.get("updates", {})
    state.setdefault("installed_version", GLOBAL_APP_VERSION)
    state.setdefault("available", False)
    state.setdefault("pending_restart", False)
    state.setdefault("update_in_progress", False)
    state["auto_update"] = bool(updates_cfg.get("auto_update", False))
    state["repo"] = updates_cfg.get("repo", "")
    state["channel"] = updates_cfg.get("channel", "stable")
    return state


def run_updater(command, background=False):
    """Run updater.py with a controlled command from the config portal."""
    cmd = [sys.executable, "updater.py", command]
    if background:
        # Mark update_in_progress immediately so the display overlay activates
        # before updater.py has had a chance to write the file itself.
        try:
            state = load_update_state()
            state["update_in_progress"] = True
            state["pending_restart"] = False
            _atomic_write_json(UPDATE_STATE_FILE, state)
        except Exception as e:
            print(f"⚠️ Could not pre-set update_in_progress: {e}")
        subprocess.Popen(cmd, cwd=os.getcwd(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"status": "started", "command": command}

    proc = subprocess.run(cmd, cwd=os.getcwd(), capture_output=True, text=True, timeout=90)
    payload = {"status": "ok" if proc.returncode == 0 else "error", "returncode": proc.returncode}
    if proc.stdout.strip():
        try:
            payload["updater"] = json.loads(proc.stdout)
        except Exception:
            payload["stdout"] = proc.stdout.strip()
    if proc.stderr.strip():
        payload["stderr"] = proc.stderr.strip()
    return payload

# =============================================================================
# Brightness controls
# =============================================================================
def press(pin, duration=PRESS_DURATION):
    """Simulate a hardware button press on the selected GPIO pin."""
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)
    GPIO.output(pin, GPIO.LOW)
    time.sleep(duration)
    GPIO.output(pin, GPIO.HIGH)
    GPIO.cleanup(pin)

def set_brightness(level):
    """Reset brightness to minimum and step upward to the requested level."""
    level = max(0, min(100, int(level)))
    press(BRIGHTNESS_DOWN, PRESS_DURATION)
    GPIO.cleanup(BRIGHTNESS_DOWN)
    time.sleep(0.5)
    for _ in range(level):
        press(BRIGHTNESS_UP, 0.5)
        time.sleep(STEP_DELAY - 0.1)



# =============================================================================
# Frame/display quick controls
# =============================================================================
def reload_display_clients():
    """Trigger the display frontend SSE reload by touching watched metadata files."""
    touched = []
    for path in [CONFIG_FILE, PHOTO_JSON]:
        try:
            if os.path.exists(path):
                os.utime(path, None)
                touched.append(path)
        except Exception as e:
            print(f"⚠️ Could not touch {path}: {e}")
    return touched


def restart_frame_services():
    """Restart display-side services without restarting the config portal itself."""
    subprocess.Popen(
        [
            "sh",
            "-c",
            "sleep 1; sudo systemctl restart mementoframe-display.service mementoframe-kiosk.service",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def set_screen_on():
    """Wake the display using the same GPIO line as the display service."""
    GPIO.setup(SCREEN_PIN, GPIO.OUT, initial=GPIO.HIGH)
    GPIO.output(SCREEN_PIN, GPIO.HIGH)

# =============================================================================
# Flask routes: dashboard, assets, photos, settings, versions, and Spotify
# =============================================================================
@app.route("/", methods=["GET", "POST"])
def dashboard():
    """Render the configuration dashboard and handle Wi-Fi connection submissions."""
    mode = get_mode()
    ip = get_local_ip()
    photos = load_photos()
    networks = scan_networks()
    spotify_user = get_spotify_user()
    spotify_msg = request.args.get("msg")
    spotify_env = read_env_values()
    spotify_configured = bool(
        spotify_env.get("SPOTIFY_CLIENT_ID") and spotify_env.get("SPOTIFY_CLIENT_SECRET")
    )
    config = load_config()

    if request.method == "POST" and "ssid" in request.form:
        ssid = request.form["ssid"].strip()
        psk = request.form.get("psk", "").strip()
        success, msg = connect_wifi_sudo(ssid, psk)
        return redirect(url_for("dashboard", msg=msg))

    return render_template(
        "config_portal.html",
        mode=mode,
        ip=ip,
        networks=networks,
        photos=photos,
        spotify_user=spotify_user,
        spotify_msg=spotify_msg,
        spotify_env=spotify_env,
        spotify_configured=spotify_configured,
        update_state=load_update_state(),
        config=config,
    )

@app.route("/assets/<path:filename>")
def serve_assets(filename):
    """Serve read-only static assets from the project assets directory."""
    return send_from_directory(ASSETS_DIR, filename)

@app.route("/userdata/<path:filename>")
def serve_userdata(filename):
    """Serve persistent user data files required by the configuration UI."""
    return send_from_directory(USERDATA_DIR, filename)

@app.route("/resources/Photos/full/<path:filename>")
def serve_full(filename):
    """Serve a full-size uploaded photo file."""
    return send_from_directory(FULL_DIR, filename)

@app.route("/resources/Photos/thumbs/<path:filename>")
def serve_thumb(filename):
    """Serve a generated thumbnail photo file."""
    return send_from_directory(THUMB_DIR, filename)

@app.route("/upload", methods=["POST"])
def upload_photo():
    """Queue uploaded images quickly, then process WebP files in the background."""
    files = request.files.getlist("photos")
    if not files or all(f.filename == "" for f in files):
        return "No file", 400

    batch_id = uuid.uuid4().hex
    batch_dir = os.path.join(PHOTO_TMP_DIR, batch_id)
    os.makedirs(batch_dir, exist_ok=True)

    queued = 0
    for file in files:
        filename = secure_filename(file.filename)
        if not filename:
            continue

        _name, ext = os.path.splitext(filename)
        if ext.lower() not in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}:
            continue

        temp_path = unique_temp_upload_path(batch_dir, filename)
        file.save(temp_path)
        queued += 1

    if queued == 0:
        try:
            os.rmdir(batch_dir)
        except OSError:
            pass
        return "No supported image files", 400

    update_photo_processing_status(
        active=True,
        queued=queued,
        processed=0,
        failed=0,
        last_batch_id=batch_id,
        last_error=None,
    )

    threading.Thread(
        target=process_uploaded_photo_batch,
        args=(batch_id, batch_dir),
        daemon=True,
    ).start()

    return redirect(url_for(
        "dashboard",
        msg=f"{queued} photo(s) uploaded. Processing in the background; the frame will reload when ready."
    ))


@app.route("/upload/status")
def upload_status():
    """Return current background photo-processing status."""
    return jsonify(get_photo_processing_status())


@app.route("/delete_selected_photos", methods=["POST"])
def delete_selected_photos():
    """Remove selected photo files and update the saved photo list."""
    selected = request.form.getlist("selected_photos")
    for name in selected:
        filename = secure_filename(name)
        full_path = os.path.join(FULL_DIR, filename)
        thumb_path = os.path.join(THUMB_DIR, filename)
        if os.path.exists(full_path):
            os.remove(full_path)
        if os.path.exists(thumb_path):
            os.remove(thumb_path)
    photos = [p for p in load_photos() if p not in selected]
    save_photos(photos)
    return redirect(url_for("dashboard"))

@app.route("/test_brightness", methods=["POST"])
def test_brightness():
    """Validate a brightness level and start a non-blocking brightness update."""
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
    """Save label/timezone settings for the dashboard clocks."""
    config = load_config()

    def make_clock(prefix):
        """Build one clock configuration object from submitted form fields."""
        return {
            "label": request.form.get(f"{prefix}_label", prefix.title()),
            "timezone": request.form.get(f"{prefix}_tz", "UTC")
        }

    config["clock1"] = make_clock("clock1")
    config["clock2"] = make_clock("clock2")
    config["clock2"]["enabled"] = "enable_clock2" in request.form

    save_config(config)
    return redirect(url_for("dashboard"))


@app.route("/save_display_settings", methods=["POST"])
def save_display_settings():
    """Save brightness settings and apply them asynchronously."""
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
    """Save automatic display power schedule settings."""
    config = load_config()
    config["auto_power"]["enabled"] = "auto_power_enabled" in request.form
    config["auto_power"]["off_time"] = request.form.get("off_time", "23:00")
    config["auto_power"]["on_time"] = request.form.get("on_time", "07:00")
    save_config(config)
    return redirect(url_for("dashboard"))


@app.route("/save_weather_api", methods=["POST"])
def save_weather_api():
    """Save WeatherAPI credentials and region settings."""
    config = load_config()
    config["weather_api_key"] = request.form.get("weather_api_key", "")
    config["weather_region"] = request.form.get("weather_region", "")
    save_config(config)
    return redirect(url_for("dashboard"))




@app.route("/display/reload", methods=["POST"])
def display_reload():
    """Ask connected display browser clients to reload via the existing SSE watcher."""
    touched = reload_display_clients()
    if not touched:
        return jsonify({"status": "error", "message": "No watched display files could be touched."}), 500
    return jsonify({"status": "ok", "message": "Display reload requested.", "touched": touched})


@app.route("/frame/restart", methods=["POST"])
def frame_restart():
    """Restart display-side frame services. The config portal stays running."""
    try:
        restart_frame_services()
        return jsonify({"status": "ok", "message": "Frame services are restarting."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Could not restart frame services: {e}"}), 500


@app.route("/screen/on", methods=["POST"])
def config_screen_on():
    """Turn/wake the screen on from the config portal."""
    try:
        set_screen_on()
        return jsonify({"status": "ok", "message": "Screen on requested."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Could not turn screen on: {e}"}), 500

@app.route("/health")
def health_check():
    """Return a basic health-check response for post-update validation."""
    return jsonify({"status": "ok", "service": "dashboard", "timestamp": time.time()})


@app.route("/update/status")
def update_status():
    """Return current software update state for the config portal."""
    return jsonify(load_update_state())


@app.route("/update/check", methods=["POST"])
def update_check():
    """Check GitHub releases for an available MementoFrame update."""
    return jsonify(run_updater("check", background=False))


@app.route("/update/install", methods=["POST"])
def update_install():
    """Start a software update. updater.py handles the reboot when complete."""
    return jsonify(run_updater("update", background=True))


@app.route("/save_update_settings", methods=["POST"])
def save_update_settings():
    """Save software-update preferences from the configuration dashboard."""
    config = load_config()
    updates = config.setdefault("updates", {})
    updates["auto_update"] = "auto_update" in request.form
    updates["repo"] = request.form.get("update_repo", updates.get("repo", "")).strip()
    updates["channel"] = request.form.get("update_channel", updates.get("channel", "stable")).strip() or "stable"
    save_config(config)
    return redirect(url_for("dashboard", msg="Update settings saved."))

@app.route("/versions")
def versions():
    """Return component version information as JSON."""
    return jsonify(VERSION_INFO)

@app.route("/save_spotify_settings", methods=["POST"])
def save_spotify_settings():
    """Save Spotify app credentials to .env and restart services so they reload."""
    client_id = request.form.get("spotify_client_id", "").strip()
    client_secret = request.form.get("spotify_client_secret", "").strip()
    redirect_uri = request.form.get("spotify_redirect_uri", "").strip() or "https://httpbin.org/anything"

    write_env_values({
        "SPOTIFY_CLIENT_ID": client_id,
        "SPOTIFY_CLIENT_SECRET": client_secret,
        "SPOTIFY_REDIRECT_URI": redirect_uri,
    })

    restart_runtime_services_after_env_change()

    return redirect(url_for(
        "dashboard",
        msg="Spotify app settings saved. Services are restarting; refresh the page in a few seconds."
    ))


@app.route("/spotify/connect")
def spotify_connect():
    """Redirect the user to Spotify authorization."""
    oauth = get_spotify_oauth()
    if not oauth:
        return redirect(url_for("dashboard", msg="Spotify Client ID and Client Secret must be saved first."))
    return redirect(oauth.get_authorize_url())


@app.route("/spotify/manual", methods=["POST"])
def spotify_manual():
    """Extract the Spotify callback code from a pasted URL and cache the access token."""
    if not spotify_credentials_configured():
        return redirect(url_for("dashboard", msg="Spotify Client ID and Client Secret must be saved first."))

    pasted_url = request.form.get("spotify_url")
    if not pasted_url:
        return redirect(url_for("dashboard", msg="No URL provided"))

    from urllib.parse import urlparse, parse_qs
    try:
        query = urlparse(pasted_url).query
        code = parse_qs(query).get("code", [None])[0]
    except Exception:
        code = None

    if not code:
        return redirect(url_for("dashboard", msg="Invalid URL – code not found"))

    try:
        oauth = get_spotify_oauth()
        if not oauth:
            return redirect(url_for("dashboard", msg="Spotify Client ID and Client Secret must be saved first."))

        oauth.get_access_token(code)
        user = get_spotify_user()
        if user:
            return redirect(url_for("dashboard", msg=f"Connected as {user.get('display_name', user.get('id'))}"))
        return redirect(url_for("dashboard", msg="Spotify connected."))
    except Exception as e:
        return redirect(url_for("dashboard", msg=f"Spotify error: {e}"))


@app.route("/spotify/disconnect", methods=["POST"])
def spotify_disconnect():
    """Delete cached Spotify credentials and return to the dashboard."""
    if os.path.exists(SPOTIFY_CACHE):
        os.remove(SPOTIFY_CACHE)
    return redirect(url_for("dashboard", msg="Spotify disconnected."))


if __name__ == "__main__":
    clear_config_portal_pin()
    photos = load_photos()
    sync_photo_js(photos)
    app.run(host="0.0.0.0", port=5000)