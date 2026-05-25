/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 */

import { state } from "../state.js";
import { PATHS, INTERVALS, SELECTORS } from "../constants.js";
import { $, fetchJson } from "../utils.js";

let lastWeatherAt = null;
const STALE = 2 * 60 * 60 * 1000;
const WEATHER_ALERT_CYCLE_MS = 5 * 60 * 1000;
const WEATHER_ALERT_VISIBLE_MS = 60 * 1000;

let currentWeatherCondition = "";
let currentWeatherIconUrl = PATHS.WEATHER_OFFLINE_ICON;
let currentWeatherUvIconUrl = null;
let currentWeatherAlerts = [];
let weatherAlertTimer = null;

export function initWeather() {
  const box = $(SELECTORS.weatherBox);
  if (box) box.style.display = "none";

  window.addEventListener("mementoframe:forecast-view-changed", () => {
    scheduleConditionScrollRefresh();
  });

  window.addEventListener("resize", () => {
    scheduleConditionScrollRefresh();
    scheduleWeatherConditionScrollRefresh();
  });

  if (document.fonts?.ready) {
    document.fonts.ready.then(() => {
      scheduleConditionScrollRefresh();
      scheduleWeatherConditionScrollRefresh();
    }).catch(() => {});
  }

  if (!weatherAlertTimer) {
    weatherAlertTimer = setInterval(applyWeatherContainerDisplay, 15000);
  }

  setInterval(updateWeather, INTERVALS.WEATHER);
  updateWeather();
}

export async function updateWeather() {
  const box  = $(SELECTORS.weatherBox);
  const tEl  = $(SELECTORS.weatherTemp);
  const cEl  = $(SELECTORS.weatherCond);
  const icon = $(SELECTORS.weatherIcon);

  if (!state.online) {
    currentWeatherCondition = "Offline";
    currentWeatherIconUrl = PATHS.WEATHER_OFFLINE_ICON;
    currentWeatherUvIconUrl = null;
    currentWeatherAlerts = [];
    if (tEl)  tEl.textContent = "--°C";
    applyWeatherContainerDisplay();
    if (!lastWeatherAt || Date.now() - lastWeatherAt > STALE) {
      if (box) box.style.display = "none";
      clearForecasts();
    }
    return;
  }

  const data = await fetchJson(PATHS.WEATHER);
  if (!data || data.error) {
    if (!lastWeatherAt || Date.now() - lastWeatherAt > STALE) {
      if (box) box.style.display = "none";
      clearForecasts();
    }
    return;
  }

  currentWeatherCondition = data.condition || "";
  currentWeatherIconUrl = normalizeIconUrl(data.icon || PATHS.WEATHER_OFFLINE_ICON);
  currentWeatherUvIconUrl = data.uvIcon ? normalizeIconUrl(data.uvIcon) : null;
  currentWeatherAlerts = Array.isArray(data.alerts) ? data.alerts : [];

  if (tEl) tEl.textContent = `${data.temperature}°C`;

  lastWeatherAt = Date.now();
  if (box) box.style.display = "flex";
  applyWeatherContainerDisplay();
  scheduleWeatherConditionScrollRefresh();

  // Forecast data is owned by the backend/mock service.
  // If /weather.json has no valid forecast, do not generate fake frontend data.
  const forecast = data.forecast;
  const forecastAvailable = hasValidForecast(forecast);
  updateWeatherAvailability(true, forecastAvailable);

  if (forecastAvailable) {
    renderForecasts(forecast);
  } else {
    clearForecasts(false);
  }
}

function hasValidForecast(forecast) {
  return Boolean(
    forecast &&
    Array.isArray(forecast.hourly) &&
    Array.isArray(forecast.daily) &&
    forecast.hourly.length &&
    forecast.daily.length
  );
}

function clearForecasts(updateAvailability = true) {
  if (updateAvailability) updateWeatherAvailability(false, false);

  for (const id of ["forecast-5h-icons", "forecast-5h-big", "forecast-5d-big"]) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = "";
  }
}

function updateWeatherAvailability(available, forecastAvailable) {
  if (!state.weather) return;

  const changed =
    state.weather.available !== available ||
    state.weather.forecastAvailable !== forecastAvailable;

  state.weather.available = available;
  state.weather.forecastAvailable = forecastAvailable;

  if (changed) {
    window.dispatchEvent(new CustomEvent("mementoframe:weather-availability-changed", {
      detail: { available, forecastAvailable }
    }));
  }
}

