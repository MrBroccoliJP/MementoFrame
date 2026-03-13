import { INTERVALS } from "./constants.js";
import { state } from "./state.js";
import { loadConfig, setupConfigWatcher } from "./modules/config.js";
import { initClocks } from "./modules/clock.js";
import { initPhotos, burstPhotos } from "./modules/photoslideshow.js";
import { initSpotify } from "./modules/spotify.js";
import { initWeather } from "./modules/weather.js";
import { initWiFi } from "./modules/wifi.js";
import { swapPanels, checkHourlyCalendarDisplay, setCalendarOpacity } from "./modules/layout.js";
import { initPower } from "./modules/power.js";
import { initQR } from "./modules/qr.js";

window.addEventListener("DOMContentLoaded", async () => {
  // base opacity for calendar on load
  setCalendarOpacity(0.75);

  await loadConfig();

  // init features
  initClocks();
  initPhotos();
  initSpotify();
  initWeather();
  initWiFi();
  initPower();
  initQR();

  // behaviors
  setInterval(checkHourlyCalendarDisplay, INTERVALS.HOURLY_CHECK);
  setInterval(swapPanels, INTERVALS.SWAP_PANELS);

  setupConfigWatcher();
});

// === DEV HELPERS (for console debugging) ===
window.swapPanels = swapPanels;
window.burstPhotos = burstPhotos;
window.state = state;

console.log("🧩 Dev helpers available in console:");
console.log("- swapPanels()");
console.log("- burstPhotos()");
console.log("- state");
