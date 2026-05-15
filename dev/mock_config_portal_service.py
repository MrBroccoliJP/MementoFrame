#!/usr/bin/env python3
# MementoFrame - Raspberry Pi Smart Photo Frame
# Copyright (c) 2026 João Fernandes
# Licensed under Creative Commons Attribution-NonCommercial 4.0 International.
"""Mock replacement for config_portal_service.py, running on port 5000."""
from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, render_template_string, request, send_from_directory, session, url_for
from flask_cors import CORS
from PIL import Image, ImageOps
from werkzeug.utils import secure_filename

from mock_shared import (
    ASSETS_DIR,
    CACHE_DIR,
    CONFIG_FILE,
    FULL_DIR,
    MOCK_TRACKS,
    PHOTO_JSON,
    STATIC_DIR,
    PHOTO_JS,
    THUMB_DIR,
    TEMPLATES_DIR,
    USERDATA_DIR,
    build_photo_list,
    cache_spotify_token_from_url,
    check_for_updates_mock,
    clear_spotify_cache,
    current_track_payload,
    forced_time_payload,
    get_or_create_config_portal_pin_record,
    get_spotify_authorize_url,
    load_config,
    load_photos,
    load_state,
    load_update_state,
    mock_autoupdate,
    mock_install_update_blocked,
    pin_response_payload,
    read_config_portal_pin_record,
    real_spotify_user,
    remove_config_portal_pin,
    save_config,
    save_photos,
    save_state,
    set_mock_pending_update,
    weather_payload,
    write_env_values,
    read_env_values,
)

app = Flask(__name__, template_folder=str(TEMPLATES_DIR), static_folder=str(STATIC_DIR), static_url_path="/static")
app.secret_key = os.getenv("FLASK_SECRET_KEY") or "mementoframe-mock-secret"
CORS(app)

PHOTO_TMP_DIR = Path(USERDATA_DIR) / "Photos" / "tmp_uploads"
PHOTO_TMP_DIR.mkdir(parents=True, exist_ok=True)

upload_status_lock = threading.Lock()
upload_status = {
    "active": False,
    "queued": 0,
    "processed": 0,
    "failed": 0,
    "last_batch_id": None,
    "last_message": None,
    "updated_at": None,
}

CONFIG_PORTAL_PIN_EXEMPT_ENDPOINTS = {"config_portal_pin_page", "config_portal_pin_submit", "static", "serve_assets", "health_check"}


def bool_form(name: str) -> bool:
    return name in request.form


def wants_json_response() -> bool:
    """Return True for fetch/AJAX-style requests from the no-reload config portal UI."""
    return (
        request.headers.get("X-Requested-With") == "fetch"
        or request.accept_mimetypes.best == "application/json"
    )


def json_or_redirect(payload: dict, endpoint: str = "dashboard"):
    """Return JSON for fetch requests, otherwise keep classic redirect behaviour."""
    if wants_json_response():
        return jsonify(payload)
    return redirect(url_for(endpoint, msg=payload.get("message")))


def touch_for_display_reload() -> None:
    """Touch files watched by the mock display SSE stream so the frontend reloads."""
    now = time.time()

    # The display mock watches config.json and photos.json. Touching either is
    # enough to emit a reload without changing user settings.
    for path in [Path(CONFIG_FILE), Path(PHOTO_JSON), Path(PHOTO_JS)]:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                os.utime(path, (now, now))
        except Exception as exc:
            print(f"[mock-display-reload] could not touch {path}: {exc}")


def wake_screen() -> None:
    state = load_state()
    state["screen"] = "on"
    save_state(state)


@app.before_request
def enforce_config_portal_pin_gate():
    if request.endpoint in CONFIG_PORTAL_PIN_EXEMPT_ENDPOINTS:
        return None
    if session.get("config_unlocked") is not True:
        wake_screen()
        get_or_create_config_portal_pin_record()
        return redirect(url_for("config_portal_pin_page"))
    return None


