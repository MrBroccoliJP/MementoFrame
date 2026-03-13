import { state } from "../state.js";
import { PATHS, INTERVALS, SELECTORS } from "../constants.js";
import { $, fetchJson } from "../utils.js";
import { updateWeather } from "./weather.js";
import { updateSpotify } from "./spotify.js";

export function initWiFi() {
  setInterval(updateWiFiStatus, INTERVALS.WIFI);
  updateWiFiStatus();
}

async function updateWiFiStatus() {
  const statusDiv = $(SELECTORS.wifiStatus);
  let prevOnline = state.online;
  let apMode = false;
  let klass = "wifi-red";

  try {
    const data = await fetchJson(PATHS.STATUS);
    if (data?.mode === "ap") {
      apMode = true; state.online = false; klass = "wifi-blue";
    } else {
      // probe internet
      try {
        await fetch("https://1.1.1.1", { mode: "no-cors" });
        state.online = true; klass = "wifi-green";
      } catch { state.online = false; klass = "wifi-red"; }
    }
  } catch {
    try {
      await fetch("https://1.1.1.1", { mode: "no-cors" });
      state.online = true; klass = "wifi-green";
    } catch { state.online = false; klass = "wifi-red"; }
  }

  if (statusDiv) statusDiv.className = "wifistatus " + klass;

  if (state.online && !prevOnline) {
    updateWeather(); updateSpotify();
  } else if (!state.online && prevOnline && !apMode) {
    // nothing to do here; ambient accent handled by spotify module
  }
}
