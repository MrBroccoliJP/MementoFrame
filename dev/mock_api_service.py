#!/usr/bin/env python3
# MementoFrame - Raspberry Pi Smart Photo Frame
# Copyright (c) 2026 João Fernandes
# Licensed under Creative Commons Attribution-NonCommercial 4.0 International.
"""
MementoFrame Mock — api_service.py replacement (port 5001)

Display/frontend API for local development:
- Spotify mock playback
- Weather mock data
- AP/client status
- configuration portal PIN display endpoints
- SSE reload stream
- screen on/off controls
- /mock management UI and JSON APIs

Run with: python mock_api_service.py
"""

from flask import Flask, jsonify, render_template, send_from_directory, Response, request, redirect, url_for
from flask_cors import CORS
import os
import sys
import json
import time

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
    load_config,
    load_state,
    load_update_state,
    mock_install_update_blocked,
    next_track as shared_next_track,
    pin_response_payload,
    remove_config_portal_pin,
    save_config,
    set_mock_pending_update,
    save_state,
)

# Paths are provided by mock_shared and point at repo-root/mementoframe.
PHOTO_JSON = os.path.join(USERDATA_DIR, "Photos", "photos.json")
os.makedirs(USERDATA_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)

app = Flask(
    __name__,
    template_folder=TEMPLATES_DIR,
    static_folder=STATIC_DIR,
    static_url_path="/static",
)
CORS(app)


def _bool(value):
    return str(value).lower() in {"1", "true", "yes", "on"}


