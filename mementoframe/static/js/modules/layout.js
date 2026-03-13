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
 * - Cancels any pending calendarFullTimeout timer.
 * - Hides the calendar box and shows the Spotify box using
 *   "hidden"/"visible" CSS classes.
 * - Restores calendar opacity to 1 so it is not dim if it reappears.
 * - Updates panel state to reflect that Spotify is playing, which
 *   triggers a panel width animation via `applyPanelDimensions`.
 */
export function showSpotify() {
  const spotify  = $(SELECTORS.spotifyBox);
  const calendar = $(SELECTORS.calendarBox);

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
 * - If the current minute is < 10 and full-opacity mode is not already
 *   active, triggers `showCalendarFull()` for the hourly highlight.
 *   Otherwise sets calendar opacity to 0.75 (ambient dim level).
 */
export function showCalendar() {
  const spotify  = $(SELECTORS.spotifyBox);
  const calendar = $(SELECTORS.calendarBox);

  spotify?.classList.add("hidden");
  spotify?.classList.remove("visible");
  calendar?.classList.remove("hidden");
  calendar?.classList.add("visible");

  updatePanelState({ spotifyPlaying: false });

  const now     = new Date();
  const minutes = now.getMinutes();
  if (minutes < 10 && !state.panels.calendarFullOpacity) {
    showCalendarFull();
  } else if (!state.panels.calendarFullOpacity) {
    setCalendarOpacity(0.75);
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
 * Show the calendar at full opacity for a timed period.
 *
 * Only activates when the Spotify box is hidden (i.e. not currently
 * playing). Sets a timeout of `INTERVALS.CALENDAR_FULL_TIMEOUT` ms
 * after which `hideCalendarFull` automatically restores ambient opacity.
 *
 * Safe to call multiple times — clears any existing timeout before
 * setting a new one.
 */
export function showCalendarFull() {
  const spotifyBox = $(SELECTORS.spotifyBox);
  if (spotifyBox && spotifyBox.classList.contains("hidden")) {
    setCalendarOpacity(1);
    updatePanelState({ calendarFullOpacity: true });
    if (state.timers.calendarFullTimeout) clearTimeout(state.timers.calendarFullTimeout);
    state.timers.calendarFullTimeout = setTimeout(hideCalendarFull, INTERVALS.CALENDAR_FULL_TIMEOUT);
  }
}

/**
 * Restore calendar to ambient (0.75) opacity after the full-opacity period ends.
 *
 * Only applies when the Spotify box is hidden. Clears the timeout
 * reference so subsequent calls to `showCalendarFull` work correctly.
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
}

/**
 * Trigger full-opacity calendar display at the top of each hour.
 *
 * Called on every clock tick. Activates `showCalendarFull` only during
 * the first 5 seconds of the hour (minutes === 0, seconds < 5) and only
 * if full-opacity mode is not already active — preventing repeated
 * triggers within the same minute.
 */
export function checkHourlyCalendarDisplay() {
  const now = new Date();
  if (now.getMinutes() === 0 && now.getSeconds() < 5 && !state.panels.calendarFullOpacity) {
    showCalendarFull();
  }
}