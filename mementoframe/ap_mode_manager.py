# MementoFrame - Raspberry Pi Smart Photo Frame
# Copyright (c) 2026 João Fernandes
# Licensed under CC BY-NC 4.0

#!/usr/bin/env python3
"""
ap_mode_manager.py — Wi-Fi / Access Point Mode Manager
Raspberry Pi OS Bookworm / NetworkManager edition

Separation of concerns:
  - app.py never calls nmcli and never starts/stops AP mode.
  - app.py writes runtime/wifi_request.json when the user submits Wi-Fi credentials.
  - this manager owns all NetworkManager/AP/client Wi-Fi behavior.
  - this manager continuously publishes runtime/wifi_state.json,
    runtime/wifi_result.json and runtime/wifi_networks.json for the dashboard.

NetworkManager owns the actual AP implementation through the MementoAP profile
using ipv4.method=shared. This script decides when to activate/deactivate it.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

AP_INTERFACE = "wlan0"
AP_CON_NAME  = "MementoAP"
AP_SSID      = "MementoFrame"
AP_IP        = "192.168.4.1"
AP_CHANNEL   = "6"

CHECK_INTERVAL     = 5
NETWORK_SCAN_EVERY = 30
PROBE_EVERY        = 120
PROBE_TIMEOUT      = 35
MAX_AP_DURATION    = 600
REQUEST_MAX_AGE    = 10 * 60

RUNTIME_DIR = Path("runtime")
WIFI_REQUEST_FILE  = RUNTIME_DIR / "wifi_request.json"
WIFI_STATE_FILE    = RUNTIME_DIR / "wifi_state.json"
WIFI_RESULT_FILE   = RUNTIME_DIR / "wifi_result.json"
WIFI_NETWORKS_FILE = RUNTIME_DIR / "wifi_networks.json"

# ─────────────────────────────────────────────────────────────────────────────
# Global state
# ─────────────────────────────────────────────────────────────────────────────

_ap_start_time = 0.0
_last_probe = 0.0
_last_scan = 0.0

# ─────────────────────────────────────────────────────────────────────────────
# JSON helpers
# ─────────────────────────────────────────────────────────────────────────────


def ensure_runtime():
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def atomic_write_json(path: Path, data):
    ensure_runtime()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def remove_file(path: Path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"⚠️ Could not remove {path}: {e}")


def write_state(status="monitoring", extra=None):
    data = {
        "mode": current_mode(),
        "ip": current_ip(),
        "ap_running": ap_active(),
        "connection": current_connection(),
        "status": status,
        "updated_at": time.time(),
    }
    if extra:
        data.update(extra)
    atomic_write_json(WIFI_STATE_FILE, data)


def write_result(success: bool, message: str, ssid=None):
    atomic_write_json(WIFI_RESULT_FILE, {
        "success": success,
        "message": message,
        "ssid": ssid,
        "updated_at": time.time(),
    })

# ─────────────────────────────────────────────────────────────────────────────
# Shell helpers
# ─────────────────────────────────────────────────────────────────────────────


def run(cmd, label=None):
    tag = label or " ".join(str(c) for c in cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"  ❌ FAILED [{tag}]")
        if proc.stdout.strip():
            print(f"     stdout: {proc.stdout.strip()}")
        if proc.stderr.strip():
            print(f"     stderr: {proc.stderr.strip()}")
    return proc


def sh(cmd):
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()


def nmcli(*args):
    return run(["sudo", "nmcli"] + list(args))

# ─────────────────────────────────────────────────────────────────────────────
# Network state
# ─────────────────────────────────────────────────────────────────────────────


def current_connection():
    try:
        out = sh(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 4 and parts[0] == AP_INTERFACE and parts[1] == "wifi":
                return parts[3] if parts[2] == "connected" else None
    except subprocess.CalledProcessError:
        pass
    return None


def ap_active():
    return current_connection() == AP_CON_NAME


def wifi_connected():
    con = current_connection()
    return bool(con and con != AP_CON_NAME)


def current_ip():
    try:
        out = sh(["ip", "-4", "addr", "show", AP_INTERFACE])
        for line in out.splitlines():
            stripped = line.strip()
            if stripped.startswith("inet "):
                return stripped.split()[1].split("/")[0]
    except subprocess.CalledProcessError:
        pass
    return AP_IP if ap_active() else None


def current_mode():
    if ap_active():
        return "ap"
    if wifi_connected():
        return "client"
    return "unknown"


def ap_profile_exists():
    try:
        out = sh(["nmcli", "-t", "-f", "NAME", "connection", "show"])
        return AP_CON_NAME in out.splitlines()
    except subprocess.CalledProcessError:
        return False


def clients_connected():
    try:
        out = sh(["sudo", "iw", "dev", AP_INTERFACE, "station", "dump"])
        return "Station" in out
    except subprocess.CalledProcessError:
        return False

# ─────────────────────────────────────────────────────────────────────────────
# First-run setup
# ─────────────────────────────────────────────────────────────────────────────


def check_for_conflicts():
    conflicts = []
    for service in ["hostapd", "dnsmasq"]:
        try:
            if sh(["systemctl", "is-active", service]) == "active":
                conflicts.append(service)
        except subprocess.CalledProcessError:
            pass

    if conflicts:
        print("❌ Conflicting services are running:")
        for s in conflicts:
            print(f"   - {s}")
        print("\nNetworkManager AP mode uses internal dnsmasq. Disable conflicts:")
        for s in conflicts:
            print(f"   sudo systemctl stop {s} && sudo systemctl disable {s}")
        sys.exit(1)


def ensure_ap_profile():
    if ap_profile_exists():
        return

    print(f"🔧 Creating NetworkManager AP profile '{AP_CON_NAME}'…")
    run(["sudo", "nmcli", "connection", "delete", AP_CON_NAME], label=f"cleanup stale {AP_CON_NAME}")

    commands = [
        ["sudo", "nmcli", "connection", "add",
         "type", "wifi", "ifname", AP_INTERFACE,
         "con-name", AP_CON_NAME, "autoconnect", "no", "ssid", AP_SSID],

        ["sudo", "nmcli", "connection", "modify", AP_CON_NAME,
         "802-11-wireless.mode", "ap",
         "802-11-wireless.band", "bg",
         "802-11-wireless.channel", AP_CHANNEL],

        ["sudo", "nmcli", "connection", "modify", AP_CON_NAME,
         "ipv4.method", "shared",
         "ipv4.address", f"{AP_IP}/24"],

        ["sudo", "nmcli", "connection", "modify", AP_CON_NAME,
         "ipv6.method", "disabled"],
    ]

    for cmd in commands:
        if run(cmd).returncode != 0:
            print("❌ AP profile creation failed.")
            sys.exit(1)

    conn_file = f"/etc/NetworkManager/system-connections/{AP_CON_NAME}.nmconnection"
    try:
        with open(conn_file, "r", encoding="utf-8") as f:
            content = f.read()
        if "powersave=" not in content:
            content = content.replace("[wifi]\n", "[wifi]\npowersave=2\n")
            with open(conn_file, "w", encoding="utf-8") as f:
                f.write(content)
        run(["sudo", "nmcli", "connection", "reload"])
    except (FileNotFoundError, PermissionError) as e:
        print(f"  ⚠️ Could not write powersave setting: {e}")

    print(f"  ✅ AP profile ready — SSID: {AP_SSID} | Gateway: {AP_IP}")


def ensure_client_profiles_patched():
    try:
        profiles_out = sh(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
    except subprocess.CalledProcessError:
        return

    for line in profiles_out.splitlines():
        parts = line.split(":", 1)
        if len(parts) != 2 or parts[1] != "802-11-wireless":
            continue
        name = parts[0]
        if name == AP_CON_NAME:
            continue
        run(["sudo", "nmcli", "connection", "modify", name,
             "connection.autoconnect", "yes",
             "connection.autoconnect-retries", "0"],
            label=f"patch client profile {name}")

# ─────────────────────────────────────────────────────────────────────────────
# Scanning and profiles
# ─────────────────────────────────────────────────────────────────────────────


def parse_ssid_lines(out):
    networks = []
    for line in out.splitlines():
        ssid = line.strip()
        if ssid and ssid not in networks and ssid != AP_SSID:
            networks.append(ssid)
    return networks


def scan_networks(force=True):
    """
    Scan Wi-Fi networks and publish runtime/wifi_networks.json.

    When the single Wi-Fi radio is actively serving AP mode, scans may fail or
    return stale results depending on driver state. We keep the previous list if
    a scan fails, so the config page does not suddenly go blank.
    """
    previous = read_json(WIFI_NETWORKS_FILE) or {}
    previous_networks = previous.get("networks", []) if isinstance(previous, dict) else []

    networks = []
    try:
        if force:
            run(["sudo", "nmcli", "device", "wifi", "rescan", "ifname", AP_INTERFACE], label="wifi rescan")
            time.sleep(2)

        out = sh(["nmcli", "-t", "-f", "SSID", "device", "wifi", "list", "ifname", AP_INTERFACE])
        networks = parse_ssid_lines(out)

    except subprocess.CalledProcessError as e:
        print(f"  ⚠️ Wi-Fi scan failed; keeping cached networks if available: {e}")
        networks = previous_networks

    atomic_write_json(WIFI_NETWORKS_FILE, {
        "networks": networks,
        "updated_at": time.time(),
        "source": "nmcli" if networks != previous_networks else "cache_or_nmcli",
    })
    return networks


def create_or_update_client_profile(ssid, psk):
    ssid = (ssid or "").strip()
    psk = (psk or "").strip()
    if not ssid:
        return False, "SSID is required"

    run(["sudo", "nmcli", "connection", "delete", ssid], label=f"delete stale profile {ssid}")

    rc = run([
        "sudo", "nmcli", "connection", "add",
        "type", "wifi",
        "ifname", AP_INTERFACE,
        "con-name", ssid,
        "ssid", ssid,
        "autoconnect", "yes",
    ], label=f"add profile {ssid}")
    if rc.returncode != 0:
        return False, "Failed to create Wi-Fi profile"

    if psk:
        rc = run(["sudo", "nmcli", "connection", "modify", ssid,
                  "802-11-wireless-security.key-mgmt", "wpa-psk"],
                 label=f"set WPA mode {ssid}")
        if rc.returncode != 0:
            return False, "Failed to configure Wi-Fi security"

        rc = run(["sudo", "nmcli", "connection", "modify", ssid,
                  "802-11-wireless-security.psk", psk],
                 label=f"set WPA password {ssid}")
        if rc.returncode != 0:
            return False, "Failed to save Wi-Fi password"

    run(["sudo", "nmcli", "connection", "modify", ssid,
         "connection.autoconnect", "yes",
         "connection.autoconnect-retries", "0"],
        label=f"patch autoconnect {ssid}")

    return True, "Wi-Fi profile saved"

# ─────────────────────────────────────────────────────────────────────────────
# Mode switching
# ─────────────────────────────────────────────────────────────────────────────


def start_ap():
    global _ap_start_time
    if ap_active():
        return True

    print("📡 Activating AP mode…")
    result = nmcli("connection", "up", AP_CON_NAME)
    if result.returncode != 0:
        print("  ❌ AP activation failed.")
        return False

    time.sleep(3)
    _ap_start_time = time.time()
    write_state("ap_active")
    # Attempt to publish a list immediately. It may be cached if scan fails.
    scan_networks(force=True)
    print(f"  ✅ AP '{AP_SSID}' live at {AP_IP}")
    return True


def stop_ap():
    if not ap_active():
        return True

    print("🔌 Deactivating AP mode…")
    result = nmcli("connection", "down", AP_CON_NAME)
    if result.returncode != 0:
        run(["sudo", "nmcli", "device", "disconnect", AP_INTERFACE], label="device disconnect fallback")
        return False

    time.sleep(2)
    write_state("ap_stopped")
    print("  AP stopped. NetworkManager can connect client profiles now.")
    return True


def connect_requested_network(ssid, psk):
    print(f"🔁 User requested Wi-Fi connection: {ssid!r}")
    write_state("connecting", extra={"target_ssid": ssid})
    write_result(False, f"Connecting to {ssid}…", ssid)

    ok, msg = create_or_update_client_profile(ssid, psk)
    if not ok:
        write_result(False, msg, ssid)
        start_ap()
        return False

    stop_ap()
    run(["sudo", "nmcli", "radio", "wifi", "on"], label="wifi radio on")

    rc = nmcli("connection", "up", ssid)
    if rc.returncode != 0:
        write_result(False, f"Failed to connect to {ssid}. Restoring AP mode.", ssid)
        start_ap()
        return False

    deadline = time.time() + PROBE_TIMEOUT
    while time.time() < deadline:
        if wifi_connected():
            write_state("connected", extra={"target_ssid": ssid})
            write_result(True, f"Connected to {ssid}", ssid)
            scan_networks(force=True)
            print(f"✅ Connected to Wi-Fi: {ssid}")
            return True
        time.sleep(2)

    write_result(False, f"Connection to {ssid} timed out. Restoring AP mode.", ssid)
    start_ap()
    return False

# ─────────────────────────────────────────────────────────────────────────────
# Request handling and reconnect probes
# ─────────────────────────────────────────────────────────────────────────────


def consume_wifi_request():
    req = read_json(WIFI_REQUEST_FILE)
    if not req:
        return False

    # Move request out of the way before acting, so repeated loop iterations do
    # not submit the same credentials multiple times.
    remove_file(WIFI_REQUEST_FILE)

    ssid = (req.get("ssid") or "").strip()
    psk = req.get("psk") or ""
    created_at = float(req.get("created_at") or 0)

    if not ssid:
        write_result(False, "SSID is required")
        return True

    if created_at and time.time() - created_at > REQUEST_MAX_AGE:
        write_result(False, f"Wi-Fi request for {ssid} expired", ssid)
        return True

    connect_requested_network(ssid, psk)
    return True


def known_client_profiles():
    profiles = []
    try:
        profiles_out = sh(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
    except subprocess.CalledProcessError:
        return profiles

    for line in profiles_out.splitlines():
        parts = line.split(":", 1)
        if len(parts) == 2 and parts[1] == "802-11-wireless" and parts[0] != AP_CON_NAME:
            profiles.append(parts[0])
    return profiles


def probe_reconnect(force=False):
    if ap_active() and not force and clients_connected():
        print("🛠 Client connected to AP — skipping reconnect probe.")
        return False

    print("🔎 Probing saved Wi-Fi profiles…")
    scan_networks(force=True)

    profiles = known_client_profiles()
    if not profiles:
        print("  No saved Wi-Fi profiles — staying in AP mode.")
        return False

    stop_ap()
    run(["sudo", "nmcli", "radio", "wifi", "on"], label="wifi radio on")

    for profile in profiles:
        print(f"  Trying saved profile: {profile}")
        nmcli("connection", "up", profile)
        deadline = time.time() + 15
        while time.time() < deadline:
            if wifi_connected():
                write_state("connected", extra={"target_ssid": profile})
                write_result(True, f"Reconnected to {profile}", profile)
                print(f"  ✅ Reconnected to Wi-Fi: {profile}")
                return True
            time.sleep(2)

    print("  ⏳ Saved profiles failed — restoring AP.")
    start_ap()
    return False

# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────


def main():
    global _last_probe, _last_scan

    ensure_runtime()
    check_for_conflicts()
    ensure_ap_profile()
    ensure_client_profiles_patched()

    print()
    print("🖼  MementoFrame AP Mode Manager")
    print(f"   Interface : {AP_INTERFACE}")
    print(f"   AP SSID   : {AP_SSID} (open network — config PIN protects dashboard)")
    print(f"   Gateway   : {AP_IP}")
    print(f"   Runtime   : {RUNTIME_DIR}")
    print()

    write_state("starting")

    # Write an empty networks file immediately so app.py never reads None
    # while waiting for the first real scan to complete.
    if not WIFI_NETWORKS_FILE.exists():
        atomic_write_json(WIFI_NETWORKS_FILE, {
            "networks": [],
            "updated_at": time.time(),
            "source": "startup_placeholder",
        })

    scan_networks(force=True)

    while True:
        now = time.time()

        # Highest priority: user-submitted Wi-Fi credentials from app.py.
        if consume_wifi_request():
            _last_probe = now
            _last_scan = now
            time.sleep(CHECK_INTERVAL)
            continue

        # Keep network list fresh for the config page.
        if now - _last_scan >= NETWORK_SCAN_EVERY:
            scan_networks(force=True)
            _last_scan = now

        if wifi_connected():
            write_state("connected")
            print("📶 Connected to Wi-Fi — monitoring…")

        else:
            if not ap_active():
                print("⚠️ No Wi-Fi — entering AP mode.")
                start_ap()
                _last_probe = now

            else:
                write_state("ap_active")
                uptime = now - _ap_start_time if _ap_start_time else 0
                since_probe = now - _last_probe

                if uptime > MAX_AP_DURATION:
                    print(f"⏰ AP up {uptime:.0f}s — forcing reconnect probe.")
                    probe_reconnect(force=True)
                    _last_probe = now

                elif since_probe >= PROBE_EVERY:
                    probe_reconnect(force=False)
                    _last_probe = now

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()