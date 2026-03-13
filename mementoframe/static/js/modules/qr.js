import { INTERVALS, SELECTORS } from "../constants.js";
import { $ } from "../utils.js";

export function initQR() {
  const container = $(SELECTORS.qrContainer);
  if (!container || typeof QRCode === "undefined") return;

  let lastIP = null;

  const generate = (text) => {
    container.innerHTML = "";
    new QRCode(container, {
      text, width: 70, height: 70, colorDark: "#000", colorLight: "#fff",
      correctLevel: QRCode.CorrectLevel.L,
    });
  };

  async function fetchIP() {
    try {
      const res = await fetch("/get_ip");
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      return data?.ip || null;
    } catch {
      return null;
    }
  }

  async function tick() {
    const ip = await fetchIP();
    if (ip && ip !== lastIP) {
      generate(`http://${ip}:5000`);
      lastIP = ip;
      console.log("🔄 QR updated:", ip);
    }
  }

  tick();
  setInterval(tick, INTERVALS.QR);
}