def render_pin_page(error=None):
    if (TEMPLATES_DIR / "pin.html").exists():
        return render_template("pin.html", error=error)
    pin = pin_response_payload().get("pin")
    return render_template_string("""
<!doctype html><title>MementoFrame PIN</title><main style="max-width:420px;margin:12vh auto;font-family:system-ui;padding:24px">
<h1>Enter frame PIN</h1><p>The active mock PIN is shown on the display UI or at <code>/config_portal_pin.json</code>.</p>
{% if pin %}<p>Development helper: <b>{{ pin }}</b></p>{% endif %}
{% if error %}<p style="color:#dc2626"><b>{{ error }}</b></p>{% endif %}
<form method="post"><input name="pin" autofocus inputmode="numeric" style="font-size:24px;padding:10px;width:100%;box-sizing:border-box"><button style="margin-top:12px;padding:10px 16px">Unlock</button></form></main>
""", error=error, pin=pin)


@app.route("/config-portal-pin", methods=["GET"])
def config_portal_pin_page():
    wake_screen()
    get_or_create_config_portal_pin_record()
    return render_pin_page()


@app.route("/config-portal-pin", methods=["POST"])
def config_portal_pin_submit():
    record = read_config_portal_pin_record()
    submitted = request.form.get("pin", "").strip()
    if record and submitted == record.get("pin"):
        session["config_unlocked"] = True
        remove_config_portal_pin()
        return redirect(url_for("dashboard"))
    wake_screen()
    get_or_create_config_portal_pin_record()
    return render_pin_page(error="Incorrect or expired PIN — try again.")


