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
  evaluateLayout(true); // Run once immediately to set the initial state
}

export function setCalendarOpacity(opacity) {
  const calendarBox = document.getElementById('calendar-box');
  const forecastBox = document.getElementById('forecast-box');
  if (calendarBox) calendarBox.style.opacity = opacity;
  if (forecastBox) forecastBox.style.opacity = opacity;
  $(SELECTORS.dateBox)?.style && ($(SELECTORS.dateBox).style.opacity = opacity);
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
  const systemInfo = document.querySelector(".system-info-box");

  if (state.panels.swapped) {
    rightPanel.style.left = "";
    if (wifiInfo && qrCode) {
      wifiInfo.after(qrCode);
      wifiInfo.style.textAlign = "";
      qrCode.style.textAlign = "";
    }
    if (systemInfo) systemInfo.style.justifyContent = "flex-end";
    updatePanelState({ swapped: false });
  } else {
    rightPanel.style.left = "0";
    if (wifiInfo && qrCode) {
      qrCode.after(wifiInfo);
      wifiInfo.style.textAlign = "left";
      qrCode.style.textAlign = "left";
    }
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

function evaluateLayout(force = false) {
    const currentMinute = new Date().getMinutes();
    const cycleMinute = currentMinute % INTERVALS.LAYOUT_CYCLE_MINUTES;
    const isSpotify = state.panels.spotifyPlaying;
    const isBigMode = state.panels.bigModeActive;

    let updates = {
        spotifyView: 'hidden',
        calendarView: 'hidden',
        forecastView: 'hidden'
    };

if (isSpotify) {
        // NEW STATE: Spotify shrunk + BOTH widgets stacked
        if (cycleMinute === 0) { 
            updates.spotifyView = 'shrunk'; 
            updates.calendarView = 'week'; 
            updates.forecastView = '5h-icons'; 
        }
        else { 
            updates.spotifyView = 'big'; 
            updates.calendarView = 'hidden'; 
            updates.forecastView = 'hidden'; 
        }
    }
    else {
        if (isBigMode) {
            // BIG MODE logic
            if (cycleMinute === 0) updates.forecastView = '5h-big';
            else if (cycleMinute === 1) updates.forecastView = '5d-big';
            else updates.calendarView = 'month';
        } else {
            // NORMAL MODE logic
            if (cycleMinute === 1) updates.forecastView = '5h-icons';
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
// ============================================
// ANIMATED WIDGET TRANSITIONS
// ============================================

// Must match the transition duration in your CSS (the opacity/transform transition)
const WIDGET_TRANSITION_MS = 450;

// Tracks pending collapse timers per element id so rapid changes don't stack
const _widgetTimers = new Map();

/**
 * Transition a top-level widget box between three states:
 *
 *   'visible' — in flow, opacity 1, fully interactive
 *   'gone'    — fades out first, then collapses to display:none after
 *               WIDGET_TRANSITION_MS so the CSS transition is visible
 *
 * The two-step gone sequence is the key fix: jumping straight to
 * display:none kills the transition before it plays.
 */
function setWidget(el, targetMode) {
  if (!el) return;
  const id = el.id;

  // Cancel any pending collapse timer for this element
  if (_widgetTimers.has(id)) {
    clearTimeout(_widgetTimers.get(id));
    _widgetTimers.delete(id);
  }

  if (targetMode === 'visible') {
    // 1. Ensure it's in the DOM flow (remove display:none)
    el.style.display = '';
    el.classList.remove('hidden');

    // 2. Force reflow so browser registers the element before we animate
    void el.offsetHeight;

    // 3. Now fade in
    el.style.opacity = '1';
    el.style.transform = 'scale(1) translateY(0)';
    el.style.pointerEvents = 'auto';

  } else { // 'gone'
    // Step 1: fade out (element still in flow so transition plays)
    el.style.opacity = '0';
    el.style.transform = 'scale(0.97) translateY(-6px)';
    el.style.pointerEvents = 'none';

    // Step 2: after transition finishes, remove from flow
    const timer = setTimeout(() => {
      el.classList.add('hidden');
      el.style.display = 'none';
      _widgetTimers.delete(id);
    }, WIDGET_TRANSITION_MS);

    _widgetTimers.set(id, timer);
  }
}

/**
 * Applies widget visibility and layout modes based on the current state.
 * This is the single source of truth for DOM manipulation.
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

    // 1. Spotify
    if (spotifyView === 'hidden') {
        setWidget(spotifyBox, 'gone');
    } else {
        setWidget(spotifyBox, 'visible');
        spotifyBox?.classList.toggle('spotify-shrunk', spotifyView === 'shrunk');
    }

    // 2. Calendar
    if (calendarView === 'hidden') {
        setWidget(calendarBox, 'gone');
    } else {
        setWidget(calendarBox, 'visible');
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

    // 3. Forecast
    if (forecastView === 'hidden') {
        setWidget(forecastBox, 'gone');
    } else {
        setWidget(forecastBox, 'visible');
        f5hIcons?.classList.add('hidden');
        f5hBig?.classList.add('hidden');
        f5dBig?.classList.add('hidden');
        if (forecastView === '5h-icons') f5hIcons?.classList.remove('hidden');
        if (forecastView === '5h-big')   f5hBig?.classList.remove('hidden');
        if (forecastView === '5d-big')   f5dBig?.classList.remove('hidden');
    }
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