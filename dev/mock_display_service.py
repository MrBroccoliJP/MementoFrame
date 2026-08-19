#!/usr/bin/env python3
# MementoFrame - Raspberry Pi Smart Photo Frame
# Copyright (c) 2026 João Fernandes
# Licensed under Creative Commons Attribution-NonCommercial 4.0 International.
"""Mock replacement for display_service.py, running on port 5001."""
from __future__ import annotations

import os
import json
import time
import threading
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, render_template, request, send_from_directory, url_for
from flask_cors import CORS

from mock_shared import (
    ASSETS_DIR,
    CONFIG_FILE,
    MOCK_TRACKS,
    PHOTO_JSON,
    STATIC_DIR,
    TEMPLATES_DIR,
    USERDATA_DIR,
    cache_spotify_token_from_url,
    check_for_updates_mock,
    clear_spotify_cache,
    current_track_payload,
    forced_time_payload,
    get_or_create_config_portal_pin_record,
    get_spotify_authorize_url,
    load_config,
    load_state,
    load_update_state,
    mock_autoupdate,
    mock_install_update_blocked,
    next_track,
    pin_response_payload,
    remove_config_portal_pin,
    save_config,
    save_state,
    set_mock_pending_update,
    time_override_script,
    weather_payload,
)

app = Flask(__name__, template_folder=str(TEMPLATES_DIR), static_folder=str(STATIC_DIR), static_url_path="/static")
CORS(app)
weather_refresh_revision = 0


def bool_form(name: str) -> bool:
    return name in request.form


def frame_html() -> str:
    template_name = "kiosk_display.html" if (TEMPLATES_DIR / "kiosk_display.html").exists() else "index.html"
    if not (TEMPLATES_DIR / template_name).exists():
        return redirect(url_for("mock_management")).get_data(as_text=True)
    html = render_template(template_name)
    tag = '<script src="/mock/time-override.js"></script>\n'
    if "</head>" in html:
        return html.replace("</head>", tag + "</head>", 1)
    return tag + html