def dashboard_fallback_html(**ctx):
    state = ctx["state"]
    config = ctx["config"]
    update_state = ctx["update_state"]
    track = current_track_payload()
    pin = pin_response_payload()
    time_cfg = forced_time_payload()
    photos = ctx["photos"]
    networks = "\n".join(ctx["networks"])
    return f"""
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>MementoFrame Mock Config Portal</title><style>
:root{{color-scheme:light dark;font-family:Inter,system-ui,sans-serif}}body{{margin:0;background:#111827;color:#f9fafb}}main{{max-width:1160px;margin:auto;padding:32px 20px 64px}}a{{color:#93c5fd}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:18px}}.card{{background:#1f2937;border:1px solid #374151;border-radius:18px;padding:18px;box-shadow:0 12px 30px rgba(0,0,0,.24)}}label{{display:block;margin:10px 0 5px;color:#d1d5db;font-size:14px}}input,select,textarea{{width:100%;box-sizing:border-box;border:1px solid #4b5563;border-radius:10px;padding:10px;background:#111827;color:#f9fafb}}input[type=checkbox]{{width:auto}}button{{border:0;border-radius:999px;padding:10px 14px;margin-top:10px;cursor:pointer;background:#2563eb;color:white;font-weight:700}}.secondary{{background:#4b5563}}.danger{{background:#dc2626}}code{{background:#111827;padding:2px 6px;border-radius:7px}}.muted{{color:#9ca3af}}
</style></head><body><main><h1>MementoFrame Mock Config Portal</h1><p class="muted">Endpoint-compatible local version of <code>config_portal_service.py</code>.</p><p><a href="http://localhost:5001">Frame UI</a> · <a href="http://localhost:5001/mock">Mock controls</a> · <a href="/versions">Versions</a> · <a href="/health">Health</a></p>{f'<p><b>{ctx["spotify_msg"]}</b></p>' if ctx.get('spotify_msg') else ''}
<div class="grid">
<section class="card"><h2>Wi‑Fi mock</h2><p>Mode <code>{state.get('mode')}</code>, IP <code>{state.get('ip')}</code></p><form method="post"><label>SSID</label><select name="ssid">{''.join(f'<option>{n}</option>' for n in ctx['networks'])}</select><label>Password</label><input name="psk" type="password"><button>Connect mock Wi‑Fi</button></form><form method="post" action="/mock/state"><label>Mode</label><select name="mode"><option value="client" {'selected' if state.get('mode')=='client' else ''}>client</option><option value="ap" {'selected' if state.get('mode')=='ap' else ''}>ap</option><option value="unknown" {'selected' if state.get('mode')=='unknown' else ''}>unknown</option></select><label>IP</label><input name="ip" value="{state.get('ip','')}"><label>Networks</label><textarea name="known_networks" rows="4">{networks}</textarea><button>Save mock state</button></form></section>
<section class="card"><h2>Photos</h2><p>{len(photos)} photo(s) loaded.</p><form method="post" action="/upload" enctype="multipart/form-data"><input type="file" name="photos" multiple><button>Upload photos</button></form><form method="post" action="/delete_selected_photos">{''.join(f'<label><input type="checkbox" name="selected_photos" value="{p}"> {p}</label>' for p in photos[:30])}<button class="danger">Delete selected</button></form></section>
<section class="card"><h2>Clocks</h2><form method="post" action="/save_clock_settings"><label>Clock 1 label</label><input name="clock1_label" value="{config.get('clock1',{}).get('label','Lisbon')}"><label>Clock 1 timezone</label><input name="clock1_tz" value="{config.get('clock1',{}).get('timezone','Europe/Lisbon')}"><label>Clock 2 label</label><input name="clock2_label" value="{config.get('clock2',{}).get('label','Shanghai')}"><label>Clock 2 timezone</label><input name="clock2_tz" value="{config.get('clock2',{}).get('timezone','Asia/Shanghai')}"><label><input type="checkbox" name="enable_clock2" {'checked' if config.get('clock2',{}).get('enabled') else ''}> Enable clock 2</label><button>Save clocks</button></form></section>
<section class="card"><h2>Display</h2><form method="post" action="/save_display_settings"><label>Brightness</label><input type="number" min="0" max="100" name="brightness" value="{config.get('brightness',80)}"><button>Save brightness</button></form><form method="post" action="/test_brightness"><button class="secondary">Test brightness endpoint with default JSON separately</button></form><form method="post" action="/save_auto_power"><label><input type="checkbox" name="auto_power_enabled" {'checked' if config.get('auto_power',{}).get('enabled') else ''}> Auto power</label><label>Off time</label><input name="off_time" type="time" value="{config.get('auto_power',{}).get('off_time','23:00')}"><label>On time</label><input name="on_time" type="time" value="{config.get('auto_power',{}).get('on_time','07:00')}"><button>Save auto power</button></form></section>
<section class="card"><h2>Weather</h2><p>Current source: <code>{state.get('weather',{}).get('source')}</code></p><form method="post" action="/save_weather_api"><label>WeatherAPI key</label><input name="weather_api_key" value="{config.get('weather_api_key','')}"><label>Weather region</label><input name="weather_region" value="{config.get('weather_region','')}"><button>Save real weather settings</button></form><form method="post" action="/mock/weather"><label>Mock/real source</label><select name="source"><option value="mock" {'selected' if state.get('weather',{}).get('source')=='mock' else ''}>mock</option><option value="real" {'selected' if state.get('weather',{}).get('source')=='real' else ''}>real WeatherAPI</option></select><label><input type="checkbox" name="enabled" {'checked' if state.get('weather',{}).get('enabled') else ''}> Enabled</label><label>City</label><input name="city" value="{state.get('weather',{}).get('city','Porto')}"><label>Temperature</label><input name="temperature" value="{state.get('weather',{}).get('temperature',18.4)}"><label>Condition</label><input name="condition" value="{state.get('weather',{}).get('condition','Partly cloudy')}"><label>Icon</label><input name="icon" value="{state.get('weather',{}).get('icon','')}"><label>Humidity</label><input name="humidity" value="{state.get('weather',{}).get('humidity',72)}"><label>Wind</label><input name="windSpeed" value="{state.get('weather',{}).get('windSpeed',14.4)}"><button>Save weather mock</button></form></section>
<section class="card"><h2>Spotify</h2><p>Current: <code>{track.get('track','not playing')}</code> {track.get('artist','')}</p><form method="post" action="/save_spotify_settings"><label>Client ID</label><input name="spotify_client_id" value="{ctx['spotify_env'].get('SPOTIFY_CLIENT_ID','')}"><label>Client secret</label><input name="spotify_client_secret" value="{ctx['spotify_env'].get('SPOTIFY_CLIENT_SECRET','')}"><label>Redirect URI</label><input name="spotify_redirect_uri" value="{ctx['spotify_env'].get('SPOTIFY_REDIRECT_URI','https://httpbin.org/anything')}"><button>Save Spotify credentials</button></form><form method="post" action="/mock/spotify"><label>Source</label><select name="source"><option value="mock" {'selected' if state.get('spotify',{}).get('source')=='mock' else ''}>mock</option><option value="real" {'selected' if state.get('spotify',{}).get('source')=='real' else ''}>real</option></select><label><input type="checkbox" name="connected" {'checked' if state.get('spotify',{}).get('connected') else ''}> Connected</label><label><input type="checkbox" name="playing" {'checked' if state.get('spotify',{}).get('playing') else ''}> Playing</label><label>Track</label><select name="track_index">{''.join(f'<option value="{i}" {"selected" if i == int(state["spotify"].get("track_index",0)) else ""}>{t["track"]} — {t["artist"]}</option>' for i,t in enumerate(MOCK_TRACKS))}</select><button>Save Spotify mock</button></form><form method="get" action="/spotify/connect"><button>Connect real Spotify</button></form><form method="post" action="/spotify/manual"><label>Paste callback URL</label><input name="spotify_url"><button>Save token</button></form><form method="post" action="/spotify/disconnect"><button class="danger">Disconnect</button></form></section>
<section class="card"><h2>Forced time</h2><p>Enabled: <code>{time_cfg['enabled']}</code>. Frame injection is served by the mock display service.</p><form method="post" action="/mock/time"><label><input type="checkbox" name="enabled" {'checked' if time_cfg['enabled'] else ''}> Enable</label><label>Fixed ISO datetime</label><input name="fixed_iso" value="{time_cfg['fixed_iso']}"><label><input type="checkbox" name="tick" {'checked' if time_cfg['tick'] else ''}> Tick forward</label><button>Save forced time</button></form></section>
<section class="card"><h2>Updates</h2><p>Installed: <code>{update_state.get('installed_version')}</code></p><p>Status: <code>{'available' if update_state.get('available') else 'not available'}</code></p><form method="post" action="/save_update_settings"><label><input type="checkbox" name="auto_update" {'checked' if config.get('updates',{}).get('auto_update') else ''}> Auto update</label><label>Repo</label><input name="update_repo" value="{config.get('updates',{}).get('repo','')}"><label>Channel</label><select name="update_channel"><option value="stable" {'selected' if config.get('updates',{}).get('channel')=='stable' else ''}>stable</option><option value="pre-release" {'selected' if config.get('updates',{}).get('channel')=='pre-release' else ''}>pre-release</option></select><button>Save update settings</button></form><form method="post" action="/mock/update/pending"><label><input type="checkbox" name="mock_pending_update" {'checked' if update_state.get('mock_pending_update') else ''}> Mock pending update</label><button>Save mock flag</button></form><form method="post" action="/update/check"><button>Check update</button></form><form method="post" action="/update/install"><button class="secondary">Install endpoint test</button></form><form method="post" action="/mock/update/autoupdate"><button class="secondary">Run autoupdate test</button></form>{f'<p class="muted">{update_state.get("last_error")}</p>' if update_state.get('last_error') else ''}</section>
<section class="card"><h2>PIN</h2><p>Active: <code>{pin.get('pin') or 'none'}</code></p><form method="post" action="/mock/pin/create"><button>Create/show PIN</button></form><form method="post" action="/mock/pin/clear"><button class="danger">Clear PIN</button></form></section>
</div></main></body></html>"""


