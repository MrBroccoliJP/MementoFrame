#!/usr/bin/env python3
"""Shared mock state helpers for local MementoFrame development."""
import json
import os
import secrets
import time
from copy import deepcopy
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ---------------------------------------------------------------------------
# Folder layout
# ---------------------------------------------------------------------------
# These mock files are intended to live in:
#
#   repo-root/
#   ├── mementoframe/   # real project files
#   └── dev/            # mock files
#
# Mock runtime data stays inside dev/runtime so it is never mixed with the
# Raspberry Pi production runtime files.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))          # repo-root/dev
REPO_ROOT = os.path.dirname(BASE_DIR)                          # repo-root
PROJECT_ROOT = os.path.join(REPO_ROOT, "mementoframe")         # repo-root/mementoframe

RUNTIME_DIR = os.path.join(BASE_DIR, "runtime")
os.makedirs(RUNTIME_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(PROJECT_ROOT, "config.json")
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")
USERDATA_DIR = os.path.join(PROJECT_ROOT, "resources", "userdata")
ASSETS_DIR = os.path.join(PROJECT_ROOT, "resources", "assets")

MOCK_STATE_FILE = os.path.join(RUNTIME_DIR, "mock_state.json")
UPDATE_STATE_FILE = os.path.join(RUNTIME_DIR, "update_state.json")
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
    "updates": {
        "auto_update": False,
        "repo": "",
        "channel": "stable",
        "mock_pending_update": False,
    },
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
        "source": "mock",
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
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
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



# ---------------------------------------------------------------------------
# Mock software-update helpers
# ---------------------------------------------------------------------------
def _global_app_version():
    try:
        from version_info import GLOBAL_APP_VERSION
        return str(GLOBAL_APP_VERSION)
    except Exception:
        try:
            from version_info import VERSIONS
            return str(VERSIONS.get("MementoFrame") or VERSIONS.get("App") or "0.0.0")
        except Exception:
            return "0.0.0"


def _normalize_version(value):
    return str(value or "0.0.0").strip().lstrip("vV")


def _version_tuple(value):
    parts = []
    for chunk in _normalize_version(value).replace("-", ".").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits or 0))
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])  


