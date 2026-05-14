#!/usr/bin/env python3
# MementoFrame - Raspberry Pi Smart Photo Frame
# Copyright (c) 2026 João Fernandes
#
# This work is licensed under the Creative Commons Attribution-NonCommercial
# 4.0 International License. To view a copy of this license, visit:
# http://creativecommons.org/licenses/by-nc/4.0/

"""
ap_mode_manager.py

Brief:
    NetworkManager watchdog for switching the Raspberry Pi between normal Wi-Fi
    client mode and fallback Access Point mode.

Endpoints:
    None — this file does not expose HTTP routes or API endpoints.

Description:
    This service keeps the MementoFrame reachable even when the configured Wi-Fi
    network is unavailable. If no client Wi-Fi connection is active, it enables
    a local Access Point named ``MementoFrame``. While AP mode is active, it
    periodically checks saved Wi-Fi profiles and reconnects when possible.

Flow chart:

    ┌──────────────┐
    │ Start script │
    └──────┬───────┘
           │
           ▼
    ┌──────────────────────┐
    │ Check service conflicts│
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────┐
    │ Ensure AP profile     │
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────┐
    │ Patch client profiles │
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────┐
    │ Watch network forever │
    └──────┬───────────────┘
           │
           ├── Wi-Fi connected ──► Monitor
           │
           └── No Wi-Fi ────────► Start AP mode
                                      │
                                      ▼
                              Periodically probe
                              saved Wi-Fi profiles
                                      │
                                      ▼
                              Reconnect or restore AP
"""

import subprocess
import sys
import time


# =============================================================================
# Configuration
# =============================================================================

# Wireless interface used by both client Wi-Fi and AP mode.
AP_INTERFACE = "wlan0"

# NetworkManager connection profile name for the fallback access point.
AP_CON_NAME = "MementoAP"

# Public SSID shown when the frame enters configuration mode.
AP_SSID = "MementoFrame"

# Gateway IP assigned to the Raspberry Pi while AP mode is active.
AP_IP = "192.168.4.1"

# Wi-Fi channel used by the access point profile.
AP_CHANNEL = "6"

# Main watchdog loop interval.
CHECK_INTERVAL = 5

# Interval between saved-profile reconnect attempts while AP mode is active.
PROBE_EVERY = 120

# Maximum time to wait for each saved Wi-Fi profile to connect.
PROBE_TIMEOUT = 15

# Maximum AP uptime before forcing a reconnect probe.
MAX_AP_DURATION = 600


# =============================================================================
# Runtime state
# =============================================================================

# Timestamp recorded when AP mode starts.
_ap_start_time = 0.0

# Timestamp recorded after the last reconnect probe.
_last_probe = 0.0


# =============================================================================
# Shell helpers
# =============================================================================

def run(cmd, label=None):
    """
    Execute a shell command and return the CompletedProcess.

    This helper captures stdout/stderr so failures can be printed clearly while
    allowing the caller to decide whether the failure is fatal.
    """
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
    """
    Execute a command and return stripped stdout.

    Raises:
        subprocess.CalledProcessError:
            Raised when the command exits with a non-zero status.
    """
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()


def nmcli(*args):
    """
    Run an nmcli command with sudo.

    Args:
        *args:
            Arguments passed directly to ``nmcli``.
    """
    return run(["sudo", "nmcli"] + list(args))


# =============================================================================
# Network state helpers
# =============================================================================

def current_connection():
    """
    Return the active NetworkManager connection name on the configured interface.

    Returns:
        str | None:
            The active connection name when wlan0 is connected, otherwise None.
    """
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
    """
    Check whether the fallback access point profile is currently active.
    """
    return current_connection() == AP_CON_NAME


def wifi_connected():
    """
    Check whether the device is connected to a normal Wi-Fi client profile.
    """
    con = current_connection()
    return bool(con and con != AP_CON_NAME)


def clients_connected():
    """
    Check whether any client device is currently associated with the AP.

    Returns:
        bool:
            True when at least one station is connected to the AP.
    """
    try:
        out = sh(["sudo", "iw", "dev", AP_INTERFACE, "station", "dump"])
        return "Station" in out

    except subprocess.CalledProcessError:
        return False


# =============================================================================
# First-run setup
# =============================================================================

def check_for_conflicts():
    """
    Stop startup if services that conflict with NetworkManager AP mode are active.

    NetworkManager uses its own internal dnsmasq behavior for shared connections.
    Running hostapd or dnsmasq separately can prevent AP mode from working
    reliably.
    """
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


def ap_profile_exists():
    """
    Check whether the fallback AP NetworkManager profile already exists.
    """
    try:
        out = sh(["nmcli", "-t", "-f", "NAME", "connection", "show"])
        return AP_CON_NAME in out.splitlines()

    except subprocess.CalledProcessError:
        return False


