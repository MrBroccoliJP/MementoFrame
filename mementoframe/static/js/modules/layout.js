/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 */

import { state } from "../state.js";
import { SELECTORS, INTERVALS } from "../constants.js";
import { $, $$ } from "../utils.js";
import { updateBurstGrid, stabilizeActiveVerticalPhotoDuringPanelResize } from "./photoslideshow.js";

// EXPORTED INIT FUNCTION: Safely starts the layout ticker only when called
export function initLayout() {
  //setInterval(() => evaluateLayout(false), INTERVALS.LAYOUT_EVALUATE);
  window.addEventListener("mementoframe:weather-availability-changed", () => evaluateLayout(true));
  evaluateLayout(true); // Run once immediately to set the initial state
}

export function setCalendarOpacity(opacity) {
  const calendarBox = document.getElementById('calendar-box');
  const forecastBox = document.getElementById('forecast-box');
  const dateBox = $(SELECTORS.dateBox);
  const weatherBox = $(SELECTORS.weatherBox);

  if (calendarBox) calendarBox.style.opacity = opacity;
  if (forecastBox) forecastBox.style.opacity = opacity;
  if (dateBox) dateBox.style.opacity = opacity;
  if (weatherBox) weatherBox.style.opacity = opacity;
}

export function showSpotify() {
  // Spotify interrupts: Pause the Big Mode timeout so it doesn't expire in the background
  if (state.timers.bigModeTimeout) {
    clearTimeout(state.timers.bigModeTimeout);
    state.timers.bigModeTimeout = null;
  }
  setCalendarOpacity(1);
  state.panels.bigModeActive = false; 
  state.panels.spotifyPlaying = true;
  evaluateLayout(true);
}

export function showCalendar() {
  state.panels.spotifyPlaying = false;

  // Calculate if we owe the user any remaining Big Mode screen time
  const remaining = state.timers.bigModeWindowUntil
    ? state.timers.bigModeWindowUntil - Date.now()
    : 0;

  if (remaining > 0) {
    // Resume Big Mode for the remaining time
    setCalendarOpacity(1);
    state.panels.bigModeActive = true;
    if (state.timers.bigModeTimeout) clearTimeout(state.timers.bigModeTimeout);
    state.timers.bigModeTimeout = setTimeout(disableBigMode, remaining);
  } else {
    // Normal mode
    if (state.timers.bigModeTimeout) {
      clearTimeout(state.timers.bigModeTimeout);
      state.timers.bigModeTimeout = null;
    }
    state.timers.bigModeWindowUntil = null;
    setCalendarOpacity(0.75);
    scheduleBigModeCycle();
  }
  evaluateLayout(true);
}

export function updatePanelState(updates) {
  Object.assign(state.panels, updates);
  const left = $(SELECTORS.leftPanel);
  left?.classList.toggle("swapped", state.panels.swapped);
  applyPanelDimensions();
  applyWidgetVisibility();
  updateBurstGrid();
}

function getPanelDimensions() {
  const { swapped, bigModeActive, spotifyPlaying } = state.panels;
  const FULL = "100%";
  const NARROW = "70%";
  if (spotifyPlaying || bigModeActive) {
    return { left: swapped ? "30%" : "0%", width: NARROW };
  }
  return { left: swapped ? "0%" : "", width: FULL };
}

function updateBurstOffset() {
  const left = $(SELECTORS.leftPanel);
  if (!left) return;
  const needsOffset = state.panels.swapped && !state.panels.bigModeActive && !state.panels.spotifyPlaying;
  left.style.setProperty("--burst-x-offset", needsOffset ? `${window.innerWidth * 0.3}px` : "0px");
}

function applyPanelDimensions() {
  const left = $(SELECTORS.leftPanel);
  if (!left) return;
  const dim = getPanelDimensions();
  const willBeNarrow = state.panels.bigModeActive || state.panels.spotifyPlaying;
  const panelWillResize = left.style.width !== dim.width || left.classList.contains("photo-narrow") !== willBeNarrow;

  if (panelWillResize) stabilizeActiveVerticalPhotoDuringPanelResize(700);

  left.style.transition = "width 0.6s ease, left 0.6s ease";
  left.style.left = dim.left;
  left.style.width = dim.width;
  left.classList.toggle("swapped", state.panels.swapped);
  left.classList.toggle("photo-narrow", willBeNarrow);
  updateBurstOffset();
}

