from flask import Flask, request, render_template, redirect, url_for, jsonify, send_from_directory
import subprocess, os, json, socket, threading, time, uuid, shlex
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from PIL import Image, ImageOps
import RPi.GPIO as GPIO
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# ---------- Initialization ----------
load_dotenv()
app = Flask(__name__)

# ---------- Paths ----------
CONFIG_FILE = "config.json"

# User data (persistent)
USERDATA_DIR = "resources/userdata"
PHOTO_DIR = os.path.join(USERDATA_DIR, "Photos")
FULL_DIR = os.path.join(PHOTO_DIR, "full")
THUMB_DIR = os.path.join(PHOTO_DIR, "thumbs")
PHOTO_JSON = os.path.join(PHOTO_DIR, "photos.json")
PHOTO_JS = os.path.join(PHOTO_DIR, "photos.js")
CACHE_DIR = os.path.join(USERDATA_DIR, "cache")
SPOTIFY_CACHE = os.path.join(CACHE_DIR, ".cache_spotify")

# Static assets (safe to overwrite in updates)
ASSETS_DIR = "resources/assets"

# Ensure structure
for d in [USERDATA_DIR, PHOTO_DIR, FULL_DIR, THUMB_DIR, CACHE_DIR, ASSETS_DIR]:
    os.makedirs(d, exist_ok=True)

# ---------- GPIO Setup ----------
BRIGHTNESS_DOWN = 21
BRIGHTNESS_UP = 20
PRESS_DURATION = 5.5
STEP_DELAY = 0.5