def ensure_ap_profile():
    """
    Create the NetworkManager AP profile when it does not already exist.

    The profile is configured as:
        - Wi-Fi access point mode
        - IPv4 shared networking
        - Static gateway address
        - IPv6 disabled
        - Wi-Fi power saving disabled where possible
    """
    if ap_profile_exists():
        return

    print(f"🔧 Creating NetworkManager AP profile '{AP_CON_NAME}'…")

    run(
        ["sudo", "nmcli", "connection", "delete", AP_CON_NAME],
        label=f"cleanup stale {AP_CON_NAME}",
    )

    commands = [
        [
            "sudo", "nmcli", "connection", "add",
            "type", "wifi", "ifname", AP_INTERFACE,
            "con-name", AP_CON_NAME, "autoconnect", "no", "ssid", AP_SSID,
        ],
        [
            "sudo", "nmcli", "connection", "modify", AP_CON_NAME,
            "802-11-wireless.mode", "ap",
            "802-11-wireless.band", "bg",
            "802-11-wireless.channel", AP_CHANNEL,
        ],
        [
            "sudo", "nmcli", "connection", "modify", AP_CON_NAME,
            "ipv4.method", "shared",
            "ipv4.address", f"{AP_IP}/24",
        ],
        [
            "sudo", "nmcli", "connection", "modify", AP_CON_NAME,
            "ipv6.method", "disabled",
        ],
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
    """
    Enable autoconnect on all saved Wi-Fi client profiles.

    The AP profile itself is excluded so NetworkManager does not automatically
    start the fallback AP unless this watchdog explicitly requests it.
    """
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

        run(
            [
                "sudo", "nmcli", "connection", "modify", name,
                "connection.autoconnect", "yes",
                "connection.autoconnect-retries", "0",
            ],
            label=f"patch client profile {name}",
        )


# =============================================================================
# Mode switching
# =============================================================================

def start_ap():
    """
    Activate fallback AP mode.

    Returns:
        bool:
            True when AP mode is already active or successfully started.
    """
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

    print(f"  ✅ AP '{AP_SSID}' live at {AP_IP}")
    return True


def stop_ap():
    """
    Deactivate fallback AP mode.

    Returns:
        bool:
            True when AP mode is inactive or successfully stopped.
    """
    if not ap_active():
        return True

    print("🔌 Deactivating AP mode…")

    result = nmcli("connection", "down", AP_CON_NAME)

    if result.returncode != 0:
        run(
            ["sudo", "nmcli", "device", "disconnect", AP_INTERFACE],
            label="device disconnect fallback",
        )
        return False

    time.sleep(2)

    print("  AP stopped. NetworkManager can connect client profiles now.")
    return True


# =============================================================================
# Reconnect probing
# =============================================================================

def known_client_profiles():
    """
    Return saved Wi-Fi client profile names, excluding the AP profile.
    """
    profiles = []

    try:
        out = sh(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])

    except subprocess.CalledProcessError:
        return profiles

    for line in out.splitlines():
        parts = line.split(":", 1)

        if len(parts) == 2 and parts[1] == "802-11-wireless" and parts[0] != AP_CON_NAME:
            profiles.append(parts[0])

    return profiles


def probe_reconnect(force=False):
    """
    Try reconnecting to saved Wi-Fi client profiles.

    Args:
        force:
            When True, probe even if a device is currently connected to the AP.

    Returns:
        bool:
            True when a saved Wi-Fi profile reconnects successfully.
    """
    if ap_active() and not force and clients_connected():
        print("🛠 Client connected to AP — skipping reconnect probe.")
        return False

    print("🔎 Probing saved Wi-Fi profiles…")

    profiles = known_client_profiles()

    if not profiles:
        print("  No saved Wi-Fi profiles — staying in AP mode.")
        return False

    stop_ap()

    run(["sudo", "nmcli", "radio", "wifi", "on"], label="wifi radio on")

    for profile in profiles:
        print(f"  Trying saved profile: {profile}")

        nmcli("connection", "up", profile)

        deadline = time.time() + PROBE_TIMEOUT

        while time.time() < deadline:
            if wifi_connected():
                print(f"  ✅ Reconnected to Wi-Fi: {profile}")
                return True

            time.sleep(2)

    print("  ⏳ All saved profiles failed — restoring AP.")

    start_ap()

    return False


# =============================================================================
# Main watchdog loop
# =============================================================================

def main():
    """
    Initialize NetworkManager configuration and continuously monitor connectivity.
    """
    global _last_probe

    check_for_conflicts()
    ensure_ap_profile()
    ensure_client_profiles_patched()

    print()
    print("🖼  MementoFrame AP Mode Manager")
    print(f"   Interface : {AP_INTERFACE}")
    print(f"   AP SSID   : {AP_SSID} (open network — config portal PIN protects dashboard)")
    print(f"   Gateway   : {AP_IP}")
    print()

    while True:
        now = time.time()

        if wifi_connected():
            print("📶 Connected to Wi-Fi — monitoring…")

        else:
            if not ap_active():
                print("⚠️ No Wi-Fi — entering AP mode.")

                start_ap()

                _last_probe = now

            else:
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