@app.route("/", methods=["GET", "POST"])
def dashboard():
    state = load_state()
    config = load_config()
    photos = load_photos()
    networks = state.get("known_networks", [])
    if request.method == "POST" and "ssid" in request.form:
        ssid = request.form["ssid"].strip()
        state["mode"] = "client"
        state["ip"] = state.get("ip") if state.get("ip") != "192.168.4.1" else "192.168.1.42"
        state["wifi_ssid"] = ssid
        state["last_wifi_message"] = f"Connected to {ssid} (mock)"
        save_state(state)
        return redirect(url_for("dashboard", msg=state["last_wifi_message"]))
    spotify_user = real_spotify_user() if state.get("spotify", {}).get("source") == "real" else ({"display_name": "Mock User", "id": "mockuser"} if state.get("spotify", {}).get("connected") else None)
    ctx = dict(mode=state.get("mode", "client"), ip=state.get("ip"), networks=networks, photos=photos, spotify_user=spotify_user, spotify_msg=request.args.get("msg"), spotify_env=read_env_values(), spotify_configured=bool(read_env_values().get("SPOTIFY_CLIENT_ID") and read_env_values().get("SPOTIFY_CLIENT_SECRET")), update_state=load_update_state(), config=config, state=state)
    if (TEMPLATES_DIR / "config_portal.html").exists():
        return render_template("config_portal.html", **ctx)
    return dashboard_fallback_html(**ctx)


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


