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



from flask import Flask, request, render_template, redirect, url_for, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps
import os, json, uuid
from version_info import VERSIONS

# ---------- All paths anchored to the script's own directory ----------
# This ensures folders are created in the right place regardless of
# which directory you run the script from (important on Windows).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def p(*parts):
    """Build an absolute path relative to the script directory."""
    return os.path.join(BASE_DIR, *parts)

CONFIG_FILE  = p("config.json")
USERDATA_DIR = p("resources", "userdata")
PHOTO_DIR    = p("resources", "userdata", "Photos")
FULL_DIR     = p("resources", "userdata", "Photos", "full")
THUMB_DIR    = p("resources", "userdata", "Photos", "thumbs")
PHOTO_JSON   = p("resources", "userdata", "Photos", "photos.json")
PHOTO_JS     = p("resources", "userdata", "Photos", "photos.js")
CACHE_DIR    = p("resources", "userdata", "cache")
ASSETS_DIR   = p("resources", "assets")
TEMPLATES_DIR = p("templates")

# Create all directories on startup
for d in [USERDATA_DIR, PHOTO_DIR, FULL_DIR, THUMB_DIR, CACHE_DIR, ASSETS_DIR]:
    os.makedirs(d, exist_ok=True)

app = Flask(__name__, template_folder=TEMPLATES_DIR)
CORS(app)

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

    if request.method == "POST" and "ssid" in request.form:
        ssid = request.form["ssid"].strip()
        print(f"[wifi] connect → SSID: {ssid} (mock)")
        return redirect(url_for("dashboard", msg=f"Connected to {ssid} (mock)"))

    return render_template(
        "backend.html",
        mode         = "wifi",
        ip           = "127.0.0.1",
        networks     = ["MockNetwork_2.4G", "MockNetwork_5G", "Neighbor_IoT"],
        photos       = photos,
        spotify_user = {"display_name": "Mock User", "id": "mockuser"},
        spotify_msg  = spotify_msg,
        config       = config,
    )

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
    return redirect(url_for("dashboard", msg="Spotify OAuth would open here (mock)"))

@app.route("/spotify/manual", methods=["POST"])
def spotify_manual():
    print(f"[spotify/manual] url: {request.form.get('spotify_url', '')}")
    return redirect(url_for("dashboard", msg="Connected as Mock User (mock)"))

@app.route("/spotify/disconnect", methods=["POST"])
def spotify_disconnect():
    return redirect(url_for("dashboard", msg="Spotify disconnected."))

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