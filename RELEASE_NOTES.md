# MementoFrame v6.68.34.35.24.25

12 October 2026

This release improves fallback access point recovery when saved Wi-Fi networks are unavailable and prevents repeated recovery reboots.

## AP recovery

- Fixed reconnect probes restarting immediately after the AP was restored. The AP now receives a full two-minute idle interval before the next probe.
- Shortened reconnect attempts by removing the extra wait after a saved network fails to connect and adding command timeouts.
- Restores the AP when a reconnect probe encounters an error.
- Loading the dashboard no longer delays starting a missing AP. Active AP clients and dashboard sessions still defer idle reconnect probes.
- Verifies that the AP profile has its gateway address before reporting successful startup.
- Retries AP setup failures without repeatedly restarting the watchdog and resetting its failure timer.

## Recovery reboot policy

- A recovery reboot is eligible only after **more than one hour of continuous AP startup failure**. Loss of client Wi-Fi alone does not trigger it.
- With **auto power disabled**, an eligible recovery reboot may occur at any time.
- With **auto power enabled**, recovery waits for the configured screen-on period in clock 1's timezone.
- A persistent guard allows **one recovery reboot per continuous failure**. If the AP still fails after reboot, startup retries continue without further reboots.
- Successful AP startup or client Wi-Fi recovery resets the failure timer and reboot guard.

## Validation

All 23 recovery tests passed locally and on the Raspberry Pi, with reboot commands mocked. A live outage test confirmed AP restoration after failed reconnect attempts and a stable 125-second interval before the next probe. Original Wi-Fi profiles were restored and verified afterward.
