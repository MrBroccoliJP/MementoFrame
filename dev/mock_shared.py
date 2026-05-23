#!/usr/bin/env python3
# MementoFrame - Raspberry Pi Smart Photo Frame
# Copyright (c) 2026 João Fernandes
# Licensed under Creative Commons Attribution-NonCommercial 4.0 International.
"""Shared helpers for the local MementoFrame mock services.

These helpers intentionally keep all mock-only runtime state in dev/runtime while
using the real project templates/static/userdata folders, so the config portal
and display frontend can be tested locally without Raspberry Pi hardware.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from copy import deepcopy
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE_DIR = Path(__file__).resolve().parent

# Resolve the real mementoframe project folder robustly.
# Supported layouts:
#   repo-root/dev/mock_*.py + repo-root/mementoframe/config_portal_service.py
#   repo-root/mementoframe/dev/mock_*.py + repo-root/mementoframe/config_portal_service.py
#   repo-root/mementoframe/mock_*.py beside the real service files
if (BASE_DIR / "config_portal_service.py").exists() and (BASE_DIR / "display_service.py").exists():
    PROJECT_ROOT = BASE_DIR
elif (BASE_DIR.parent / "config_portal_service.py").exists() and (BASE_DIR.parent / "display_service.py").exists():
    PROJECT_ROOT = BASE_DIR.parent
elif (BASE_DIR.parent / "mementoframe" / "config_portal_service.py").exists() and (BASE_DIR.parent / "mementoframe" / "display_service.py").exists():
    PROJECT_ROOT = BASE_DIR.parent / "mementoframe"
else:
    PROJECT_ROOT = BASE_DIR.parent / "mementoframe"

REPO_ROOT = PROJECT_ROOT.parent

RUNTIME_DIR = BASE_DIR / "runtime"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = PROJECT_ROOT / "config.json"
STATIC_DIR = PROJECT_ROOT / "static"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
USERDATA_DIR = PROJECT_ROOT / "resources" / "userdata"
ASSETS_DIR = PROJECT_ROOT / "resources"
PHOTO_DIR = USERDATA_DIR / "Photos"
FULL_DIR = PHOTO_DIR / "full"
THUMB_DIR = PHOTO_DIR / "thumbs"
PHOTO_JSON = PHOTO_DIR / "photos.json"
PHOTO_JS = PHOTO_DIR / "photos.js"
CACHE_DIR = USERDATA_DIR / "cache"

for folder in [USERDATA_DIR, ASSETS_DIR, PHOTO_DIR, FULL_DIR, THUMB_DIR, CACHE_DIR, RUNTIME_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

MOCK_STATE_FILE = RUNTIME_DIR / "mock_state.json"
UPDATE_STATE_FILE = RUNTIME_DIR / "update_state.json"
CONFIG_PORTAL_PIN_FILE = RUNTIME_DIR / "config_portal_pin.json"
SPOTIFY_CACHE = RUNTIME_DIR / ".cache_spotify"

CONFIG_PORTAL_PIN_LENGTH = 6
CONFIG_PORTAL_PIN_TTL_SECONDS = 10 * 60

DEFAULT_CONFIG: dict[str, Any] = {
    "clock1": {"label": "Lisbon", "timezone": "Europe/Lisbon"},
    "clock2": {"label": "Shanghai", "timezone": "Asia/Shanghai", "enabled": True},
    "weather_api_key": "",
    "weather_region": "Porto",
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
        "albumArt": "https://i.scdn.co/image/ab67616d0000b2730da2443dbadead3b4c8e0d19",
        "isPlaying": True,
        "progress": 45000,
        "duration": 199000,
        "liked": False,
        "trackId": "4SrRrB27n7fiRkQcPoKfpk",
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

DEFAULT_STATE: dict[str, Any] = {
    "screen": "on",
    "mode": "client",
    "ip": "192.168.1.42",
    "ap_ssid": "MementoFrame",
    "wifi_ssid": "MockNetwork_5G",
    "known_networks": ["MockNetwork_2.4G", "MockNetwork_5G", "Neighbor_IoT"],
    "clients_connected": 0,
    "brightness_test_level": None,
    "spotify": {
        "source": "mock",          # mock | real
        "connected": True,
        "playing": True,
        "track_index": 0,
        "track_started_at": time.time(),
        "manual_progress_ms": 0,
    },
    "weather": {
        "source": "mock",          # mock | real
        "enabled": True,
        "temperature": 18.4,
        "condition": "Partly cloudy",
        "icon": "https://cdn.weatherapi.com/weather/64x64/day/116.png",
        "humidity": 72,
        "windSpeed": 14.4,
        "city": "Porto",
        "forecast_enabled": True,
    },
    "time": {
        "enabled": False,
        "fixed_iso": "2026-05-15T10:08:00+01:00",
        "tick": True,
    },
    "last_wifi_message": None,
}


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def deep_merge(default: Any, current: Any) -> Any:
    if isinstance(default, dict) and isinstance(current, dict):
        merged = deepcopy(default)
        for key, value in current.items():
            merged[key] = deep_merge(merged.get(key), value) if key in merged else value
        return merged
    return deepcopy(current) if current is not None else deepcopy(default)


def read_json(path: Path, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return deepcopy(fallback or {})


def load_state() -> dict[str, Any]:
    if not MOCK_STATE_FILE.exists():
        save_state(deepcopy(DEFAULT_STATE))
    return deep_merge(DEFAULT_STATE, read_json(MOCK_STATE_FILE, {}))


def save_state(state: dict[str, Any]) -> None:
    atomic_write_json(MOCK_STATE_FILE, deep_merge(DEFAULT_STATE, state))


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        save_config(deepcopy(DEFAULT_CONFIG))
    return deep_merge(DEFAULT_CONFIG, read_json(CONFIG_FILE, {}))


def save_config(cfg: dict[str, Any]) -> None:
    atomic_write_json(CONFIG_FILE, deep_merge(DEFAULT_CONFIG, cfg))


def load_env_files() -> None:
    for env_path in [REPO_ROOT / ".env", PROJECT_ROOT / ".env", BASE_DIR / ".env"]:
        if not env_path.exists():
            continue
        try:
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                # Let a project/dev .env fill values that were previously absent or blank.
                # This avoids a repo-level blank SPOTIFY_CLIENT_ID blocking the real one.
                if key and (key not in os.environ or os.environ.get(key, "") == ""):
                    os.environ[key] = value
        except Exception as exc:
            print(f"[env] could not read {env_path}: {exc}")


def read_env_values() -> dict[str, str]:
    load_env_files()
    return {key: os.getenv(key, "") for key in ["SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REDIRECT_URI", "WEATHER_API_KEY", "GITHUB_TOKEN", "MEMENTOFRAME_UPDATE_REPO"]}


def write_env_values(updates: dict[str, str]) -> None:
    env_path = PROJECT_ROOT / ".env"
    existing = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    seen: set[str] = set()
    lines: list[str] = []
    for raw in existing:
        if "=" not in raw or raw.strip().startswith("#"):
            lines.append(raw)
            continue
        key, _old = raw.split("=", 1)
        key = key.strip()
        if key in updates:
            lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            lines.append(raw)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")
        os.environ[key] = value
    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------
def build_photo_list() -> list[str]:
    exts = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")
    return sorted([p.name for p in FULL_DIR.iterdir() if p.is_file() and p.suffix.lower() in exts])


def load_photos() -> list[str]:
    if not PHOTO_JSON.exists():
        photos = build_photo_list()
        save_photos(photos)
        return photos
    try:
        photos = json.loads(PHOTO_JSON.read_text(encoding="utf-8"))
        if not isinstance(photos, list):
            raise ValueError("photos.json is not a list")
        if not photos:
            photos = build_photo_list()
            save_photos(photos)
        return photos
    except Exception:
        photos = build_photo_list()
        save_photos(photos)
        return photos


def save_photos(photos: list[str]) -> None:
    PHOTO_JSON.parent.mkdir(parents=True, exist_ok=True)
    PHOTO_JSON.write_text(json.dumps(photos, indent=2), encoding="utf-8")
    PHOTO_JS.write_text("window.photos = " + json.dumps(photos, indent=2) + ";", encoding="utf-8")


# ---------------------------------------------------------------------------
# Config portal PIN
# ---------------------------------------------------------------------------
def remove_config_portal_pin() -> None:
    try:
        CONFIG_PORTAL_PIN_FILE.unlink()
    except FileNotFoundError:
        pass


def read_config_portal_pin_record() -> dict[str, Any] | None:
    record = read_json(CONFIG_PORTAL_PIN_FILE, {})
    expires_at = float(record.get("expires_at") or 0)
    pin = str(record.get("pin") or "").strip()
    if not pin or not expires_at or time.time() >= expires_at:
        remove_config_portal_pin()
        return None
    return record


def create_config_portal_pin() -> dict[str, Any]:
    now = time.time()
    record = {
        "pin": "".join(secrets.choice("0123456789") for _ in range(CONFIG_PORTAL_PIN_LENGTH)),
        "created_at": now,
        "expires_at": now + CONFIG_PORTAL_PIN_TTL_SECONDS,
        "ttl_seconds": CONFIG_PORTAL_PIN_TTL_SECONDS,
    }
    atomic_write_json(CONFIG_PORTAL_PIN_FILE, record)
    return record


def get_or_create_config_portal_pin_record() -> dict[str, Any]:
    return read_config_portal_pin_record() or create_config_portal_pin()


def pin_response_payload() -> dict[str, Any]:
    record = read_config_portal_pin_record()
    if not record:
        return {"pin": None, "active": False}
    return {
        "pin": record["pin"],
        "active": True,
        "expires_at": record["expires_at"],
        "seconds_remaining": max(0, int(float(record["expires_at"]) - time.time())),
    }


# ---------------------------------------------------------------------------
# Time override
# ---------------------------------------------------------------------------
def forced_time_payload() -> dict[str, Any]:
    state = load_state()
    cfg = state.get("time", {})
    enabled = bool(cfg.get("enabled"))
    fixed_iso = cfg.get("fixed_iso") or DEFAULT_STATE["time"]["fixed_iso"]
    try:
        fixed_dt = datetime.fromisoformat(str(fixed_iso).replace("Z", "+00:00"))
        fixed_ms = int(fixed_dt.timestamp() * 1000)
    except Exception:
        fixed_iso = DEFAULT_STATE["time"]["fixed_iso"]
        fixed_ms = int(datetime.fromisoformat(fixed_iso).timestamp() * 1000)
    return {"enabled": enabled, "fixed_iso": fixed_iso, "fixed_ms": fixed_ms, "tick": bool(cfg.get("tick", True)), "real_now_ms": int(time.time() * 1000)}


def time_override_script() -> str:
    payload = forced_time_payload()
    if not payload["enabled"]:
        return "// MementoFrame mock time override disabled\n"
    data = json.dumps(payload)
    return f"""
