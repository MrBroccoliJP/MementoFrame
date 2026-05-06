/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 *
 * Licensed under CC BY-NC 4.0
 */

import { state } from "../state.js";
import { PATHS, INTERVALS, SELECTORS } from "../constants.js";
import { $, fetchJson } from "../utils.js";
import { updateWeather } from "./weather.js";
import { updateSpotify } from "./spotify.js";

let lastMode = "unknown";
let lastIp = null;
let pinVisible = false;
let pinTimer = null;

function getDisplayIp(mode, ip) {
  if (mode === "ap") return "192.168.4.1:5000";
  return `${ip || window.location.hostname}:5000`;
}

function showPinExpansion(pin, mode = lastMode, ip = lastIp) {
  const wifiInfo = document.querySelector(".wifi-info");
  if (!wifiInfo) return;

  wifiInfo.classList.add("pin-expanded");

  const dashboardUrl = getDisplayIp(mode, ip);

  let row = wifiInfo.querySelector(".frame-pin-row");

  const html = `
    <div class="frame-pin-label">PIN</div>
    <div class="frame-pin-digits">${pin}</div>
    <div class="frame-pin-url">${dashboardUrl}</div>
  `;

  if (row) {
    row.innerHTML = html;
  } else {
    row = document.createElement("div");
    row.className = "frame-pin-row";
    row.innerHTML = html;
    wifiInfo.appendChild(row);
  }

  pinVisible = true;
}

function hidePinExpansion() {
  const wifiInfo = document.querySelector(".wifi-info");
  if (!wifiInfo) return;

  wifiInfo.classList.remove("pin-expanded");

  const row = wifiInfo.querySelector(".frame-pin-row");
  if (row) row.remove();

  pinVisible = false;
}

async function fetchPinFast() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 800);

  try {
    const res = await fetch(`/config_portal_pin.json?t=${Date.now()}`, {
      cache: "no-store",
      signal: controller.signal,
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();

    if (data?.active && data?.pin) {
      showPinExpansion(data.pin);
    } else {
      hidePinExpansion();
    }
  } catch {
    hidePinExpansion();
  } finally {
    clearTimeout(timeout);
  }
}

function schedulePinPoll() {
  clearTimeout(pinTimer);

  pinTimer = setTimeout(async () => {
    await fetchPinFast();

    // Very fast while hidden so new PIN appears almost instantly.
    // Slower once visible because we only need to notice expiry/removal.
    schedulePinPoll();
  }, pinVisible ? 1000 : 250);
}

function initPinPolling() {
  fetchPinFast();
  schedulePinPoll();
}

export function initWiFi() {
  initPinPolling();

  setInterval(updateWiFiStatus, INTERVALS.WIFI);
  updateWiFiStatus();
}

async function updateWiFiStatus() {
  const statusDiv = $(SELECTORS.wifiStatus);
  const prevOnline = state.online;

  let klass = "wifi-red";

  try {
    const data = await fetchJson(`${PATHS.STATUS}?t=${Date.now()}`);

    const mode = data?.mode || "unknown";
    const ip = data?.ip || null;

    lastMode = mode;
    lastIp = ip;

    if (mode === "ap") {
      state.online = false;
      klass = "wifi-blue";
    } else {
      try {
        await fetch("https://1.1.1.1", {
          mode: "no-cors",
          cache: "no-store",
        });

        state.online = true;
        klass = "wifi-green";
      } catch {
        state.online = false;
        klass = "wifi-red";
      }
    }
  } catch {
    try {
      await fetch("https://1.1.1.1", {
        mode: "no-cors",
        cache: "no-store",
      });

      state.online = true;
      klass = "wifi-green";
    } catch {
      state.online = false;
      klass = "wifi-red";
    }
  }

  if (statusDiv) {
    statusDiv.className = "wifistatus " + klass;
  }

  if (state.online && !prevOnline) {
    updateWeather();
    updateSpotify();
  }
}