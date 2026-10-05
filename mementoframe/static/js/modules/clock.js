/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 *
 * This work is licensed under the Creative Commons Attribution-NonCommercial
 * 4.0 International License. To view a copy of this license, visit:
 * http://creativecommons.org/licenses/by-nc/4.0/
 */

/**
 * @file clock.js
 * @description Clock display and calendar generation module.
 *
 * Handles all time-related rendering on the display:
 *   - One or two analogue/digital clocks in configurable timezones
 *   - A date strip showing day, month, and year in the primary timezone
 *   - A mini monthly calendar that auto-refreshes when the date changes
 *
 * Layout behaviour:
 *   - Single-clock mode: date box sits in the first row; the clock box
 *     spans the full width with no border.
 *   - Dual-clock mode: date box moves to the second row; each clock gets
 *     50% width; a day-offset suffix (+1d / -1d) is shown on clock 2
 *     when it is in a different calendar day from clock 1.
 *
 * Clock state is read from `state.clocks` (populated by config.js).
 * DOM selectors are sourced from `constants.js`.
 */

import { state } from "../state.js";
import { SELECTORS, INTERVALS } from "../constants.js";
import { $, setText } from "../utils.js";

/**
 * Initialise both clocks and the calendar.
 *
 * Runs an immediate update then schedules `updateClock` at the interval
 * defined by `INTERVALS.CLOCK`. Also triggers `generateCalendar` once on
 * startup so the calendar is populated before the first tick fires.
 */
export function initClocks() {
  updateClock();
  setInterval(updateClock, INTERVALS.CLOCK);
  generateCalendar();
}

/**
 * Format a Date object using the configured 12- or 24-hour clock.
 *
 * The locale and hour cycle are explicit so the result is stable across
 * browser/device locale settings.
 *
 * @param {Date}   date - The UTC date to format.
 * @param {string} tz   - IANA timezone string (e.g. "Europe/Lisbon").
 * @returns {{time: string, period: string}} Digits and optional AM/PM suffix.
 */
function fmtTime(date, tz) {
  const use12Hour = state.clocks.format === "12h";
  const parts = new Intl.DateTimeFormat(use12Hour ? "en-US" : "en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: use12Hour ? "h12" : "h23",
    timeZone: tz,
  }).formatToParts(date);

  const hour = parts.find(part => part.type === "hour")?.value || "00";
  const minute = parts.find(part => part.type === "minute")?.value || "00";
  const period = use12Hour
    ? (parts.find(part => part.type === "dayPeriod")?.value || "").toUpperCase()
    : "";
  return { time: `${hour}:${minute}`, period };
}

/** Render stable character slots and animate only the digits that change. */
function setAnimatedTime(el, formatted) {
  if (!el) return;
  const { time, period } = formatted;
  if (el.dataset.clockTime === time && el.dataset.clockPeriod === period) return;

  const previous = el.dataset.clockTime;
  el.dataset.clockTime = time;
  el.dataset.clockPeriod = period;
  el.setAttribute("aria-label", period ? `${time} ${period}` : time);

  const slots = el.querySelectorAll(":scope > .clock-character");
  if (!previous || slots.length !== time.length) {
    const characters = [...time].map((character) => {
      const slot = document.createElement("span");
      slot.className = character === ":"
        ? "clock-character clock-separator"
        : "clock-character clock-digit";
      slot.setAttribute("aria-hidden", "true");
      slot.textContent = character;
      return slot;
    });
    if (period) {
      const suffix = document.createElement("span");
      suffix.className = "clock-period";
      suffix.setAttribute("aria-hidden", "true");
      suffix.textContent = period;
      characters.push(suffix);
    }
    el.replaceChildren(...characters);
    return;
  }

  let suffix = el.querySelector(":scope > .clock-period");
  if (period && !suffix) {
    suffix = document.createElement("span");
    suffix.className = "clock-period";
    suffix.setAttribute("aria-hidden", "true");
    el.appendChild(suffix);
  }
  if (suffix) {
    suffix.textContent = period;
    suffix.hidden = !period;
  }

  [...time].forEach((character, index) => {
    if (character === previous[index]) return;
    const slot = slots[index];
    if (!slot) return;

    const outgoing = document.createElement("span");
    outgoing.className = "clock-digit-value clock-digit-value--outgoing";
    outgoing.textContent = previous[index];
    const incoming = document.createElement("span");
    incoming.className = "clock-digit-value clock-digit-value--incoming";
    incoming.textContent = character;
    slot.replaceChildren(outgoing, incoming);
    incoming.addEventListener("animationend", () => slot.replaceChildren(character), { once: true });
  });
}

