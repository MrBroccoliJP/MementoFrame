#!/usr/bin/env python3

# MementoFrame - Raspberry Pi Smart Photo Frame
# Copyright (c) 2026 João Fernandes
#
# This work is licensed under the Creative Commons Attribution-NonCommercial
# 4.0 International License. To view a copy of this license, visit:
# http://creativecommons.org/licenses/by-nc/4.0/

"""
MementoFrame Mock — app.py replacement (port 5000)
Real photo upload/delete/resize pipeline. No GPIO, no nmcli, no Spotify OAuth.
Run with: pip install flask flask-cors pillow python-dotenv werkzeug && python mock_app.py
"""



from flask import Flask, request, render_template, render_template_string, redirect, url_for, jsonify, send_from_directory, session
from flask_cors import CORS
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps
import os, sys, json, uuid, time, secrets

# Keep repo-root/dev first so `import mock_shared` always loads this dev copy,
# not any stale copy that may exist inside repo-root/mementoframe.
_DEV_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_DEV_DIR)
_PROJECT_ROOT = os.path.join(_REPO_ROOT, "mementoframe")

if _DEV_DIR in sys.path:
    sys.path.remove(_DEV_DIR)
sys.path.insert(0, _DEV_DIR)

# Add the real project folder after dev so imports like version_info still work.
if _PROJECT_ROOT in sys.path:
    sys.path.remove(_PROJECT_ROOT)
sys.path.insert(1, _PROJECT_ROOT)

try:
    from version_info import VERSIONS
except Exception:
    VERSIONS = {"mock": "local"}

from mock_shared import (
    ASSETS_DIR,
    BASE_DIR,
    CONFIG_FILE,
    MOCK_TRACKS,
    STATIC_DIR,
    TEMPLATES_DIR,
    USERDATA_DIR,
    cache_spotify_token_from_url,
    check_for_updates_mock,
    clear_spotify_cache,
    current_track_payload,
    get_or_create_config_portal_pin_record,
    get_spotify_authorize_url,
    load_state,
    load_update_state,
    mock_install_update_blocked,
    next_track as shared_next_track,
    pin_response_payload,
    read_config_portal_pin_record,
    real_spotify_user,
    remove_config_portal_pin,
    save_state,
    set_mock_pending_update,
)

# ---------- Project paths ----------
# This file is intended to live in repo-root/dev, while the real project files
# live in repo-root/mementoframe.
PHOTO_DIR    = os.path.join(USERDATA_DIR, "Photos")
FULL_DIR     = os.path.join(PHOTO_DIR, "full")
THUMB_DIR    = os.path.join(PHOTO_DIR, "thumbs")
PHOTO_JSON   = os.path.join(PHOTO_DIR, "photos.json")
PHOTO_JS     = os.path.join(PHOTO_DIR, "photos.js")
CACHE_DIR    = os.path.join(USERDATA_DIR, "cache")

# Create all directories on startup
for d in [USERDATA_DIR, PHOTO_DIR, FULL_DIR, THUMB_DIR, CACHE_DIR, ASSETS_DIR]:
    os.makedirs(d, exist_ok=True)

app = Flask(
    __name__,
    template_folder=TEMPLATES_DIR,
    static_folder=STATIC_DIR,
    static_url_path="/static",
)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or "mock-dev-secret-key"
CORS(app)


# ---------- Mock Config PIN Gate ----------
# Mirrors the real app.py flow, but without GPIO.
# The PIN is only created when someone tries to open the protected backend.
# The frame/display can poll /config_pin.json; it returns null when no unlock
# request is active, so the PIN stays hidden until needed.
RUNTIME_DIR = os.path.join(BASE_DIR, "runtime")
os.makedirs(RUNTIME_DIR, exist_ok=True)

CONFIG_PIN_FILE = os.path.join(RUNTIME_DIR, "config_portal_pin.json")
CONFIG_PIN_LENGTH = 6
CONFIG_PIN_TTL_SECONDS = 10 * 60

