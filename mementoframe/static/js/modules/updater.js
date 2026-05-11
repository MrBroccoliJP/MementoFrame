/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Display-side software update status UI.
 */

import { PATHS, INTERVALS } from "../constants.js";
import { fetchJson } from "../utils.js";

let indicatorEl = null;
let overlayEl = null;
let lastState = null;

function ensureIndicator() {
  if (indicatorEl) return indicatorEl;

  indicatorEl = document.getElementById("update-status-card");
  if (!indicatorEl) {
    indicatorEl = document.createElement("div");
    indicatorEl.id = "update-status-card";
    indicatorEl.className = "rounded-box update-status-card hidden";
    indicatorEl.title = "Software update available";
    indicatorEl.innerHTML = `
      <svg class="update-status-card__icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <path d="M12 3v10.2" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>
        <path d="M7.8 9.2 12 13.4l4.2-4.2" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M5 16.5v1.2A2.3 2.3 0 0 0 7.3 20h9.4a2.3 2.3 0 0 0 2.3-2.3v-1.2" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>
      </svg>
      <div class="update-status-card__text">UPDATE</div>
    `;

    const systemInfo = document.querySelector(".system-info-box");
    const wifiInfo = document.querySelector(".wifi-info");
    if (systemInfo && wifiInfo) wifiInfo.after(indicatorEl);
    else if (systemInfo) systemInfo.appendChild(indicatorEl);
    else document.body.appendChild(indicatorEl);
  }

  return indicatorEl;
}

function ensureOverlay() {
  if (overlayEl) return overlayEl;

  overlayEl = document.getElementById("mf-update-overlay");
  if (!overlayEl) {
    overlayEl = document.createElement("div");
    overlayEl.id = "mf-update-overlay";
    overlayEl.className = "mf-update-overlay";
    overlayEl.setAttribute("aria-hidden", "true");
    overlayEl.innerHTML = `
      <div class="mf-loading__inner">
        <div class="mf-loading__logo" aria-hidden="true">
          <div class="mf-loading__frame mf-loading__frame--back"></div>
          <div class="mf-loading__frame mf-loading__frame--mid"></div>
          <div class="mf-loading__frame mf-loading__frame--front"></div>
          <div class="mf-loading__dot mf-loading__dot--lg"></div>
          <div class="mf-loading__dot mf-loading__dot--sm"></div>
        </div>
        <div class="mf-loading__wordmark">
          <span>UPDATING</span>
          <span>FRAME</span>
        </div>
      </div>
      <div class="mf-loading__footer">
        <div class="mf-loading__status" id="updateStatusText">Applying software update</div>
        <div class="mf-loading__progress" aria-hidden="true"></div>
        <div class="mf-update-overlay__hint">The frame may restart automatically when the update finishes.</div>
      </div>
    `;
    document.body.appendChild(overlayEl);
  }

  return overlayEl;
}

function applyUpdateState(state) {
  lastState = state || {};

  const indicator = ensureIndicator();
  const overlay = ensureOverlay();
  const statusText = document.getElementById("updateStatusText");

  const available = !!lastState.available;
  const updating = !!lastState.update_in_progress;

  // Requested behavior: the rounded update card only appears when an update is available.
  indicator.classList.toggle("hidden", !available || updating);
  indicator.classList.toggle("visible", available && !updating);
  indicator.title = lastState.latest_version
    ? `Software update available: ${lastState.latest_version}`
    : "Software update available";

  overlay.classList.toggle("visible", updating);
  overlay.setAttribute("aria-hidden", updating ? "false" : "true");

  if (statusText) {
    statusText.textContent = lastState.pending_restart
      ? "Update installed — restart pending"
      : "Applying software update";
  }
}

async function refreshUpdateStatus() {
  const state = await fetchJson(`${PATHS.UPDATE_STATUS}?t=${Date.now()}`, null);
  if (state) applyUpdateState(state);
}

export function initUpdater() {
  ensureIndicator();
  ensureOverlay();
  refreshUpdateStatus();
  setInterval(refreshUpdateStatus, INTERVALS.UPDATE_STATUS || 60000);
}

export function getLastUpdateState() {
  return lastState;
}