def mock_management_html() -> str:
    state = load_state()
    config = load_config()
    pin = pin_response_payload()
    track = current_track_payload()
    update_state = load_update_state()
    time_cfg = forced_time_payload()
    weather = state["weather"]
    weather_provider = config.get("weather_provider", "openmeteo")
    weatherapi_ready = bool(config.get("weather_api_key"))
    google_ready = bool(config.get("google_weather_api_key") and config.get("weather_latitude") is not None and config.get("weather_longitude") is not None)
    openmeteo_ready = bool(config.get("weather_latitude") is not None and config.get("weather_longitude") is not None)
    networks = "\n".join(state.get("known_networks", []))
    return f"""
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>MementoFrame Mock Controls</title>
<link rel="stylesheet" href="/static/config_portal.css">
<style>
.mock-dashboard .dashboard-hero{{margin-bottom:18px}}.mock-dashboard .dashboard-meta{{max-width:560px}}
.mock-links{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px}}.mock-links a{{padding:9px 12px;border:1px solid var(--dashboard-border);border-radius:12px;color:#d7c5ff;background:rgba(183,148,255,.07);font-size:.78rem;font-weight:750;text-decoration:none}}.mock-links a:hover{{background:rgba(183,148,255,.14)}}
.mock-dashboard .settings-content>.card{{scroll-margin-top:18px;margin:0 0 12px;overflow:hidden;border:1px solid var(--dashboard-border);border-radius:20px;background:var(--dashboard-surface);box-shadow:0 14px 42px rgba(0,0,0,.16)}}.mock-dashboard .card>h2{{margin:0;padding:20px;border-bottom:1px solid rgba(255,255,255,.065);color:#f0f5f2;background:rgba(255,255,255,.018);font-size:1rem;letter-spacing:-.01em;text-transform:none}}.mock-dashboard .card>h2::before{{display:inline-grid;width:30px;height:30px;margin-right:12px;place-items:center;border:1px solid rgba(183,148,255,.32);border-radius:9px;color:var(--dashboard-accent);background:rgba(183,148,255,.1);font-size:.62rem;content:'MO'}}
.mock-dashboard .card>p,.mock-dashboard .card>.muted{{margin:14px 20px;color:var(--dashboard-muted);line-height:1.55}}.mock-dashboard .card>p a{{color:var(--dashboard-accent)}}
.mock-dashboard .section>p,.mock-dashboard .section>.muted{{margin:14px 20px;color:var(--dashboard-muted);line-height:1.55}}.mock-dashboard .section>p a{{color:var(--dashboard-accent)}}
.mock-dashboard input[type=number],.mock-dashboard textarea{{min-height:46px;border-color:rgba(255,255,255,.11);border-radius:12px;color:#eef3f0;background:#101311}}.mock-dashboard textarea{{resize:vertical}}
.mock-dashboard label:has(input[type=checkbox]){{display:flex;align-items:center;min-height:42px;padding:9px 11px;border:1px solid rgba(255,255,255,.08);border-radius:12px;background:rgba(255,255,255,.025);cursor:pointer}}.mock-dashboard label:has(input[type=checkbox]):hover{{border-color:rgba(183,148,255,.28)}}
.mock-dashboard form>button.secondary{{border:1px solid rgba(183,148,255,.28);color:#d7c5ff;background:rgba(183,148,255,.09);box-shadow:none}}.mock-dashboard form>button.danger{{color:#fff;background:#a92632;box-shadow:none}}.mock-dashboard hr{{width:100%;border:0;border-top:1px solid var(--dashboard-border);margin:8px 0}}
.mock-dashboard .status-pill.ok{{border-color:rgba(76,217,130,.25);color:#dff9e8;background:rgba(38,150,82,.16)}}.mock-dashboard .status-pill.warn{{border-color:rgba(245,180,68,.28);color:#ffe8bd;background:rgba(181,118,26,.16)}}
.scenario-panel{{display:flex;flex-direction:column;gap:.9rem;padding:14px;border:1px solid rgba(183,148,255,.15);border-radius:15px;background:rgba(183,148,255,.035)}}.scenario-panel[hidden]{{display:none}}.scenario-panel__title{{margin:0;color:var(--dashboard-accent);font-size:.7rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase}}.scenario-panel--actions{{margin:0 20px 18px}}.scenario-panel--actions form{{margin:0;padding:0;border:0}}.scenario-panel--actions form+form{{padding:0;border:0}}
.mock-dashboard .provider-switch{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:8px;margin:0;padding:0;border:0}}.mock-dashboard .provider-switch legend{{margin-bottom:8px;color:var(--dashboard-muted);font-size:.78rem}}.mock-dashboard .provider-switch label{{display:flex;align-items:center;gap:8px;min-height:44px;padding:10px 12px;border:1px solid rgba(255,255,255,.09);border-radius:12px;background:rgba(255,255,255,.025);cursor:pointer}}.mock-dashboard .provider-switch label:has(input:checked){{border-color:rgba(183,148,255,.55);color:#f3edff;background:rgba(183,148,255,.13)}}
.mock-dashboard .section form+form,.mock-dashboard .card form+form{{margin-top:0}}@media(max-width:700px){{.mock-links{{overflow-x:auto;flex-wrap:nowrap}}.mock-links a{{flex:0 0 auto}}}}
</style></head><body class="frame-theme config-dashboard mock-dashboard"><div class="container">
<header class="dashboard-hero"><div class="dashboard-brand"><span class="dashboard-brand__mark" aria-hidden="true">M</span><div><p class="dashboard-eyebrow">Development workspace</p><h1>Mock control center</h1><p class="dashboard-subtitle">Simulate frame states and integrations without Raspberry Pi hardware.</p></div></div><div class="dashboard-meta"><span class="status-pill">Weather: {weather.get('source', 'mock')}</span><span class="status-pill {'ok' if openmeteo_ready else 'warn'}">Open-Meteo {'ready' if openmeteo_ready else 'setup needed'}</span><span class="status-pill {'ok' if weatherapi_ready else 'warn'}">WeatherAPI {'ready' if weatherapi_ready else 'setup needed'}</span><span class="status-pill {'ok' if google_ready else 'warn'}">Google {'ready' if google_ready else 'setup needed'}</span><span class="status-pill">Spotify: {state['spotify'].get('source', 'mock')}</span></div></header>
<nav class="mock-links" aria-label="Developer links"><a href="/">Open frame UI</a><a href="http://localhost:5000">Configuration dashboard</a><a href="/weather.json">Weather JSON</a><a href="/spotify.json">Spotify JSON</a><a href="/status.json">Status JSON</a></nav>
<div class="dashboard-shell"><aside class="settings-sidebar"><p class="settings-sidebar__label">Mock scenarios</p><nav class="settings-nav" aria-label="Mock control sections"><a href="#system-mock"><span>Sy</span>System</a><a href="#time-mock"><span>Ti</span>Time</a><a href="#pin-mock"><span>Pi</span>PIN</a><a href="#spotify-mock"><span>Sp</span>Spotify</a><a href="#weather-mock"><span>We</span>Weather</a><a href="#updates-mock"><span>Up</span>Updates</a></nav><p class="sidebar-note">Open a section, change the scenario, and save it. The frame updates immediately where supported.</p></aside><main class="settings-content">
<section class="card"><h2>System/AP mode</h2><p>Mode: <code>{state['mode']}</code>, IP: <code>{state['ip']}</code>, screen: <code>{state['screen']}</code></p><form method="post" action="/mock/state"><label>Mode</label><select name="mode"><option value="client" {'selected' if state['mode']=='client' else ''}>client / Wi‑Fi</option><option value="ap" {'selected' if state['mode']=='ap' else ''}>ap / setup hotspot</option><option value="unknown" {'selected' if state['mode']=='unknown' else ''}>unknown</option></select><label>IP address</label><input name="ip" value="{state['ip']}"><label>Wi‑Fi SSID</label><input name="wifi_ssid" value="{state.get('wifi_ssid','')}"><label>AP SSID</label><input name="ap_ssid" value="{state.get('ap_ssid','MementoFrame')}"><label>Known networks, one per line</label><textarea name="known_networks" rows="4">{networks}</textarea><button>Save system state</button></form><form method="post" action="/dev/toggle_mode"><button class="secondary">Toggle AP/client</button></form></section>
<section class="card"><h2>Forced time</h2><p>Override enabled: <code>{time_cfg['enabled']}</code></p><form method="post" action="/mock/time"><label><input type="checkbox" name="enabled" {'checked' if time_cfg['enabled'] else ''}> Enable browser Date override on frame page</label><label>Fixed ISO datetime</label><input name="fixed_iso" value="{time_cfg['fixed_iso']}" placeholder="2026-05-15T10:08:00+01:00"><label><input type="checkbox" name="tick" {'checked' if time_cfg['tick'] else ''}> Let forced time continue ticking</label><button>Save time override</button></form><p class="muted">The frame route injects <code>/mock/time-override.js</code> before the frontend runs.</p></section>
<section class="card"><h2>Config portal PIN</h2><p>Active PIN: <code>{pin.get('pin') or 'none'}</code>{' — ' + str(pin.get('seconds_remaining')) + 's remaining' if pin.get('active') else ''}</p><form method="post" action="/mock/pin/create"><button>Create/show PIN</button></form><form method="post" action="/mock/pin/clear"><button class="danger">Clear PIN</button></form><p class="muted">Current real endpoint: <code>/config_portal_pin.json</code>. Legacy aliases are also included for local testing.</p></section>
<section class="card"><h2>Spotify</h2><p>Source: <code>{state['spotify'].get('source','mock')}</code></p><p>Current: <code>{track.get('track','not playing')}</code> {('— ' + track.get('artist','')) if track.get('artist') else ''}</p>{f'<p class="muted">{track.get("error")}</p>' if track.get('error') else ''}<form method="post" action="/mock/spotify"><label>Data source</label><select name="source"><option value="mock" {'selected' if state['spotify'].get('source','mock')=='mock' else ''}>mock data</option><option value="real" {'selected' if state['spotify'].get('source')=='real' else ''}>real Spotify</option></select><label><input type="checkbox" name="connected" {'checked' if state['spotify'].get('connected') else ''}> Connected</label><label><input type="checkbox" name="playing" {'checked' if state['spotify'].get('playing') else ''}> Playing</label><label>Mock track</label><select name="track_index">{''.join(f'<option value="{i}" {"selected" if i == int(state["spotify"].get("track_index",0)) else ""}>{t["track"]} — {t["artist"]}</option>' for i,t in enumerate(MOCK_TRACKS))}</select><button>Save Spotify</button></form><form method="post" action="/dev/toggle_spotify"><button class="secondary">Toggle play</button></form><form method="post" action="/dev/next_track"><button class="secondary">Next track</button></form><form method="get" action="/spotify/connect"><button>Connect real Spotify</button></form><form method="post" action="/spotify/manual"><label>Paste Spotify callback URL</label><input name="spotify_url" placeholder="https://httpbin.org/anything?code=..."><button>Save real Spotify token</button></form><form method="post" action="/spotify/disconnect"><button class="danger">Disconnect Spotify</button></form></section>
<section class="card"><h2>Weather</h2><p>Source: <code>{weather.get('source','mock')}</code></p><p><a href="/weather.json">Weather JSON</a></p><form method="post" action="/mock/weather"><label>Data source</label><select name="source"><option value="mock" {'selected' if weather.get('source','mock')=='mock' else ''}>mock data</option><option value="real" {'selected' if weather.get('source')=='real' else ''}>real WeatherAPI</option></select><label><input type="checkbox" name="enabled" {'checked' if weather.get('enabled') else ''}> Enabled / show weather</label><label><input type="checkbox" name="forecast_enabled" {'checked' if weather.get('forecast_enabled', True) else ''}> Include mock forecast data</label><label>City / alert matching area</label><input name="city" value="{weather.get('city','')}"><label>Temperature °C</label><input name="temperature" type="number" step="0.1" value="{weather.get('temperature',0)}"><label>Condition text</label><input name="condition" value="{weather.get('condition','')}"><label>WeatherAPI condition code</label><input name="conditionCode" type="number" value="{weather.get('conditionCode',1000)}"><label><input type="checkbox" name="isDay" {'checked' if weather.get('isDay', True) else ''}> Daytime condition</label><label>UV index</label><input name="uv" type="number" step="0.1" value="{weather.get('uv',0)}"><label>Moon phase</label><select name="moonPhase">{''.join(f'<option value="{phase}" {"selected" if str(weather.get("moonPhase","Waxing Crescent")) == phase else ""}>{phase}</option>' for phase in ["New Moon","Waxing Crescent","First Quarter","Waxing Gibbous","Full Moon","Waning Gibbous","Last Quarter","Waning Crescent"])}</select><label>Humidity %</label><input name="humidity" type="number" value="{weather.get('humidity',0)}"><label>Wind kph</label><input name="windSpeed" type="number" step="0.1" value="{weather.get('windSpeed',0)}"><hr><label><input type="checkbox" name="alerts_enabled" {'checked' if weather.get('alerts_enabled') else ''}> Include mock weather alert</label><label>Alert event</label><input name="alert_event" value="{weather.get('alert_event','Thunderstorm warning')}"><label>Alert headline</label><input name="alert_headline" value="{weather.get('alert_headline','Mock thunderstorm warning')}"><label>Alert severity</label><select name="alert_severity">{''.join(f'<option value="{sev}" {"selected" if str(weather.get("alert_severity","Moderate")) == sev else ""}>{sev}</option>' for sev in ["Minor","Moderate","Severe","Extreme"])}</select><label>Alert areas</label><input name="alert_areas" value="{weather.get('alert_areas', weather.get('city', 'Porto'))}"><label>Alert description</label><textarea name="alert_desc" rows="3">{weather.get('alert_desc','Mock alert: thunderstorms are possible in your area.')}</textarea><label>Alert instruction</label><input name="alert_instruction" value="{weather.get('alert_instruction','Stay indoors if thunder is heard.')}"><label><input type="checkbox" name="alert_second_enabled" {'checked' if weather.get('alert_second_enabled') else ''}> Include second mock alert</label><label>Second alert event</label><input name="alert_second_event" value="{weather.get('alert_second_event','High temperature warning')}"><label>Second alert headline</label><input name="alert_second_headline" value="{weather.get('alert_second_headline','Mock heat warning')}"><label>Second alert severity</label><select name="alert_second_severity">{''.join(f'<option value="{sev}" {"selected" if str(weather.get("alert_second_severity","Severe")) == sev else ""}>{sev}</option>' for sev in ["Minor","Moderate","Severe","Extreme"])}</select><label>Second alert areas</label><input name="alert_second_areas" value="{weather.get('alert_second_areas','Portugal')}"><label>Second alert description</label><textarea name="alert_second_desc" rows="3">{weather.get('alert_second_desc','Mock alert: very hot weather is expected.')}</textarea><label>Second alert instruction</label><input name="alert_second_instruction" value="{weather.get('alert_second_instruction','Drink water and avoid direct sun.')}"><button>Save weather</button></form><p class="muted">Mock weather uses local <code>/assets/Weather/meteoicons/fill</code> icons. Alert areas are filtered against the city/area above. Use a broader area like <code>Portugal</code> to test country-wide alerts.</p></section>
<section class="card"><h2>Software updates</h2><p>Installed: <code>{update_state.get('installed_version') or 'unknown'}</code></p><p>Latest: <code>{update_state.get('latest_version') or update_state.get('latest_tag') or 'not checked'}</code></p><p>Status: <code>{'mock pending update' if update_state.get('mock_pending_update') else ('available' if update_state.get('available') else 'not available')}</code></p><form method="post" action="/mock/update/pending"><label><input type="checkbox" name="mock_pending_update" {'checked' if update_state.get('mock_pending_update') else ''}> Mock pending update</label><button>Save mock flag</button></form><form method="post" action="/update/check"><button>Check GitHub releases</button></form><form method="post" action="/update/install"><button class="secondary">Install endpoint test</button></form><form method="post" action="/mock/update/autoupdate"><button class="secondary">Run autoupdate test</button></form>{f'<p class="muted">{update_state.get("last_error")}</p>' if update_state.get('last_error') else ''}<p class="muted">Mocks never install, reboot, or change project files.</p></section>
</main></div><script>
(() => {{
  const sectionIds = ['system-mock', 'time-mock', 'pin-mock', 'spotify-mock', 'weather-mock', 'updates-mock'];
  document.querySelectorAll('.settings-content > .card').forEach((card, index) => {{
    card.id = sectionIds[index] || `mock-section-${{index}}`;
  }});
  document.querySelectorAll('.settings-nav a').forEach((link) => {{
    link.addEventListener('click', () => document.querySelector(link.hash)?.scrollIntoView({{ behavior: 'smooth', block: 'start' }}));
  }});

  function groupChildren(form, startIndex, endIndex, id, title) {{
    const panel = document.createElement('div');
    panel.id = id;
    panel.className = 'scenario-panel';
    panel.innerHTML = `<p class="scenario-panel__title">${{title}}</p>`;
    [...form.children].slice(startIndex, endIndex).forEach((child) => panel.appendChild(child));
    form.insertBefore(panel, form.lastElementChild);
    return panel;
  }}

  function groupForms(forms, id, title) {{
    const panel = document.createElement('div');
    panel.id = id;
    panel.className = 'scenario-panel scenario-panel--actions';
    panel.innerHTML = `<p class="scenario-panel__title">${{title}}</p>`;
    forms[0]?.parentNode.insertBefore(panel, forms[0]);
    forms.forEach((form) => panel.appendChild(form));
    return panel;
  }}

  const spotifySource = document.querySelector('form[action="/mock/spotify"] select[name="source"]');
  const spotifyForm = spotifySource?.closest('form');
  if (spotifyForm) {{
    const mockFields = groupChildren(spotifyForm, 2, -1, 'spotify-mock-settings', 'Simulated playback');
    const card = spotifyForm.closest('.card');
    const mockActions = groupForms([
      card.querySelector('form[action="/dev/toggle_spotify"]'),
      card.querySelector('form[action="/dev/next_track"]')
    ].filter(Boolean), 'spotify-mock-actions', 'Playback actions');
    const realSettings = groupForms([
      card.querySelector('form[action="/spotify/connect"]'),
      card.querySelector('form[action="/spotify/manual"]'),
      card.querySelector('form[action="/spotify/disconnect"]')
    ].filter(Boolean), 'spotify-real-settings', 'Spotify connection');

    const updateSpotifyPanels = () => {{
      const isMock = spotifySource.value === 'mock';
      mockFields.hidden = !isMock;
      mockActions.hidden = !isMock;
      realSettings.hidden = isMock;
    }};
    spotifySource.addEventListener('change', updateSpotifyPanels);
    updateSpotifyPanels();
  }}

  const sourceSelect = document.querySelector('form[action="/mock/weather"] select[name="source"]');
  if (!sourceSelect) return;
  const savedWeatherSource = '{weather.get("source", "mock")}';
  const selectedSource = ['mock', 'openmeteo', 'weatherapi', 'google'].includes(savedWeatherSource)
    ? savedWeatherSource
    : (savedWeatherSource === 'real' ? '{weather_provider}' : 'mock');
  const weatherForm = sourceSelect.closest('form');
  const sourceLabel = sourceSelect.previousElementSibling;
  const sourceSwitch = document.createElement('fieldset');
  sourceSwitch.className = 'provider-switch';
  const weatherSources = [
    ['mock', 'Simulated weather'],
    ['openmeteo', 'Live Open-Meteo'],
    ['weatherapi', 'Live WeatherAPI'],
    ['google', 'Live Google Weather']
  ];
  sourceSwitch.innerHTML = `<legend>Weather data source</legend>${{weatherSources.map(([value, label]) => `<label><input type="radio" name="source" value="${{value}}" ${{value === selectedSource ? 'checked' : ''}}> ${{label}}</label>`).join('')}}`;
  sourceLabel?.remove();
  sourceSelect.replaceWith(sourceSwitch);

  const weatherFields = groupChildren(weatherForm, 2, -1, 'weather-mock-settings', 'Simulated weather data');
  const liveSettings = document.createElement('div');
  liveSettings.id = 'weather-live-settings';
  liveSettings.className = 'scenario-panel';
  liveSettings.innerHTML = `<p class="scenario-panel__title">Live provider settings</p>
    <div id="mock-weatherapi-settings">
      <label>WeatherAPI.com key</label><input type="password" name="weather_api_key" value="{config.get('weather_api_key', '')}" autocomplete="off">
      <label>WeatherAPI location</label><input name="weather_region" value="{config.get('weather_region', '')}" placeholder="e.g. Lisbon, Portugal">
    </div>
    <div id="mock-google-settings">
      <label>Google Weather API key</label><input type="password" name="google_weather_api_key" value="{config.get('google_weather_api_key', '')}" autocomplete="off">
    </div>
    <div id="mock-coordinate-settings">
      <label>City</label><input name="weather_city" value="{config.get('weather_city', '')}">
      <label>Region / state</label><input name="weather_state" value="{config.get('weather_region', '')}">
      <label>Country</label><input name="weather_country" value="{config.get('weather_country', '')}">
      <label>Latitude</label><input type="number" step="any" name="weather_latitude" value="{config.get('weather_latitude') if config.get('weather_latitude') is not None else ''}">
      <label>Longitude</label><input type="number" step="any" name="weather_longitude" value="{config.get('weather_longitude') if config.get('weather_longitude') is not None else ''}">
    </div>`;
  weatherForm.insertBefore(liveSettings, weatherForm.lastElementChild);

  const updateWeatherPanels = () => {{
    const selected = weatherForm.querySelector('input[name="source"]:checked')?.value || 'mock';
    weatherFields.hidden = selected !== 'mock';
    liveSettings.hidden = selected === 'mock';
    liveSettings.querySelector('#mock-weatherapi-settings').hidden = selected !== 'weatherapi';
    liveSettings.querySelector('#mock-google-settings').hidden = selected !== 'google';
    liveSettings.querySelector('#mock-coordinate-settings').hidden = !['openmeteo', 'google'].includes(selected);
  }};
  weatherForm.querySelectorAll('input[name="source"]').forEach((radio) => radio.addEventListener('change', updateWeatherPanels));
  updateWeatherPanels();
}})();
</script></div></body></html>"""


