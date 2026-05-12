#!/usr/bin/env python3
"""Shared mock state helpers for local MementoFrame development."""
import json
import os
import secrets
import time
import re
import urllib.error
import urllib.request
from copy import deepcopy
from urllib.parse import parse_qs, urlparse

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




# ---------------------------------------------------------------------------
# Mock software-update helpers
# ---------------------------------------------------------------------------
def installed_global_version():
    """Return the local app version used for GitHub release comparison."""
    try:
        from version_info import GLOBAL_APP_VERSION
        return str(GLOBAL_APP_VERSION)
    except Exception:
        pass
    try:
        from version_info import VERSIONS
        return str(VERSIONS.get("MementoFrame") or VERSIONS.get("Global App Version") or VERSIONS.get("App") or "0.0.0")
    except Exception:
        return "0.0.0"


def version_tuple(value):
    """Convert v1.2.3-ish strings into comparable integer tuples."""
    parts = re.findall(r"\d+", str(value or ""))
    nums = [int(p) for p in parts[:3]]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def normalize_tag(value):
    return str(value or "").strip().lstrip("vV")


def default_update_state():
    return {
        "installed_version": installed_global_version(),
        "latest_version": None,
        "latest_tag": None,
        "available": False,
        "checked_at": None,
        "pending_restart": False,
        "update_in_progress": False,
        "auto_update": False,
        "repo": "",
        "channel": "stable",
        "last_error": None,
        "mock": True,
        "install_blocked": True,
    }


def load_update_state():
    """Return mock update state merged with config and version defaults."""
    state = default_update_state()
    if os.path.exists(UPDATE_STATE_FILE):
        try:
            with open(UPDATE_STATE_FILE, encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                state.update(stored)
        except Exception as e:
            state["last_error"] = f"Unable to read mock update state: {e}"

    cfg = load_config()
    updates_cfg = cfg.get("updates", {}) if isinstance(cfg, dict) else {}
    state["installed_version"] = installed_global_version()
    state["auto_update"] = bool(updates_cfg.get("auto_update", False))
    state["repo"] = updates_cfg.get("repo", "")
    state["channel"] = updates_cfg.get("channel", "stable")
    state["mock"] = True
    state["install_blocked"] = True
    # Mocks must never accidentally look like they are applying an update.
    state["update_in_progress"] = False
    state["pending_restart"] = False
    return state


def save_update_state(state):
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    clean = dict(state)
    clean["update_in_progress"] = False
    clean["pending_restart"] = False
    clean["mock"] = True
    clean["install_blocked"] = True
    atomic_write_json(UPDATE_STATE_FILE, clean)
    return clean


def check_for_updates_mock():
    """Check GitHub Releases for availability, without installing anything."""
    state = load_update_state()
    cfg = load_config()
    updates_cfg = cfg.get("updates", {}) if isinstance(cfg, dict) else {}
    repo = (updates_cfg.get("repo") or os.getenv("MEMENTOFRAME_UPDATE_REPO", "")).strip()

    state.update({
        "checked_at": time.time(),
        "available": False,
        "latest_version": None,
        "latest_tag": None,
        "last_error": None,
        "update_in_progress": False,
        "pending_restart": False,
        "repo": repo,
    })

    if not repo:
        state["last_error"] = "No GitHub repository configured for mock update checks."
        return save_update_state(state)

    repo = repo.removeprefix("https://github.com/").strip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]

    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "MementoFrame-Mock-Updater",
        })
        with urllib.request.urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        tag = payload.get("tag_name") or payload.get("name") or ""
        latest = normalize_tag(tag)
        installed = normalize_tag(state.get("installed_version"))
        state.update({
            "latest_version": latest,
            "latest_tag": tag,
            "available": version_tuple(latest) > version_tuple(installed),
            "release_name": payload.get("name"),
            "release_url": payload.get("html_url"),
        })
    except urllib.error.HTTPError as e:
        state["last_error"] = f"GitHub update check failed: HTTP {e.code}"
    except Exception as e:
        state["last_error"] = f"GitHub update check failed: {e}"

    return save_update_state(state)


def mock_install_update_blocked():
    """No-op install endpoint for mocks. Never updates files or reboots."""
    state = load_update_state()
    state.update({
        "update_in_progress": False,
        "pending_restart": False,
        "last_error": "Mock environment: install/reboot is disabled. Use /update/check to test availability only.",
        "install_blocked": True,
        "mock": True,
    })
    return save_update_state(state)


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