def default_update_state():
    installed = _global_app_version()
    return {
        "installed_version": installed,
        "current_version": installed,
        "latest_version": None,
        "latest_tag": None,
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


def load_update_state():
    """Return mock update state. The mock_pending_update flag forces available=True for UI testing."""
    state = default_update_state()
    try:
        if os.path.exists(UPDATE_STATE_FILE):
            with open(UPDATE_STATE_FILE, encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                state.update(stored)
            # Always overwrite with the real value from version_info.py
            state["installed_version"] = _global_app_version()  # ADD THIS
            state["current_version"] = state["installed_version"]  # ADD THIS
    except Exception as e:
        state["last_error"] = f"Unable to read mock update state: {e}"

    cfg = load_config()
    updates_cfg = cfg.get("updates", {}) if isinstance(cfg, dict) else {}
    state["auto_update"] = bool(updates_cfg.get("auto_update", False))
    state["repo"] = updates_cfg.get("repo", state.get("repo", "")) or ""
    state["channel"] = updates_cfg.get("channel", state.get("channel", "stable")) or "stable"

    mock_pending = bool(updates_cfg.get("mock_pending_update", False) or state.get("mock_pending_update", False))
    state["mock_pending_update"] = mock_pending
    if mock_pending:
        state.update({
            "available": True,
            "latest_version": state.get("latest_version") or "9.9.9-mock",
            "latest_tag": state.get("latest_tag") or "v9.9.9-mock",
            "last_error": None,
        })

    # Mocks never actually update/reboot.
    state["update_in_progress"] = bool(state.get("update_in_progress", False))
    state["pending_restart"] = bool(state.get("pending_restart", False))
    return state


def save_update_state(state):
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    atomic_write_json(UPDATE_STATE_FILE, state)


def set_mock_pending_update(enabled):
    """Toggle the mock-only pending update flag used to test display styling."""
    cfg = load_config()
    updates = cfg.setdefault("updates", {})
    updates["mock_pending_update"] = bool(enabled)
    save_config(cfg)

    state = load_update_state()
    state["mock_pending_update"] = bool(enabled)
    if enabled:
        state.update({
            "available": True,
            "latest_version": state.get("latest_version") or "9.9.9-mock",
            "latest_tag": state.get("latest_tag") or "v9.9.9-mock",
            "last_error": None,
        })
    else:
        state.update({
            "available": False,
            "latest_version": None,
            "latest_tag": None,
        })
    save_update_state(state)
    return load_update_state()


def check_for_updates_mock():
    """Check GitHub latest release when configured. Mocks only record status; they never install."""
    state = load_update_state()
    repo = (state.get("repo") or os.getenv("MEMENTOFRAME_UPDATE_REPO", "")).strip()
    now = time.time()
    state.update({
        "checked_at": now,
        "last_checked": now,
        "update_in_progress": False,
        "pending_restart": False,
        "last_error": None,
    })

    if state.get("mock_pending_update"):
        state.update({
            "available": True,
            "latest_version": state.get("latest_version") or "9.9.9-mock",
            "latest_tag": state.get("latest_tag") or "v9.9.9-mock",
        })
        save_update_state(state)
        return state

    if not repo or "/" not in repo:
        state.update({
            "available": False,
            "latest_version": None,
            "latest_tag": None,
            "last_error": "No GitHub repository configured for mock update checks.",
        })
        save_update_state(state)
        return state

    channel = state.get("channel", "stable")
    if channel == "pre-release":
        url = f"https://api.github.com/repos/{repo}/releases?per_page=5"
    else:
        url = f"https://api.github.com/repos/{repo}/releases/latest"

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "MementoFrame-Mock-Updater",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=8) as res:
            payload = json.loads(res.read().decode("utf-8"))

        if isinstance(payload, list):
            if not payload:
                raise RuntimeError("No releases found.")
            payload = payload[0]

        tag = str(payload.get("tag_name") or "").strip()
        latest = _normalize_version(tag)
        installed = _normalize_version(state.get("installed_version"))
        available = bool(tag) and _version_tuple(latest) > _version_tuple(installed)
        state.update({
            "latest_tag": tag or None,
            "latest_version": latest if tag else None,
            "available": available,
            "release_name": payload.get("name"),
            "release_url": payload.get("html_url"),
            "last_error": None,
        })
    except HTTPError as e:
        state.update({"available": False, "latest_version": None, "latest_tag": None, "last_error": f"GitHub update check failed: HTTP {e.code}"})
    except (URLError, TimeoutError, json.JSONDecodeError, Exception) as e:
        state.update({"available": False, "latest_version": None, "latest_tag": None, "last_error": f"GitHub update check failed: {e}"})

    save_update_state(state)
    return state


def mock_install_update_blocked():
    """No-op install endpoint. Mocks must never update files or reboot."""
    state = load_update_state()
    state.update({
        "update_in_progress": False,
        "pending_restart": False,
        "last_error": "Mock environment: install/reboot is disabled.",
    })
    save_update_state(state)
    return state


def load_local_env_files():
    """Load local .env values from repo/project roots without requiring python-dotenv."""
    for env_path in [os.path.join(REPO_ROOT, ".env"), os.path.join(PROJECT_ROOT, ".env")]:
        if not os.path.exists(env_path):
            continue
        try:
            with open(env_path, encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
        except Exception as e:
            print(f"[env] could not load {env_path}: {e}")


def spotify_cache_path():
    """Return the dev-only Spotify cache path used by the mock environment."""
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    return os.path.join(RUNTIME_DIR, ".cache_spotify")


def get_spotify_oauth():
    """Create a SpotifyOAuth helper using local .env credentials, when available."""
    load_local_env_files()
    try:
        from spotipy.oauth2 import SpotifyOAuth
    except Exception as e:
        raise RuntimeError("spotipy is not installed. Run: pip install spotipy python-dotenv") from e

    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "https://httpbin.org/anything")

    if not client_id or not client_secret:
        raise RuntimeError("SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are missing from your local .env")

    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope="user-read-playback-state user-read-currently-playing user-library-read",
        cache_path=spotify_cache_path(),
        open_browser=False,
    )