@app.route("/")
def home():
    return frame_html()


@app.route("/mock")
def mock_management():
    return mock_management_html()


@app.route("/mock/time-override.js")
def mock_time_override_js():
    return Response(time_override_script(), mimetype="application/javascript")


@app.route("/mock/time.json")
def mock_time_json():
    return jsonify(forced_time_payload())


@app.route("/assets/<path:filename>")
def serve_assets(filename):
    return send_from_directory(ASSETS_DIR, filename) if (ASSETS_DIR / filename).exists() else ("", 404)


@app.route("/userdata/<path:filename>")
def serve_userdata(filename):
    return send_from_directory(USERDATA_DIR, filename) if (USERDATA_DIR / filename).exists() else jsonify({})


@app.route("/config.json")
def serve_config():
    return jsonify(load_config())


@app.route("/spotify.json")
def spotify_status():
    return jsonify(current_track_payload())


@app.route("/weather.json")
def weather_status():
    payload = weather_payload()
    return jsonify(payload)


@app.route("/weather/refresh", methods=["POST"])
def weather_refresh():
    global weather_refresh_revision
    payload = weather_payload()
    if not payload.get("available"):
        weather_refresh_revision += 1
        return jsonify({"status": "error", "message": payload["error"]}), 503
    weather_refresh_revision += 1
    return jsonify({
        "status": "ok",
        "message": "Mock weather information refreshed.",
        "weather": payload,
    })


