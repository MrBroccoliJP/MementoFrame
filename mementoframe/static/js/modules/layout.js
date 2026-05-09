/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 *
 * This work is licensed under the Creative Commons Attribution-NonCommercial
 * 4.0 International License. To view a copy of this license, visit:
 * http://creativecommons.org/licenses/by-nc/4.0/
 */

/**
 * @file layout.js
 * @description Panel layout, visibility, and transition management.
 *
 * The display is divided into two panels:
 *   - Left panel  — photo slideshow background + floating burst photos
 *   - Right panel — clock, calendar, weather, Spotify widget
 *
 * The right panel switches between two widget states:
 *   - CALENDAR view  — shown when nothing is playing on Spotify
 *   - SPOTIFY view   — shown when a track is actively playing
 *
 * Panel width transitions smoothly between 99% (full, calendar only) and
 * 69% (narrow, Spotify widget visible beside it) using CSS transitions.
 *
 * Panels can also be swapped (left ↔ right) via `swapPanels()`, which
 * adjusts positions, padding, and any floating photos already in the DOM.
 *
 * Calendar full-opacity mode:
 *   At the start of each hour (minutes < 10), or when triggered manually,
 *   the calendar is shown at full opacity for `INTERVALS.CALENDAR_FULL_TIMEOUT`
 *   milliseconds before fading back to 0.75 opacity. This draws attention
 *   to the time at the top of the hour without being permanently bright.
 */

import { state } from "../state.js";
import { SELECTORS, INTERVALS } from "../constants.js";
import { $, $$ } from "../utils.js";

/**
 * Set the opacity of the calendar, weather, and date boxes simultaneously.
 *
 * Used to dim supporting widgets when Spotify is active, or restore them
 * to full brightness during full-opacity calendar mode or on hour change.
 *
 * @param {number} opacity - CSS opacity value (0–1).
 */
export function setCalendarOpacity(opacity) {
  $(SELECTORS.calendarBox)?.style && ($(SELECTORS.calendarBox).style.opacity = opacity);
  $(SELECTORS.weatherBox)?.style  && ($(SELECTORS.weatherBox).style.opacity  = opacity);
  $(SELECTORS.dateBox)?.style     && ($(SELECTORS.dateBox).style.opacity     = opacity);
}

/**
 * Transition the right panel to Spotify view.
 *
 * - Cancels any pending calendarFullTimeout timer (either an active
 *   full-opacity window or the next cycle trigger). Preserves
 *   `calendarWindowUntil` so showCalendar() can resume the window for
 *   the remaining time if the window was still active when Spotify opened.
 * - Hides the calendar box and shows the Spotify box using
 *   "hidden"/"visible" CSS classes.
 * - Restores calendar opacity to 1 so it is not dim if it reappears.
 * - Updates panel state to reflect that Spotify is playing, which
 *   triggers a panel width animation via `applyPanelDimensions`.
 */
export function showSpotify() {
  const spotify  = $(SELECTORS.spotifyBox);
  const calendar = $(SELECTORS.calendarBox);

  // Cancel any active window or pending cycle trigger.
  // Keep calendarWindowUntil intact — showCalendar() reads it to resume.
  if (state.timers.calendarFullTimeout) {
    clearTimeout(state.timers.calendarFullTimeout);
    state.timers.calendarFullTimeout = null;
  }

  calendar?.classList.add("hidden");
  calendar?.classList.remove("visible");
  spotify?.classList.remove("hidden");
  spotify?.classList.add("visible");

  setCalendarOpacity(1);
  updatePanelState({ calendarFullOpacity: false, spotifyPlaying: true });
}

/**
 * Transition the right panel to calendar view.
 *
 * - Hides the Spotify box and shows the calendar box.
 * - Updates panel state to mark Spotify as not playing.
 * - If a full-opacity window was active when Spotify opened and time
 *   still remains on it, resumes full opacity for the remaining duration.
 * - Otherwise resets the 30-min cycle to start from now, so the user
 *   gets a fresh cycle rather than waiting for whenever the original
 *   trigger was due.
 * - If neither applies, sets calendar to ambient (0.75) opacity.
 */
