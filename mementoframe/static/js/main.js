import { PATHS, INTERVALS } from "./constants.js";
import { state } from "./state.js";
import { loadConfig, setupConfigWatcher } from "./modules/config.js";
import { initClocks } from "./modules/clock.js";
import { initPhotos, burstPhotos } from "./modules/photoslideshow.js";
import { initSpotify } from "./modules/spotify.js";
import { initWeather } from "./modules/weather.js";
import { initWiFi } from "./modules/wifi.js";
import { initLayout, swapPanels, scheduleBigModeCycle, setCalendarOpacity, enableBigMode, disableBigMode } from "./modules/layout.js";
import { initPower } from "./modules/power.js";
import { initQR } from "./modules/qr.js";
import { loadVersions, hideLoadingScreen, setLoadingStatus, delay } from "./modules/loading.js";
import { initUpdater } from "./modules/updater.js";

window.addEventListener("DOMContentLoaded", async () => {
  setCalendarOpacity(0.75);

  setLoadingStatus("Loading config");
  await loadConfig();

  setLoadingStatus("Loading versions");
  await loadVersions();

  setLoadingStatus("Starting modules");
  initClocks();
  
  initPhotos();
  
  initSpotify();
  initWeather();
  initWiFi();
  initPower();
  initQR();
  initUpdater();

  initLayout();

  scheduleBigModeCycle(); // <-- UPDATED
  setInterval(swapPanels, INTERVALS.SWAP_PANELS);
  setupConfigWatcher();

  await delay(2000);
  hideLoadingScreen();
});