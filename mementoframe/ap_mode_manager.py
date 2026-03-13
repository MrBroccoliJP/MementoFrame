# MementoFrame - Raspberry Pi Smart Photo Frame
# Copyright (c) 2026 João Fernandes
#
# This work is licensed under the Creative Commons Attribution-NonCommercial
# 4.0 International License. To view a copy of this license, visit:
# http://creativecommons.org/licenses/by-nc/4.0/

#!/usr/bin/env python3
"""
ap_mode_manager.py — Wi-Fi / Access Point Mode Manager

Monitors Wi-Fi connectivity on the Raspberry Pi and automatically switches
between two network modes:

  CLIENT MODE  — wlan0 is connected to a home/external Wi-Fi network.
                 NetworkManager manages the interface normally.

  AP MODE      — No Wi-Fi is available. wlan0 becomes a hotspot (192.168.4.1)
                 powered by hostapd + dnsmasq, so the user can connect directly
                 to the frame and configure it via the web dashboard.

State machine (runs every CHECK_INTERVAL seconds):
  ┌─────────────┐   Wi-Fi lost       ┌──────────┐
  │ CLIENT MODE │ ─────────────────► │  AP MODE │
  │             │ ◄───────────────── │          │
  └─────────────┘   Wi-Fi found      └──────────┘
                                         │
                              Every PROBE_EVERY seconds (or after
                              MAX_AP_DURATION), attempts to reconnect.
                              Skipped if a client device is connected.

Dependencies:
  - NetworkManager (nmcli)
  - hostapd
  - dnsmasq
  - iwgetid (wireless-tools)
  - iproute2 (ip)
"""

import subprocess
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AP_INTERFACE   = "wlan0"           # Wireless interface used for both modes
AP_SERVICES    = ["hostapd",       # Services started in AP mode (order matters
                  "dnsmasq"]       # for startup; reversed on shutdown)

CHECK_INTERVAL = 30                # Seconds between each main-loop iteration
PROBE_EVERY    = 120               # Seconds between reconnect attempts while AP
                                   # is active (only runs if no client connected)
PROBE_TIMEOUT  = 20                # Seconds to wait for NM to establish a
                                   # connection during a probe attempt
MAX_AP_DURATION = 600              # Seconds of continuous AP uptime before a
                                   # forced reconnect is triggered regardless of
                                   # whether a client device is connected

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

AP_RUNNING    = False   # True while hostapd/dnsmasq are running
_last_probe   = 0       # Timestamp of the last reconnect probe
_ap_start_time = 0      # Timestamp when AP mode was last started


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(cmd):
    """
    Run a shell command, silently discarding all output.
    Used for fire-and-forget system calls (nmcli, ip, systemctl).
    """
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def sh(cmd):
    """
    Run a shell command and return its stdout as a stripped string.
    Raises subprocess.CalledProcessError if the command exits non-zero.
    """
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()


def wifi_connected():
    """
    Check whether wlan0 is currently associated with a Wi-Fi network.

    Uses iwgetid to read the current SSID. Returns True if an SSID is
    present (i.e. we are connected), False otherwise.

    Returns:
        bool: True if connected to a Wi-Fi network, False if not.
    """
    try:
        ssid = sh(["iwgetid", "-r"])
        return bool(ssid)
    except subprocess.CalledProcessError:
        return False


def nm_set_managed(managed: bool):
    """
    Tell NetworkManager whether it should manage the AP interface.

    In AP mode, NM must relinquish control of wlan0 so that hostapd can
    drive it. When returning to client mode, NM is given back control so
    it can reconnect to saved networks.

    Args:
        managed (bool): True to hand control to NM, False to release it.
    """
    state = "true" if managed else "false"
    print(f"🔧 NetworkManager managed={state} on {AP_INTERFACE}")
    run(["sudo", "nmcli", "device", "set", AP_INTERFACE, f"managed {state}"])


def set_ap_ip():
    """
    Assign the static IP address required for AP mode.

    Flushes any existing addresses from the interface, then assigns
    192.168.4.1/24 — the gateway address that dnsmasq will hand out
    to connecting clients. Brings the interface up afterwards.
    """
    run(["sudo", "ip", "addr", "flush", "dev", AP_INTERFACE])
    run(["sudo", "ip", "addr", "add", "192.168.4.1/24", "dev", AP_INTERFACE])
    run(["sudo", "ip", "link", "set", AP_INTERFACE, "up"])


def clear_ip():
    """
    Remove the static IP from the interface when leaving AP mode.

    Flushes all addresses so NetworkManager can assign a DHCP address
    from the home network once it takes control back.
    """
    run(["sudo", "ip", "addr", "flush", "dev", AP_INTERFACE])
    run(["sudo", "ip", "link", "set", AP_INTERFACE, "up"])


def clients_connected():
    """
    Check whether any device is currently connected to the AP.

    Queries hostapd_cli for a list of associated stations. A non-empty
    response means at least one client is connected.

    This is used to avoid interrupting a user who is actively configuring
    the frame through the web dashboard.

    Returns:
        bool: True if one or more clients are connected, False otherwise.
    """
    try:
        out = subprocess.check_output(
            ["sudo", "hostapd_cli", "-i", AP_INTERFACE, "all_sta"],
            stderr=subprocess.DEVNULL,
        ).decode()
        return bool(out.strip())
    except subprocess.CalledProcessError:
        return False