@app.route("/config_portal_pin.json")
def config_portal_pin_json():
    return jsonify(pin_response_payload())


@app.route("/config_pin.json")
@app.route("/frame_pin.json")
@app.route("/ap_pin.json")
def legacy_pin_aliases():
    return jsonify(pin_response_payload())


@app.route("/status.json")
def system_status():
    state = load_state()
    return jsonify({"mode": state.get("mode", "client"), "ip": state.get("ip"), "uptime": time.time(), "screen": state.get("screen"), "ap_ssid": state.get("ap_ssid"), "wifi_ssid": state.get("wifi_ssid"), "clients_connected": state.get("clients_connected", 0)})


@app.route("/health")
def health_check():
    return jsonify({"status": "ok", "timestamp": time.time(), "service": "mock_display_service"})


@app.route("/get_ip")
def get_ip():
    return jsonify({"ip": load_state().get("ip")})


@app.route("/versions")
def versions():
    try:
        from version_info import VERSION_INFO
        return jsonify(VERSION_INFO)
    except Exception:
        return jsonify({"mock_display_service": "local"})


@app.route("/update_status.json")
def update_status_json():
    return jsonify(load_update_state())


@app.route("/update/status")
def update_status():
    return jsonify(load_update_state())


@app.route("/update/stream")
def update_stream():
    def event_stream():
        last_payload = None
        while True:
            state = load_update_state()
            payload = json.dumps(state, sort_keys=True)
            if payload != last_payload:
                last_payload = payload
                yield f"event: state\ndata: {payload}\n\n"
            else:
                yield ": heartbeat\n\n"
            time.sleep(1)

    return Response(event_stream(), mimetype="text/event-stream")


