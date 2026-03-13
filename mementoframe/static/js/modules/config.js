import { state } from "../state.js";
import { fetchJson } from "../utils.js";
import { PATHS } from "../constants.js";

export async function loadConfig() {
  const cfg = await fetchJson(PATHS.CONFIG, {});
  state.config = cfg || {};

  state.clocks.enableSecond = cfg?.clock2?.enabled ?? false;
  state.clocks.clock1Tz = cfg?.clock1?.timezone || "UTC";
  state.clocks.clock2Tz = cfg?.clock2?.timezone || "UTC";
  state.clocks.clock1Label = cfg?.clock1?.label || "Clock 1";
  state.clocks.clock2Label = cfg?.clock2?.label || "Clock 2";
}

export function setupConfigWatcher() {
  const es = new EventSource(PATHS.CONFIG_STREAM);
  es.onmessage = (e) => {
    if (e.data === "reload") {
      // small debounce if multiple changes happen quickly
      setTimeout(() => window.location.reload(), 500);
    }
  };
  es.onerror = () => {
    // try reconnecting after a pause
    setTimeout(setupConfigWatcher, 5000);
  };
}
