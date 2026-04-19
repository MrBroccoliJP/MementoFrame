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
  - iproute2 (ip)

Changes from original:
  - [BUG FIX] nm_set_managed(): "managed true/false" was passed as a single
    argument, causing nmcli to fail silently. Now passed as separate args,
    and uses "yes"/"no" which nmcli actually accepts.
  - [BUG FIX] stop_ap(): removed `nmcli device disconnect` which was
    actively killing the interface right before NM could reclaim it.
  - [BUG FIX] probe_reconnect(): replaced `device connect` (unreliable) with
    `device up` + autoconnect, and added a scan settling delay.
  - [IMPROVEMENT] run(): now logs failures instead of swallowing them silently.
  - [IMPROVEMENT] wifi_connected(): now queries NetworkManager directly instead
    of iwgetid, which can return stale/false SSIDs (e.g. the AP's own SSID).
"""

import subprocess
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AP_INTERFACE    = "wlan0"           # Wireless interface used for both modes
AP_SERVICES     = ["hostapd",       # Services started in AP mode (order matters
                   "dnsmasq"]       # for startup; reversed on shutdown)

CHECK_INTERVAL  = 30                # Seconds between each main-loop iteration
PROBE_EVERY     = 120               # Seconds between reconnect attempts while AP
                                    # is active (only runs if no client connected)
PROBE_TIMEOUT   = 30                # Seconds to wait for NM to establish a
                                    # connection during a probe attempt
MAX_AP_DURATION = 600               # Seconds of continuous AP uptime before a
                                    # forced reconnect is triggered regardless of
                                    # whether a client device is connected

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

AP_RUNNING     = False  # True while hostapd/dnsmasq are running
_last_probe    = 0      # Timestamp of the last reconnect probe
_ap_start_time = 0      # Timestamp when AP mode was last started


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(cmd):
    """
    Run a shell command and log any failures to stdout.

    Previously this silently discarded all output, which hid real errors
    (notably the broken nmcli managed= call). Now failures are visible
    in the service log (journalctl -u <service>).

    Returns:
        subprocess.CompletedProcess: the result object (returncode, stdout, stderr).
    """
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"❌ Command failed: {' '.join(cmd)}")
        if proc.stdout.strip():
            print(f"   stdout: {proc.stdout.strip()}")
        if proc.stderr.strip():
            print(f"   stderr: {proc.stderr.strip()}")
    return proc


def sh(cmd):
    """
    Run a shell command and return its stdout as a stripped string.
    Raises subprocess.CalledProcessError if the command exits non-zero.
    """
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()


def wifi_connected():
    """
    Check whether wlan0 is currently connected to a Wi-Fi network,
    according to NetworkManager.

    Previously used iwgetid, which can return the AP's own SSID when
    hostapd is running, producing false positives. Querying NM directly
    is more reliable — it only reports "connected" once DHCP has completed
    and the link is fully up.

    Returns:
        bool: True if NM reports wlan0 as connected, False otherwise.
    """
    try:
        out = sh(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"])
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 3:
                dev, dev_type, state = parts[0], parts[1], parts[2]
                if dev == AP_INTERFACE and dev_type == "wifi" and state == "connected":
                    return True
        return False
    except subprocess.CalledProcessError:
        return False


def nm_set_managed(managed: bool):
    """
    Tell NetworkManager whether it should manage the AP interface.

    FIX: Original code passed "managed true" as a single argument, which
    nmcli does not parse correctly and fails silently. The correct form is
    two separate arguments, and nmcli requires "yes"/"no" not "true"/"false".

    Args:
        managed (bool): True to hand control to NM, False to release it.
    """
    state = "yes" if managed else "no"
    print(f"🔧 NetworkManager managed={state} on {AP_INTERFACE}")
    run(["sudo", "nmcli", "device", "set", AP_INTERFACE, "managed", state])


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

    print("📡 Starting Access Point (192.168.4.1)…")

    # Only release NM if we are not mid-connection; avoids a race condition
    # where stopping NM management drops a Wi-Fi link that just came up.
    if not wifi_connected():
        nm_set_managed(False)
    else:
        print("⚠️  Wi-Fi still connected — not disabling NetworkManager yet.")

    set_ap_ip()

    for s in AP_SERVICES:
        run(["sudo", "systemctl", "start", s])

    _ap_start_time = time.time()
    AP_RUNNING = True
    print("📡 Access Point is up.")


def stop_ap():
    """
    Transition the device out of Access Point mode.

    Steps:
      1. Guard — does nothing if AP is not running.
      2. Stops dnsmasq then hostapd (reverse startup order).
      3. Flushes the static IP.
      4. Returns wlan0 to NetworkManager control.

    FIX: Removed `nmcli device disconnect` which was actively dropping the
    interface immediately after handing it back to NM, preventing auto-
    reconnect. NM will handle reconnection on its own once it has control.

    Globals modified:
        AP_RUNNING (bool): Set to False.
    """
    global AP_RUNNING
    if not AP_RUNNING:
        return

    print("🔌 Stopping Access Point, returning control to NetworkManager…")

    for s in reversed(AP_SERVICES):
        run(["sudo", "systemctl", "stop", s])

    clear_ip()
    nm_set_managed(True)
    run(["sudo", "nmcli", "radio", "wifi", "on"])
    run(["sudo", "ip", "link", "set", AP_INTERFACE, "up"])
    # NOTE: Do NOT call `nmcli device disconnect` here. That would drop
    # the interface and break NM's ability to auto-reconnect.

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
      3. Triggers a Wi-Fi rescan, waits for results to settle, then asks NM
         to bring the interface up (which triggers autoconnect).
      4. Polls for up to PROBE_TIMEOUT seconds for a successful link.
      5. If no link is established, restarts AP mode and returns False.

    FIX: Replaced `nmcli device connect <iface>` with a rescan + settle
    delay + `nmcli device up`, which is more reliable for reconnecting to
    saved networks. Also added `autoconnect yes` to ensure NM will pick up
    a saved profile automatically.

    Args:
        force (bool): If True, skips the client-connected check and always
                      attempts reconnection. Used after MAX_AP_DURATION.

    Returns:
        bool: True if Wi-Fi was successfully re-established, False otherwise.
    """
    if not force and clients_connected():
        print("🛠  User connected to AP — skipping reconnect probe.")
        return False

    print("🔎 Probe: attempting to reconnect to saved Wi-Fi…")
    stop_ap()

    # Ensure NM has full control and the interface is ready
    nm_set_managed(True)
    run(["sudo", "nmcli", "radio", "wifi", "on"])
    run(["sudo", "ip", "link", "set", AP_INTERFACE, "up"])

    # Re-enable autoconnect on this device in case it was cleared
    run(["sudo", "nmcli", "device", "set", AP_INTERFACE, "autoconnect", "yes"])

    # Rescan and give NM a moment for results to settle before connecting
    run(["sudo", "nmcli", "device", "wifi", "rescan"])
    time.sleep(5)

    # `device up` triggers NM's autoconnect logic — more reliable than
    # `device connect` which tries to connect to a specific device rather
    # than picking the best saved network profile.
    run(["sudo", "nmcli", "device", "up", AP_INTERFACE])

    # Poll until connected or timeout expires
    t0 = time.time()
    while time.time() - t0 < PROBE_TIMEOUT:
        if wifi_connected():
            print("✅ Reconnected to Wi-Fi successfully.")
            return True
        time.sleep(2)

    # Reconnect failed — restore AP so the user can still reach the dashboard
    print("⏳ Probe timed out — restoring AP mode.")
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
    print("🖼  MementoFrame AP Mode Manager started.")

    while True:
        connected = wifi_connected()

        if connected:
            if AP_RUNNING:
                print("✅ Wi-Fi detected — stopping AP mode.")
                stop_ap()
            else:
                print("📶 Connected to Wi-Fi — monitoring…")

        else:
            if not AP_RUNNING:
                print("⚠️  No Wi-Fi — starting AP mode.")
                start_ap()
                _last_probe = time.time()
            else:
                uptime = time.time() - _ap_start_time

                if uptime > MAX_AP_DURATION:
                    print(f"⏰ AP running for {uptime:.0f}s — forcing reconnect attempt.")
                    probe_reconnect(force=True)
                    _last_probe = time.time()

                elif time.time() - _last_probe >= PROBE_EVERY:
                    _last_probe = time.time()
                    probe_reconnect()

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()