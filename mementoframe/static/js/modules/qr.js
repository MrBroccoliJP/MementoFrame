/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 *
 * This work is licensed under the Creative Commons Attribution-NonCommercial
 * 4.0 International License. To view a copy of this license, visit:
 * http://creativecommons.org/licenses/by-nc/4.0/
 */

/**
 * @file qr.js
 * @description QR code generator for the admin dashboard URL.
 *
 * Renders a QR code into the designated container element that encodes
 * the URL of the admin dashboard (app.py, port 5000) using the Pi's
 * current local IP address. This lets users on the same network scan the
 * code with their phone to open the dashboard without typing an IP.
 *
 * The IP is polled every `INTERVALS.QR` milliseconds via GET /get_ip.
 * The QR code is only regenerated when the IP actually changes, avoiding
 * unnecessary DOM redraws (e.g. when toggling between AP and client mode).
 *
 * Requires the `QRCode` library to be loaded globally (qrcode.min.js).
 * If the container element or the library is absent, `initQR` exits
 * silently without throwing.
 */

import { INTERVALS, SELECTORS } from "../constants.js";
import { $ } from "../utils.js";

/**
 * Initialise the QR code widget.
 *
 * Guards against missing DOM element or missing QRCode library, then
 * generates an initial QR code and starts the polling interval.
 *
 * The QR code encodes: `http://<local-ip>:5000`
 * (the admin dashboard served by app.py).
 */
export function initQR() {
  const container = $(SELECTORS.qrContainer);
  if (!container || typeof QRCode === "undefined") return;

  /** @type {string|null} Tracks the last IP used to generate the QR code. */
  let lastIP = null;

  /**
   * Render a QR code for the given URL into the container.
   * Clears any previously rendered code first.
   *
   * @param {string} text - The URL to encode in the QR code.
   */
  const generate = (text) => {
    container.innerHTML = "";
    new QRCode(container, {
      text,
      width:        70,
      height:       70,
      colorDark:    "#000",
      colorLight:   "#fff",
      correctLevel: QRCode.CorrectLevel.L,
    });
  };

  /**
   * Fetch the Pi's current local IP address from the backend.
   *
   * @async
   * @returns {Promise<string|null>} IP address string, or null on error.
   */
  async function fetchIP() {
    try {
      const res = await fetch("/get_ip");
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      return data?.ip || null;
    } catch {
      return null;
    }
  }

  /**
   * Poll the IP and regenerate the QR code if it has changed.
   *
   * Called immediately on init and then every `INTERVALS.QR` ms.
   * Skips regeneration if the IP is the same as the last known value,
   * preventing unnecessary DOM operations on each tick.
   *
   * @async
   */
  async function tick() {
    const ip = await fetchIP();
    if (ip && ip !== lastIP) {
      generate(`http://${ip}:5000`);
      lastIP = ip;
      console.log("🔄 QR updated:", ip);
    }
  }

  tick();
  setInterval(tick, INTERVALS.QR);
}