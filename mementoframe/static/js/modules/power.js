/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 Joao Fernandes
 * Licensed under Creative Commons Attribution-NonCommercial 4.0 International.
 */
/** Report kiosk liveness; the backend owns scheduling and screen power. */
import { PATHS, INTERVALS } from "../constants.js";

export function initPower() {
  const token = document.querySelector('meta[name="kiosk-heartbeat-token"]')?.content;
  if (!token) return;

  async function heartbeat() {
    try {
      const response = await fetch(PATHS.KIOSK_HEARTBEAT, {
        method: "POST",
        headers: { "X-Kiosk-Token": token },
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      });
      // A display-service restart rotates the token. Reinitialize the old page.
      if (response.status === 403) window.location.reload();
      else if (!response.ok) console.warn("Kiosk heartbeat failed:", response.status);
    } catch (error) {
      console.warn("Kiosk heartbeat failed:", error);
    } finally {
      setTimeout(heartbeat, INTERVALS.KIOSK_HEARTBEAT);
    }
  }

  heartbeat();
}