export function swapPanels() {
  const leftPanel = $(SELECTORS.leftPanel);
  const rightPanel = $(SELECTORS.rightPanel);
  const wifiInfo = document.querySelector(".wifi-info");
  const qrCode = document.querySelector(".qrcode_icon");
  const updateCard = document.getElementById("update-status-card");
  const systemInfo = document.querySelector(".system-info-box");

  function moveSystemItems(order) {
    if (!systemInfo) return;

    order.forEach((item) => {
      if (item && item.parentElement === systemInfo) {
        systemInfo.appendChild(item);
      }
    });
  }

  if (state.panels.swapped) {
    rightPanel.style.left = "";

    // Normal order, right aligned:
    // Wi-Fi → Update → QR
    moveSystemItems([wifiInfo, updateCard, qrCode]);

    if (wifiInfo) wifiInfo.style.textAlign = "";
    if (updateCard) updateCard.style.textAlign = "";
    if (qrCode) qrCode.style.textAlign = "";
    if (systemInfo) systemInfo.style.justifyContent = "flex-end";

    updatePanelState({ swapped: false });
  } else {
    rightPanel.style.left = "0";

    // Swapped order, left aligned:
    // QR → Update → Wi-Fi
    moveSystemItems([qrCode, updateCard, wifiInfo]);

    if (wifiInfo) wifiInfo.style.textAlign = "left";
    if (updateCard) updateCard.style.textAlign = "left";
    if (qrCode) qrCode.style.textAlign = "left";
    if (systemInfo) systemInfo.style.justifyContent = "flex-start";

    updatePanelState({ swapped: true });
  }
}

// ============================================
// BIG MODE CONTROLS
// ============================================

export function enableBigMode() {
  setCalendarOpacity(1);
  state.panels.bigModeActive = true;
  if (state.timers.bigModeTimeout) clearTimeout(state.timers.bigModeTimeout);
  state.timers.bigModeWindowUntil = Date.now() + INTERVALS.CALENDAR_FULL_TIMEOUT;
  state.timers.bigModeTimeout = setTimeout(disableBigMode, INTERVALS.CALENDAR_FULL_TIMEOUT);
  evaluateLayout(true);
}

export function disableBigMode() {
  setCalendarOpacity(0.75);
  state.panels.bigModeActive = false;
  if (state.timers.bigModeTimeout) {
    clearTimeout(state.timers.bigModeTimeout);
    state.timers.bigModeTimeout = null;
  }
  state.timers.bigModeWindowUntil = null;
  scheduleBigModeCycle();
  evaluateLayout(true);
}

export function scheduleBigModeCycle(delay = INTERVALS.CALENDAR_CYCLE) {
  state.timers.bigModeNextTrigger = Date.now() + delay;
  state.timers.bigModeTimeout = setTimeout(() => {
    state.timers.bigModeTimeout = null;
    state.timers.bigModeNextTrigger = null;
    enableBigMode();
  }, delay);
}

// ============================================
// STATE MACHINE: DYNAMIC ROTATION
// ============================================

export function evaluateLayout(force = false) {
    const currentMinute = new Date().getMinutes();
    const cycleMinute = currentMinute % INTERVALS.LAYOUT_CYCLE_MINUTES;
    const isSpotify = state.panels.spotifyPlaying;
    const isBigMode = state.panels.bigModeActive;
    const hasForecast = !!state.weather.forecastAvailable;

    let updates = {
        spotifyView: 'hidden',
        calendarView: 'hidden',
        forecastView: 'hidden'
    };

if (isSpotify) {
        // Spotify shrunk + widgets stacked. Only show forecast if weather data exists.
        if (cycleMinute === 0) { 
            updates.spotifyView = 'shrunk'; 
            updates.calendarView = 'week'; 
            updates.forecastView = hasForecast ? '5h-icons' : 'hidden'; 
        }
        else { 
            updates.spotifyView = 'big'; 
            updates.calendarView = 'hidden'; 
            updates.forecastView = 'hidden'; 
        }
    }
    else {
        if (isBigMode) {
            // BIG MODE logic. If weather is unavailable, keep the calendar up instead.
            if (hasForecast && cycleMinute === 0) updates.forecastView = '5h-big';
            else if (hasForecast && cycleMinute === 1) updates.forecastView = '5d-big';
            else updates.calendarView = 'month';
        } else {
            // NORMAL MODE logic. If weather is unavailable, do not rotate into forecast.
            if (hasForecast && cycleMinute === 1) updates.forecastView = '5h-icons';
            else updates.calendarView = 'week';
        }
    }

    if (force ||
        state.panels.spotifyView !== updates.spotifyView ||
        state.panels.calendarView !== updates.calendarView ||
        state.panels.forecastView !== updates.forecastView) {
        updatePanelState(updates);
    }
}