def mock_management_html():
    state = load_state()
    config = load_config()
    pin = pin_response_payload()
    track = current_track_payload()
    update_state = load_update_state()
    weather = state["weather"]
    networks = "\n".join(state.get("known_networks", []))
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MementoFrame Mock Management</title>
  <style>
    :root {{ color-scheme: light dark; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
    body {{ margin: 0; background: #111827; color: #f9fafb; }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px 64px; }}
    h1 {{ margin: 0 0 6px; }}
    a {{ color: #93c5fd; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 18px; margin-top: 22px; }}
    .card {{ background: #1f2937; border: 1px solid #374151; border-radius: 18px; padding: 18px; box-shadow: 0 12px 30px rgba(0,0,0,.25); }}
    label {{ display: block; margin: 10px 0 5px; color: #d1d5db; font-size: 14px; }}
    input, select, textarea {{ width: 100%; box-sizing: border-box; border: 1px solid #4b5563; border-radius: 10px; padding: 10px; background: #111827; color: #f9fafb; }}
    input[type=checkbox] {{ width: auto; }}
    button {{ border: 0; border-radius: 999px; padding: 10px 14px; margin: 8px 8px 0 0; cursor: pointer; background: #2563eb; color: white; font-weight: 700; }}
    button.secondary {{ background: #4b5563; }}
    button.danger {{ background: #dc2626; }}
    code {{ background: #111827; padding: 2px 6px; border-radius: 7px; }}
    .muted {{ color: #9ca3af; }}
    .row {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
  </style>
</head>
<body>
<main>
  <h1>MementoFrame Mock Management</h1>
  <p class="muted">Use this page to drive the local frontend without the Raspberry Pi hardware.</p>
  <p><a href="/">Frame UI</a> · <a href="/spotify.json">Spotify JSON</a> · <a href="/weather.json">Weather JSON</a> · <a href="/status.json">Status JSON</a> · <a href="/config_portal_pin.json">PIN JSON</a></p>

  <div class="grid">
    <section class="card">
      <h2>System/AP mode</h2>
      <p>Current mode: <code>{state['mode']}</code>, IP: <code>{state['ip']}</code>, screen: <code>{state['screen']}</code></p>
      <form method="post" action="/mock/state">
        <label>Mode</label><select name="mode"><option value="client" {'selected' if state['mode']=='client' else ''}>client / Wi‑Fi</option><option value="ap" {'selected' if state['mode']=='ap' else ''}>ap / setup hotspot</option><option value="unknown" {'selected' if state['mode']=='unknown' else ''}>unknown</option></select>
        <label>IP address</label><input name="ip" value="{state['ip']}">
        <label>Wi‑Fi SSID</label><input name="wifi_ssid" value="{state.get('wifi_ssid','')}">
        <label>AP SSID</label><input name="ap_ssid" value="{state.get('ap_ssid','MementoFrame')}">
        <label>Known networks, one per line</label><textarea name="known_networks" rows="4">{networks}</textarea>
        <button>Save system state</button>
      </form>
      <form class="row" method="post" action="/dev/toggle_mode"><button class="secondary">Toggle AP/client</button></form>
    </section>

    <section class="card">
      <h2>Config portal PIN</h2>
      <p>Active PIN: <code>{pin.get('pin') or 'none'}</code>{' — ' + str(pin.get('seconds_remaining')) + 's remaining' if pin.get('active') else ''}</p>
      <form class="row" method="post" action="/mock/pin/create"><button>Create/show PIN</button></form>
      <form class="row" method="post" action="/mock/pin/clear"><button class="danger">Clear PIN</button></form>
      <p class="muted">Supports <code>/config_portal_pin.json</code>, <code>/config_pin.json</code>, <code>/frame_pin.json</code>, and <code>/ap_pin.json</code>.</p>
    </section>

    <section class="card">
      <h2>Software updates</h2>
      <p>Installed: <code>{update_state.get('installed_version') or 'unknown'}</code></p>
      <p>Latest: <code>{update_state.get('latest_version') or update_state.get('latest_tag') or 'not checked'}</code></p>
      <p>Status: <code>{'mock pending update' if update_state.get('mock_pending_update') else ('available' if update_state.get('available') else 'not available')}</code></p>
      <form class="row" method="post" action="/mock/update/pending">
        <label><input type="checkbox" name="mock_pending_update" {'checked' if update_state.get('mock_pending_update') else ''}> Mock pending update</label>
        <button>Save mock flag</button>
      </form>
      <form class="row" method="post" action="/update/check"><button>Check GitHub releases</button></form>
      <form class="row" method="post" action="/update/install"><button class="secondary">Install endpoint test</button></form>
      {f'<p class="muted">{update_state.get("last_error")}</p>' if update_state.get('last_error') else ''}
      <p class="muted">The mock pending flag forces <code>available: true</code> for styling tests. Mocks never install or reboot.</p>
    </section>

    <section class="card">
      <h2>Spotify</h2>
      <p>Source: <code>{state['spotify'].get('source', 'mock')}</code></p>
      <p>Current: <code>{track.get('track', 'not playing')}</code> {('— ' + track.get('artist', '')) if track.get('artist') else ''}</p>
      <p class="muted">{track.get('error', '')}</p>
      <form method="post" action="/mock/spotify">
        <label>Data source</label><select name="source"><option value="mock" {'selected' if state['spotify'].get('source','mock')=='mock' else ''}>mock data</option><option value="real" {'selected' if state['spotify'].get('source','mock')=='real' else ''}>real Spotify</option></select>
        <label><input type="checkbox" name="connected" {'checked' if state['spotify'].get('connected') else ''}> Connected</label>
        <label><input type="checkbox" name="playing" {'checked' if state['spotify'].get('playing') else ''}> Playing</label>
        <label>Track</label><select name="track_index">{''.join(f'<option value="{i}" {"selected" if i == int(state["spotify"].get("track_index",0)) else ""}>{t["track"]} — {t["artist"]}</option>' for i,t in enumerate(MOCK_TRACKS))}</select>
        <button>Save Spotify</button>
      </form>
      <form class="row" method="post" action="/dev/toggle_spotify"><button class="secondary">Toggle play</button></form>
      <form class="row" method="post" action="/dev/next_track"><button class="secondary">Next track</button></form>
      <form class="row" method="get" action="/spotify/connect"><button>Connect real Spotify</button></form>
      <p class="muted">For real Spotify: set source to real, click connect, log in, then paste the callback URL into the admin dashboard manual Spotify form.</p>
    </section>

    <section class="card">
      <h2>Weather</h2>
      <form method="post" action="/mock/weather">
        <label><input type="checkbox" name="enabled" {'checked' if weather.get('enabled') else ''}> Enabled</label>
        <label>City</label><input name="city" value="{weather.get('city','')}">
        <label>Temperature °C</label><input name="temperature" type="number" step="0.1" value="{weather.get('temperature',0)}">
        <label>Condition</label><input name="condition" value="{weather.get('condition','')}">
        <label>Icon URL</label><input name="icon" value="{weather.get('icon','')}">
        <label>Humidity %</label><input name="humidity" type="number" value="{weather.get('humidity',0)}">
        <label>Wind kph</label><input name="windSpeed" type="number" step="0.1" value="{weather.get('windSpeed',0)}">
        <button>Save weather</button>
      </form>
    </section>

    <section class="card">
      <h2>Frame config</h2>
      <form method="post" action="/mock/config">
        <label>Weather API key</label><input name="weather_api_key" value="{config.get('weather_api_key','')}">
        <label>Weather region</label><input name="weather_region" value="{config.get('weather_region','')}">
        <label>Brightness</label><input name="brightness" type="number" min="0" max="100" value="{config.get('brightness',80)}">
        <label><input type="checkbox" name="auto_power_enabled" {'checked' if config.get('auto_power',{}).get('enabled') else ''}> Auto power</label>
        <label>Off time</label><input name="off_time" type="time" value="{config.get('auto_power',{}).get('off_time','23:00')}">
        <label>On time</label><input name="on_time" type="time" value="{config.get('auto_power',{}).get('on_time','07:00')}">
        <button>Save config.json</button>
      </form>
    </section>
  </div>
</main>
</body>
</html>
"""


@app.route("/")
def home():
    template_path = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(template_path):
        return render_template("index.html")
    return redirect(url_for("mock_management"))


@app.route("/mock")
def mock_management():
    return mock_management_html()


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
    return jsonify(load_config())


@app.route("/spotify.json")
def spotify_status():
    return jsonify(current_track_payload())


@app.route("/weather.json")
def weather_status():
    state = load_state()
    weather = state.get("weather", {})
    if not weather.get("enabled", True):
        return jsonify({"error": "Weather API key not configured"}), 503
    return jsonify({
        "temperature": round(float(weather.get("temperature", 0)), 1),
        "condition": weather.get("condition", "Clear"),
        "icon": weather.get("icon"),
        "humidity": int(weather.get("humidity", 0)),
        "windSpeed": float(weather.get("windSpeed", 0)),
        "city": weather.get("city", "Porto"),
    })


@app.route("/config_portal_pin.json")
def config_portal_pin_json():
    return jsonify(pin_response_payload())


@app.route("/config_pin.json")
def config_pin_json_alias():
    payload = pin_response_payload()
    return jsonify({"pin": payload.get("pin"), **payload})


@app.route("/frame_pin.json")
@app.route("/ap_pin.json")
def legacy_pin_aliases():
    return config_pin_json_alias()


@app.route("/status.json")
def system_status():
    state = load_state()
    return jsonify({
        "mode": state.get("mode", "client"),
        "ip": state.get("ip"),
        "uptime": time.time(),
        "screen": state.get("screen"),
        "ap_ssid": state.get("ap_ssid", "MementoFrame"),
        "wifi_ssid": state.get("wifi_ssid"),
        "clients_connected": state.get("clients_connected", 0),
    })


@app.route("/health")
def health_check():
    return jsonify({"status": "ok", "timestamp": time.time(), "service": "mock_api_service"})


@app.route("/get_ip")
def get_ip():
    return jsonify({"ip": load_state().get("ip")})


@app.route("/versions")
def versions():
    return jsonify(VERSIONS)


@app.route("/config/stream")
def config_stream():
    watched = [CONFIG_FILE, PHOTO_JSON]

    def event_stream():
        mtimes = {f: os.path.getmtime(f) if os.path.exists(f) else 0 for f in watched}
        yield "data: ready\n\n"
        while True:
            time.sleep(1)
            changed = False
            for f in watched:
                try:
                    mtime = os.path.getmtime(f)
                    if mtime != mtimes[f]:
                        mtimes[f] = mtime
                        changed = True
                        print(f"🔄 {f} changed — notifying clients")
                except FileNotFoundError:
                    if mtimes.get(f) != 0:
                        mtimes[f] = 0
                        changed = True
            yield "data: reload\n\n" if changed else ": heartbeat\n\n"

    print("📡 SSE client connected to /config/stream")
    return Response(event_stream(), mimetype="text/event-stream")


@app.route("/screen/on", methods=["POST"])
def screen_on():
    state = load_state()
    state["screen"] = "on"
    save_state(state)
    return jsonify({"status": "on"})


@app.route("/screen/off", methods=["POST"])
def screen_off():
    state = load_state()
    state["screen"] = "off"
    save_state(state)
    return jsonify({"status": "off"})


@app.route("/update_status.json")
def update_status_json():
    """Read-only display update state. Used by the frontend update indicator."""
    return jsonify(load_update_state())


@app.route("/update/status")
def update_status():
    return jsonify(load_update_state())


@app.route("/update/check", methods=["POST"])
def update_check():
    state = check_for_updates_mock()
    return jsonify({"status": "ok" if not state.get("last_error") else "error", "updater": state})


@app.route("/update/install", methods=["POST"])
def update_install():
    state = mock_install_update_blocked()
    return jsonify({
        "status": "blocked",
        "message": "Mock environment: update install/reboot is disabled.",
        "updater": state,
    })


@app.route("/mock/update/pending", methods=["POST"])
def mock_update_pending():
    state = set_mock_pending_update("mock_pending_update" in request.form)
    return jsonify(state) if request.accept_mimetypes.best == "application/json" else redirect(url_for("mock_management"))


@app.route("/dev/state", methods=["GET", "POST"])
def dev_state():
    if request.method == "POST":
        state = load_state()
        data = request.get_json(silent=True) or {}
        for key in ["screen", "mode", "ip", "ap_ssid", "wifi_ssid", "clients_connected"]:
            if key in data:
                state[key] = data[key]
        if "spotify" in data and isinstance(data["spotify"], dict):
            state["spotify"].update(data["spotify"])
        if "weather" in data and isinstance(data["weather"], dict):
            state["weather"].update(data["weather"])
        save_state(state)
    return jsonify(load_state())


@app.route("/mock/state", methods=["POST"])
def save_mock_state_form():
    state = load_state()
    state["mode"] = request.form.get("mode", state.get("mode", "client"))
    state["ip"] = request.form.get("ip") or ("192.168.4.1" if state["mode"] == "ap" else "192.168.1.42")
    state["wifi_ssid"] = request.form.get("wifi_ssid", "")
    state["ap_ssid"] = request.form.get("ap_ssid", "MementoFrame")
    state["known_networks"] = [line.strip() for line in request.form.get("known_networks", "").splitlines() if line.strip()]
    save_state(state)
    return redirect(url_for("mock_management"))


@app.route("/mock/spotify", methods=["POST"])
def save_mock_spotify_form():
    state = load_state()
    spotify = state["spotify"]
    spotify["source"] = request.form.get("source", spotify.get("source", "mock"))
    spotify["connected"] = "connected" in request.form
    spotify["playing"] = "playing" in request.form
    spotify["track_index"] = int(request.form.get("track_index", 0))
    spotify["track_started_at"] = time.time()
    spotify["manual_progress_ms"] = 0
    save_state(state)
    return redirect(url_for("mock_management"))


@app.route("/mock/weather", methods=["POST"])
def save_mock_weather_form():
    state = load_state()
    weather = state["weather"]
    weather.update({
        "enabled": "enabled" in request.form,
        "city": request.form.get("city", "Porto"),
        "temperature": float(request.form.get("temperature", 0) or 0),
        "condition": request.form.get("condition", "Clear"),
        "icon": request.form.get("icon", ""),
        "humidity": int(float(request.form.get("humidity", 0) or 0)),
        "windSpeed": float(request.form.get("windSpeed", 0) or 0),
    })
    save_state(state)
    return redirect(url_for("mock_management"))


@app.route("/mock/config", methods=["POST"])
def save_mock_config_form():
    config = load_config()
    config["weather_api_key"] = request.form.get("weather_api_key", "")
    config["weather_region"] = request.form.get("weather_region", "")
    config["brightness"] = max(0, min(100, int(request.form.get("brightness", 80) or 80)))
    config["auto_power"] = {
        "enabled": "auto_power_enabled" in request.form,
        "off_time": request.form.get("off_time", "23:00"),
        "on_time": request.form.get("on_time", "07:00"),
    }
    save_config(config)
    return redirect(url_for("mock_management"))


@app.route("/mock/pin/create", methods=["POST"])
def mock_pin_create():
    get_or_create_config_portal_pin_record()
    return redirect(url_for("mock_management"))


@app.route("/mock/pin/clear", methods=["POST"])
def mock_pin_clear():
    remove_config_portal_pin()
    return redirect(url_for("mock_management"))


@app.route("/dev/toggle_spotify", methods=["POST"])
def toggle_spotify():
    state = load_state()
    state["spotify"]["playing"] = not state["spotify"].get("playing", True)
    state["spotify"]["connected"] = True
    state["spotify"]["track_started_at"] = time.time()
    state["spotify"]["manual_progress_ms"] = current_track_payload().get("progress", 0)
    save_state(state)
    return jsonify(load_state()) if request.accept_mimetypes.best == "application/json" else redirect(url_for("mock_management"))


@app.route("/dev/toggle_mode", methods=["POST"])
def toggle_mode():
    state = load_state()
    state["mode"] = "ap" if state.get("mode") == "client" else "client"
    state["ip"] = "192.168.4.1" if state["mode"] == "ap" else "192.168.1.42"
    save_state(state)
    return jsonify(load_state()) if request.accept_mimetypes.best == "application/json" else redirect(url_for("mock_management"))


@app.route("/dev/next_track", methods=["POST"])
def next_track_route():
    payload = shared_next_track()
    return jsonify(payload) if request.accept_mimetypes.best == "application/json" else redirect(url_for("mock_management"))


@app.route("/spotify/connect")
def spotify_connect():
    state = load_state()
    state["spotify"]["source"] = "real"
    state["spotify"]["connected"] = True
    save_state(state)
    try:
        return redirect(get_spotify_authorize_url())
    except Exception as e:
        return jsonify({"error": str(e), "hint": "Install spotipy and add Spotify credentials to your local .env"}), 500


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
        return redirect(url_for("mock_management"))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/spotify/disconnect", methods=["POST"])
def spotify_disconnect():
    clear_spotify_cache()
    state = load_state()
    state["spotify"]["source"] = "mock"
    state["spotify"]["connected"] = False
    state["spotify"]["playing"] = False
    save_state(state)
    return redirect(url_for("mock_management"))


if __name__ == "__main__":
    print("🖼  MementoFrame Mock — API Service (api_service.py)")
    print("   Frame/API:  http://localhost:5001")
    print("   Mock UI:    http://localhost:5001/mock")
    print("   PIN JSON:   /config_portal_pin.json")
    app.run(host="0.0.0.0", port=5001, debug=True)