function renderForecasts(forecast) {
  const f5hIcons = document.getElementById("forecast-5h-icons");
  const f5hBig   = document.getElementById("forecast-5h-big");
  const f5dBig   = document.getElementById("forecast-5d-big");

  const hourly = forecast.hourly.slice(0, 5);
  const daily  = forecast.daily.slice(0, 5);

  if (f5hIcons) {
    f5hIcons.innerHTML = `<div class="forecast-row">${
      hourly.map((h) => `
        <div class="forecast-item">
          <div class="time">${escapeHtml(h.time)}</div>
          <img src="${escapeAttr(normalizeIconUrl(h.icon))}" crossorigin="anonymous" alt="${escapeAttr(h.condition)}">
        </div>`
      ).join("")
    }</div>`;
  }

  if (f5hBig) {
    f5hBig.innerHTML = `<div class="forecast-list">${
      hourly.map((h) => forecastRow({
        label: h.time,
        icon: h.icon,
        condition: h.condition,
        tempHtml: escapeHtml(formatTemp(h.temp)),
      })).join("")
    }</div>`;
  }

  if (f5dBig) {
    f5dBig.innerHTML = `<div class="forecast-list">${
      daily.map((d) => forecastRow({
        label: d.label,
        icon: d.icon,
        condition: d.condition,
        tempHtml: `
          <span class="temp-high">${escapeHtml(formatTemp(d.high))}</span>
          <span class="temp-low">${escapeHtml(formatTemp(d.low))}</span>
        `,
        tempClass: "temp-stack",
      })).join("")
    }</div>`;
  }

  scheduleConditionScrollRefresh();
}

function forecastRow({ label, icon, condition, tempHtml, tempClass = "" }) {
  const cleanCondition = String(condition || "").trim() || "—";

  return `
    <div class="forecast-list-item">
      <div class="time">${escapeHtml(label)}</div>
      <img src="${escapeAttr(normalizeIconUrl(icon))}" crossorigin="anonymous" alt="${escapeAttr(cleanCondition)}">
      <div class="cond" title="${escapeAttr(cleanCondition)}">
        <span class="cond-inner">${escapeHtml(cleanCondition)}</span>
      </div>
      <div class="temp ${tempClass}">${tempHtml}</div>
    </div>`;
}

function applyWeatherContainerDisplay() {
  const cEl  = $(SELECTORS.weatherCond);
  const icon = $(SELECTORS.weatherIcon);

  const alert = getActiveWeatherAlert();
  if (alert) {
    if (cEl) setWeatherConditionText(cEl, formatWeatherAlertText(alert));
    if (icon) setWeatherIcon(icon, normalizeIconUrl(alert.icon || currentWeatherIconUrl), null);
    return;
  }

  if (cEl) setWeatherConditionText(cEl, currentWeatherCondition);
  if (icon) setWeatherIcon(icon, currentWeatherIconUrl, currentWeatherUvIconUrl);
}

function getActiveWeatherAlert() {
  if (!currentWeatherAlerts.length) return null;
  const inAlertWindow = Date.now() % WEATHER_ALERT_CYCLE_MS < WEATHER_ALERT_VISIBLE_MS;
  return inAlertWindow ? currentWeatherAlerts[0] : null;
}

function formatWeatherAlertText(alert) {
  const event = String(alert?.event || "").trim();
  const headline = String(alert?.headline || "").trim();
  const severity = String(alert?.severity || "").trim();

  if (event && severity) return `⚠ ${severity}: ${event}`;
  if (event) return `⚠ ${event}`;
  if (headline) return `⚠ ${headline}`;
  return "⚠ Weather alert";
}