/**
 * Applies widget visibility and layout modes based on the current state.
 * This function is the "single source of truth" for DOM manipulation.
 */
function applyWidgetVisibility() {
  const { spotifyView, calendarView, forecastView } = state.panels;
 
  const spotifyBox  = document.getElementById('spotify-box');
  const calendarBox = document.getElementById('calendar-box');
  const calMonth    = document.getElementById('calendar-month');
  const calWeek     = document.getElementById('calendar-week');
  const forecastBox = document.getElementById('forecast-box');
  const f5hIcons    = document.getElementById('forecast-5h-icons');
  const f5hBig      = document.getElementById('forecast-5h-big');
  const f5dBig      = document.getElementById('forecast-5d-big');
 
  // ── Helper: set one of three widget states ──────────────────────────────
  function setWidget(el, mode) {
    // mode: 'visible' | 'hidden' | 'gone'
    if (!el) return;
    el.classList.remove('widget-visible', 'widget-hidden', 'widget-gone');
    el.classList.add(`widget-${mode}`);
 
    // Keep legacy .hidden/.visible in sync for any CSS that still references them
    el.classList.toggle('hidden',  mode !== 'visible');
    el.classList.toggle('visible', mode === 'visible');
  }
 
  // ── 1. Spotify box ───────────────────────────────────────────────────────
  if (spotifyView === 'hidden') {
    setWidget(spotifyBox, 'gone');
  } else {
    setWidget(spotifyBox, 'visible');
    spotifyBox?.classList.toggle('spotify-shrunk', spotifyView === 'shrunk');
  }
 
  // ── 2. Calendar box ──────────────────────────────────────────────────────
  if (calendarView === 'hidden') {
    // Use 'gone' when Spotify is big (no space needed), 'hidden' when
    // Spotify is shrunk (might reappear soon without layout jump).
    setWidget(calendarBox, spotifyView === 'big' ? 'gone' : 'gone');
  } else {
    setWidget(calendarBox, 'visible');
 
    // Switch inner sub-panels
    if (calendarView === 'month') {
      calMonth?.classList.remove('hidden');
      calWeek?.classList.add('hidden');
      calendarBox?.classList.remove('week-mode');
    } else if (calendarView === 'week') {
      calMonth?.classList.add('hidden');
      calWeek?.classList.remove('hidden');
      calendarBox?.classList.add('week-mode');
    }
  }
 
  // ── 3. Forecast box ──────────────────────────────────────────────────────
  if (forecastView === 'hidden') {
    setWidget(forecastBox, spotifyView === 'big' ? 'gone' : 'gone');
  } else {
    setWidget(forecastBox, 'visible');
 
    // Hide all sub-views first, then show the right one
    f5hIcons?.classList.add('hidden');
    f5hBig?.classList.add('hidden');
    f5dBig?.classList.add('hidden');
 
    if (forecastView === '5h-icons') f5hIcons?.classList.remove('hidden');
    if (forecastView === '5h-big')   f5hBig?.classList.remove('hidden');
    if (forecastView === '5d-big')   f5dBig?.classList.remove('hidden');

    // Big forecast panels should be fully opaque, matching the other right-panel cards.
    if (forecastView === '5h-big' || forecastView === '5d-big') {
      forecastBox.style.opacity = "1";
    }
  }

  window.dispatchEvent(new CustomEvent("mementoframe:forecast-view-changed", {
    detail: { spotifyView, calendarView, forecastView }
  }));
}

// ============================================
// TEMPORARY TESTING TOOL
// ============================================
window.testLayout = function(spotify, calendar, forecast) {
    updatePanelState({
        spotifyView: spotify,
        calendarView: calendar,
        forecastView: forecast
    });
    console.log(`Test layout applied! | Spotify: ${spotify} | Calendar: ${calendar} | Forecast: ${forecast}`);
};

window.swapPanels = swapPanels; // Expose for testing