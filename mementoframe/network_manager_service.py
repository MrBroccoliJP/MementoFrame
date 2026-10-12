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

import json
import os
import subprocess
import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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

# NetworkManager settings that define the fallback AP profile. These are applied
# on every startup so older or partially-created profiles get repaired in place.
AP_PROFILE_SETTINGS = [
    ("connection.autoconnect", "no"),
    ("connection.interface-name", AP_INTERFACE),
    ("802-11-wireless.ssid", AP_SSID),
    ("802-11-wireless.mode", "ap"),
    ("802-11-wireless.band", "bg"),
    ("802-11-wireless.channel", AP_CHANNEL),
    ("ipv4.method", "shared"),
    ("ipv4.addresses", f"{AP_IP}/24"),
    ("ipv6.method", "disabled"),
]

# Main watchdog loop interval.
CHECK_INTERVAL = 5

# Interval between saved-profile reconnect attempts while AP mode is active.
PROBE_EVERY = 120

# Maximum time to wait for each saved Wi-Fi profile to connect.
PROBE_TIMEOUT = 45

# Reconnect probes are delayed while a user is connected to AP/config portal.
AP_CLIENT_GRACE = 5 * 60

# Maximum AP uptime before forcing a reconnect probe, only when AP is idle.
MAX_AP_DURATION = 600

# Restart NetworkManager during AP-to-client transitions. This matches the
# manual recovery sequence that clears stuck supplicant/scan state on Pi Wi-Fi.
NETWORKMANAGER_SETTLE = 10
WIFI_RESCAN_SETTLE = 5

# Reboot once only after AP activation has continuously failed for over an hour.
# When auto power is enabled, recovery reboots wait for its scheduled on period.
AP_FAILURE_REBOOT_AFTER = 60 * 60
COMMAND_TIMEOUT = 30
CONFIG_FILE = "config.json"

# Shared runtime state used by the config portal and network watchdog.
RUNTIME_DIR = "runtime"
CONFIG_PORTAL_ACTIVITY_FILE = os.path.join(RUNTIME_DIR, "config_portal_activity.json")
AP_FAILURE_REBOOT_FLAG_FILE = os.path.join(RUNTIME_DIR, "rebooted_for_ap_failure.flag")


# =============================================================================
# Runtime state
# =============================================================================

# Timestamp recorded when AP mode starts.
_ap_start_time = 0.0

# Timestamp recorded after the last reconnect probe.
_last_probe = 0.0

# Timestamp until which AP mode should not be interrupted because a client was
# recently seen. This covers drivers where station detection is intermittent.
_ap_client_hold_until = 0.0

# Monotonic timestamp of the first unsuccessful AP activation in this failure.
# Deliberately stopping the AP for a client probe does not start this timer.
_ap_failed_since = None

# Guard against the main loop fighting an in-progress reconnect attempt.
_reconnect_in_progress = False


# =============================================================================
# Shell helpers
# =============================================================================

def run(cmd, label=None, timeout=COMMAND_TIMEOUT):
    """
    Execute a shell command and return the CompletedProcess.

    This helper captures stdout/stderr so failures can be printed clearly while
    allowing the caller to decide whether the failure is fatal.
    """
    tag = label or " ".join(str(c) for c in cmd)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc = subprocess.CompletedProcess(cmd, 124, "", f"Command timed out after {timeout}s")
    except OSError as e:
        proc = subprocess.CompletedProcess(cmd, 127, "", str(e))

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
    try:
        return subprocess.check_output(
            cmd, stderr=subprocess.DEVNULL, timeout=COMMAND_TIMEOUT,
        ).decode().strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        raise subprocess.CalledProcessError(124, cmd) from e


def nmcli(*args, timeout=COMMAND_TIMEOUT):
    """
    Run an nmcli command with sudo.

    Args:
        *args:
            Arguments passed directly to ``nmcli``.
    """
    return run(["sudo", "nmcli"] + list(args), timeout=timeout)


# =============================================================================
# Runtime coordination helpers
# =============================================================================

def ensure_runtime_dir():
    """Ensure the shared runtime directory exists."""
    try:
        os.makedirs(RUNTIME_DIR, exist_ok=True)
    except Exception as e:
        print(f"  ⚠️ Could not create runtime directory: {e}")


def read_json_file(path):
    """Read a JSON file, returning None when it is missing or invalid."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"  ⚠️ Could not read {path}: {e}")
        return None


def remove_file(path):
    """Remove a file if it exists."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"  ⚠️ Could not remove {path}: {e}")


def clear_ap_failure_state():
    """Reset recovery after either client Wi-Fi or the fallback AP is healthy."""
    global _ap_failed_since
    _ap_failed_since = None
    remove_file(AP_FAILURE_REBOOT_FLAG_FILE)


