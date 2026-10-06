/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Display-side software update status UI.
 */

import { PATHS, INTERVALS } from "../constants.js";
import { fetchJson } from "../utils.js";

let indicatorEl = null;
let overlayEl = null;
let lastState = null;
let updateStream = null;

const ACTIVE_UPDATE_PHASES = new Set([
  "applying",
  "awaiting_reboot",
  "verifying",
  "rolling_back",
  "awaiting_rollback_reboot",
  "verifying_rollback",
]);

function stateRevision(state) {
  const revision = Number(state?.state_revision);
  return Number.isFinite(revision) ? revision : null;
}

export function isUpdateStateActive(state) {
  return !!(
    state?.update_in_progress ||
    state?.pending_restart ||
    state?.reboot_requested ||
    state?.post_reboot_pending ||
    state?.rollback_in_progress ||
    state?.rollback_reboot_requested ||
    state?.post_rollback_pending ||
    ACTIVE_UPDATE_PHASES.has(state?.update_phase)
  );
}

export function shouldAcceptUpdateState(previousState, nextState) {
  const previousRevision = stateRevision(previousState);
  const nextRevision = stateRevision(nextState);
  if (previousRevision !== null && (nextRevision === null || nextRevision < previousRevision)) return false;
  if (nextState?.state_valid === false && isUpdateStateActive(previousState) && !isUpdateStateActive(nextState)) {
    return false;
  }
  return true;
}

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

export function ensureOverlay() {
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

  // Keep the overlay controlled by opacity/visibility only.
  // Do not use inline display toggles.
  overlayEl.style.removeProperty("display");

  return overlayEl;
}

export function applyUpdateState(state) {
  const nextState = state || {};

  // Polling and SSE run independently. Never let a delayed pre-update poll or
  // an invalid read override a newer active lifecycle.
  if (!shouldAcceptUpdateState(lastState, nextState)) return;

  lastState = nextState;

  const indicator = ensureIndicator();
  const overlay = ensureOverlay();
  const statusText = document.getElementById("updateStatusText");

  const available = !!lastState.available;
  const rollbackActive = !!(
    lastState.rollback_in_progress ||
    lastState.rollback_reboot_requested ||
    lastState.post_rollback_pending ||
    ["rolling_back", "awaiting_rollback_reboot", "verifying_rollback"].includes(lastState.update_phase)
  );
  const updating = isUpdateStateActive(lastState) || rollbackActive;
  const downloadBusy = !!(
    lastState.download_in_progress ||
    ["downloading", "preparing"].includes(lastState.update_phase)
  );

  indicator.classList.toggle("hidden", !available || updating || downloadBusy);
  indicator.classList.toggle("visible", available && !updating && !downloadBusy);
  indicator.title = lastState.latest_version
    ? `Software update available: ${lastState.latest_version}`
    : "Software update available";

  overlay.classList.toggle("is-updating", updating);
  overlay.setAttribute("aria-hidden", updating ? "false" : "true");

  if (statusText) {
    const rollbackVerifying = !!(
      lastState.post_rollback_pending ||
      lastState.update_phase === "verifying_rollback" ||
      (rollbackActive && lastState.rollback_post_reboot_attempt)
    );
    const verifying = !!(
      lastState.post_reboot_pending ||
      lastState.update_phase === "verifying" ||
      (updating && lastState.post_reboot_attempt)
    );
    if (rollbackVerifying) {
      statusText.textContent = "Restoring previous version - verifying frame";
    } else if (lastState.rollback_reboot_requested) {
      statusText.textContent = "Previous version restored - restarting frame";
    } else if (lastState.rollback_in_progress || lastState.rollback_required) {
      statusText.textContent = "Update failed - restoring previous version";
    } else if (verifying) {
      statusText.textContent = "Finishing update - verifying update";
    } else {
      statusText.textContent = "Applying software update";
    }
  }
}

async function refreshUpdateStatus() {
  const state = await fetchJson(`${PATHS.UPDATE_STATUS}?t=${Date.now()}`, null);
  if (state) applyUpdateState(state);
}

function setupUpdateStream() {
  if (!window.EventSource || updateStream) return;

  try {
    updateStream = new EventSource(PATHS.UPDATE_STREAM || "/update/stream");

    updateStream.addEventListener("state", (event) => {
      try {
        const state = JSON.parse(event.data || "{}");
        applyUpdateState(state);
      } catch (error) {
        console.warn("Could not parse update stream state", error);
      }
    });

    updateStream.onerror = () => {
      // Keep the normal polling fallback alive. EventSource auto-reconnects.
    };
  } catch (error) {
    updateStream = null;
  }
}

export function initUpdater() {
  ensureIndicator();
  ensureOverlay();
  setupUpdateStream();
  const initialStatus = refreshUpdateStatus();
  setInterval(refreshUpdateStatus, INTERVALS.UPDATE_STATUS || 60000);
  return initialStatus;
}

export function getLastUpdateState() {
  return lastState;
}

/* Console helpers */
if (typeof window !== "undefined") {
  window.showUpdateOverlay = () => {
    const overlay = ensureOverlay();
    overlay.classList.add("is-updating");
    overlay.setAttribute("aria-hidden", "false");
  };

  window.hideUpdateOverlay = () => {
    const overlay = ensureOverlay();
    overlay.classList.remove("is-updating");
    overlay.setAttribute("aria-hidden", "true");
  };

  window.applyUpdateState = applyUpdateState;
}