def _set_upload_status(**updates):
    """Update mock upload progress in a thread-safe way."""
    with upload_status_lock:
        upload_status.update(updates)
        upload_status["updated_at"] = time.time()


def _snapshot_upload_status():
    """Return a copy of the current mock upload progress."""
    with upload_status_lock:
        return dict(upload_status)


def _unique_output_name(original_filename: str, existing_photos: list[str]) -> str:
    """Return a collision-safe WebP filename for a processed upload."""
    name = Path(original_filename).stem or "photo"
    base_name = secure_filename(name) or "photo"
    candidate_base = base_name
    counter = 1
    existing = set(existing_photos)

    while True:
        webp_name = f"{candidate_base}.webp"
        if webp_name not in existing and not (FULL_DIR / webp_name).exists():
            return webp_name
        candidate_base = f"{base_name}_{counter}"
        counter += 1


def _process_uploaded_photo_batch(batch_dir: Path, saved_files: list[str], batch_id: str) -> None:
    """Convert temp-uploaded originals to display-ready WebP files in the background."""
    _set_upload_status(
        active=True,
        queued=len(saved_files),
        processed=0,
        failed=0,
        last_batch_id=batch_id,
        last_message="Processing uploaded photos…",
    )

    photos = load_photos()
    processed = 0
    failed = 0

    for saved_name in saved_files:
        temp_path = batch_dir / saved_name
        original_name = saved_name.split("__", 1)[-1]

        try:
            webp_name = _unique_output_name(original_name, photos)
            full_path = FULL_DIR / webp_name
            thumb_path = THUMB_DIR / webp_name

            with Image.open(temp_path) as img:
                img = ImageOps.exif_transpose(img).convert("RGB")

                full_img = img.copy()
                full_img.thumbnail((1000, 1000))
                full_img.save(full_path, format="WEBP", quality=100, method=6)

                thumb_img = img.copy()
                thumb_img.thumbnail((250, 250))
                thumb_img.save(thumb_path, format="WEBP", quality=80, method=6)

            photos.append(webp_name)
            processed += 1
            print(f"[upload:{batch_id}] processed {original_name} → {webp_name}")

        except Exception as exc:
            failed += 1
            print(f"[upload:{batch_id}] failed to process {original_name}: {exc}")

        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
            _set_upload_status(processed=processed, failed=failed)

    if processed:
        save_photos(photos)

    try:
        shutil.rmtree(batch_dir, ignore_errors=True)
    except Exception as exc:
        print(f"[upload:{batch_id}] could not remove temp batch folder: {exc}")

    _set_upload_status(
        active=False,
        processed=processed,
        failed=failed,
        last_message=f"Processed {processed} photo(s); {failed} failed.",
    )


@app.route("/upload", methods=["POST"])
def upload_photo():
    files = request.files.getlist("photos")
    if not files or all(f.filename == "" for f in files):
        return "No file", 400

    batch_id = uuid.uuid4().hex[:12]
    batch_dir = PHOTO_TMP_DIR / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []
    for file in files:
        filename = secure_filename(file.filename)
        if not filename:
            continue

        temp_name = f"{uuid.uuid4().hex[:8]}__{filename}"
        temp_path = batch_dir / temp_name
        file.save(temp_path)
        saved_files.append(temp_name)

    if not saved_files:
        shutil.rmtree(batch_dir, ignore_errors=True)
        return "No valid files", 400

    _set_upload_status(
        active=True,
        queued=len(saved_files),
        processed=0,
        failed=0,
        last_batch_id=batch_id,
        last_message=f"Queued {len(saved_files)} photo(s) for processing.",
    )

    threading.Thread(
        target=_process_uploaded_photo_batch,
        args=(batch_dir, saved_files, batch_id),
        daemon=True,
    ).start()

    return redirect(url_for(
        "dashboard",
        msg=f"{len(saved_files)} photo(s) uploaded. Processing in the background; the frame will reload when ready.",
    ))


@app.route("/upload/status")
def upload_status_json():
    return jsonify(_snapshot_upload_status())


