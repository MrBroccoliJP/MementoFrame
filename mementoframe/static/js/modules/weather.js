import { state } from "../state.js";
import { PATHS, INTERVALS, SELECTORS } from "../constants.js";
import { $, fetchJson } from "../utils.js";

let lastWeatherAt = null;
const STALE = 2 * 60 * 60 * 1000;

export function initWeather() {
  const box = $(SELECTORS.weatherBox);
  if (box) box.style.display = "none";
  setInterval(updateWeather, INTERVALS.WEATHER);
  updateWeather();
}

export async function updateWeather() {
  const box = $(SELECTORS.weatherBox);
  const tEl = $(SELECTORS.weatherTemp);
  const cEl = $(SELECTORS.weatherCond);
  const icon = $(SELECTORS.weatherIcon);

  if (!state.online) {
    if (tEl) tEl.textContent = "--°C";
    if (cEl) cEl.textContent = "Offline";
    if (icon) icon.src = PATHS.WEATHER_OFFLINE_ICON;
    if (!lastWeatherAt || Date.now() - lastWeatherAt > STALE) {
      if (box) box.style.display = "none";
    }
    return;
  }

  const data = await fetchJson(PATHS.WEATHER);
  if (!data || data.error) {
    if (!lastWeatherAt || Date.now() - lastWeatherAt > STALE) {
      if (box) box.style.display = "none";
    }
    return;
  }

  if (tEl) tEl.textContent = `${data.temperature}°C`;
  if (cEl) cEl.textContent = data.condition;
  if (icon && data.icon) {
    icon.crossOrigin = "anonymous";
    const iconUrl = data.icon.startsWith("//") ? "https:" + data.icon : data.icon;
    icon.src = `${iconUrl}?t=${Date.now()}`;
  }
  lastWeatherAt = Date.now();
  if (box) box.style.display = "flex";
}
