#!/usr/bin/env python3
import subprocess
import time

# --- Configuration ---
AP_INTERFACE = "wlan0"
AP_SERVICES = ["hostapd", "dnsmasq"]
CHECK_INTERVAL = 30           # main loop interval (s)
PROBE_EVERY = 120              # how often to attempt reconnect while AP is running (s)
PROBE_TIMEOUT = 20            # how long to wait for NetworkManager to connect (s)
MAX_AP_DURATION = 600         # max AP time before forcing reconnect (s)
AP_RUNNING = False
_last_probe = 0
_ap_start_time = 0


# --- Helpers ---
def run(cmd):
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def sh(cmd):
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()

def wifi_connected():
    """Return True if currently connected to a Wi-Fi network."""
    try:
        ssid = sh(["iwgetid", "-r"])
        return bool(ssid)
    except subprocess.CalledProcessError:
        return False

def nm_set_managed(managed: bool):
    """Enable/disable NetworkManager control for wlan0."""
    state = "true" if managed else "false"
    print(f"🔧 NetworkManager managed={state} on {AP_INTERFACE}")
    run(["sudo", "nmcli", "device", "set", AP_INTERFACE, f"managed {state}"])

def set_ap_ip():
    """Assign static IP to wlan0 for AP mode."""
    run(["sudo", "ip", "addr", "flush", "dev", AP_INTERFACE])
    run(["sudo", "ip", "addr", "add", "192.168.4.1/24", "dev", AP_INTERFACE])
    run(["sudo", "ip", "link", "set", AP_INTERFACE, "up"])

def clear_ip():
    """Clear IP address for client mode."""
    run(["sudo", "ip", "addr", "flush", "dev", AP_INTERFACE])
    run(["sudo", "ip", "link", "set", AP_INTERFACE, "up"])

def clients_connected():
    """Check if any device is connected to the AP."""
    try:
        out = subprocess.check_output(
            ["sudo", "hostapd_cli", "-i", AP_INTERFACE, "all_sta"],
            stderr=subprocess.DEVNULL,
        ).decode()
        return bool(out.strip())
    except subprocess.CalledProcessError:
        return False


# --- Mode control ---
def start_ap():
    """Start AP mode only if not already running."""
    global AP_RUNNING, _ap_start_time
    if AP_RUNNING:
        return
    print("Starting Access Point (192.168.4.1)…")
    # Disable NM only if not currently connected
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
    """Stop AP mode and return wlan0 to NM control."""
    global AP_RUNNING
    if not AP_RUNNING:
        return
    print("Stopping Access Point, returning control to NetworkManager")
    for s in reversed(AP_SERVICES):
        run(["sudo", "systemctl", "stop", s])
    clear_ip()
    nm_set_managed(True)
    run(["sudo", "nmcli", "radio", "wifi", "on"])
    run(["sudo", "nmcli", "device", "disconnect", AP_INTERFACE])
    AP_RUNNING = False


# --- Probe reconnect logic ---
def probe_reconnect(force=False):
    """Try to reconnect to saved Wi-Fi networks."""
    if not force and clients_connected():
        print("🛠 User connected — skipping reconnect probe for now.")
        return False

    print("🔎 Probe: trying to reconnect to saved Wi-Fi…")
    stop_ap()

    # Hand control to NM
    nm_set_managed(True)
    run(["sudo", "nmcli", "radio", "wifi", "on"])
    run(["sudo", "nmcli", "device", "wifi", "rescan"])
    run(["sudo", "nmcli", "device", "connect", AP_INTERFACE])

    # Wait for connection
    t0 = time.time()
    while time.time() - t0 < PROBE_TIMEOUT + 5:
        if wifi_connected():
            print("✅ Reconnected to Wi-Fi successfully")
            return True
        time.sleep(2)

    print("⏳ Probe failed — restoring AP")
    start_ap()
    return False


# --- Main loop ---
def main():
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
