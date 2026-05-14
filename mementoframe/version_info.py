# MementoFrame version metadata.
#
# Versioning model:
#   release.frontend.app.api.ap.updater
#
# Example:
#   1.25.22.21.21.13
#
# Meaning:
#   1  = release counter
#   25 = frontend version
#   22 = dashboard app.py version
#   21 = api_service.py version
#   21 = ap_mode_manager.py version
#   13 = updater.py version
#
# GitHub release tags should use:
#   v{GLOBAL_APP_VERSION}

RELEASE_COUNTER = 1

VERSION_ORDER = [
    "frontend",
    "app",
    "api_service",
    "ap_mode_manager",
    "updater",
]

COMPONENTS = {
    "frontend": {
        "label": "Frontend",
        "version": 25,
        "description": "HTML, CSS, JavaScript, templates, and display UI assets",
    },
    "app": {
        "label": "Dashboard App",
        "version": 22,
        "file": "app.py",
        "description": "Admin dashboard and configuration portal",
    },
    "api_service": {
        "label": "Display API",
        "version": 21,
        "file": "api_service.py",
        "description": "Local display API, widget data, and hardware endpoints",
    },
    "ap_mode_manager": {
        "label": "AP Mode Manager",
        "version": 21,
        "file": "ap_mode_manager.py",
        "description": "NetworkManager Wi-Fi/AP fallback watchdog",
    },
    "updater": {
        "label": "Updater",
        "version": 13,
        "file": "updater.py",
        "description": "Install, update, backup, and post-reboot health logic",
    },
}

VERSION_SCHEMA = "release.frontend.app.api.ap.updater"


def build_global_version() -> str:
    """Build the release tag version from the release counter and component versions."""
    parts = [RELEASE_COUNTER]
    parts.extend(COMPONENTS[key]["version"] for key in VERSION_ORDER)
    return ".".join(str(part) for part in parts)


GLOBAL_APP_VERSION = build_global_version()
GLOBAL_APP_TAG = f"v{GLOBAL_APP_VERSION}"

VERSION_INFO = {
    "name": "MementoFrame",
    "version": GLOBAL_APP_VERSION,
    "tag": GLOBAL_APP_TAG,
    "schema": VERSION_SCHEMA,
    "release": RELEASE_COUNTER,
    "order": VERSION_ORDER,
    "components": COMPONENTS,
}
