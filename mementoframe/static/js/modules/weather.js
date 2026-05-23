/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 */

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
  const box  = $(SELECTORS.weatherBox);
  const tEl  = $(SELECTORS.weatherTemp);
  const cEl  = $(SELECTORS.weatherCond);
  const icon = $(SELECTORS.weatherIcon);

  if (!state.online) {
    if (tEl)  tEl.textContent = "--°C";
    if (cEl)  cEl.textContent = "Offline";
    if (icon) icon.src        = PATHS.WEATHER_OFFLINE_ICON;
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

  if (tEl)  tEl.textContent = `${data.temperature}°C`;
  if (cEl)  cEl.textContent = data.condition;

  let validIconUrl = PATHS.WEATHER_OFFLINE_ICON;
  if (icon && data.icon) {
    icon.crossOrigin = "anonymous";
    validIconUrl = data.icon.startsWith("//") ? "https:" + data.icon : data.icon;
    icon.src = `${validIconUrl}?t=${Date.now()}`;
  }

  lastWeatherAt = Date.now();
  if (box) box.style.display = "flex";

  // Parse or Mock the Forecast data required for Dynamic Layout
// Real forecast data from backend — falls back to mock if absent
  const forecast = data.forecast || generateMockForecasts(
    data.temperature || "--",
    data.condition   || "Unknown",
    validIconUrl
  );

  renderForecasts(forecast);
}

function renderForecasts(forecast) {
  const f5hIcons = document.getElementById('forecast-5h-icons');
  const f5hBig   = document.getElementById('forecast-5h-big');
  const f5dBig   = document.getElementById('forecast-5d-big');

  // Horizontal icon strip — 5 hours
  if (f5hIcons) {
    f5hIcons.innerHTML = '<div class="forecast-row">' +
      forecast.hourly.map(h => `
        <div class="forecast-item">
          <div class="time">${h.time}</div>
          <img src="${h.icon}" crossorigin="anonymous" alt="${h.condition}">
        </div>`
      ).join('') + '</div>';
  }

  // Vertical hourly list
  if (f5hBig) {
    f5hBig.innerHTML = '<div class="forecast-list">' +
      forecast.hourly.map(h => `
        <div class="forecast-list-item">
          <div class="time">${h.time}</div>
          <img src="${h.icon}" crossorigin="anonymous" alt="${h.condition}">
          <div class="cond">${h.condition}</div>
          <div class="temp">${h.temp}</div>
        </div>`
      ).join('') + '</div>';
  }

  // Vertical daily list — label is "Today", "Mon", "Tue" etc.
  if (f5dBig) {
    f5dBig.innerHTML = '<div class="forecast-list">' +
      forecast.daily.map(d => `
        <div class="forecast-list-item">
          <div class="time">${d.label}</div>
          <img src="${d.icon}" crossorigin="anonymous" alt="${d.condition}">
          <div class="cond">${d.condition}</div>
          <div class="temp">${d.high} / ${d.low}</div>
        </div>`
      ).join('') + '</div>';
  }
}