@app.route("/update/check", methods=["POST"])
def update_check():
    state = check_for_updates_mock()
    return jsonify({"status": "ok" if not state.get("last_error") else "error", "updater": state})


@app.route("/update/install", methods=["POST"])
def update_install():
    state = mock_install_update_blocked()
    return jsonify({"status": "started", "message": "Mock environment: simulated update started; install/reboot are disabled.", "updater": state})


@app.route("/config/stream")
def config_stream():
    watched = {CONFIG_FILE: "config", PHOTO_JSON: "reload"}
    def event_stream():
        last_weather_revision = weather_refresh_revision
        mtimes = {str(f): f.stat().st_mtime if f.exists() else 0 for f in watched}
        yield "data: ready\n\n"
        while True:
            time.sleep(1)
            events = []
            for f, event_name in watched.items():
                key = str(f)
                mtime = f.stat().st_mtime if f.exists() else 0
                if mtime != mtimes.get(key):
                    mtimes[key] = mtime
                    events.append(event_name)
            if weather_refresh_revision != last_weather_revision:
                last_weather_revision = weather_refresh_revision
                events.append("weather")
            if events:
                for event_name in dict.fromkeys(events):
                    yield f"data: {event_name}\n\n"
            else:
                yield ": heartbeat\n\n"
    return Response(event_stream(), mimetype="text/event-stream")