/**
 * Update all clock and date elements in the DOM.
 *
 * Called every `INTERVALS.CLOCK` milliseconds. On each tick:
 *   1. Reads the current UTC time.
 *   2. Updates clock 1 time and region label.
 *   3. Checks if the calendar date has changed in clock 1's timezone;
 *      if so, regenerates the calendar.
 *   4. In dual-clock mode: updates clock 2 time, region label, and
 *      appends a day-offset suffix if the two clocks are on different
 *      calendar days.
 *   5. Updates the date strip (day number, month, and year).
 *   6. Adjusts layout classes and the position of the date box to match
 *      single- or dual-clock configuration.
 *
 * All DOM reads use the `$` helper with selectors from `SELECTORS`.
 */
export function updateClock() {
  const nowUtc = new Date();

  const dualBox   = $(SELECTORS.dualBox);
  const clock1Box = $(SELECTORS.clock1Box);
  const clock2Box = $(SELECTORS.clock2Box);
  const dateBox   = $(SELECTORS.dateBox);
  const firstRow  = $(SELECTORS.firstRow);
  const secondRow = $(SELECTORS.secondRow);
  const weatherBox = $(SELECTORS.weatherBox);

  const clock1El  = $(SELECTORS.clock1);
  const clock2El  = $(SELECTORS.clock2);
  const region1El = clock1Box?.querySelector(".region");
  const region2El = clock2Box?.querySelector(".region");

  dualBox?.classList.toggle("twelve-hour", state.clocks.format === "12h");

  // --- Clock 1 ---
  setAnimatedTime(clock1El, fmtTime(nowUtc, state.clocks.clock1Tz));
  if (region1El) setText(region1El, state.clocks.clock1Label);

  // Detect date change in clock 1's timezone and regenerate calendar
  const clock1Now = new Date(nowUtc.toLocaleString("en-US", { timeZone: state.clocks.clock1Tz }));
  const dateKey   = clock1Now.toISOString().split("T")[0];
  if (dateKey !== state.clocks.lastCalendarDate) {
    state.clocks.lastCalendarDate = dateKey;
    generateCalendar();
  }

  // --- Clock 2 (dual-clock mode) ---
  if (state.clocks.enableSecond) {
    if (clock2Box) clock2Box.style.display = "flex";
    clock1Box?.classList.remove("no-border");
    dualBox?.classList.remove("single-clock");
    const calendarVisible = state.panels.calendarView !== "hidden";
    weatherBox?.classList.toggle("single-clock-weather", calendarVisible);
    dateBox?.classList.toggle("dual-calendar-hidden", calendarVisible);
    if (clock1Box) clock1Box.style.width = "50%";

    // Move date box to second row so both clocks sit in the first row
    if (dateBox && secondRow && !secondRow.contains(dateBox)) secondRow.appendChild(dateBox);

    setAnimatedTime(clock2El, fmtTime(nowUtc, state.clocks.clock2Tz));

    // Calculate day difference between the two timezones
    const date1 = new Date(nowUtc.toLocaleString("en-US", { timeZone: state.clocks.clock1Tz }));
    const date2 = new Date(nowUtc.toLocaleString("en-US", { timeZone: state.clocks.clock2Tz }));
    const dayDiff = date2.getDate() - date1.getDate();
    const suffix  = dayDiff === 1 ? " (+1d)" : dayDiff === -1 ? " (-1d)" : "";
    if (region2El) setText(region2El, state.clocks.clock2Label + suffix);

  } else {
    // Single-clock mode: hide clock 2, restore full-width layout
    if (clock2Box) clock2Box.style.display = "none";
    dualBox?.classList.add("single-clock");
    weatherBox?.classList.add("single-clock-weather");
    dateBox?.classList.remove("dual-calendar-hidden");
    clock1Box?.classList.add("no-border");

    // Return date box to the first row
    if (dateBox && firstRow && !firstRow.contains(dateBox)) firstRow.appendChild(dateBox);
  }

  // --- Date strip (always in clock 1's timezone) ---
  const parts = new Intl.DateTimeFormat([], {
    day: "2-digit", month: "short", year: "numeric",
    timeZone: state.clocks.clock1Tz,
  }).formatToParts(nowUtc);

  setText($(SELECTORS.day),       parts.find(p => p.type === "day").value);
  setText($(SELECTORS.monthYear), `${parts.find(p => p.type === "month").value} ${parts.find(p => p.type === "year").value}`);
}