function setWeatherIcon(iconEl, iconUrl, uvIconUrl = null) {
  if (!iconEl) return;

  const normalizedIcon = normalizeIconUrl(iconUrl || PATHS.WEATHER_OFFLINE_ICON);
  iconEl.crossOrigin = "anonymous";

  if (iconEl.src !== normalizedIcon && !iconEl.src.endsWith(normalizedIcon)) {
    iconEl.src = normalizedIcon;
  }

  const parent = iconEl.parentElement;
  if (!parent) return;

  parent.style.position = parent.style.position || "relative";

  let uvBadge = parent.querySelector(".weather-uv-index-badge");
  if (!uvIconUrl) {
    uvBadge?.remove();
    return;
  }

  if (!uvBadge) {
    uvBadge = document.createElement("img");
    uvBadge.className = "weather-uv-index-badge";
    uvBadge.alt = "UV index";
    uvBadge.setAttribute("aria-hidden", "true");
    Object.assign(uvBadge.style, {
      position: "absolute",
      right: "-4px",
      bottom: "8px",
      width: "26px",
      height: "26px",
      objectFit: "contain",
      filter: "drop-shadow(0 2px 3px rgba(0,0,0,0.45))",
      pointerEvents: "none",
    });
    parent.appendChild(uvBadge);
  }

  uvBadge.src = normalizeIconUrl(uvIconUrl);
}

function setWeatherConditionText(el, condition) {
  const cleanCondition = String(condition || "").trim();
  el.title = cleanCondition;
  el.innerHTML = `<span class="weather-condition__inner">${escapeHtml(cleanCondition)}</span>`;
  scheduleWeatherConditionScrollRefresh();
}

function scheduleWeatherConditionScrollRefresh() {
  requestAnimationFrame(() => {
    updateWeatherConditionScrollFlag();
    setTimeout(updateWeatherConditionScrollFlag, 80);
    setTimeout(updateWeatherConditionScrollFlag, 250);
  });
}

function updateWeatherConditionScrollFlag() {
  const cond = $(SELECTORS.weatherCond);
  if (!cond) return;

  const inner = cond.querySelector(".weather-condition__inner");
  if (!inner) {
    cond.classList.remove("is-scroll-y");
    cond.style.removeProperty("--weather-cond-scroll-distance");
    cond.style.removeProperty("--weather-cond-scroll-duration");
    return;
  }

  const boxHeight = Math.floor(cond.getBoundingClientRect().height || cond.clientHeight || 0);
  const textHeight = Math.ceil(inner.scrollHeight || inner.getBoundingClientRect().height || 0);
  const distance = Math.max(0, textHeight - boxHeight);
  const shouldScroll = boxHeight > 0 && distance > 2;

  cond.classList.toggle("is-scroll-y", shouldScroll);
  cond.style.setProperty("--weather-cond-scroll-distance", `${distance}px`);

  const duration = Math.max(5.5, Math.min(11, 4.5 + distance / 12));
  cond.style.setProperty("--weather-cond-scroll-duration", `${duration.toFixed(1)}s`);
}

function scheduleConditionScrollRefresh() {
  requestAnimationFrame(() => {
    updateConditionScrollFlags();
    setTimeout(updateConditionScrollFlags, 80);
    setTimeout(updateConditionScrollFlags, 250);
  });
}

function updateConditionScrollFlags() {
  document.querySelectorAll("#forecast-5h-big .cond, #forecast-5d-big .cond").forEach((cond) => {
    const inner = cond.querySelector(".cond-inner");
    if (!inner) return;

    const boxWidth = Math.floor(cond.getBoundingClientRect().width || cond.clientWidth || 0);
    const textWidth = Math.ceil(inner.scrollWidth || inner.getBoundingClientRect().width || 0);
    const distance = Math.max(0, textWidth - boxWidth);
    const shouldScroll = boxWidth > 0 && distance > 2;

    cond.classList.toggle("is-scroll", shouldScroll);
    cond.style.setProperty("--cond-scroll-distance", `${distance}px`);

    const duration = Math.max(6, Math.min(13, 5 + distance / 24));
    cond.style.setProperty("--cond-scroll-duration", `${duration.toFixed(1)}s`);
  });
}

function normalizeIconUrl(icon) {
  const value = String(icon || PATHS.WEATHER_OFFLINE_ICON);
  return value.startsWith("//") ? `https:${value}` : value;
}

function formatTemp(value) {
  const raw = String(value ?? "--").trim();
  if (!raw || raw === "undefined" || raw === "null") return "--°";
  return raw
    .replace(/\s+/g, "")
    .replace("°C", "°")
    .replace("C", "°")
    .replace("°°", "°");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}