export function showCalendar() {
  const spotify  = $(SELECTORS.spotifyBox);
  const calendar = $(SELECTORS.calendarBox);

  spotify?.classList.add("hidden");
  spotify?.classList.remove("visible");
  calendar?.classList.remove("hidden");
  calendar?.classList.add("visible");

  updatePanelState({ spotifyPlaying: false });

  const remaining = state.timers.calendarWindowUntil
    ? state.timers.calendarWindowUntil - Date.now()
    : 0;

  if (remaining > 0) {
    // Resume the window for however long was left when Spotify opened.
    setCalendarOpacity(1);
    updatePanelState({ calendarFullOpacity: true });
    if (state.timers.calendarFullTimeout) clearTimeout(state.timers.calendarFullTimeout);
    state.timers.calendarFullTimeout = setTimeout(hideCalendarFull, remaining);
  } else {
    // No active window — reset the 30-min cycle from now so the user
    // doesn't wait up to 30 min just because Spotify interrupted the schedule.
    if (state.timers.calendarFullTimeout) {
      clearTimeout(state.timers.calendarFullTimeout);
      state.timers.calendarFullTimeout = null;
    }
    state.timers.calendarWindowUntil = null;
    setCalendarOpacity(0.75);
    scheduleCalendarCycle();
  }
}

/**
 * Merge updates into `state.panels` and reapply panel dimensions.
 *
 * All panel state changes should go through this function so that
 * `applyPanelDimensions` is always called after a state mutation.
 *
 * @param {Partial<state.panels>} updates - Key/value pairs to merge into state.panels.
 */
export function updatePanelState(updates) {
  Object.assign(state.panels, updates);
  applyPanelDimensions();
}

/**
 * Calculate the target left position and width for the left panel.
 *
 * Rules:
 *   - If Spotify is playing OR calendar is in full-opacity mode:
 *       width = 69% (NARROW), leaving room for the right panel widget.
 *       If panels are swapped: left = 30%; otherwise left = 0%.
 *   - Otherwise (calendar ambient mode):
 *       width = 99% (FULL), photo fills most of the screen.
 *
 * @returns {{ left: string, width: string }} CSS values for the left panel.
 */
function getPanelDimensions() {
  const { swapped, calendarFullOpacity, spotifyPlaying } = state.panels;
  const FULL   = "99%";
  const NARROW = "69%";
  if (spotifyPlaying || calendarFullOpacity) {
    return { left: swapped ? "30%" : "0%", width: NARROW };
  }
  return { left: swapped ? "0%" : "", width: FULL };
}

/**
 * Apply the calculated panel dimensions to the left panel DOM element.
 *
 * Animates width and left position using a 0.6s CSS transition so
 * panel changes feel smooth rather than instant.
 */
function applyPanelDimensions() {
  const left = $(SELECTORS.leftPanel);
  if (!left) return;
  const dim = getPanelDimensions();
  left.style.transition = "width 0.6s ease, left 0.6s ease";
  left.style.left  = dim.left;
  left.style.width = dim.width;
}

/**
 * Toggle the left and right panel positions.
 *
 * Moves the right panel to the left side of the screen and the left
 * panel (photo) to the right. Also:
 *   - Reorders the WiFi info and QR code elements to maintain visual
 *     alignment after the swap.
 *   - Adjusts system info box justification.
 *   - Offsets any currently visible floating burst photos so they
 *     remain within the (now repositioned) left panel.
 */
export function swapPanels() {
  const leftPanel  = $(SELECTORS.leftPanel);
  const rightPanel = $(SELECTORS.rightPanel);
  const wifiInfo   = document.querySelector(".wifi-info");
  const qrCode     = document.querySelector(".qrcode_icon");
  const systemInfo = document.querySelector(".system-info-box");

  const floating    = $$(".floating-photo");
  const hadFloating = floating.length > 0;

  if (state.panels.swapped) {
    // Restore default positions
    rightPanel.style.left        = "";
    rightPanel.style.paddingLeft = "";
    leftPanel.style.left         = "";
    leftPanel.style.paddingLeft  = "";
    if (wifiInfo && qrCode) {
      wifiInfo.after(qrCode);
      wifiInfo.style.textAlign = "";
      qrCode.style.textAlign   = "";
    }
    if (systemInfo) systemInfo.style.justifyContent = "flex-end";
    updatePanelState({ swapped: false });

  } else {
    // Move right panel to left edge
    rightPanel.style.left        = "0";
    rightPanel.style.paddingLeft = "0";
    leftPanel.style.left         = "auto";
    leftPanel.style.paddingLeft  = "";
    if (wifiInfo && qrCode) {
      qrCode.after(wifiInfo);
      wifiInfo.style.textAlign = "left";
      qrCode.style.textAlign   = "left";
    }
    if (systemInfo) systemInfo.style.justifyContent = "flex-start";
    updatePanelState({ swapped: true });
  }

  // Shift floating photos to match the new panel position
  if (hadFloating) {
    const offset = state.panels.swapped ? window.innerWidth * 0.3 : 0;
    floating.forEach(photo => {
      if (!photo.dataset.baseLeft) photo.dataset.baseLeft = parseFloat(photo.style.left) || 0;
      const base = parseFloat(photo.dataset.baseLeft);
      photo.style.left = `${base + offset}px`;
    });
  }
}