CONFIG_PIN_EXEMPT_ENDPOINTS = {
    "config_portal_pin_page",
    "config_portal_pin_submit",
    "config_pin_json",
    "update_status",
    "update_check",
    "update_install",
    "mock_update_pending",
    "static",
    "serve_assets",
}


def read_config_pin():
    """Return the active PIN string, or None if no unlock request is active."""
    record = read_config_portal_pin_record()
    return record.get("pin") if record else None


def create_config_pin():
    """Create a fresh temporary configuration portal PIN record."""
    return get_or_create_config_portal_pin_record().get("pin")


def get_or_create_config_pin():
    """Return the current PIN, or create one because unlock was requested."""
    return get_or_create_config_portal_pin_record().get("pin")


def clear_config_pin():
    """Remove the temporary PIN so the frame display hides it."""
    remove_config_portal_pin()

def config_pin_gate_required():
    """Return True if this browser session has not unlocked the backend."""
    return session.get("config_unlocked") is not True


def wake_screen():
    """Mock screen wake. Real app drives GPIO 26 HIGH here."""
    print("[screen] wake requested (mock)")


@app.before_request
def enforce_config_pin_gate():
    """Protect backend routes with the config PIN."""
    if request.endpoint in CONFIG_PIN_EXEMPT_ENDPOINTS:
        return None

    if config_pin_gate_required():
        wake_screen()
        get_or_create_config_pin()
        return redirect(url_for("config_portal_pin_page"))

    return None


def render_pin_page(error=None):
    """Render templates/pin.html, or a built-in fallback when templates are absent."""
    template = os.path.join(TEMPLATES_DIR, "pin.html")
    if os.path.exists(template):
        return render_template("pin.html", error=error)
    return render_template_string("""
    <!doctype html><title>MementoFrame PIN</title>
    <main style="max-width:420px;margin:12vh auto;font-family:system-ui;padding:24px">
      <h1>Enter frame PIN</h1>
      <p>The active mock PIN is shown on the local frame UI or at <code>/config_portal_pin.json</code>.</p>
      {% if error %}<p style="color:#dc2626"><b>{{ error }}</b></p>{% endif %}
      <form method="post"><input name="pin" autofocus inputmode="numeric" style="font-size:24px;padding:10px;width:100%;box-sizing:border-box"><button style="margin-top:12px;padding:10px 16px">Unlock</button></form>
    </main>
    """, error=error)


@app.route("/config_portal_pin_page", methods=["GET"], endpoint="config_portal_pin_page")
@app.route("/config-pin", methods=["GET"])
def config_portal_pin_page():
    """PIN entry page for the config dashboard."""
    wake_screen()
    get_or_create_config_pin()
    return render_pin_page(error=None)


@app.route("/config_portal_pin_submit", methods=["POST"], endpoint="config_portal_pin_submit")
@app.route("/config-pin", methods=["POST"])
def config_portal_pin_submit():
    """Validate submitted PIN and unlock this browser session."""
    active_pin = read_config_pin()
    submitted = request.form.get("pin", "").strip()

    if active_pin and submitted == active_pin:
        session["config_unlocked"] = True
        clear_config_pin()
        return redirect(url_for("dashboard"))

    wake_screen()
    get_or_create_config_pin()
    return render_pin_page(error="Incorrect PIN — try again.")


@app.route("/config_portal_pin.json")
@app.route("/config_pin.json")
@app.route("/frame_pin.json")
@app.route("/ap_pin.json")
def config_pin_json():
    """Expose the active PIN to the mock frame display only while requested."""
    payload = pin_response_payload()
    response = jsonify(payload)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


# ---------- Photo helpers ----------
def build_photo_list():
    exts = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")
    return sorted([f for f in os.listdir(FULL_DIR) if f.lower().endswith(exts)])