def get_spotify_authorize_url():
    """Return the Spotify authorization URL for the mock dashboard."""
    return get_spotify_oauth().get_authorize_url()


def cache_spotify_token_from_url(pasted_url):
    """Extract an OAuth code from a pasted callback URL and save the token cache."""
    query = urlparse(pasted_url or "").query
    code = parse_qs(query).get("code", [None])[0]
    if not code:
        raise RuntimeError("No Spotify code found in pasted callback URL")
    return get_spotify_oauth().get_access_token(code, as_dict=True)


def clear_spotify_cache():
    """Remove the dev-only Spotify token cache."""
    try:
        os.remove(spotify_cache_path())
    except FileNotFoundError:
        pass


def real_spotify_user():
    """Return the real Spotify user profile when local credentials/cache are valid."""
    try:
        import spotipy
        oauth = get_spotify_oauth()
        token_info = oauth.get_cached_token()
        if not token_info:
            return None
        sp = spotipy.Spotify(auth=token_info["access_token"])
        return sp.current_user()
    except Exception as e:
        print(f"[spotify-real-user] {e}")
        return None


def real_spotify_payload():
    """Fetch the real current Spotify playback in the same shape as /spotify.json."""
    try:
        import spotipy
        oauth = get_spotify_oauth()
        token_info = oauth.get_cached_token()
        if not token_info:
            return {"isPlaying": False, "source": "real", "error": "Spotify is set to real, but no cached token exists. Use /spotify/connect first."}

        sp = spotipy.Spotify(auth=token_info["access_token"])
        data = sp.current_playback()
        if not data or not data.get("item"):
            return {"isPlaying": False, "source": "real"}

        item = data["item"]
        track_id = item.get("id")
        liked = False
        if track_id:
            try:
                liked_result = sp.current_user_saved_tracks_contains([track_id])
                liked = bool(liked_result and liked_result[0])
            except Exception as e:
                print(f"[spotify-real-liked] {e}")

        return {
            "track": item.get("name"),
            "artist": ", ".join(a.get("name", "") for a in item.get("artists", [])),
            "albumArt": item.get("album", {}).get("images", [{}])[0].get("url") if item.get("album", {}).get("images") else None,
            "isPlaying": bool(data.get("is_playing", False)),
            "progress": int(data.get("progress_ms") or 0),
            "duration": int(item.get("duration_ms") or 0),
            "liked": liked,
            "trackId": track_id,
            "source": "real",
        }
    except Exception as e:
        print(f"[spotify-real] {e}")
        return {"isPlaying": False, "source": "real", "error": str(e)}

def current_track_payload():
    state = load_state()
    spotify = state["spotify"]

    if spotify.get("source", "mock") == "real":
        return real_spotify_payload()

    if not spotify.get("connected") or not spotify.get("playing"):
        return {"isPlaying": False, "source": "mock"}
    track = deepcopy(MOCK_TRACKS[int(spotify.get("track_index", 0)) % len(MOCK_TRACKS)])
    elapsed = int((time.time() - float(spotify.get("track_started_at", time.time()))) * 1000)
    progress = int(spotify.get("manual_progress_ms", track.get("progress", 0))) + elapsed
    track["progress"] = min(progress, track["duration"])
    track["isPlaying"] = True
    track["source"] = "mock"
    return track


def next_track():
    def mutate(state):
        spotify = state["spotify"]
        spotify["track_index"] = (int(spotify.get("track_index", 0)) + 1) % len(MOCK_TRACKS)
        spotify["track_started_at"] = time.time()
        spotify["manual_progress_ms"] = 0
    update_state(mutate)
    return current_track_payload()