(() => {{
  const cfg = {data};
  if (!cfg.enabled) return;
  const NativeDate = Date;
  const startedAt = NativeDate.now();
  const fixedAt = Number(cfg.fixed_ms || startedAt);
  function nowMs() {{ return cfg.tick ? fixedAt + (NativeDate.now() - startedAt) : fixedAt; }}
  function MockDate(...args) {{ return args.length ? new NativeDate(...args) : new NativeDate(nowMs()); }}
  MockDate.UTC = NativeDate.UTC;
  MockDate.parse = NativeDate.parse;
  MockDate.now = nowMs;
  MockDate.prototype = NativeDate.prototype;
  Object.setPrototypeOf(MockDate, NativeDate);
  window.Date = MockDate;
  window.__MEMENTOFRAME_MOCK_TIME__ = cfg;
}})();
""".lstrip()


# ---------------------------------------------------------------------------
# Spotify
# ---------------------------------------------------------------------------
def get_spotify_oauth():
    load_env_files()
    try:
        from spotipy.oauth2 import SpotifyOAuth
    except Exception as exc:
        raise RuntimeError("spotipy is not installed. Run: pip install spotipy python-dotenv") from exc
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "https://httpbin.org/anything")
    if not client_id or not client_secret:
        raise RuntimeError("SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are missing from .env")
    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope="user-read-playback-state user-read-currently-playing user-library-read",
        cache_path=str(SPOTIFY_CACHE),
        open_browser=False,
    )


def get_spotify_authorize_url() -> str:
    return get_spotify_oauth().get_authorize_url()


def cache_spotify_token_from_url(pasted_url: str) -> dict[str, Any]:
    code = parse_qs(urlparse(pasted_url or "").query).get("code", [None])[0]
    if not code:
        raise RuntimeError("No Spotify OAuth code found in pasted callback URL")
    return get_spotify_oauth().get_access_token(code, as_dict=True)


def clear_spotify_cache() -> None:
    try:
        SPOTIFY_CACHE.unlink()
    except FileNotFoundError:
        pass


def real_spotify_user() -> dict[str, Any] | None:
    try:
        import spotipy
        oauth = get_spotify_oauth()
        token = oauth.get_cached_token()
        if not token:
            return None
        return spotipy.Spotify(auth=token["access_token"]).current_user()
    except Exception as exc:
        print(f"[spotify-user] {exc}")
        return None


def real_spotify_payload() -> dict[str, Any]:
    try:
        import spotipy
        oauth = get_spotify_oauth()
        token = oauth.get_cached_token()
        if not token:
            return {"isPlaying": False, "spotifyConfigured": True, "source": "real", "error": "No cached Spotify token. Use /spotify/connect first."}
        sp = spotipy.Spotify(auth=token["access_token"])
        data = sp.current_playback()
        if not data or not data.get("item"):
            return {"isPlaying": False, "spotifyConfigured": True, "source": "real"}
        item = data["item"]
        track_id = item.get("id")
        liked = False
        if track_id:
            try:
                liked_result = sp.current_user_saved_tracks_contains([track_id])
                liked = bool(liked_result and liked_result[0])
            except Exception as exc:
                print(f"[spotify-liked] {exc}")
        return {
            "track": item.get("name"),
            "artist": ", ".join(a.get("name", "") for a in item.get("artists", [])),
            "albumArt": item.get("album", {}).get("images", [{}])[0].get("url") if item.get("album", {}).get("images") else None,
            "isPlaying": bool(data.get("is_playing", False)),
            "progress": int(data.get("progress_ms") or 0),
            "duration": int(item.get("duration_ms") or 0),
            "liked": liked,
            "trackId": track_id,
            "spotifyConfigured": True,
            "source": "real",
        }
    except Exception as exc:
        return {"isPlaying": False, "spotifyConfigured": False, "source": "real", "error": str(exc)}


def current_track_payload() -> dict[str, Any]:
    state = load_state()
    spotify = state["spotify"]
    if spotify.get("source") == "real":
        return real_spotify_payload()
    if not spotify.get("connected"):
        return {"isPlaying": False, "spotifyConfigured": True, "source": "mock"}
    if not spotify.get("playing"):
        return {"isPlaying": False, "spotifyConfigured": True, "source": "mock"}
    track = deepcopy(MOCK_TRACKS[int(spotify.get("track_index", 0)) % len(MOCK_TRACKS)])
    elapsed = int((time.time() - float(spotify.get("track_started_at", time.time()))) * 1000)
    base_progress = int(spotify.get("manual_progress_ms", track.get("progress", 0)))
    track["progress"] = min(base_progress + elapsed, int(track["duration"]))
    track["isPlaying"] = True
    track["spotifyConfigured"] = True
    track["source"] = "mock"
    return track


def next_track() -> dict[str, Any]:
    state = load_state()
    spotify = state["spotify"]
    spotify["track_index"] = (int(spotify.get("track_index", 0)) + 1) % len(MOCK_TRACKS)
    spotify["track_started_at"] = time.time()
    spotify["manual_progress_ms"] = 0
    spotify["connected"] = True
    spotify["playing"] = True
    save_state(state)
    return current_track_payload()


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------
def _weather_icon_url(icon: str | None, fallback: str = "https://cdn.weatherapi.com/weather/64x64/day/116.png") -> str:
    """Normalize WeatherAPI icon values into browser-ready absolute URLs."""
    value = str(icon or "").strip() or fallback
    if value.startswith("//"):
        return "https:" + value
    return value


def mock_forecast_payload(weather: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Return deterministic local forecast data for the display weather rotation."""
    base_temp = round(float(weather.get("temperature", 18.4)))
    condition = str(weather.get("condition") or "Partly cloudy")
    icon = _weather_icon_url(weather.get("icon"))

    now = datetime.now()
    hourly: list[dict[str, str]] = []
    hourly_conditions = [condition, "Cloudy", "Light rain", "Partly cloudy", "Clear"]
    hourly_offsets = [0, 1, -1, -2, -1]
    for index in range(5):
        slot = now + timedelta(hours=index + 1)
        hourly.append({
            "time": slot.strftime("%H:00"),
            "icon": icon,
            "temp": f"{base_temp + hourly_offsets[index]}°C",
            "condition": hourly_conditions[index],
        })

    daily: list[dict[str, str]] = []
    daily_conditions = [condition, "Sunny", "Cloudy", "Light rain", "Partly cloudy"]
    high_offsets = [3, 4, 2, 1, 3]
    low_offsets = [-4, -3, -5, -6, -4]
    for index in range(5):
        day = date.today() + timedelta(days=index)
        daily.append({
            "label": "Today" if index == 0 else day.strftime("%a"),
            "icon": icon,
            "high": f"{base_temp + high_offsets[index]}°C",
            "low": f"{base_temp + low_offsets[index]}°C",
            "condition": daily_conditions[index],
        })

    return {"hourly": hourly, "daily": daily}


