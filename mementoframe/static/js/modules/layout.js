import { state } from "../state.js";
import { SELECTORS, INTERVALS } from "../constants.js";
import { $, $$ } from "../utils.js";

export function setCalendarOpacity(opacity) {
  $(SELECTORS.calendarBox)?.style && ( $(SELECTORS.calendarBox).style.opacity = opacity );
  $(SELECTORS.weatherBox)?.style && ( $(SELECTORS.weatherBox).style.opacity = opacity );
  $(SELECTORS.dateBox)?.style && ( $(SELECTORS.dateBox).style.opacity = opacity );
}

export function showSpotify() {
  const spotify = $(SELECTORS.spotifyBox);
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

export function showCalendar() {
  const spotify = $(SELECTORS.spotifyBox);
  const calendar = $(SELECTORS.calendarBox);

  spotify?.classList.add("hidden");
  spotify?.classList.remove("visible");
  calendar?.classList.remove("hidden");
  calendar?.classList.add("visible");

  updatePanelState({ spotifyPlaying: false });

  const now = new Date();
  const minutes = now.getMinutes();
  if (minutes < 10 && !state.panels.calendarFullOpacity) {
    showCalendarFull();
  } else if (!state.panels.calendarFullOpacity) {
    setCalendarOpacity(0.75);
  }
}

export function updatePanelState(updates) {
  Object.assign(state.panels, updates);
  applyPanelDimensions();
}

function getPanelDimensions() {
  const { swapped, calendarFullOpacity, spotifyPlaying } = state.panels;
  const FULL = "99%";
  const NARROW = "69%";
  if (spotifyPlaying || calendarFullOpacity) return { left: swapped ? "30%" : "0%", width: NARROW };
  return { left: swapped ? "0%" : "", width: FULL };
}

function applyPanelDimensions() {
  const left = $(SELECTORS.leftPanel);
  if (!left) return;
  const dim = getPanelDimensions();
  left.style.transition = "width 0.6s ease, left 0.6s ease";
  left.style.left = dim.left;
  left.style.width = dim.width;
}

export function swapPanels() {
  const leftPanel = $(SELECTORS.leftPanel);
  const rightPanel = $(SELECTORS.rightPanel);
  const wifiInfo = document.querySelector(".wifi-info");
  const qrCode = document.querySelector(".qrcode_icon");
  const systemInfo = document.querySelector(".system-info-box");

  const floating = $$(".floating-photo");
  const hadFloating = floating.length > 0;

  if (state.panels.swapped) {
    rightPanel.style.left = "";
    rightPanel.style.paddingLeft = "";
    leftPanel.style.left = "";
    leftPanel.style.paddingLeft = "";
    if (wifiInfo && qrCode) { wifiInfo.after(qrCode); wifiInfo.style.textAlign = ""; qrCode.style.textAlign = ""; }
    if (systemInfo) systemInfo.style.justifyContent = "flex-end";
    updatePanelState({ swapped: false });
  } else {
    rightPanel.style.left = "0";
    rightPanel.style.paddingLeft = "0";
    leftPanel.style.left = "auto";
    leftPanel.style.paddingLeft = "";
    if (wifiInfo && qrCode) { qrCode.after(wifiInfo); wifiInfo.style.textAlign = "left"; qrCode.style.textAlign = "left"; }
    if (systemInfo) systemInfo.style.justifyContent = "flex-start";
    updatePanelState({ swapped: true });
  }

  if (hadFloating) {
    const offset = state.panels.swapped ? window.innerWidth * 0.3 : 0;
    floating.forEach(photo => {
      if (!photo.dataset.baseLeft) photo.dataset.baseLeft = parseFloat(photo.style.left) || 0;
      const base = parseFloat(photo.dataset.baseLeft);
      photo.style.left = `${base + offset}px`;
    });
  }
}

export function showCalendarFull() {
  const spotifyBox = $(SELECTORS.spotifyBox);
  if (spotifyBox && spotifyBox.classList.contains("hidden")) {
    setCalendarOpacity(1);
    updatePanelState({ calendarFullOpacity: true });
    if (state.timers.calendarFullTimeout) clearTimeout(state.timers.calendarFullTimeout);
    state.timers.calendarFullTimeout = setTimeout(hideCalendarFull, INTERVALS.CALENDAR_FULL_TIMEOUT);
  }
}

export function hideCalendarFull() {
  const spotifyBox = $(SELECTORS.spotifyBox);
  if (spotifyBox && spotifyBox.classList.contains("hidden")) {
    setCalendarOpacity(0.75);
    updatePanelState({ calendarFullOpacity: false });
  }
  if (state.timers.calendarFullTimeout) { clearTimeout(state.timers.calendarFullTimeout); state.timers.calendarFullTimeout = null; }
}

export function checkHourlyCalendarDisplay() {
  const now = new Date();
  if (now.getMinutes() === 0 && now.getSeconds() < 5 && !state.panels.calendarFullOpacity) showCalendarFull();
}