@app.route("/screen/on", methods=["POST"])
def screen_on():
    state = load_state(); state["screen"] = "on"; save_state(state)
    return jsonify({"status": "on"})


@app.route("/screen/off", methods=["POST"])
def screen_off():
    state = load_state(); state["screen"] = "off"; save_state(state)
    return jsonify({"status": "off"})


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


@app.route("/mock/time", methods=["POST"])
def save_mock_time_form():
    state = load_state()
    state["time"].update({"enabled": bool_form("enabled"), "fixed_iso": request.form.get("fixed_iso") or state["time"].get("fixed_iso"), "tick": bool_form("tick")})
    save_state(state)
    return redirect(url_for("mock_management"))


@app.route("/mock/spotify", methods=["POST"])
def save_mock_spotify_form():
    state = load_state()
    spotify = state["spotify"]
    spotify["source"] = request.form.get("source", spotify.get("source", "mock"))
    spotify["connected"] = bool_form("connected")
    spotify["playing"] = bool_form("playing")
    spotify["track_index"] = int(request.form.get("track_index", 0) or 0)
    spotify["track_started_at"] = time.time()
    spotify["manual_progress_ms"] = 0
    save_state(state)
    return redirect(url_for("mock_management"))


@app.route("/mock/weather", methods=["POST"])
def save_mock_weather_form():
    global weather_refresh_revision
    state = load_state()
    config = load_config()
    source = request.form.get("source", "mock").strip().lower()
    if source not in {"mock", "openmeteo", "weatherapi", "google"}:
        source = "mock"
    state["weather"].update({
        "source": source,
        "enabled": bool_form("enabled"),
        "forecast_enabled": bool_form("forecast_enabled"),
        "city": request.form.get("city", "Porto"),
        "temperature": float(request.form.get("temperature", 0) or 0),
        "condition": request.form.get("condition", "Clear"),
        "conditionCode": int(float(request.form.get("conditionCode", 1000) or 1000)),
        "isDay": bool_form("isDay"),
        "uv": float(request.form.get("uv", 0) or 0),
        "moonPhase": request.form.get("moonPhase", "Waxing Crescent"),
        "humidity": int(float(request.form.get("humidity", 0) or 0)),
        "windSpeed": float(request.form.get("windSpeed", 0) or 0),
        "alerts_enabled": bool_form("alerts_enabled"),
        "alert_event": request.form.get("alert_event", "Thunderstorm warning"),
        "alert_headline": request.form.get("alert_headline", "Mock thunderstorm warning"),
        "alert_severity": request.form.get("alert_severity", "Moderate"),
        "alert_areas": request.form.get("alert_areas", request.form.get("city", "Porto")),
        "alert_desc": request.form.get("alert_desc", "Mock alert: thunderstorms are possible in your area."),
        "alert_instruction": request.form.get("alert_instruction", "Stay indoors if thunder is heard."),
        "alert_second_enabled": bool_form("alert_second_enabled"),
        "alert_second_event": request.form.get("alert_second_event", "High temperature warning"),
        "alert_second_headline": request.form.get("alert_second_headline", "Mock heat warning"),
        "alert_second_severity": request.form.get("alert_second_severity", "Severe"),
        "alert_second_areas": request.form.get("alert_second_areas", "Portugal"),
        "alert_second_desc": request.form.get("alert_second_desc", "Mock alert: very hot weather is expected."),
        "alert_second_instruction": request.form.get("alert_second_instruction", "Drink water and avoid direct sun."),
    })
    if source != "mock":
        config["weather_provider"] = source
        config["weather_api_key"] = request.form.get("weather_api_key", config.get("weather_api_key", "")).strip()
        config["google_weather_api_key"] = request.form.get("google_weather_api_key", config.get("google_weather_api_key", "")).strip()
        if source == "weatherapi":
            config["weather_region"] = request.form.get("weather_region", config.get("weather_region", "")).strip()
        else:
            city = request.form.get("weather_city", "").strip()
            region = request.form.get("weather_state", "").strip()
            country = request.form.get("weather_country", "").strip()
            try:
                latitude = float(request.form.get("weather_latitude", ""))
                longitude = float(request.form.get("weather_longitude", ""))
            except (TypeError, ValueError):
                latitude = longitude = None
            config.update({
                "weather_city": city,
                "weather_region": region,
                "weather_country": country,
                "weather_latitude": latitude,
                "weather_longitude": longitude,
                "weather_location_name": ", ".join(filter(None, [city, region, country])),
            })
        save_config(config)
    save_state(state)
    weather_refresh_revision += 1
    return redirect(url_for("mock_management"))