def load_photos():
    if not os.path.exists(PHOTO_JSON):
        photos = build_photo_list()
        save_photos(photos)
        return photos
    try:
        with open(PHOTO_JSON, encoding="utf-8") as f:
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
    with open(PHOTO_JSON, "w", encoding="utf-8") as f:
        json.dump(photos, f, indent=2)
    sync_photo_js(photos)
    print(f"[photos] saved {len(photos)} entries → {PHOTO_JSON}")

def sync_photo_js(photos=None):
    if photos is None:
        photos = load_photos()
    js_content = "window.photos = " + json.dumps(photos, indent=2) + ";"
    with open(PHOTO_JS, "w", encoding="utf-8") as f:
        f.write(js_content)
    print(f"[photos] synced photos.js → {PHOTO_JS}")

# ---------- Config helpers ----------
def load_config():
    default = {
        "clock1": {"label": "Lisbon", "timezone": "Europe/Lisbon"},
        "clock2": {"label": "Shanghai", "timezone": "Asia/Shanghai", "enabled": True},
        "weather_api_key": "",
        "weather_region": "",
        "brightness": 80,
        "auto_power": {"enabled": False, "off_time": "23:00", "on_time": "07:00"},
        "updates": {"auto_update": False, "repo": "", "channel": "stable", "mock_pending_update": False},
    }
    if not os.path.exists(CONFIG_FILE):
        return default
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        for key, val in default.items():
            cfg.setdefault(key, val)
        return cfg
    except Exception as e:
        print(f"⚠️  Error loading config.json: {e}")
        return default

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

# ---------- Routes ----------
@app.route("/", methods=["GET", "POST"])
def dashboard():
    config      = load_config()
    photos      = load_photos()
    spotify_msg = request.args.get("msg")
    update_state  = load_update_state()

    if request.method == "POST" and "ssid" in request.form:
        ssid = request.form["ssid"].strip()
        print(f"[wifi] connect → SSID: {ssid} (mock)")
        return redirect(url_for("dashboard", msg=f"Connected to {ssid} (mock)"))

    state = load_state()
    networks = state.get("known_networks", ["MockNetwork_2.4G", "MockNetwork_5G", "Neighbor_IoT"])
    if os.path.exists(os.path.join(TEMPLATES_DIR, "backend.html")):
        return render_template(
            "backend.html",
            mode         = state.get("mode", "wifi"),
            ip           = state.get("ip", "127.0.0.1"),
            networks     = networks,
            photos       = photos,
            spotify_user = (real_spotify_user() if state.get("spotify", {}).get("source") == "real" else ({"display_name": "Mock User", "id": "mockuser"} if state.get("spotify", {}).get("connected", True) else None)),
            spotify_msg  = spotify_msg,
            config       = config,
            update_state  = update_state,
        )
    return render_template_string(MOCK_ADMIN_TEMPLATE, state=state, config=config, photos=photos, networks=networks, spotify_msg=spotify_msg, track=current_track_payload(), pin=pin_response_payload(), tracks=MOCK_TRACKS, update_state=update_state)