/**
 * Render a mini monthly calendar into the calendar DOM element.
 *
 * Builds an HTML `<table>` for the current month in clock 1's timezone.
 * The week starts on Monday (ISO week). Today's date cell receives the
 * CSS class "today" for highlight styling.
 *
 * Called once by `initClocks` and again automatically whenever
 * `updateClock` detects that the date has rolled over.
 */
export function generateCalendar() {
  const monthEl = document.getElementById('calendar-month');
  const weekEl = document.getElementById('calendar-week');
  
  const now = new Date(new Date().toLocaleString("en-US", { timeZone: state.clocks.clock1Tz }));
  const today = now.getDate();
  const month = now.getMonth();
  const year = now.getFullYear();
  const monthNames = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

  // 1. GENERATE MONTH VIEW
  if (monthEl) {
    const firstDayObj = new Date(new Date(year, month, 1).toLocaleString("en-US", { timeZone: state.clocks.clock1Tz }));
    const firstDay = (firstDayObj.getDay() + 6) % 7;
    const lastDate = new Date(year, month + 1, 0).getDate();

    const blanks = Array.from({ length: firstDay }, () => "<td></td>").join("");
    const cells = Array.from({ length: lastDate }, (_, i) => {
      const day = i + 1;
      const isToday = day === today ? "today" : "";
      const dayOfWeek = (firstDay + i) % 7;
      const isWeekend = dayOfWeek >= 5 ? "weekend" : "";
      return `<td class="${[isToday, isWeekend].filter(Boolean).join(" ")}">${day}</td>`;
    }).join("");

    const all = blanks + cells;
    const rows = all.match(/(?:<td.*?<\/td>){1,7}/g)?.join("</tr><tr>") || "";

    monthEl.innerHTML = `<table>
      <thead>
        <tr><th class="calendar-title" colspan="7">${monthNames[month]} ${year}</th></tr>
        <tr class="calendar-weekdays">
          <th>Mon</th><th>Tue</th><th>Wed</th>
          <th>Thu</th><th>Fri</th><th>Sat</th><th>Sun</th>
        </tr>
      </thead>
      <tbody><tr>${rows}</tr></tbody>
    </table>`;
  }

  // 2. GENERATE WEEK VIEW
  if (weekEl) {
    const currentDayOfWeek = (now.getDay() + 6) % 7; // Monday = 0
    const weekStart = new Date(now);
    weekStart.setDate(today - currentDayOfWeek);

    let weekCells = "";
    const days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
    
    for (let i = 0; i < 7; i++) {
        const d = new Date(weekStart);
        d.setDate(weekStart.getDate() + i);
        const isToday = d.getDate() === today && d.getMonth() === month ? "today" : "";
        const isWeekend = i >= 5 ? "weekend" : "";
        weekCells += `
          <td class="${[isToday, isWeekend].filter(Boolean).join(" ")}">
            <div class="wk-day">${days[i]}</div>
            <div class="wk-date">${d.getDate()}</div>
          </td>`;
    }

    weekEl.innerHTML = `<table><tbody><tr>${weekCells}</tr></tbody></table>`;
  }
}