@app.route("/mock/pin/create", methods=["POST"])
def mock_pin_create():
    get_or_create_config_portal_pin_record()
    return redirect(url_for("mock_management"))


@app.route("/mock/pin/clear", methods=["POST"])
def mock_pin_clear():
    remove_config_portal_pin()
    return redirect(url_for("mock_management"))


@app.route("/mock/update/pending", methods=["POST"])
def mock_update_pending():
    state = set_mock_pending_update(bool_form("mock_pending_update"))
    return jsonify(state) if request.accept_mimetypes.best == "application/json" else redirect(url_for("mock_management"))


@app.route("/mock/update/autoupdate", methods=["POST"])
def mock_update_autoupdate():
    mock_autoupdate()
    return jsonify(load_update_state()) if request.accept_mimetypes.best == "application/json" else redirect(url_for("mock_management"))


@app.route("/dev/state", methods=["GET", "POST"])
def dev_state():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        state = load_state()
        for key in ["screen", "mode", "ip", "ap_ssid", "wifi_ssid", "clients_connected"]:
            if key in data:
                state[key] = data[key]
        for key in ["spotify", "weather", "time"]:
            if isinstance(data.get(key), dict):
                state[key].update(data[key])
        save_state(state)
    return jsonify(load_state())


@app.route("/dev/toggle_spotify", methods=["POST"])
def toggle_spotify():
    state = load_state(); state["spotify"]["playing"] = not state["spotify"].get("playing", True); state["spotify"]["connected"] = True; state["spotify"]["track_started_at"] = time.time(); state["spotify"]["manual_progress_ms"] = current_track_payload().get("progress", 0); save_state(state)
    return jsonify(load_state()) if request.accept_mimetypes.best == "application/json" else redirect(url_for("mock_management"))