MOCK_ADMIN_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MementoFrame Mock Admin</title>
  <style>
    :root { color-scheme: light dark; font-family: Inter, system-ui, sans-serif; }
    body { margin: 0; background:#111827; color:#f9fafb; } main { max-width:1100px; margin:auto; padding:32px 20px 64px; }
    a { color:#93c5fd; } .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:18px; }
    .card { background:#1f2937; border:1px solid #374151; border-radius:18px; padding:18px; box-shadow:0 12px 30px rgba(0,0,0,.24); }
    label { display:block; margin:10px 0 5px; color:#d1d5db; font-size:14px; }
    input, select, textarea { width:100%; box-sizing:border-box; border:1px solid #4b5563; border-radius:10px; padding:10px; background:#111827; color:#f9fafb; }
    input[type=checkbox] { width:auto; } button { border:0; border-radius:999px; padding:10px 14px; margin-top:10px; cursor:pointer; background:#2563eb; color:white; font-weight:700; }
    .secondary { background:#4b5563; } .danger { background:#dc2626; } code { background:#111827; padding:2px 6px; border-radius:7px; } .muted { color:#9ca3af; }
  </style>
</head>
<body><main>
<h1>MementoFrame Mock Admin</h1>
<p class="muted">Local-only control panel for frontend design testing. Protected by the same mock PIN gate as the real config portal.</p>
<p><a href="/mock">Mock controls</a> · <a href="http://localhost:5001/mock">Display API controls</a> · <a href="/config_portal_pin.json">PIN JSON</a> · <a href="/versions">Versions</a></p>
{% if spotify_msg %}<p><b>{{ spotify_msg }}</b></p>{% endif %}
<div class="grid">
  <section class="card"><h2>System/AP</h2><p>Mode <code>{{ state.mode }}</code>, IP <code>{{ state.ip }}</code></p>
    <form method="post" action="/mock/state"><label>Mode</label><select name="mode"><option value="client" {% if state.mode=='client' %}selected{% endif %}>client</option><option value="ap" {% if state.mode=='ap' %}selected{% endif %}>ap</option><option value="unknown" {% if state.mode=='unknown' %}selected{% endif %}>unknown</option></select><label>IP</label><input name="ip" value="{{ state.ip }}"><label>Wi-Fi SSID</label><input name="wifi_ssid" value="{{ state.wifi_ssid }}"><label>AP SSID</label><input name="ap_ssid" value="{{ state.ap_ssid }}"><label>Known networks</label><textarea name="known_networks" rows="4">{{ networks|join('\n') }}</textarea><button>Save state</button></form>
  </section>
  <section class="card"><h2>PIN</h2><p>Active PIN: <code>{{ pin.pin or 'none' }}</code>{% if pin.active %} — {{ pin.seconds_remaining }}s{% endif %}</p><form method="post" action="/mock/pin/create"><button>Create/show PIN</button></form><form method="post" action="/mock/pin/clear"><button class="danger">Clear PIN</button></form></section>
  <section class="card"><h2>Software updates</h2><p>Installed: <code>{{ update_state.installed_version or 'unknown' }}</code></p><p>Latest: <code>{{ update_state.latest_version or update_state.latest_tag or 'not checked' }}</code></p><p>Status: <code>{% if update_state.mock_pending_update %}mock pending update{% elif update_state.available %}available{% else %}not available{% endif %}</code></p><form method="post" action="/mock/update/pending"><label><input type="checkbox" name="mock_pending_update" {% if update_state.mock_pending_update %}checked{% endif %}> Mock pending update</label><button>Save mock flag</button></form><form method="post" action="/update/check"><button>Check GitHub releases</button></form><form method="post" action="/update/install"><button class="secondary">Install endpoint test</button></form>{% if update_state.last_error %}<p class="muted">{{ update_state.last_error }}</p>{% endif %}<p class="muted">Forces the frontend update indicator without installing or rebooting.</p></section>
  <section class="card"><h2>Spotify</h2><p>Source <code>{{ state.spotify.source or 'mock' }}</code></p><p><code>{{ track.track or 'not playing' }}</code> {{ track.artist or '' }}</p>{% if track.error %}<p class="muted">{{ track.error }}</p>{% endif %}<form method="post" action="/mock/spotify"><label>Data source</label><select name="source"><option value="mock" {% if (state.spotify.source or 'mock') == 'mock' %}selected{% endif %}>mock data</option><option value="real" {% if state.spotify.source == 'real' %}selected{% endif %}>real Spotify</option></select><label><input type="checkbox" name="connected" {% if state.spotify.connected %}checked{% endif %}> Connected</label><label><input type="checkbox" name="playing" {% if state.spotify.playing %}checked{% endif %}> Playing</label><label>Track</label><select name="track_index">{% for t in tracks %}<option value="{{ loop.index0 }}" {% if loop.index0 == state.spotify.track_index %}selected{% endif %}>{{ t.track }} — {{ t.artist }}</option>{% endfor %}</select><button>Save Spotify</button></form><form method="post" action="/mock/spotify/next"><button class="secondary">Next track</button></form><form method="get" action="/spotify/connect"><button>Connect real Spotify</button></form><form method="post" action="/spotify/manual"><label>Paste Spotify callback URL</label><input name="spotify_url" placeholder="https://httpbin.org/anything?code=..."><button>Save real Spotify token</button></form><form method="post" action="/spotify/disconnect"><button class="danger">Disconnect Spotify</button></form></section>
  <section class="card"><h2>Weather</h2><form method="post" action="/mock/weather"><label><input type="checkbox" name="enabled" {% if state.weather.enabled %}checked{% endif %}> Enabled</label><label>City</label><input name="city" value="{{ state.weather.city }}"><label>Temperature</label><input type="number" step="0.1" name="temperature" value="{{ state.weather.temperature }}"><label>Condition</label><input name="condition" value="{{ state.weather.condition }}"><label>Humidity</label><input type="number" name="humidity" value="{{ state.weather.humidity }}"><label>Wind kph</label><input type="number" step="0.1" name="windSpeed" value="{{ state.weather.windSpeed }}"><label>Icon URL</label><input name="icon" value="{{ state.weather.icon }}"><button>Save weather</button></form></section>
  <section class="card"><h2>Photos</h2><p>{{ photos|length }} photo(s) loaded.</p><form method="post" action="/upload" enctype="multipart/form-data"><input type="file" name="photos" multiple><button>Upload photos</button></form></section>
</div>
</main></body></html>
"""

@app.route("/mock")
def mock_admin():
    state = load_state()
    return render_template_string(MOCK_ADMIN_TEMPLATE, state=state, config=load_config(), photos=load_photos(), networks=state.get("known_networks", []), spotify_msg=request.args.get("msg"), track=current_track_payload(), pin=pin_response_payload(), tracks=MOCK_TRACKS, update_state=update_state)

@app.route("/mock/state", methods=["POST"])
def mock_save_state():
    state = load_state()
    state["mode"] = request.form.get("mode", state.get("mode", "client"))
    state["ip"] = request.form.get("ip") or ("192.168.4.1" if state["mode"] == "ap" else "192.168.1.42")
    state["wifi_ssid"] = request.form.get("wifi_ssid", "")
    state["ap_ssid"] = request.form.get("ap_ssid", "MementoFrame")
    state["known_networks"] = [line.strip() for line in request.form.get("known_networks", "").splitlines() if line.strip()]
    save_state(state)
    return redirect(url_for("mock_admin"))

@app.route("/mock/spotify", methods=["POST"])
def mock_save_spotify():
    state = load_state()
    state["spotify"]["source"] = request.form.get("source", state["spotify"].get("source", "mock"))
    state["spotify"]["connected"] = "connected" in request.form
    state["spotify"]["playing"] = "playing" in request.form
    state["spotify"]["track_index"] = int(request.form.get("track_index", 0))
    state["spotify"]["track_started_at"] = time.time()
    state["spotify"]["manual_progress_ms"] = 0
    save_state(state)
    return redirect(url_for("mock_admin"))

@app.route("/mock/spotify/next", methods=["POST"])
def mock_spotify_next():
    shared_next_track()
    return redirect(url_for("mock_admin"))

@app.route("/mock/weather", methods=["POST"])
def mock_save_weather():
    state = load_state()
    state["weather"].update({
        "enabled": "enabled" in request.form,
        "city": request.form.get("city", "Porto"),
        "temperature": float(request.form.get("temperature", 0) or 0),
        "condition": request.form.get("condition", "Clear"),
        "humidity": int(float(request.form.get("humidity", 0) or 0)),
        "windSpeed": float(request.form.get("windSpeed", 0) or 0),
        "icon": request.form.get("icon", ""),
    })
    save_state(state)
    return redirect(url_for("mock_admin"))

@app.route("/mock/pin/create", methods=["POST"])
def mock_create_pin():
    get_or_create_config_portal_pin_record()
    return redirect(url_for("mock_admin"))

@app.route("/mock/pin/clear", methods=["POST"])
def mock_clear_pin():
    clear_config_pin()
    return redirect(url_for("mock_admin"))

@app.route("/dev/state")
def dev_state():
    return jsonify(load_state())

# ---------- Static serving ----------
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

# ---------- Photo upload ----------
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

        # Find a collision-safe .webp name
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

        # Save original to a temp file first
        temp_path = os.path.join(FULL_DIR, f"temp_{uuid.uuid4().hex[:8]}{ext}")
        file.save(temp_path)
        print(f"[upload] saved temp → {temp_path}")

        try:
            with Image.open(temp_path) as img:
                img = ImageOps.exif_transpose(img).convert("RGB")

                # Full size (max 1000x1000)
                full_img = img.copy()
                full_img.thumbnail((1000, 1000))
                full_img.save(full_path, format="WEBP", quality=100, method=6)
                print(f"[upload] ✅ full  → {full_path}")

                # Thumb (max 250x250)
                thumb_img = img.copy()
                thumb_img.thumbnail((250, 250))
                thumb_img.save(thumb_path, format="WEBP", quality=80, method=6)
                print(f"[upload] ✅ thumb → {thumb_path}")

            os.remove(temp_path)
            photos.append(webp_name)

        except Exception as e:
            print(f"[upload] ❌ error processing {filename}: {e}")
            # Fallback: keep original file without conversion
            fallback = os.path.join(FULL_DIR, filename)
            os.replace(temp_path, fallback)  # os.replace works on Windows unlike os.rename across drives
            if filename not in photos:
                photos.append(filename)

    save_photos(photos)
    return redirect(url_for("dashboard"))

# ---------- Photo delete ----------
@app.route("/delete_selected_photos", methods=["POST"])
def delete_selected_photos():
    selected = request.form.getlist("selected_photos")
    for name in selected:
        filename = secure_filename(name)
        for d in [FULL_DIR, THUMB_DIR]:
            path = os.path.join(d, filename)
            if os.path.exists(path):
                os.remove(path)
                print(f"[delete] 🗑  {path}")
    photos = [p for p in load_photos() if p not in selected]
    save_photos(photos)
    return redirect(url_for("dashboard"))

# ---------- Settings ----------
@app.route("/save_clock_settings", methods=["POST"])
def save_clock_settings():
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
    config = load_config()
    try:
        level = max(0, min(100, int(request.form.get("brightness", 80))))
    except ValueError:
        level = 80
    config["brightness"] = level
    print(f"[brightness] {level} (mock — no GPIO)")
    save_config(config)
    return redirect(url_for("dashboard"))

@app.route("/save_auto_power", methods=["POST"])
def save_auto_power():
    config = load_config()
    config["auto_power"] = {
        "enabled":  "auto_power_enabled" in request.form,
        "off_time": request.form.get("off_time", "23:00"),
        "on_time":  request.form.get("on_time", "07:00"),
    }
    save_config(config)
    return redirect(url_for("dashboard"))

@app.route("/save_weather_api", methods=["POST"])
def save_weather_api():
    config = load_config()
    config["weather_api_key"] = request.form.get("weather_api_key", "")
    config["weather_region"]  = request.form.get("weather_region", "")
    save_config(config)
    return redirect(url_for("dashboard"))

@app.route("/test_brightness", methods=["POST"])
def test_brightness():
    data = request.get_json() or {}
    try:
        level = max(0, min(100, int(data.get("level", 80))))
    except ValueError:
        return jsonify({"error": "Invalid level"}), 400
    print(f"[brightness] test {level} (mock — no GPIO)")
    return jsonify({"status": "started", "level": level})

# ---------- Spotify stubs ----------
@app.route("/spotify/connect")
def spotify_connect():
    state = load_state()
    state["spotify"]["source"] = "real"
    state["spotify"]["connected"] = True
    save_state(state)
    try:
        return redirect(get_spotify_authorize_url())
    except Exception as e:
        return redirect(url_for("dashboard", msg=f"Spotify setup error: {e}"))

@app.route("/spotify/manual", methods=["POST"])
def spotify_manual():
    pasted_url = request.form.get("spotify_url", "")
    try:
        cache_spotify_token_from_url(pasted_url)
        state = load_state()
        state["spotify"]["source"] = "real"
        state["spotify"]["connected"] = True
        state["spotify"]["playing"] = True
        save_state(state)
        user = real_spotify_user()
        name = (user or {}).get("display_name") or (user or {}).get("id") or "Spotify"
        return redirect(url_for("dashboard", msg=f"Connected as {name}"))
    except Exception as e:
        return redirect(url_for("dashboard", msg=f"Spotify error: {e}"))

@app.route("/spotify/disconnect", methods=["POST"])
def spotify_disconnect():
    clear_spotify_cache()
    state = load_state()
    state["spotify"]["source"] = "mock"
    state["spotify"]["connected"] = False
    state["spotify"]["playing"] = False
    save_state(state)
    return redirect(url_for("dashboard", msg="Spotify disconnected."))


@app.route("/health")
def health_check():
    return jsonify({"status": "ok", "timestamp": time.time(), "service": "mock_app"})


@app.route("/update/status")
def update_status():
    """Return mock software-update state for the config portal."""
    return jsonify(load_update_state())


@app.route("/update/check", methods=["POST"])
def update_check():
    """Check GitHub releases but never install anything in mock mode."""
    state = check_for_updates_mock()
    return jsonify({"status": "ok" if not state.get("last_error") else "error", "updater": state})


@app.route("/update/install", methods=["POST"])
def update_install():
    """No-op in mocks: expose endpoint compatibility without applying updates."""
    state = mock_install_update_blocked()
    return jsonify({
        "status": "blocked",
        "message": "Mock environment: update install/reboot is disabled.",
        "updater": state,
    })


@app.route("/mock/update/pending", methods=["POST"])
def mock_update_pending():
    """Toggle mock-only pending update state for styling tests."""
    state = set_mock_pending_update("mock_pending_update" in request.form)
    return jsonify(state) if request.accept_mimetypes.best == "application/json" else redirect(url_for("dashboard", msg="Mock pending update flag saved."))


@app.route("/save_update_settings", methods=["POST"])
def save_update_settings():
    config = load_config()
    updates = config.setdefault("updates", {})
    updates["auto_update"] = "auto_update" in request.form
    updates["repo"] = request.form.get("update_repo", updates.get("repo", "")).strip()
    updates["channel"] = request.form.get("update_channel", updates.get("channel", "stable")).strip() or "stable"
    updates["mock_pending_update"] = "mock_pending_update" in request.form
    save_config(config)
    set_mock_pending_update(updates["mock_pending_update"])
    return redirect(url_for("dashboard", msg="Mock update settings saved."))


@app.route("/versions")
def versions():
    return jsonify(VERSIONS)

# ---------- Run ----------
if __name__ == "__main__":
    photos = load_photos()
    sync_photo_js(photos)
    print()
    print("🖼  MementoFrame Mock — Admin Dashboard (port 5000)")
    print(f"   Script dir : {BASE_DIR}")
    print(f"   Full dir   : {FULL_DIR}")
    print(f"   Thumb dir  : {THUMB_DIR}")
    print(f"   photos.json: {PHOTO_JSON}")
    print(f"   photos.js  : {PHOTO_JS}")
    print()
    app.run(host="0.0.0.0", port=5000, debug=True)