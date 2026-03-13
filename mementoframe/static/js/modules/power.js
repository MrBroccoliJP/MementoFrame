import { state } from "../state.js";
import { PATHS, INTERVALS } from "../constants.js";

export function initPower() {
  // wake screen once on load
  fetch(PATHS.SCREEN_ON, { method: "POST" })
    .then(() => console.log("🖥️ Screen: forced ON at startup"))
    .catch(err => console.error("⚠️ Failed to wake screen:", err));
  setInterval(checkScreenSchedule, INTERVALS.HOURLY_CHECK);
}

export function checkScreenSchedule() {
  const ap = state.config?.auto_power;
  if (!ap || !ap.enabled) return;

  const tz = state.clocks.clock1Tz;
  const now = new Date(new Date().toLocaleString("en-US", { timeZone: tz }));

  const off = parseHM(ap.off_time);
  const on  = parseHM(ap.on_time);

  const offDate = new Date(now); offDate.setHours(off.h, off.m, 0, 0);
  const onDate  = new Date(now); onDate.setHours(on.h, on.m, 0, 0);

  let shouldOff = false;
  if (offDate < onDate) {
    shouldOff = now >= offDate && now < onDate;
  } else {
    shouldOff = now >= offDate || now < onDate;
  }

  fetch(shouldOff ? PATHS.SCREEN_OFF : PATHS.SCREEN_ON, { method: "POST" })
    .then(r => r.json()).then(d => console.log("🖥️ Screen:", d.status))
    .catch(err => console.error("⚠️ Screen update failed:", err));
}

function parseHM(str = "00:00") {
  const [h, m] = (str || "00:00").split(":").map(n => parseInt(n, 10) || 0);
  return { h, m };
}