/**
 * Show the calendar at full opacity for INTERVALS.CALENDAR_FULL_TIMEOUT ms.
 *
 * Only activates when the Spotify box is hidden. Records the window
 * expiry time in `state.timers.calendarWindowUntil` so that showCalendar()
 * can resume the window correctly if Spotify hides mid-window.
 *
 * Safe to call multiple times — clears any existing timeout before
 * setting a new one.
 */
export function showCalendarFull() {
  const spotifyBox = $(SELECTORS.spotifyBox);
  if (!spotifyBox || !spotifyBox.classList.contains("hidden")) return;

  setCalendarOpacity(1);
  updatePanelState({ calendarFullOpacity: true });

  if (state.timers.calendarFullTimeout) clearTimeout(state.timers.calendarFullTimeout);

  state.timers.calendarWindowUntil = Date.now() + INTERVALS.CALENDAR_FULL_TIMEOUT;
  state.timers.calendarFullTimeout = setTimeout(hideCalendarFull, INTERVALS.CALENDAR_FULL_TIMEOUT);
}

/**
 * Restore calendar to ambient (0.75) opacity after the full-opacity window ends.
 *
 * Clears the window expiry timestamp so showCalendar() knows no window
 * is active, then schedules the next cycle.
 */
export function hideCalendarFull() {
  const spotifyBox = $(SELECTORS.spotifyBox);
  if (spotifyBox && spotifyBox.classList.contains("hidden")) {
    setCalendarOpacity(0.75);
    updatePanelState({ calendarFullOpacity: false });
  }

  if (state.timers.calendarFullTimeout) {
    clearTimeout(state.timers.calendarFullTimeout);
    state.timers.calendarFullTimeout = null;
  }

  state.timers.calendarWindowUntil = null;
  scheduleCalendarCycle();
}

/**
 * Schedule the next calendar full-opacity cycle.
 *
 * Fires showCalendarFull() after INTERVALS.CALENDAR_CYCLE ms (30 min),
 * then calls itself recursively to keep the cycle running indefinitely.
 *
 * Records the next trigger timestamp in `state.timers.calendarNextTrigger`
 * so that showCalendar() can cancel the pending trigger and reset it to
 * "now + 30 min" when Spotify hides, avoiding a long wait if Spotify was
 * active for most of the cycle.
 *
 * Call once on app startup (from main.js). Do not call setInterval from
 * main.js for this — the self-scheduling setTimeout approach is used so
 * the 30-min gap is always measured from the *end* of the window, not
 * from a fixed clock boundary.
 */
export function scheduleCalendarCycle(delay = INTERVALS.CALENDAR_CYCLE) {
  // Callers are responsible for clearing calendarFullTimeout before calling
  // this. Two call sites:
  //   - hideCalendarFull(): window just ended naturally, timeout already fired.
  //   - showCalendar() else branch: Spotify hid with no active window;
  //     timeout was explicitly cleared before this call, delay = 30 min from now.
  state.timers.calendarNextTrigger = Date.now() + delay;

  // Reuse the calendarFullTimeout slot — only one of (active window, pending
  // trigger) can exist at a time, so one slot covers both cases.
  state.timers.calendarFullTimeout = setTimeout(() => {
    state.timers.calendarFullTimeout = null;
    state.timers.calendarNextTrigger = null;
    showCalendarFull();
    // hideCalendarFull() will call scheduleCalendarCycle() when the window ends.
  }, delay);
}