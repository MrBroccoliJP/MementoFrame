#!/usr/bin/env python3
"""
MementoFrame Mock — api_service.py replacement (port 5001)
Display frontend: Spotify, weather, SSE stream, screen control.
Run with: python mock_api_service.py
"""

from flask import Flask, jsonify, render_template, send_from_directory, Response, request
from flask_cors import CORS
import os, json, time, random

app = Flask(__name__, static_folder="static", static_url_path="/static")
CORS(app)

# ---------- Paths ----------
CONFIG_FILE = "config.json"
USERDATA_DIR = "resources/userdata"
ASSETS_DIR = "resources/assets"

# ---------- Mock state ----------
state = {
    "screen": "on",
    "spotify_playing": True,
    "mode": "client",
    "ip": "192.168.1.42",
}

MOCK_CONFIG = {
    "clock1": {"label": "Lisbon", "timezone": "Europe/Lisbon"},
    "clock2": {"label": "Shanghai", "timezone": "Asia/Shanghai", "enabled": True},
    "weather_api_key": "mock-key",
    "weather_region": "Porto",
    "brightness": 80,
    "auto_power": {"enabled": True, "off_time": "23:00", "on_time": "07:00"},
}

MOCK_TRACKS = [
    {
        "track": "Nights",
        "artist": "Frank Ocean",
        "albumArt": "https://i.scdn.co/image/ab67616d0000b273c5649add07ed3720be9d5526",
        "isPlaying": True,
        "progress": 123000,
        "duration": 307000,
        "liked": True,
        "trackId": "7eqoqGkKwgOaWNNHx90uEZ",
    },
    {
        "track": "Motion Picture Soundtrack",
        "artist": "Radiohead",
        "albumArt": "https://i.scdn.co/image/ab67616d0000b2734f2e48ba59f01ef58c72a52b",
        "isPlaying": True,
        "progress": 45000,
        "duration": 286000,
        "liked": False,
        "trackId": "0gGpHoFMtqNjxLh5F3BBFA",
    },
    {
        "track": "Pink + White",
        "artist": "Frank Ocean",
        "albumArt": "https://i.scdn.co/image/ab67616d0000b273c5649add07ed3720be9d5526",
        "isPlaying": True,
        "progress": 60000,
        "duration": 213000,
        "liked": True,
        "trackId": "3xKsf9qdS1CyvXSMEid6g8",
    },
]
_track_index = 0
_track_start = time.time()

# ---------- Routes ----------
@app.route("/")
def home():
    if os.path.exists("templates/index.html"):
        return render_template("index.html")
    return """
    <h2>MementoFrame Mock API Service ✅ (port 5001)</h2>
    <ul>
      <li><a href="/spotify.json">/spotify.json</a></li>
      <li><a href="/weather.json">/weather.json</a></li>
      <li><a href="/status.json">/status.json</a></li>
      <li><a href="/health">/health</a></li>
      <li><a href="/get_ip">/get_ip</a></li>
      <li><a href="/config.json">/config.json</a></li>
    </ul>
    <hr>
    <h3>Dev toggles (POST)</h3>
    <button onclick="fetch('/dev/toggle_spotify',{method:'POST'}).then(()=>location.reload())">Toggle Spotify</button>
    <button onclick="fetch('/dev/toggle_mode',{method:'POST'}).then(()=>location.reload())">Toggle AP/Client</button>
    <button onclick="fetch('/dev/next_track',{method:'POST'}).then(()=>location.reload())">Next Track</button>
    """

@app.route("/assets/<path:filename>")
def serve_assets(filename):
    if os.path.exists(os.path.join(ASSETS_DIR, filename)):
        return send_from_directory(ASSETS_DIR, filename)
    return "", 200

@app.route("/userdata/<path:filename>")
def serve_userdata(filename):
    if os.path.exists(os.path.join(USERDATA_DIR, filename)):
        return send_from_directory(USERDATA_DIR, filename)
    return jsonify({}), 200

@app.route("/config.json")
def serve_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return jsonify(json.load(f))
    return jsonify(MOCK_CONFIG)

# ---------- Spotify ----------
@app.route("/spotify.json")
def spotify_status():
    if not state["spotify_playing"]:
        return jsonify({"isPlaying": False})
    track = MOCK_TRACKS[_track_index % len(MOCK_TRACKS)].copy()
    # Simulate progress based on real elapsed time
    elapsed = int((time.time() - _track_start) * 1000)
    track["progress"] = min(track["progress"] + elapsed, track["duration"])
    return jsonify(track)

# ---------- Weather ----------
@app.route("/weather.json")
def weather_status():
    return jsonify({
        "temperature": 18.4,
        "condition": "Partly cloudy",
        "icon": "https://cdn.weatherapi.com/weather/64x64/day/116.png",
        "humidity": 72,
        "windSpeed": 14.4,
        "city": "Porto",
    })

# ---------- System ----------
@app.route("/status.json")
def system_status():
    return jsonify({
        "mode": state["mode"],
        "ip": state["ip"],
        "uptime": time.time(),
    })

@app.route("/health")
def health_check():
    return jsonify({"status": "ok", "timestamp": time.time()})

@app.route("/get_ip")
def get_ip():
    return jsonify({"ip": state["ip"]})

# ---------- SSE ----------
@app.route("/config/stream")
def config_stream():
    CONFIG_FILES = [CONFIG_FILE, os.path.join(USERDATA_DIR, "Photos/photos.json")]

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
            yield "data: reload\n\n" if changed else ": heartbeat\n\n"

    print("📡 SSE client connected")
    return Response(event_stream(), mimetype="text/event-stream")

# ---------- Screen control ----------
@app.route("/screen/on", methods=["POST"])
def screen_on():
    state["screen"] = "on"
    print("🖥  Screen ON (mock)")
    return jsonify({"status": "on"})

@app.route("/screen/off", methods=["POST"])
def screen_off():
    state["screen"] = "off"
    print("🖥  Screen OFF (mock)")
    return jsonify({"status": "off"})

# ---------- Dev toggles ----------
@app.route("/dev/toggle_spotify", methods=["POST"])
def toggle_spotify():
    state["spotify_playing"] = not state["spotify_playing"]
    print(f"[dev] spotify_playing → {state['spotify_playing']}")
    return jsonify(state)

@app.route("/dev/toggle_mode", methods=["POST"])
def toggle_mode():
    state["mode"] = "ap" if state["mode"] == "client" else "client"
    state["ip"] = "192.168.4.1" if state["mode"] == "ap" else "192.168.1.42"
    print(f"[dev] mode → {state['mode']}, ip → {state['ip']}")
    return jsonify(state)

@app.route("/dev/next_track", methods=["POST"])
def next_track():
    global _track_index, _track_start
    _track_index += 1
    _track_start = time.time()
    track = MOCK_TRACKS[_track_index % len(MOCK_TRACKS)]
    print(f"[dev] track → {track['track']} — {track['artist']}")
    return jsonify(track)

@app.route("/dev/state")
def dev_state():
    return jsonify(state)

# ---------- Run ----------
if __name__ == "__main__":
    print("🖼  MementoFrame Mock — API Service (api_service.py)")
    print("   http://localhost:5001")
    print()
    print("   Dev toggles: POST /dev/toggle_spotify | /dev/toggle_mode | /dev/next_track")
    app.run(host="0.0.0.0", port=5001, debug=True)
