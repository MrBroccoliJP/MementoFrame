import { state } from "../state.js";
import { SELECTORS, INTERVALS } from "../constants.js";
import { $, setText } from "../utils.js";

export function initClocks() {
  updateClock();
  setInterval(updateClock, INTERVALS.CLOCK);
  generateCalendar(); // initial
}

function fmtTime(date, tz) {
  return new Intl.DateTimeFormat([], { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: tz }).format(date);
}

export function updateClock() {
  const nowUtc = new Date();

  const dualBox = $(SELECTORS.dualBox);
  const clock1Box = $(SELECTORS.clock1Box);
  const clock2Box = $(SELECTORS.clock2Box);
  const dateBox = $(SELECTORS.dateBox);
  const firstRow = $(SELECTORS.firstRow);
  const secondRow = $(SELECTORS.secondRow);

  const clock1El = $(SELECTORS.clock1);
  const clock2El = $(SELECTORS.clock2);
  const region1El = clock1Box?.querySelector(".region");
  const region2El = clock2Box?.querySelector(".region");

  // clock 1
  setText(clock1El, fmtTime(nowUtc, state.clocks.clock1Tz));
  if (region1El) setText(region1El, state.clocks.clock1Label);

  // calendar auto-refresh (date change in clock1 tz)
  const clock1Now = new Date(nowUtc.toLocaleString("en-US", { timeZone: state.clocks.clock1Tz }));
  const dateKey = clock1Now.toISOString().split("T")[0];
  if (dateKey !== state.clocks.lastCalendarDate) {
    state.clocks.lastCalendarDate = dateKey;
    generateCalendar();
  }

  // second clock
  if (state.clocks.enableSecond) {
    if (clock2Box) clock2Box.style.display = "flex";
    clock1Box?.classList.remove("no-border");
    dualBox?.classList.remove("single-clock");
    if (clock1Box) clock1Box.style.width = "50%";
    if (dateBox && secondRow && !secondRow.contains(dateBox)) secondRow.appendChild(dateBox);

    setText(clock2El, fmtTime(nowUtc, state.clocks.clock2Tz));

    const date1 = new Date(nowUtc.toLocaleString("en-US", { timeZone: state.clocks.clock1Tz }));
    const date2 = new Date(nowUtc.toLocaleString("en-US", { timeZone: state.clocks.clock2Tz }));
    const dayDiff = date2.getDate() - date1.getDate();
    const suffix = dayDiff === 1 ? " (+1d)" : dayDiff === -1 ? " (-1d)" : "";
    if (region2El) setText(region2El, state.clocks.clock2Label + suffix);
  } else {
    if (clock2Box) clock2Box.style.display = "none";
    dualBox?.classList.add("single-clock");
    clock1Box?.classList.add("no-border");
    if (dateBox && firstRow && !firstRow.contains(dateBox)) firstRow.appendChild(dateBox);
  }

  // date text (clock1 tz)
  const parts = new Intl.DateTimeFormat([], { day: "2-digit", month: "short", year: "numeric", timeZone: state.clocks.clock1Tz }).formatToParts(nowUtc);
  setText($(SELECTORS.day), parts.find(p => p.type === "day").value);
  setText($(SELECTORS.monthYear), `${parts.find(p => p.type === "month").value} ${parts.find(p => p.type === "year").value}`);
}

export function generateCalendar() {
  const el = $(SELECTORS.calendarEl);
  if (!el) return;

  const now = new Date(new Date().toLocaleString("en-US", { timeZone: state.clocks.clock1Tz }));
  const today = now.getDate(), month = now.getMonth(), year = now.getFullYear();

  const firstDayObj = new Date(new Date(year, month, 1).toLocaleString("en-US", { timeZone: state.clocks.clock1Tz }));
  const firstDay = (firstDayObj.getDay() + 6) % 7; // Monday=0
  const lastDate = new Date(year, month + 1, 0).getDate();
  const monthNames = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

  const blanks = Array.from({ length: firstDay }, () => "<td></td>").join("");
  const cells = Array.from({ length: lastDate }, (_, i) => {
    const day = i + 1;
    const isToday = day === today ? "today" : "";
    return `<td class="${isToday}">${day}</td>`;
  }).join("");

  // break rows each 7
  const all = blanks + cells;
  const rows = all.match(/(?:<td.*?<\/td>){1,7}/g)?.join("</tr><tr>") || "";

  el.innerHTML = `<table>
    <thead>
      <tr><th class="calendar-title" colspan="7">${monthNames[month]} ${year}</th></tr>
      <tr class="calendar-weekdays"><th>Mon</th><th>Tue</th><th>Wed</th><th>Thu</th><th>Fri</th><th>Sat</th><th>Sun</th></tr>
    </thead>
    <tbody><tr>${rows}</tr></tbody>
  </table>`;
}
