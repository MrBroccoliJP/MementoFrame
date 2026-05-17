# MementoFrame version metadata.
#
# Versioning model:
#   release.frontend.config.display.network.updater
#
# Example:
#   1.25.22.21.21.13
#
# Meaning:
#   1  = release counter
#   25 = frontend version
#   22 = config portal service version
#   21 = display service version
#   21 = network manager service version
#   13 = updater.py version
#
# GitHub release tags should use:
#   v{GLOBAL_APP_VERSION}

RELEASE_COUNTER = 4

VERSION_ORDER = [
    "frontend",
    "config_portal",
    "display_service",
    "network_manager",
    "updater",
]

COMPONENTS = {
    "frontend": {
        "label": "Frontend",
        "version": 30, #Shows photo upload progress | config portal styling update
        "description": "HTML, CSS, JavaScript, templates, and display UI assets",
    },
    "config_portal": {
        "label": "Config Portal",
        "version": 25, #Photo uploads now upload to a tmp folder and then are processed in the device, to avoid the config portal to be stuck loading.
        "file": "config_portal_service.py",
        "description": "Admin dashboard and configuration portal",
    },
    "display_service": {
        "label": "Display Service",
        "version": 23, #updated to use chromium and handle spotify without permissions
        "file": "display_service.py",
        "description": "Local display API, widget data, and hardware endpoints",
    },
    "network_manager": {
        "label": "Network Manager",
        "version": 21,
        "file": "network_manager_service.py",
        "description": "NetworkManager Wi-Fi/AP fallback watchdog",
    },
    "updater": {
        "label": "Updater",
        "version": 17,  #changed install scripts
        "file": "updater.py",
        "description": "Install, update, backup, and post-reboot health logic",
    },
}

VERSION_SCHEMA = "release.frontend.config.display.network.updater"


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