def _forecast_from_weatherapi(data: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Extract the frontend forecast shape from a WeatherAPI forecast.json response."""
    forecast_days = data.get("forecast", {}).get("forecastday", []) or []
    hourly: list[dict[str, str]] = []
    now_epoch = time.time()

    for day_fc in forecast_days:
        for hour_fc in day_fc.get("hour", []):
            try:
                if float(hour_fc.get("time_epoch", 0)) <= now_epoch:
                    continue
            except Exception:
                pass
            condition = hour_fc.get("condition", {}) or {}
            hourly.append({
                "time": str(hour_fc.get("time", "")).split(" ")[-1][:5],
                "icon": _weather_icon_url(condition.get("icon")),
                "temp": f"{round(float(hour_fc.get('temp_c', 0)))}°C",
                "condition": condition.get("text", ""),
            })
            if len(hourly) == 5:
                break
        if len(hourly) == 5:
            break

    daily: list[dict[str, str]] = []
    today = date.today()
    for day_fc in forecast_days[:5]:
        try:
            day_date = date.fromisoformat(str(day_fc.get("date")))
        except Exception:
            day_date = today + timedelta(days=len(daily))
        day_data = day_fc.get("day", {}) or {}
        condition = day_data.get("condition", {}) or {}
        daily.append({
            "label": "Today" if day_date == today else day_date.strftime("%a"),
            "icon": _weather_icon_url(condition.get("icon")),
            "high": f"{round(float(day_data.get('maxtemp_c', 0)))}°C",
            "low": f"{round(float(day_data.get('mintemp_c', 0)))}°C",
            "condition": condition.get("text", ""),
        })

    return {"hourly": hourly, "daily": daily}


def real_weather_payload() -> dict[str, Any]:
    load_env_files()
    cfg = load_config()
    key = cfg.get("weather_api_key") or os.getenv("WEATHER_API_KEY")
    location = cfg.get("weather_region") or "Porto"
    if not key:
        return {"error": "Weather API key not configured", "source": "real"}
    try:
        import requests
        res = requests.get(
            "https://api.weatherapi.com/v1/forecast.json",
            params={"key": key, "q": location, "days": 5, "aqi": "no", "alerts": "no"},
            timeout=5,
        )
        res.raise_for_status()
        data = res.json()
        current = data["current"]
        current_condition = current.get("condition", {}) or {}
        payload = {
            "temperature": round(float(current["temp_c"]), 1),
            "condition": current_condition.get("text", ""),
            "icon": _weather_icon_url(current_condition.get("icon")),
            "humidity": int(current["humidity"]),
            "windSpeed": float(current["wind_kph"]),
            "city": data["location"]["name"],
            "source": "real",
        }
        forecast = _forecast_from_weatherapi(data)
        if forecast.get("hourly") and forecast.get("daily"):
            payload["forecast"] = forecast
        return payload
    except Exception as exc:
        return {"error": f"Weather request failed: {exc}", "source": "real"}


def weather_payload() -> dict[str, Any]:
    state = load_state()
    weather = state.get("weather", {})
    if weather.get("source") == "real":
        return real_weather_payload()
    if not weather.get("enabled", True):
        return {"error": "Mock weather disabled", "source": "mock"}

    payload = {
        "temperature": round(float(weather.get("temperature", 0)), 1),
        "condition": weather.get("condition", "Clear"),
        "icon": _weather_icon_url(weather.get("icon")),
        "humidity": int(float(weather.get("humidity", 0))),
        "windSpeed": float(weather.get("windSpeed", 0)),
        "city": weather.get("city", "Porto"),
        "source": "mock",
    }
    if weather.get("forecast_enabled", True):
        payload["forecast"] = mock_forecast_payload(weather)
    return payload


# ---------------------------------------------------------------------------
# Update mock
# ---------------------------------------------------------------------------
def global_app_version() -> str:
    try:
        import runpy
        version_file = PROJECT_ROOT / "version_info.py"
        data = runpy.run_path(str(version_file))
        return str(data.get("GLOBAL_APP_VERSION") or data.get("VERSION") or "0.0.0")
    except Exception:
        return "0.0.0"


def parse_version(value: str) -> tuple[int, ...]:
    import re
    parts = [int(x) for x in re.findall(r"\d+", str(value or "0"))]
    return tuple(parts or [0])


def version_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def default_update_state() -> dict[str, Any]:
    installed = global_app_version()
    return {
        "installed_version": installed,
        "latest_version": None,
        "latest_tag": None,
        "release_name": None,
        "release_url": None,
        "available": False,
        "mock_pending_update": False,
        "pending_restart": False,
        "update_in_progress": False,
        "auto_update": False,
        "repo": "",
        "channel": "stable",
        "checked_at": None,
        "last_checked": None,
        "last_error": None,
        "mock": True,
    }


def load_update_state() -> dict[str, Any]:
    state = default_update_state()
    state.update(read_json(UPDATE_STATE_FILE, {}))
    state["installed_version"] = global_app_version()
    cfg = load_config().get("updates", {})
    state["auto_update"] = bool(cfg.get("auto_update", False))
    state["repo"] = cfg.get("repo", state.get("repo", "")) or os.getenv("MEMENTOFRAME_UPDATE_REPO", "")
    state["channel"] = cfg.get("channel", state.get("channel", "stable")) or "stable"
    if bool(state.get("mock_pending_update")):
        state.update({"available": True, "latest_version": state.get("latest_version") or "9.9.9-mock", "latest_tag": state.get("latest_tag") or "v9.9.9-mock", "last_error": None})
    return state


def save_update_state(state: dict[str, Any]) -> None:
    atomic_write_json(UPDATE_STATE_FILE, state)


def set_mock_pending_update(enabled: bool) -> dict[str, Any]:
    state = load_update_state()
    state["mock_pending_update"] = bool(enabled)
    if enabled:
        state.update({"available": True, "latest_version": "9.9.9-mock", "latest_tag": "v9.9.9-mock", "last_error": None})
    else:
        state.update({"available": False, "latest_version": None, "latest_tag": None})
    save_update_state(state)
    return load_update_state()


def check_for_updates_mock() -> dict[str, Any]:
    state = load_update_state()
    now = time.time()
    state.update({"checked_at": now, "last_checked": now, "update_in_progress": False, "pending_restart": False, "last_error": None})
    if state.get("mock_pending_update"):
        save_update_state(state)
        return load_update_state()
    repo = str(state.get("repo") or "").strip()
    if not repo or "/" not in repo:
        state.update({"available": False, "latest_version": None, "latest_tag": None, "last_error": "No GitHub repository configured for mock update checks."})
        save_update_state(state)
        return state
    url = f"https://api.github.com/repos/{repo}/releases/latest" if state.get("channel") != "pre-release" else f"https://api.github.com/repos/{repo}/releases?per_page=5"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "MementoFrame-Mock-Updater"}
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, headers=headers), timeout=8) as res:
            payload = json.loads(res.read().decode("utf-8"))
        if isinstance(payload, list):
            payload = next((r for r in payload if not r.get("draft") and r.get("tag_name")), payload[0] if payload else {})
        tag = str(payload.get("tag_name") or "").strip()
        latest = tag.lstrip("vV")
        installed = state.get("installed_version", "0.0.0")
        state.update({
            "latest_tag": tag or None,
            "latest_version": latest or None,
            "available": bool(latest and version_newer(latest, installed)),
            "release_name": payload.get("name"),
            "release_url": payload.get("html_url"),
            "last_error": None,
        })
    except HTTPError as exc:
        state.update({"available": False, "latest_version": None, "latest_tag": None, "last_error": f"GitHub update check failed: HTTP {exc.code}"})
    except (URLError, TimeoutError, json.JSONDecodeError, Exception) as exc:
        state.update({"available": False, "latest_version": None, "latest_tag": None, "last_error": f"GitHub update check failed: {exc}"})
    save_update_state(state)
    return state


def mock_install_update_blocked() -> dict[str, Any]:
    state = load_update_state()
    state.update({"update_in_progress": False, "pending_restart": False, "last_error": "Mock environment: install/reboot is disabled."})
    save_update_state(state)
    return state


def mock_autoupdate() -> dict[str, Any]:
    state = load_update_state()
    if not state.get("auto_update"):
        state.update({"last_autoupdate_check": time.time(), "auto_update_skipped": "disabled"})
        save_update_state(state)
        return state
    checked = check_for_updates_mock()
    if checked.get("available"):
        checked["last_error"] = "Mock environment: autoupdate found an update but install/reboot is disabled."
        checked["update_in_progress"] = False
        checked["pending_restart"] = False
        save_update_state(checked)
    return load_update_state()
