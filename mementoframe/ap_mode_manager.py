# MementoFrame - Raspberry Pi Smart Photo Frame
# Copyright (c) 2026 João Fernandes
#
# This work is licensed under the Creative Commons Attribution-NonCommercial
# 4.0 International License. To view a copy of this license, visit:
# http://creativecommons.org/licenses/by-nc/4.0/

#!/usr/bin/env python3
"""
ap_mode_manager.py — Wi-Fi / Access Point Mode Manager
Raspberry Pi OS Bookworm (NetworkManager) edition

On first run, this script automatically creates the MementoAP NetworkManager
profile and patches saved client profiles. No manual setup step required.

Architecture
────────────
Two persistent NetworkManager profiles are managed:

  ┌──────────────────────────────────────────────────────────────┐
  │  Profile: <your home SSID>   (created by raspi-config/nmtui) │
  │  autoconnect-retries: 0  ← patched on first run (was 4)      │
  └──────────────────────────────────────────────────────────────┘
  ┌──────────────────────────────────────────────────────────────┐
  │  Profile: MementoAP          (created on first run)          │
  │  ipv4.method: shared  ← NM handles DHCP/dnsmasq internally   │
  │  powersave: 2         ← off, required for AP stability        │
  └──────────────────────────────────────────────────────────────┘

State machine (runs every CHECK_INTERVAL seconds):
  ┌─────────────────┐   no known SSID in range  ┌──────────┐
  │   CLIENT MODE   │ ────────────────────────► │  AP MODE │
  │  (NM connected) │ ◄──────────────────────── │          │
  └─────────────────┘   known SSID found        └──────────┘
                                                     │
                            Every PROBE_EVERY s, AP scans for known
                            SSIDs. If found → stop AP, reconnect.
                            Skipped if a client device is connected.
                            Forced after MAX_AP_DURATION regardless.

Why NOT hostapd/dnsmasq?
────────────────────────
Bookworm's NetworkManager runs its own internal dnsmasq when using
ipv4.method=shared. A separately running hostapd or dnsmasq.service
WILL conflict with NM and silently break AP mode. If either is
installed, this script will warn and exit. Disable them with:
  sudo systemctl stop hostapd dnsmasq
  sudo systemctl disable hostapd dnsmasq

Usage:
  sudo python3 ap_mode_manager.py

Logs (when running as a systemd service):
  journalctl -u mementoframe-ap -f
"""

import subprocess
import time
import sys

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

AP_INTERFACE    = "wlan0"           # Wireless interface name
AP_CON_NAME     = "MementoAP"      # NM connection profile name for AP mode
AP_SSID         = "MementoFrame"   # SSID broadcast in AP mode
AP_PASSWORD     = "mementoframe"   # WPA2 password (min 8 chars)
AP_IP           = "192.168.4.1"    # Gateway IP served to AP clients
AP_CHANNEL      = "6"              # 2.4 GHz channel (1, 6, or 11 recommended)

CHECK_INTERVAL  = 30               # Seconds between main-loop iterations
PROBE_EVERY     = 120              # Seconds between reconnect probes in AP mode
PROBE_TIMEOUT   = 30               # Seconds to wait for NM to reconnect
MAX_AP_DURATION = 600              # Force a probe after this many AP-mode seconds

# ─────────────────────────────────────────────────────────────────────────────
# Global state
# ─────────────────────────────────────────────────────────────────────────────

AP_RUNNING      = False
_ap_start_time  = 0.0
_last_probe     = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Shell helpers
# ─────────────────────────────────────────────────────────────────────────────

def run(cmd, label=None):
    """Run a command, log any failures. Never raises."""
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
    """Run a command, return stripped stdout. Raises CalledProcessError on failure."""
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()


def nmcli(*args):
    """Convenience: sudo nmcli <args>."""
    return run(["sudo", "nmcli"] + list(args))


# ─────────────────────────────────────────────────────────────────────────────
# Network state queries
# ─────────────────────────────────────────────────────────────────────────────