@app.route("/dev/next_track", methods=["POST"])
def next_track_route():
    payload = next_track()
    return jsonify(payload) if request.accept_mimetypes.best == "application/json" else redirect(url_for("mock_management"))


@app.route("/dev/toggle_mode", methods=["POST"])
def toggle_mode():
    state = load_state(); state["mode"] = "ap" if state.get("mode") == "client" else "client"; state["ip"] = "192.168.4.1" if state["mode"] == "ap" else "192.168.1.42"; save_state(state)
    return jsonify(load_state()) if request.accept_mimetypes.best == "application/json" else redirect(url_for("mock_management"))


@app.route("/spotify/connect")
def spotify_connect():
    state = load_state(); state["spotify"].update({"source": "real", "connected": True}); save_state(state)
    try:
        return redirect(get_spotify_authorize_url())
    except Exception as exc:
        return jsonify({"error": str(exc), "hint": "Install spotipy and add Spotify credentials to .env"}), 500


@app.route("/spotify/disconnect", methods=["POST"])
def spotify_disconnect():
    clear_spotify_cache(); state = load_state(); state["spotify"].update({"source": "mock", "connected": False, "playing": False}); save_state(state)
    return redirect(url_for("mock_management"))


def _autoupdate_worker():
    while True:
        time.sleep(60 * 60)
        try:
            state = load_update_state()
            if not state.get("auto_update") or state.get("update_in_progress"):
                continue
            checked = check_for_updates_mock()
            if checked.get("available"):
                mock_autoupdate()
        except Exception as exc:
            print(f"[mock-autoupdate] {exc}")


threading.Thread(target=_autoupdate_worker, daemon=True).start()

if __name__ == "__main__":
    print("🖼  MementoFrame Mock — Display Service")
    print("   Frame/API:  http://localhost:5001")
    print("   Mock UI:    http://localhost:5001/mock")
    app.run(host="0.0.0.0", port=5001, debug=True)