@app.route("/delete_selected_photos", methods=["POST"])
def delete_selected_photos():
    selected = request.form.getlist("selected_photos")
    for name in selected:
        filename = secure_filename(name)
        for folder in [FULL_DIR, THUMB_DIR]:
            path = folder / filename
            path.unlink(missing_ok=True)
    save_photos([p for p in load_photos() if p not in selected])
    return redirect(url_for("dashboard"))


@app.route("/test_brightness", methods=["POST"])
def test_brightness():
    data = request.get_json(silent=True) or {}
    try:
        level = max(0, min(100, int(data.get("level", 80))))
    except ValueError:
        return jsonify({"error": "Invalid level"}), 400
    state = load_state(); state["brightness_test_level"] = level; save_state(state)
    return jsonify({"status": "started", "level": level})


@app.route("/save_clock_settings", methods=["POST"])
def save_clock_settings():
    config = load_config()
    config["clock1"] = {"label": request.form.get("clock1_label", "Clock1"), "timezone": request.form.get("clock1_tz", "UTC")}
    config["clock2"] = {"label": request.form.get("clock2_label", "Clock2"), "timezone": request.form.get("clock2_tz", "UTC"), "enabled": bool_form("enable_clock2")}
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
    save_config(config)
    return redirect(url_for("dashboard"))


@app.route("/save_auto_power", methods=["POST"])
def save_auto_power():
    config = load_config()
    config["auto_power"] = {"enabled": bool_form("auto_power_enabled"), "off_time": request.form.get("off_time", "23:00"), "on_time": request.form.get("on_time", "07:00")}
    save_config(config)
    return redirect(url_for("dashboard"))


@app.route("/save_weather_api", methods=["POST"])
def save_weather_api():
    config = load_config()
    config["weather_api_key"] = request.form.get("weather_api_key", "")
    config["weather_region"] = request.form.get("weather_region", "")
    save_config(config)
    return redirect(url_for("dashboard"))


@app.route("/health")
def health_check():
    return jsonify({"status": "ok", "service": "mock_config_portal", "timestamp": time.time()})


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
    return jsonify({"status": "blocked", "message": "Mock environment: update install/reboot is disabled.", "updater": state})


@app.route("/save_update_settings", methods=["POST"])
def save_update_settings():
    config = load_config()
    updates = config.setdefault("updates", {})
    updates["auto_update"] = bool_form("auto_update")
    updates["repo"] = request.form.get("update_repo", updates.get("repo", "")).strip()
    updates["channel"] = request.form.get("update_channel", updates.get("channel", "stable")).strip() or "stable"
    save_config(config)
    return redirect(url_for("dashboard", msg="Mock update settings saved."))


@app.route("/versions")
def versions():
    try:
        from version_info import VERSION_INFO
        return jsonify(VERSION_INFO)
    except Exception:
        return jsonify({"mock_config_portal_service": "local"})


@app.route("/save_spotify_settings", methods=["POST"])
def save_spotify_settings():
    write_env_values({"SPOTIFY_CLIENT_ID": request.form.get("spotify_client_id", "").strip(), "SPOTIFY_CLIENT_SECRET": request.form.get("spotify_client_secret", "").strip(), "SPOTIFY_REDIRECT_URI": request.form.get("spotify_redirect_uri", "").strip() or "https://httpbin.org/anything"})
    return redirect(url_for("dashboard", msg="Spotify app settings saved for mock services. Restart mocks if needed."))


@app.route("/spotify/connect")
def spotify_connect():
    state = load_state(); state["spotify"].update({"source": "real", "connected": True}); save_state(state)
    try:
        return redirect(get_spotify_authorize_url())
    except Exception as exc:
        return redirect(url_for("dashboard", msg=f"Spotify setup error: {exc}"))


@app.route("/spotify/manual", methods=["POST"])
def spotify_manual():
    try:
        cache_spotify_token_from_url(request.form.get("spotify_url", ""))
        state = load_state(); state["spotify"].update({"source": "real", "connected": True, "playing": True}); save_state(state)
        user = real_spotify_user() or {}
        return redirect(url_for("dashboard", msg=f"Connected as {user.get('display_name') or user.get('id') or 'Spotify'}"))
    except Exception as exc:
        return redirect(url_for("dashboard", msg=f"Spotify error: {exc}"))