def wifi_connected():
    """
    Ask NetworkManager if wlan0 is fully connected in client (infrastructure) mode.
    NM only reports 'connected' (not 'connected:local') after DHCP completes.
    Never returns True while the interface is in AP mode.
    """
    try:
        out = sh(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"])
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[0] == AP_INTERFACE and parts[1] == "wifi":
                return parts[2] == "connected"
        return False
    except subprocess.CalledProcessError:
        return False


def known_ssids_in_range():
    """
    Perform a live scan and return True if any saved client profile's SSID
    is currently visible.

    Uses `iw dev scan` rather than `nmcli device wifi list` because iw
    always performs a fresh scan while nmcli can return stale cached results,
    especially when the interface has recently been in AP mode.
    """
    # Collect SSIDs from all saved client (non-AP) wifi profiles
    try:
        profiles_out = sh(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
    except subprocess.CalledProcessError:
        return False

    saved_ssids = set()
    for line in profiles_out.splitlines():
        parts = line.split(":", 1)
        if len(parts) == 2 and parts[1] == "802-11-wireless":
            name = parts[0]
            if name == AP_CON_NAME:
                continue
            try:
                raw = sh(["nmcli", "-t", "-f", "802-11-wireless.ssid",
                          "connection", "show", name])
                ssid = raw.split(":", 1)[-1].strip()
                if ssid:
                    saved_ssids.add(ssid)
            except subprocess.CalledProcessError:
                pass

    if not saved_ssids:
        return False

    # Live scan
    try:
        scan_out = sh(["sudo", "iw", "dev", AP_INTERFACE, "scan"])
        for line in scan_out.splitlines():
            stripped = line.strip()
            if stripped.startswith("SSID:"):
                visible_ssid = stripped[5:].strip()
                if visible_ssid in saved_ssids:
                    print(f"  📶 Known SSID in range: {visible_ssid!r}")
                    return True
    except subprocess.CalledProcessError:
        print("  ⚠️  iw scan failed (interface busy?) — assuming no SSIDs in range.")

    return False


def ap_profile_exists():
    """Return True if the MementoAP NM connection profile exists."""
    try:
        out = sh(["nmcli", "-t", "-f", "NAME", "connection", "show"])
        return AP_CON_NAME in out.splitlines()
    except subprocess.CalledProcessError:
        return False


def clients_connected():
    """
    Return True if any Wi-Fi station is associated with our AP.
    Uses `iw dev station dump` — no hostapd_cli required.
    """
    try:
        out = sh(["sudo", "iw", "dev", AP_INTERFACE, "station", "dump"])
        return "Station" in out
    except subprocess.CalledProcessError:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# First-run setup (idempotent — safe to call on every boot)
# ─────────────────────────────────────────────────────────────────────────────

def check_for_conflicts():
    """
    Warn and exit if hostapd or dnsmasq.service are active.
    Both conflict with NM's internal AP/DHCP stack on Bookworm.
    """
    conflicts = []
    for service in ["hostapd", "dnsmasq"]:
        try:
            if sh(["systemctl", "is-active", service]) == "active":
                conflicts.append(service)
        except subprocess.CalledProcessError:
            pass  # Not installed — fine

    if conflicts:
        print("❌ Conflicting services are running:")
        for s in conflicts:
            print(f"   - {s}")
        print()
        print("These conflict with NetworkManager's AP mode on Bookworm.")
        print("Disable them before running this script:")
        for s in conflicts:
            print(f"   sudo systemctl stop {s} && sudo systemctl disable {s}")
        sys.exit(1)


def ensure_ap_profile():
    """
    Create the MementoAP NM connection profile if it doesn't already exist.
    Idempotent: exits immediately if the profile is already present.

    Key settings:
      802-11-wireless.mode ap     — AP (not client) mode
      ipv4.method shared          — NM runs DHCP/NAT internally via dnsmasq-base
      wifi-sec.proto rsn          — WPA2 only, no WPA1
      wifi-sec.group/pairwise ccmp — CCMP only, no TKIP
      connection.autoconnect no   — script controls activation manually
      powersave=2                 — power save OFF; required for AP stability on
                                   Bookworm (NM started enforcing this Oct 2024)
    """
    if ap_profile_exists():
        return  # Nothing to do

    print(f"🔧 First run: creating AP profile '{AP_CON_NAME}'…")

    # Clean up any broken remnant with the same name
    run(["sudo", "nmcli", "connection", "delete", AP_CON_NAME],
        label=f"cleanup stale {AP_CON_NAME}")

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

        ["sudo", "nmcli", "connection", "modify", AP_CON_NAME,
         "wifi-sec.key-mgmt", "wpa-psk",
         "wifi-sec.proto", "rsn",
         "wifi-sec.group", "ccmp",
         "wifi-sec.pairwise", "ccmp",
         "wifi-sec.psk", AP_PASSWORD],
    ]

    for cmd in commands:
        if run(cmd).returncode != 0:
            print("❌ AP profile creation failed. See errors above.")
            sys.exit(1)

    # Write powersave=2 into the .nmconnection file directly —
    # nmcli has no CLI flag for this setting.
    conn_file = (f"/etc/NetworkManager/system-connections/"
                 f"{AP_CON_NAME}.nmconnection")
    try:
        with open(conn_file, "r") as f:
            content = f.read()
        if "powersave=" not in content:
            content = content.replace("[wifi]\n", "[wifi]\npowersave=2\n")
            with open(conn_file, "w") as f:
                f.write(content)
        run(["sudo", "nmcli", "connection", "reload"])
    except (FileNotFoundError, PermissionError) as e:
        print(f"  ⚠️  Could not write powersave setting: {e}")
        print("     AP may drop clients after extended idle. Try running as root.")

    print(f"  ✅ AP profile created — SSID: {AP_SSID}  |  Password: {AP_PASSWORD}  |  IP: {AP_IP}")


def ensure_client_profiles_patched():
    """
    Patch all saved client Wi-Fi profiles to use autoconnect-retries=0.
    Idempotent: skips profiles already set correctly.

    NM's default of -1 means only ~4 reconnect attempts before giving up
    forever until reboot. Setting 0 means retry indefinitely — essential
    for a headless device that must recover from temporary signal loss.
    """
    try:
        profiles_out = sh(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
    except subprocess.CalledProcessError:
        return

    for line in profiles_out.splitlines():
        parts = line.split(":", 1)
        if len(parts) == 2 and parts[1] == "802-11-wireless":
            name = parts[0]
            if name == AP_CON_NAME:
                continue
            try:
                current = sh(["nmcli", "-t", "-f", "connection.autoconnect-retries",
                               "connection", "show", name])
                value = current.split(":")[-1].strip()
                if value == "0":
                    continue  # Already patched
            except subprocess.CalledProcessError:
                pass
            print(f"🔧 Patching client profile '{name}': autoconnect-retries → 0")
            run(["sudo", "nmcli", "connection", "modify", name,
                 "connection.autoconnect-retries", "0"])


# ─────────────────────────────────────────────────────────────────────────────
# Mode switching
# ─────────────────────────────────────────────────────────────────────────────

def start_ap():
    """
    Activate the MementoAP NM profile.
    NM handles the AP beacon, WPA2, DHCP, and routing internally.
    """
    global AP_RUNNING, _ap_start_time
    if AP_RUNNING:
        return

    print("📡 Activating AP mode…")
    result = nmcli("connection", "up", AP_CON_NAME)
    if result.returncode != 0:
        print("  ❌ AP activation failed.")
        return

    time.sleep(3)  # Let NM fully bring the profile up before we poll it
    _ap_start_time = time.time()
    AP_RUNNING = True
    print(f"  ✅ AP '{AP_SSID}' live at {AP_IP}")


def stop_ap():
    """
    Deactivate the MementoAP NM profile.
    NM's autoconnect will then try to associate wlan0 with saved client
    profiles — we do not need to trigger this manually.
    """
    global AP_RUNNING
    if not AP_RUNNING:
        return

    print("🔌 Deactivating AP mode…")
    result = nmcli("connection", "down", AP_CON_NAME)
    if result.returncode != 0:
        run(["sudo", "nmcli", "device", "disconnect", AP_INTERFACE],
            label="device disconnect (fallback)")

    AP_RUNNING = False
    print("  AP stopped — NM will now attempt to reconnect to saved networks.")


# ─────────────────────────────────────────────────────────────────────────────
# Reconnect probe
# ─────────────────────────────────────────────────────────────────────────────

def probe_reconnect(force=False):
    """
    While in AP mode: scan for known networks and attempt to reconnect.

      1. Skip if a client device is connected (unless forced).
      2. Live-scan for known SSIDs.
      3. If none visible: stay in AP mode.
      4. Stop AP — NM autoconnect takes over.
      5. Poll for PROBE_TIMEOUT seconds.
      6. Success → return True. Timeout → restart AP, return False.

    Args:
        force: Ignore connected clients; used when MAX_AP_DURATION is exceeded.
    """
    if not force and clients_connected():
        print("🛠  Client connected to AP — skipping probe.")
        return False

    print("🔎 Scanning for known Wi-Fi networks…")

    if not known_ssids_in_range():
        print("  No known networks visible — staying in AP mode.")
        return False

    print("  Known network found — attempting reconnect.")
    stop_ap()
    time.sleep(5)  # Give NM time to begin association

    t0 = time.time()
    while time.time() - t0 < PROBE_TIMEOUT:
        if wifi_connected():
            print("  ✅ Reconnected to Wi-Fi.")
            return True
        time.sleep(2)

    print("  ⏳ Reconnect timed out — restoring AP.")
    start_ap()
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────

def main():
    global _last_probe

    # ── First-run setup (idempotent — fast no-ops after first boot) ──────────
    check_for_conflicts()
    ensure_ap_profile()
    ensure_client_profiles_patched()
    # ─────────────────────────────────────────────────────────────────────────

    print()
    print("🖼  MementoFrame AP Mode Manager")
    print(f"   Interface : {AP_INTERFACE}")
    print(f"   AP SSID   : {AP_SSID}  |  Gateway: {AP_IP}")
    print(f"   Loop      : every {CHECK_INTERVAL}s  |  Probe: every {PROBE_EVERY}s")
    print()

    while True:
        connected = wifi_connected()

        if connected:
            if AP_RUNNING:
                print("✅ Wi-Fi client connection detected — stopping AP.")
                stop_ap()
            else:
                print("📶 Connected to Wi-Fi — monitoring…")

        else:
            if not AP_RUNNING:
                print("⚠️  No Wi-Fi — entering AP mode.")
                start_ap()
                _last_probe = time.time()

            else:
                uptime = time.time() - _ap_start_time
                since_probe = time.time() - _last_probe

                if uptime > MAX_AP_DURATION:
                    print(f"⏰ AP up {uptime:.0f}s — forcing reconnect probe.")
                    probe_reconnect(force=True)
                    _last_probe = time.time()

                elif since_probe >= PROBE_EVERY:
                    _last_probe = time.time()
                    probe_reconnect()

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()