def create_ap_reboot_flag():
    """Persist the one-shot guard before requesting an AP recovery reboot."""
    ensure_runtime_dir()
    try:
        with open(AP_FAILURE_REBOOT_FLAG_FILE, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
            f.flush()
            os.fsync(f.fileno())
        return True
    except Exception as e:
        print(f"  ⚠️ Could not write AP reboot flag: {e}")
        return False


def record_ap_failure():
    """Start the continuous failure timer only after AP activation fails."""
    global _ap_failed_since
    if _ap_failed_since is None:
        _ap_failed_since = time.monotonic()


def recovery_reboot_allowed():
    """Allow anytime if auto power is off, otherwise only its scheduled on period.

    An unreadable config or invalid enabled schedule cannot authorize a reboot.
    Equal on/off times mean always off, matching the display schedule.
    """
    config = read_json_file(CONFIG_FILE)
    if not isinstance(config, dict):
        return False
    schedule = config.get("auto_power")
    if schedule is None:
        return True
    if not isinstance(schedule, dict):
        return False
    if schedule.get("enabled", False) is False:
        return True
    if schedule.get("enabled") is not True:
        return False
    try:
        def minutes(value):
            hour, minute = value.split(":")
            if not (hour.isdigit() and minute.isdigit() and len(minute) == 2):
                raise ValueError("Invalid schedule time")
            hour, minute = int(hour), int(minute)
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Invalid schedule time")
            return hour * 60 + minute

        on = minutes(schedule.get("on_time"))
        off = minutes(schedule.get("off_time"))
        clock = config.get("clock1") or {}
        now = datetime.now(ZoneInfo(clock.get("timezone") or "UTC"))
        current = now.hour * 60 + now.minute
    except (AttributeError, TypeError, ValueError, ZoneInfoNotFoundError):
        return False
    if on < off:
        return on <= current < off
    if on > off:
        return current >= on or current < off
    return False


def maybe_reboot_for_ap_failure():
    """Reboot once for prolonged AP failure when the power schedule permits."""
    if _ap_failed_since is None:
        return False
    if wifi_connected() or ap_ready():
        clear_ap_failure_state()
        return False
    if (
        time.monotonic() - _ap_failed_since <= AP_FAILURE_REBOOT_AFTER
        or _reconnect_in_progress
        or wifi_config_transition_active()
        or os.path.exists(AP_FAILURE_REBOOT_FLAG_FILE)
        or not recovery_reboot_allowed()
    ):
        return False
    if not create_ap_reboot_flag():
        return False
    print("🔁 AP startup has failed for over 1 hour and the power schedule allows recovery — rebooting once.")
    result = run(["sudo", "reboot"], label="AP failure recovery reboot")
    if result.returncode != 0:
        remove_file(AP_FAILURE_REBOOT_FLAG_FILE)
    return result.returncode == 0


def config_portal_quiet_until():
    """Return the timestamp until which AP mode should stay uninterrupted."""
    record = read_json_file(CONFIG_PORTAL_ACTIVITY_FILE)
    if not isinstance(record, dict):
        return 0.0

    try:
        return float(record.get("quiet_until") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def config_portal_active():
    """Check whether the dashboard was loaded recently enough to hold AP mode."""
    return time.time() < config_portal_quiet_until()


def wifi_config_transition_active():
    """Only an explicit Wi-Fi change may delay starting a missing AP."""
    record = read_json_file(CONFIG_PORTAL_ACTIVITY_FILE)
    return (
        isinstance(record, dict)
        and record.get("reason") == "wifi-connect"
        and config_portal_active()
    )


def seconds_until_config_portal_idle():
    """Return remaining config portal quiet-window seconds."""
    return max(0, int(config_portal_quiet_until() - time.time()))


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


def ap_ready():
    """Require the AP profile to be active with its configured gateway address."""
    if not ap_active():
        return False
    try:
        addresses = sh(["nmcli", "-g", "IP4.ADDRESS", "device", "show", AP_INTERFACE])
        return any(address.split("/", 1)[0] == AP_IP for address in addresses.splitlines())
    except subprocess.CalledProcessError:
        return False


def wifi_connected():
    """
    Check whether the device is connected to a normal Wi-Fi client profile.
    """
    con = current_connection()
    return bool(con and con != AP_CON_NAME)


def clients_connected():
    """
    Check whether any client device is currently associated with the AP.

    Multiple signals are used because ``iw station dump`` can be empty on some
    drivers even while an SSH/config-portal client is active.
    """
    try:
        out = sh(["sudo", "iw", "dev", AP_INTERFACE, "station", "dump"])
        if "Station" in out:
            return True
    except subprocess.CalledProcessError:
        pass

    try:
        out = sh(["ss", "-H", "-tn", "state", "established"])
        if "192.168.4." in out:
            return True
    except subprocess.CalledProcessError:
        pass

    try:
        out = sh(["ip", "neigh", "show", "dev", AP_INTERFACE])
        for line in out.splitlines():
            if "192.168.4." in line and "FAILED" not in line:
                return True
    except subprocess.CalledProcessError:
        pass

    return False


def ap_should_hold():
    """
    Return a reason to keep AP mode stable, or None when probing is allowed.

    AP mode is protected when a client is connected, when a client was recently
    seen, or when the config dashboard was loaded recently.
    """
    global _ap_client_hold_until

    now = time.time()

    if clients_connected():
        _ap_client_hold_until = max(_ap_client_hold_until, now + AP_CLIENT_GRACE)
        return f"AP client active — delaying reconnect for {AP_CLIENT_GRACE // 60} minutes."

    if now < _ap_client_hold_until:
        remaining = int(_ap_client_hold_until - now)
        return f"AP client was recently active — delaying reconnect for {remaining}s."

    if config_portal_active():
        remaining = seconds_until_config_portal_idle()
        return f"Config portal active — delaying reconnect for {remaining}s."

    return None


# =============================================================================
# First-run setup
# =============================================================================

def check_for_conflicts():
    """
    Report whether services conflict with NetworkManager AP mode.

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

        return False
    return True


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
    exists = ap_profile_exists()

    if exists:
        print(f"🔧 Repairing NetworkManager AP profile '{AP_CON_NAME}'…")
    else:
        print(f"🔧 Creating NetworkManager AP profile '{AP_CON_NAME}'…")

        run(
            ["sudo", "nmcli", "connection", "delete", AP_CON_NAME],
            label=f"cleanup stale {AP_CON_NAME}",
        )

        if run(
            [
                "sudo", "nmcli", "connection", "add",
                "type", "wifi", "ifname", AP_INTERFACE,
                "con-name", AP_CON_NAME, "autoconnect", "no", "ssid", AP_SSID,
            ],
            label=f"create {AP_CON_NAME}",
        ).returncode != 0:
            print("❌ AP profile creation failed.")
            return False

    for key, value in AP_PROFILE_SETTINGS:
        if run(
            [
                "sudo", "nmcli", "connection", "modify", AP_CON_NAME,
                key, value,
            ],
            label=f"set {AP_CON_NAME} {key}",
        ).returncode != 0:
            print("❌ AP profile configuration failed.")
            return False

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
    return True


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

def prepare_wifi_device_for_ap():
    """
    Put the Wi-Fi device in a clean state before activating AP mode.

    NetworkManager can leave wlan0 disconnected, unmanaged, or radio-disabled
    after failed client connection attempts. These commands are intentionally
    best-effort; AP activation still reports the real failure if it cannot start.
    """
    run(["sudo", "nmcli", "radio", "wifi", "on"], label="wifi radio on before AP")
    run(
        ["sudo", "nmcli", "device", "set", AP_INTERFACE, "managed", "yes"],
        label=f"ensure {AP_INTERFACE} managed",
    )
    run(
        ["sudo", "nmcli", "device", "disconnect", AP_INTERFACE],
        label=f"clear {AP_INTERFACE} state before AP",
    )
    time.sleep(2)


def start_ap():
    """
    Activate fallback AP mode.

    Returns:
        bool:
            True when AP mode is already active or successfully started.
    """
    global _ap_start_time

    if ap_ready():
        clear_ap_failure_state()
        return True

    print("📡 Activating AP mode…")

    prepare_wifi_device_for_ap()
    result = nmcli("--wait", "30", "connection", "up", AP_CON_NAME, "ifname", AP_INTERFACE, timeout=35)

    if result.returncode != 0:
        print("  ⚠️ AP activation failed once; retrying after NetworkManager reload.")
        run(["sudo", "nmcli", "connection", "reload"], label="reload NetworkManager connections")
        prepare_wifi_device_for_ap()
        result = nmcli("--wait", "30", "connection", "up", AP_CON_NAME, "ifname", AP_INTERFACE, timeout=35)

    if result.returncode != 0:
        print("  ❌ AP activation failed.")
        record_ap_failure()
        return False

    time.sleep(3)

    if not ap_ready():
        print("  ❌ AP activation returned success but the AP gateway is not ready.")
        record_ap_failure()
        return False

    _ap_start_time = time.monotonic()
    clear_ap_failure_state()

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



def reset_networkmanager_for_client_mode():
    """Reset NetworkManager before trying client Wi-Fi from AP mode."""
    print("♻️ Resetting NetworkManager before Wi-Fi reconnect…")

    stop_ap()

    run(
        ["sudo", "nmcli", "device", "disconnect", AP_INTERFACE],
        label="disconnect wlan0 before NetworkManager reset",
    )

    result = run(
        ["sudo", "systemctl", "restart", "NetworkManager"],
        label="restart NetworkManager",
    )

    if result.returncode != 0:
        print("  ⚠️ NetworkManager restart failed; continuing with nmcli reset only.")

    time.sleep(NETWORKMANAGER_SETTLE)

    run(["sudo", "nmcli", "radio", "wifi", "on"], label="wifi radio on")
    time.sleep(2)

    run(
        ["sudo", "nmcli", "device", "wifi", "rescan", "ifname", AP_INTERFACE],
        label="wifi rescan",
    )
    time.sleep(WIFI_RESCAN_SETTLE)


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

    The AP-to-client transition intentionally restarts NetworkManager because
    Raspberry Pi Wi-Fi can get stuck after AP mode. If every profile fails, AP
    mode is restored so the frame stays reachable.
    """
    global _reconnect_in_progress

    if _reconnect_in_progress:
        print("🔁 Reconnect already in progress — skipping duplicate probe.")
        return False

    if ap_active() and not force:
        hold_reason = ap_should_hold()
        if hold_reason:
            print(f"🛠 {hold_reason}")
            return False

    print("🔎 Probing saved Wi-Fi profiles…")

    profiles = known_client_profiles()

    if not profiles:
        print("  No saved Wi-Fi profiles — staying in AP mode.")
        return False

    _reconnect_in_progress = True

    try:
        reset_networkmanager_for_client_mode()

        for profile in profiles:
            if wifi_connected():
                clear_ap_failure_state()
                return True
            print(f"  Trying saved profile: {profile}")

            run(
                [
                    "sudo", "nmcli", "connection", "modify", profile,
                    "802-11-wireless-security.wps-method", "disabled",
                ],
                label=f"disable WPS for {profile}",
            )

            nmcli(
                "--wait", str(PROBE_TIMEOUT), "connection", "up", profile,
                "ifname", AP_INTERFACE, timeout=PROBE_TIMEOUT + 5,
            )
            if wifi_connected():
                print(f"  ✅ Reconnected to Wi-Fi: {current_connection()}")
                clear_ap_failure_state()
                return True

        print("  ⏳ All saved profiles failed — restoring AP.")
        return False
    except Exception as e:
        print(f"  ⚠️ Reconnect probe failed: {e} — restoring AP.")
        return False
    finally:
        # Recovery is required even when the probe exits through an error.
        try:
            if not wifi_connected():
                start_ap()
        finally:
            _reconnect_in_progress = False


# =============================================================================
# Main watchdog loop
# =============================================================================

def main():
    """
    Initialize NetworkManager configuration and continuously monitor connectivity.
    """
    global _last_probe

    ensure_runtime_dir()
    profiles_ready = False

    print()
    print("🖼  MementoFrame AP Mode Manager")
    print(f"   Interface : {AP_INTERFACE}")
    print(f"   AP SSID   : {AP_SSID} (open network — config portal PIN protects dashboard)")
    print(f"   Gateway   : {AP_IP}")
    print()

    while True:
        if not profiles_ready:
            if check_for_conflicts() and ensure_ap_profile():
                ensure_client_profiles_patched()
                profiles_ready = True
            else:
                # Startup configuration failures must not create a service
                # restart loop that continually resets the AP failure timer.
                if wifi_connected() or ap_ready():
                    clear_ap_failure_state()
                else:
                    record_ap_failure()
                    maybe_reboot_for_ap_failure()
                time.sleep(CHECK_INTERVAL)
                continue
        now = time.monotonic()

        if wifi_connected():
            print("📶 Connected to Wi-Fi — monitoring…")
            clear_ap_failure_state()

        else:
            if not ap_ready():
                if wifi_config_transition_active() or _reconnect_in_progress:
                    print("🛠 Wi-Fi transition/config portal active — not restoring AP yet.")
                else:
                    print("⚠️ No Wi-Fi — entering AP mode.")
                    start_ap()
                    _last_probe = time.monotonic()
                    maybe_reboot_for_ap_failure()

            else:
                clear_ap_failure_state()
                hold_reason = ap_should_hold()

                if hold_reason:
                    print(f"🛠 {hold_reason}")
                    _last_probe = now

                else:
                    uptime = now - _ap_start_time if _ap_start_time else 0
                    since_probe = now - _last_probe

                    if uptime > MAX_AP_DURATION:
                        print(f"⏰ AP up {uptime:.0f}s and idle — forcing reconnect probe.")
                        probe_reconnect(force=True)
                        _last_probe = time.monotonic()
                        maybe_reboot_for_ap_failure()

                    elif since_probe >= PROBE_EVERY:
                        probe_reconnect(force=False)
                        _last_probe = time.monotonic()
                        maybe_reboot_for_ap_failure()

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