GPIO.setmode(GPIO.BCM)
GPIO.setup(BRIGHTNESS_DOWN, GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(BRIGHTNESS_UP, GPIO.OUT, initial=GPIO.HIGH)
gpio_lock = threading.Lock()

# ---------- Photo Helpers ----------
def build_photo_list():
    exts = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")
    return sorted([f for f in os.listdir(FULL_DIR) if f.lower().endswith(exts)])

def load_photos():
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
    with open(PHOTO_JSON, "w") as f:
        json.dump(photos, f, indent=2)
    sync_photo_js(photos)

def sync_photo_js(photos=None):
    if photos is None:
        photos = load_photos()
    js_content = "window.photos = " + json.dumps(photos, indent=2) + ";"
    with open(PHOTO_JS, "w") as f:
        f.write(js_content)

# ---------- Wi-Fi helpers ----------
AP_INTERFACE = "wlan0"
AP_CON_NAME  = "MementoAP"
AP_IP        = "192.168.4.1"


def _sh(cmd):
    """Run a shell command and return stdout, or raise on error."""
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()


def _run(cmd):
    """Run a shell command and return (returncode, stdout, stderr)."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _nmcli(*args):
    """Run an nmcli command with sudo."""
    return _run(["sudo", "nmcli"] + list(args))


def get_current_connection():
    """Return the active NetworkManager connection name on wlan0, or None."""
    try:
        out = _sh(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 4 and parts[0] == AP_INTERFACE and parts[1] == "wifi":
                return parts[3] if parts[2] == "connected" else None
    except subprocess.CalledProcessError:
        pass
    return None


def _stop_ap_for_wifi():
    """Stop AP mode and return wlan0 to NetworkManager client mode now.

    This intentionally mirrors ap_mode_manager.py: stop AP services, clear
    the AP IP, hand wlan0 back to NetworkManager, turn Wi-Fi on, and force
    a clean device disconnect before trying the saved client profile.
    """
    if get_current_connection() == AP_CON_NAME:
        print("🔌 Stopping NetworkManager AP profile before connecting…")
        _run(["sudo", "nmcli", "connection", "down", AP_CON_NAME])

    for service in ("dnsmasq", "hostapd"):
        _run(["sudo", "systemctl", "stop", service])

    _run(["sudo", "ip", "addr", "flush", "dev", AP_INTERFACE])
    _run(["sudo", "ip", "link", "set", AP_INTERFACE, "up"])

    # ap_mode_manager.py may have set wlan0 unmanaged while serving the AP.
    _run(["sudo", "nmcli", "device", "set", AP_INTERFACE, "managed", "yes"])
    _run(["sudo", "nmcli", "radio", "wifi", "on"])

    # This is the missing bit compared with the manager's stop_ap(): reset the
    # device state so NM does not wait until the next external reconnect probe.
    _run(["sudo", "nmcli", "device", "disconnect", AP_INTERFACE])

    # Give NetworkManager a moment to re-own wlan0 after AP teardown.
    time.sleep(2)


def get_mode():
    """Return 'ap' if the AP profile/IP is active, otherwise 'wifi'."""
    con = get_current_connection()
    if con == AP_CON_NAME:
        return "ap"
    try:
        out = _sh(["ip", "-4", "addr", "show", AP_INTERFACE])
        if "192.168.4.1/24" in out:
            return "ap"
    except subprocess.CalledProcessError:
        pass
    return "wifi"


def get_local_ip():
    """Return the current IP address of wlan0, falling back to socket detection."""
    try:
        out = _sh(["ip", "-4", "addr", "show", AP_INTERFACE])
        for line in out.splitlines():
            if line.strip().startswith("inet "):
                return line.split()[1].split("/")[0]
    except subprocess.CalledProcessError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return AP_IP


def scan_networks():
    """Trigger a Wi-Fi scan and return visible SSIDs."""
    try:
        _nmcli("device", "wifi", "rescan", "ifname", AP_INTERFACE)
        time.sleep(2)
        out = _sh(["nmcli", "-t", "-f", "SSID", "device", "wifi", "list", "ifname", AP_INTERFACE])
        seen = set()
        networks = []
        for line in out.splitlines():
            ssid = line.strip()
            if ssid and ssid not in seen and ssid != "MementoFrame":
                seen.add(ssid)
                networks.append(ssid)
        return networks
    except subprocess.CalledProcessError:
        return []


def connect_wifi(ssid, psk, timeout=10):
    """Connect to a Wi-Fi network immediately after password submission."""
    ssid = (ssid or "").strip()
    psk  = (psk  or "").strip()

    if not ssid:
        return False, "SSID is required"

    try:
        _stop_ap_for_wifi()

        # Remove stale profile with same name to avoid NM conflicts.
        _run(["sudo", "nmcli", "connection", "delete", ssid])

        rc, out, err = _run([
            "sudo", "nmcli", "connection", "add",
            "type", "wifi", "ifname", AP_INTERFACE,
            "con-name", ssid, "ssid", ssid, "autoconnect", "no",
        ])
        if rc != 0:
            return False, f"Failed to create profile: {err or out}"

        # Open networks should be allowed, but normal WPA networks need the PSK.
        if psk:
            _run(["sudo", "nmcli", "connection", "modify", ssid,
                  "802-11-wireless-security.key-mgmt", "wpa-psk"])
            _run(["sudo", "nmcli", "connection", "modify", ssid,
                  "802-11-wireless-security.psk", psk])

        _run(["sudo", "nmcli", "connection", "modify", ssid,
              "connection.autoconnect", "yes"])

        # Do the manager's reconnect probe immediately, but target the profile
        # we just saved instead of waiting for PROBE_EVERY.
        _run(["sudo", "nmcli", "device", "wifi", "rescan", "ifname", AP_INTERFACE])

        deadline = time.time() + min(max(timeout, 1), 30)
        last_error = ""
        while time.time() < deadline:
            rc, out, err = _run(["sudo", "nmcli", "connection", "up", ssid, "ifname", AP_INTERFACE])
            if rc == 0:
                rc2, state, _ = _run(["nmcli", "-t", "-f", "DEVICE,STATE,CONNECTION", "device", "status"])
                for line in state.splitlines():
                    parts = line.split(":")
                    if len(parts) >= 3 and parts[0] == AP_INTERFACE and parts[1] == "connected" and parts[2] == ssid:
                        return True, f"Connected to {ssid}"
            last_error = err or out or last_error

            # If the profile-up call lost a race with AP teardown, force the
            # generic device reconnect that ap_mode_manager.py uses.
            _run(["sudo", "nmcli", "device", "connect", AP_INTERFACE])
            time.sleep(2)

        return False, f"Saved {ssid}, but immediate connect did not complete: {last_error or 'timed out'}"

    except Exception as e:
        return False, f"Connection error: {e}"

# ---------- Spotify ----------
def get_spotify_oauth():
    return SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri="https://httpbin.org/anything",
        scope="user-read-playback-state user-read-currently-playing user-library-read",
        cache_path=SPOTIFY_CACHE
    )

def get_spotify_user():
    try:
        oauth = get_spotify_oauth()
        token_info = oauth.get_cached_token()
        if not token_info:
            return None
        sp = spotipy.Spotify(auth=token_info["access_token"])
        return sp.current_user()
    except Exception:
        return None

# ---------- Config ----------
def load_config():
    default = {
        "clock1": {"label": "Lisbon", "timezone": "Europe/Lisbon"},
        "clock2": {"label": "Shanghai", "timezone": "Asia/Shanghai", "enabled": True},
        "weather_api_key": "",
        "weather_region": "",
        "brightness": 80,
        "auto_power": {"enabled": False, "off_time": "23:00", "on_time": "07:00"},
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
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

# ---------- Brightness ----------
def press(pin, duration=PRESS_DURATION):
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)
    GPIO.output(pin, GPIO.LOW)
    time.sleep(duration)
    GPIO.output(pin, GPIO.HIGH)
    GPIO.cleanup(pin)

def set_brightness(level):
    level = max(0, min(100, int(level)))
    press(BRIGHTNESS_DOWN, PRESS_DURATION)
    GPIO.cleanup(BRIGHTNESS_DOWN)
    time.sleep(0.5)
    for _ in range(level):
        press(BRIGHTNESS_UP, 0.5)
        time.sleep(STEP_DELAY - 0.1)

# ---------- Routes ----------
@app.route("/", methods=["GET", "POST"])
def dashboard():
    mode = get_mode()
    ip = get_local_ip()
    photos = load_photos()
    networks = scan_networks()
    spotify_user = get_spotify_user()
    spotify_msg = request.args.get("msg")
    config = load_config()

    if request.method == "POST" and "ssid" in request.form:
        ssid = request.form["ssid"].strip()
        psk = request.form.get("psk", "").strip()
        success, msg = connect_wifi(ssid, psk)
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

@app.route("/assets/<path:filename>")
def serve_assets(filename):
    return send_from_directory(ASSETS_DIR, filename)

@app.route("/userdata/<path:filename>")
def serve_userdata(filename):
    return send_from_directory(USERDATA_DIR, filename)

@app.route("/resources/Photos/full/<path:filename>")
def serve_full(filename):
    return send_from_directory(FULL_DIR, filename)

@app.route("/resources/Photos/thumbs/<path:filename>")
def serve_thumb(filename):
    return send_from_directory(THUMB_DIR, filename)

@app.route("/upload", methods=["POST"])
def upload_photo():
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
        base_name = name
        counter = 1
        while True:
            webp_name = f"{base_name}.webp"
            full_path = os.path.join(FULL_DIR, webp_name)
            thumb_path = os.path.join(THUMB_DIR, webp_name)
            if not os.path.exists(full_path):
                break
            base_name = f"{name}_{counter}"
            counter += 1
        temp_path = os.path.join(FULL_DIR, f"temp_{uuid.uuid4().hex[:6]}{ext}")
        file.save(temp_path)
        try:
            with Image.open(temp_path) as img:
                img = ImageOps.exif_transpose(img).convert("RGB")
                img.thumbnail((1000, 1000))
                img.save(full_path, format="WEBP", quality=100, method=6)
                thumb = img.copy()
                thumb.thumbnail((250, 250))
                thumb.save(thumb_path, format="WEBP", quality=80, method=6)
            os.remove(temp_path)
            photos.append(webp_name)
        except Exception as e:
            print(f"Error processing {filename}: {e}")
            fallback_full = os.path.join(FULL_DIR, filename)
            os.rename(temp_path, fallback_full)
            if filename not in photos:
                photos.append(filename)
    save_photos(photos)
    return redirect(url_for("dashboard"))

@app.route("/delete_selected_photos", methods=["POST"])
def delete_selected_photos():
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
    data = request.get_json() or {}
    level = data.get("level", 80)
    try:
        level = int(level)
        level = max(0, min(100, level))
    except ValueError:
        return jsonify({"error": "Invalid level"}), 400
    threading.Thread(target=set_brightness, args=(level,), daemon=True).start()
    return jsonify({"status": "started", "level": level})

# ---------- Clock Settings ----------
@app.route("/save_clock_settings", methods=["POST"])
def save_clock_settings():
    config = load_config()

    def make_clock(prefix):
        return {
            "label": request.form.get(f"{prefix}_label", prefix.title()),
            "timezone": request.form.get(f"{prefix}_tz", "UTC")
        }

    config["clock1"] = make_clock("clock1")
    config["clock2"] = make_clock("clock2")
    config["clock2"]["enabled"] = "enable_clock2" in request.form

    save_config(config)
    return redirect(url_for("dashboard"))


# ---------- Display Settings ----------
@app.route("/save_display_settings", methods=["POST"])
def save_display_settings():
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


# ---------- Auto Power Schedule ----------
@app.route("/save_auto_power", methods=["POST"])
def save_auto_power():
    config = load_config()
    config["auto_power"]["enabled"] = "auto_power_enabled" in request.form
    config["auto_power"]["off_time"] = request.form.get("off_time", "23:00")
    config["auto_power"]["on_time"] = request.form.get("on_time", "07:00")
    save_config(config)
    return redirect(url_for("dashboard"))


# ---------- Weather API ----------
@app.route("/save_weather_api", methods=["POST"])
def save_weather_api():
    config = load_config()
    config["weather_api_key"] = request.form.get("weather_api_key", "")
    config["weather_region"] = request.form.get("weather_region", "")
    save_config(config)
    return redirect(url_for("dashboard"))


# ---------- Spotify Integration ----------
@app.route("/spotify/connect")
def spotify_connect():
    oauth = get_spotify_oauth()
    return redirect(oauth.get_authorize_url())


@app.route("/spotify/manual", methods=["POST"])
def spotify_manual():
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
        oauth.get_access_token(code)
        user = get_spotify_user()
        if user:
            return redirect(url_for("dashboard", msg=f"Connected as {user.get('display_name', user.get('id'))}"))
        return redirect(url_for("dashboard", msg="Spotify connected."))
    except Exception as e:
        return redirect(url_for("dashboard", msg=f"Spotify error: {e}"))


@app.route("/spotify/disconnect", methods=["POST"])
def spotify_disconnect():
    if os.path.exists(SPOTIFY_CACHE):
        os.remove(SPOTIFY_CACHE)
    return redirect(url_for("dashboard", msg="Spotify disconnected."))



# ---------- Run ----------
if __name__ == "__main__":
    photos = load_photos()
    sync_photo_js(photos)
    app.run(host="0.0.0.0", port=5000)
