#!/usr/bin/env python3
"""Shared mock state helpers for local MementoFrame development."""
import json
import os
import secrets
import time
from copy import deepcopy

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(BASE_DIR, "runtime")
os.makedirs(RUNTIME_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
MOCK_STATE_FILE = os.path.join(RUNTIME_DIR, "mock_state.json")
CONFIG_PORTAL_PIN_FILE = os.path.join(RUNTIME_DIR, "config_portal_pin.json")
LEGACY_CONFIG_PIN_FILE = os.path.join(RUNTIME_DIR, "config_pin.txt")

CONFIG_PORTAL_PIN_LENGTH = 6
CONFIG_PORTAL_PIN_TTL_SECONDS = 10 * 60

DEFAULT_CONFIG = {
    "clock1": {"label": "Lisbon", "timezone": "Europe/Lisbon"},
    "clock2": {"label": "Shanghai", "timezone": "Asia/Shanghai", "enabled": True},
    "weather_api_key": "mock-key",
    "weather_region": "Porto",
    "brightness": 80,
    "auto_power": {"enabled": False, "off_time": "23:00", "on_time": "07:00"},
}

DEFAULT_STATE = {
    "screen": "on",
    "mode": "client",
    "ip": "192.168.1.42",
    "ap_ssid": "MementoFrame",
    "wifi_ssid": "MockNetwork_5G",
    "known_networks": ["MockNetwork_2.4G", "MockNetwork_5G", "Neighbor_IoT"],
    "clients_connected": 0,
    "spotify": {
        "connected": True,
        "playing": True,
        "track_index": 0,
        "track_started_at": time.time(),
        "manual_progress_ms": 0,
    },
    "weather": {
        "enabled": True,
        "temperature": 18.4,
        "condition": "Partly cloudy",
        "icon": "https://cdn.weatherapi.com/weather/64x64/day/116.png",
        "humidity": 72,
        "windSpeed": 14.4,
        "city": "Porto",
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


def deep_merge(default, current):
    merged = deepcopy(default)
    if not isinstance(current, dict):
        return merged
    for key, value in current.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def atomic_write_json(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def load_state():
    if not os.path.exists(MOCK_STATE_FILE):
        save_state(DEFAULT_STATE)
        return deepcopy(DEFAULT_STATE)
    try:
        with open(MOCK_STATE_FILE, encoding="utf-8") as f:
            return deep_merge(DEFAULT_STATE, json.load(f))
    except Exception:
        return deepcopy(DEFAULT_STATE)


def save_state(state):
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    atomic_write_json(MOCK_STATE_FILE, state)


def update_state(mutator):
    state = load_state()
    result = mutator(state)
    save_state(state)
    return state if result is None else result


def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return deepcopy(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return deep_merge(DEFAULT_CONFIG, json.load(f))
    except Exception:
        return deepcopy(DEFAULT_CONFIG)


def save_config(cfg):
    atomic_write_json(CONFIG_FILE, deep_merge(DEFAULT_CONFIG, cfg))


def remove_config_portal_pin():
    for path in [CONFIG_PORTAL_PIN_FILE, LEGACY_CONFIG_PIN_FILE]:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"⚠️ Could not remove {path}: {e}")


def read_config_portal_pin_record():
    try:
        with open(CONFIG_PORTAL_PIN_FILE, encoding="utf-8") as f:
            record = json.load(f)
    except FileNotFoundError:
        # Legacy fallback for any older mock process still writing config_pin.txt.
        try:
            with open(LEGACY_CONFIG_PIN_FILE, encoding="utf-8") as f:
                pin = f.read().strip()
            if not pin:
                return None
            age = time.time() - os.path.getmtime(LEGACY_CONFIG_PIN_FILE)
            expires_at = time.time() + max(0, CONFIG_PORTAL_PIN_TTL_SECONDS - age)
            return {"pin": pin, "created_at": time.time() - age, "expires_at": expires_at, "ttl_seconds": CONFIG_PORTAL_PIN_TTL_SECONDS}
        except Exception:
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
    now = time.time()
    pin = "".join(secrets.choice("0123456789") for _ in range(CONFIG_PORTAL_PIN_LENGTH))
    record = {
        "pin": pin,
        "created_at": now,
        "expires_at": now + CONFIG_PORTAL_PIN_TTL_SECONDS,
        "ttl_seconds": CONFIG_PORTAL_PIN_TTL_SECONDS,
    }
    atomic_write_json(CONFIG_PORTAL_PIN_FILE, record)
    with open(LEGACY_CONFIG_PIN_FILE, "w", encoding="utf-8") as f:
        f.write(pin)
    try:
        os.chmod(CONFIG_PORTAL_PIN_FILE, 0o600)
        os.chmod(LEGACY_CONFIG_PIN_FILE, 0o600)
    except Exception:
        pass
    print(f"[config-portal-pin] created temporary PIN: {pin}")
    return record


def get_or_create_config_portal_pin_record():
    return read_config_portal_pin_record() or create_config_portal_pin()


def pin_response_payload():
    record = read_config_portal_pin_record()
    if not record:
        return {"pin": None, "active": False}
    remaining = max(0, int(float(record["expires_at"]) - time.time()))
    return {"pin": record["pin"], "active": True, "expires_at": record["expires_at"], "seconds_remaining": remaining}


def current_track_payload():
    state = load_state()
    spotify = state["spotify"]
    if not spotify.get("connected") or not spotify.get("playing"):
        return {"isPlaying": False}
    track = deepcopy(MOCK_TRACKS[int(spotify.get("track_index", 0)) % len(MOCK_TRACKS)])
    elapsed = int((time.time() - float(spotify.get("track_started_at", time.time()))) * 1000)
    progress = int(spotify.get("manual_progress_ms", track.get("progress", 0))) + elapsed
    track["progress"] = min(progress, track["duration"])
    track["isPlaying"] = True
    return track


def next_track():
    def mutate(state):
        spotify = state["spotify"]
        spotify["track_index"] = (int(spotify.get("track_index", 0)) + 1) % len(MOCK_TRACKS)
        spotify["track_started_at"] = time.time()
        spotify["manual_progress_ms"] = 0
    update_state(mutate)
    return current_track_payload()
