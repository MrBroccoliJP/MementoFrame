# MementoFrame v6.69.35.37.24.25

9 November 2026

This release moves screen power scheduling into the display backend and adds automatic recovery when the Chromium kiosk stops responding.

## Screen power and kiosk recovery

- The existing display service now owns screen scheduling and GPIO 26. Scheduling follows clock 1's timezone and continues when the browser fails.
- The initialized local frontend sends a token-protected heartbeat every 10 seconds, including while the screen is scheduled off. Remote frontend sessions cannot keep the kiosk watchdog healthy.
- Startup includes a two-minute grace period followed by a 60-second missing-heartbeat timeout. Recovery cannot begin before three minutes after the display service starts.
- The screen remains on until two minutes of continuing frontend heartbeats have been received, even during a scheduled off period. Watchdog recovery takes priority if the kiosk fails.
- Missing heartbeats turn the screen off and restart `mementoframe-kiosk.service`. The screen returns after a fresh heartbeat, subject to the schedule and any active manual override.
- Repeated recovery attempts back off to at most one every 15 minutes.
- `/health` now includes read-only screen and heartbeat diagnostics without extending kiosk liveness.
- Every 30 seconds, the controller checks GPIO 26 against the expected screen state and restores it if needed, logging any mismatch. Startup visibility, manual overrides, and kiosk recovery retain priority over the schedule. GPIO readback verifies the pin level; it cannot confirm that the panel is physically lit.

## Manual controls

- Opening the configuration dashboard or PIN page, or pressing its screen-on button, requests a five-minute wake through the display service.
- Manual wakes preserve night-time access without overriding a known kiosk failure.
- Screen utility scripts now use the backend endpoints instead of configuring GPIO independently. This also removes the screen-on utility's immediate GPIO cleanup.

## Validation

All 56 Python tests passed locally and on the Raspberry Pi, including 20 screen-policy and endpoint tests. Frontend checks covered heartbeat submission, exclusion of remote sessions, and reloading after the backend rotates its token.

Live Raspberry Pi checks confirmed:

- The screen stayed enabled through 120.5 seconds of frontend heartbeats before a temporary night schedule switched GPIO 26 off.
- Heartbeats continued while the screen was scheduled off, without restarting the kiosk.
- The PIN page, unlocked dashboard, and screen-on button each woke the screen through the backend. Physical screen wake was also confirmed by the user.
- Deliberately killing the Chromium renderer stopped heartbeats. The watchdog restarted the kiosk about 61 seconds after the last heartbeat, held GPIO 26 low during recovery, and re-enabled it after fresh frontend heartbeats arrived.
- The display backend stayed running throughout the renderer crash and kiosk recovery.
- A live readback test deliberately forced GPIO 26 low while the controller expected it high. The controller restored the output in 29.6 seconds without restarting the kiosk or interrupting frontend heartbeats. Unit tests also covered the reverse mismatch, manual-wake priority, screen-off recovery priority, and readback failures.

The original 08:00–23:00 schedule was restored, all three display/config/kiosk services were active, and GPIO 26 was high at the end of testing. Installed files were backed up before deployment. Startup was tested by restarting services; a full Pi reboot was not performed.

---

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