@app.route("/spotify/disconnect", methods=["POST"])
def spotify_disconnect():
    clear_spotify_cache()
    state = load_state(); state["spotify"].update({"source": "mock", "connected": False, "playing": False}); save_state(state)
    return redirect(url_for("dashboard", msg="Spotify disconnected."))


@app.route("/display/reload", methods=["POST"])
def display_reload():
    """Mock the config-portal Reload Display button by triggering the display SSE reload."""
    touch_for_display_reload()
    state = load_state()
    state["display_reload_requested_at"] = time.time()
    save_state(state)
    return json_or_redirect({
        "status": "ok",
        "message": "Display reload requested.",
        "mock": True,
    })


@app.route("/frame/restart", methods=["POST"])
def frame_restart():
    """Mock restarting the frame/display services without touching local processes."""
    state = load_state()
    state["frame_restart_requested_at"] = time.time()
    state["display_reload_requested_at"] = time.time()
    save_state(state)
    touch_for_display_reload()
    return json_or_redirect({
        "status": "ok",
        "message": "Mock frame restart requested. No local services were restarted.",
        "mock": True,
    })


@app.route("/screen/on", methods=["POST"])
def screen_on():
    """Mock the Screen On button by setting the shared screen state to on."""
    wake_screen()
    return json_or_redirect({
        "status": "on",
        "message": "Screen set to on.",
        "mock": True,
    })


# Local-only controls also exposed on port 5000 for convenience.
@app.route("/mock/state", methods=["POST"])
def mock_state():
    state = load_state(); state["mode"] = request.form.get("mode", state.get("mode")); state["ip"] = request.form.get("ip", state.get("ip")); state["known_networks"] = [line.strip() for line in request.form.get("known_networks", "").splitlines() if line.strip()] or state.get("known_networks", []); save_state(state)
    return redirect(url_for("dashboard"))

@app.route("/mock/weather", methods=["POST"])
def mock_weather():
    state = load_state(); state["weather"].update({"source": request.form.get("source", "mock"), "enabled": bool_form("enabled"), "city": request.form.get("city", "Porto"), "temperature": float(request.form.get("temperature", 0) or 0), "condition": request.form.get("condition", "Clear"), "icon": request.form.get("icon", ""), "humidity": int(float(request.form.get("humidity", 0) or 0)), "windSpeed": float(request.form.get("windSpeed", 0) or 0)}); save_state(state)
    return redirect(url_for("dashboard"))

@app.route("/mock/spotify", methods=["POST"])
def mock_spotify():
    state = load_state(); state["spotify"].update({"source": request.form.get("source", "mock"), "connected": bool_form("connected"), "playing": bool_form("playing"), "track_index": int(request.form.get("track_index", 0) or 0), "track_started_at": time.time(), "manual_progress_ms": 0}); save_state(state)
    return redirect(url_for("dashboard"))

@app.route("/mock/time", methods=["POST"])
def mock_time():
    state = load_state(); state["time"].update({"enabled": bool_form("enabled"), "fixed_iso": request.form.get("fixed_iso") or state["time"].get("fixed_iso"), "tick": bool_form("tick")}); save_state(state)
    return redirect(url_for("dashboard"))

@app.route("/mock/pin/create", methods=["POST"])
def mock_pin_create():
    get_or_create_config_portal_pin_record(); return redirect(url_for("dashboard"))

@app.route("/mock/pin/clear", methods=["POST"])
def mock_pin_clear():
    remove_config_portal_pin(); return redirect(url_for("dashboard"))

@app.route("/mock/update/pending", methods=["POST"])
def mock_update_pending():
    set_mock_pending_update(bool_form("mock_pending_update")); return redirect(url_for("dashboard", msg="Mock pending update flag saved."))

@app.route("/mock/update/autoupdate", methods=["POST"])
def mock_update_autoupdate():
    mock_autoupdate(); return redirect(url_for("dashboard", msg="Mock autoupdate check ran."))

if __name__ == "__main__":
    save_photos(load_photos())
    print("🖼  MementoFrame Mock — Config Portal")
    print("   Dashboard: http://localhost:5000")
    print("   PIN page : /config-portal-pin")
    app.run(host="0.0.0.0", port=5000, debug=True)