# ---------------------------------------------------------------------------
# Mode control
# ---------------------------------------------------------------------------

def start_ap():
    """
    Transition the device into Access Point mode.

    Steps:
      1. Guard — does nothing if AP is already running.
      2. Releases NM control of wlan0 (only if Wi-Fi is not currently
         connected, to avoid dropping an active connection prematurely).
      3. Assigns the static gateway IP (192.168.4.1/24).
      4. Starts hostapd then dnsmasq via systemctl.
      5. Records the start timestamp for MAX_AP_DURATION enforcement.

    Globals modified:
        AP_RUNNING (bool): Set to True.
        _ap_start_time (float): Set to current time.
    """
    global AP_RUNNING, _ap_start_time
    if AP_RUNNING:
        return

    print("Starting Access Point (192.168.4.1)…")

    # Only release NM if we are not mid-connection; avoids a race condition
    # where stopping NM management drops a Wi-Fi link that just came up.
    if not wifi_connected():
        nm_set_managed(False)
    else:
        print("⚠️ Wi-Fi still connected, not disabling NetworkManager yet.")

    set_ap_ip()

    for s in AP_SERVICES:
        run(["sudo", "systemctl", "start", s])

    _ap_start_time = time.time()
    AP_RUNNING = True


def stop_ap():
    """
    Transition the device out of Access Point mode.

    Steps:
      1. Guard — does nothing if AP is not running.
      2. Stops dnsmasq then hostapd (reverse startup order).
      3. Flushes the static IP.
      4. Returns wlan0 to NetworkManager control and triggers a reconnect.

    Globals modified:
        AP_RUNNING (bool): Set to False.
    """
    global AP_RUNNING
    if not AP_RUNNING:
        return

    print("Stopping Access Point, returning control to NetworkManager")

    # Stop services in reverse order (dnsmasq before hostapd)
    for s in reversed(AP_SERVICES):
        run(["sudo", "systemctl", "stop", s])

    clear_ip()
    nm_set_managed(True)
    run(["sudo", "nmcli", "radio", "wifi", "on"])
    run(["sudo", "nmcli", "device", "disconnect", AP_INTERFACE])

    AP_RUNNING = False


# ---------------------------------------------------------------------------
# Reconnect probe
# ---------------------------------------------------------------------------

def probe_reconnect(force=False):
    """
    Attempt to reconnect to a saved Wi-Fi network while AP mode is active.

    Called periodically (every PROBE_EVERY seconds) or when the AP has been
    running longer than MAX_AP_DURATION. The probe:
      1. Optionally skips if a client is actively connected (unless forced).
      2. Stops AP mode and hands control back to NetworkManager.
      3. Triggers a Wi-Fi rescan and connection attempt.
      4. Polls for up to (PROBE_TIMEOUT + 5) seconds for a successful link.
      5. If no link is established, restarts AP mode and returns False.

    Args:
        force (bool): If True, skips the client-connected check and always
                      attempts reconnection. Used after MAX_AP_DURATION.

    Returns:
        bool: True if Wi-Fi was successfully re-established, False otherwise.
    """
    if not force and clients_connected():
        print("🛠 User connected — skipping reconnect probe for now.")
        return False

    print("🔎 Probe: trying to reconnect to saved Wi-Fi…")
    stop_ap()

    # Hand control back to NM and request a scan + connect
    nm_set_managed(True)
    run(["sudo", "nmcli", "radio", "wifi", "on"])
    run(["sudo", "nmcli", "device", "wifi", "rescan"])
    run(["sudo", "nmcli", "device", "connect", AP_INTERFACE])

    # Poll until connected or timeout expires
    t0 = time.time()
    while time.time() - t0 < PROBE_TIMEOUT + 5:
        if wifi_connected():
            print("✅ Reconnected to Wi-Fi successfully")
            return True
        time.sleep(2)

    # Reconnect failed — restore AP so the user can still reach the dashboard
    print("⏳ Probe failed — restoring AP")
    start_ap()
    return False


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    """
    Entry point — runs the AP/client state machine indefinitely.

    Each iteration (every CHECK_INTERVAL seconds):
      - If Wi-Fi is connected and AP is running  → stop AP (we're back online).
      - If Wi-Fi is connected and AP is not running → log and continue.
      - If Wi-Fi is not connected and AP is not running → start AP.
      - If Wi-Fi is not connected and AP is running:
          - If AP uptime > MAX_AP_DURATION → force a reconnect probe.
          - If PROBE_EVERY seconds have elapsed → attempt a normal probe.

    Globals modified:
        _last_probe (float): Updated after each probe attempt.
    """
    global _last_probe
    print("SmartFrame AP Mode Manager started (NetworkManager mode)")

    while True:
        connected = wifi_connected()

        if connected:
            if AP_RUNNING:
                print("✅ Wi-Fi detected — stopping AP mode")
                stop_ap()
            else:
                print("📶 Connected to Wi-Fi — monitoring…")

        else:
            if not AP_RUNNING:
                print("No Wi-Fi — starting AP mode")
                start_ap()
                _last_probe = time.time()
            else:
                uptime = time.time() - _ap_start_time

                if uptime > MAX_AP_DURATION:
                    print(f"AP running {uptime:.0f}s — forcing reconnect attempt")
                    probe_reconnect(force=True)
                    _last_probe = time.time()

                elif time.time() - _last_probe >= PROBE_EVERY:
                    _last_probe = time.time()
                    probe_reconnect()

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()