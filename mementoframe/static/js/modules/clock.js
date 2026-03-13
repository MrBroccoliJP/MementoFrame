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
 * Format a Date object as "HH:MM" in a given IANA timezone.
 *
 * Uses `Intl.DateTimeFormat` with `hour12: false` so the output is always
 * 24-hour, locale-independent, and zero-padded.
 *
 * @param {Date}   date - The UTC date to format.
 * @param {string} tz   - IANA timezone string (e.g. "Europe/Lisbon").
 * @returns {string} Formatted time string, e.g. "14:05".
 */
function fmtTime(date, tz) {
  return new Intl.DateTimeFormat([], {
    hour: "2-digit", minute: "2-digit", hour12: false, timeZone: tz,
  }).format(date);
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

  const clock1El  = $(SELECTORS.clock1);
  const clock2El  = $(SELECTORS.clock2);
  const region1El = clock1Box?.querySelector(".region");
  const region2El = clock2Box?.querySelector(".region");

  // --- Clock 1 ---
  setText(clock1El, fmtTime(nowUtc, state.clocks.clock1Tz));
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
    if (clock1Box) clock1Box.style.width = "50%";

    // Move date box to second row so both clocks sit in the first row
    if (dateBox && secondRow && !secondRow.contains(dateBox)) secondRow.appendChild(dateBox);

    setText(clock2El, fmtTime(nowUtc, state.clocks.clock2Tz));

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
  const el = $(SELECTORS.calendarEl);
  if (!el) return;

  const now      = new Date(new Date().toLocaleString("en-US", { timeZone: state.clocks.clock1Tz }));
  const today    = now.getDate();
  const month    = now.getMonth();
  const year     = now.getFullYear();

  // Determine the weekday of the 1st (Monday = 0, Sunday = 6)
  const firstDayObj = new Date(new Date(year, month, 1).toLocaleString("en-US", { timeZone: state.clocks.clock1Tz }));
  const firstDay    = (firstDayObj.getDay() + 6) % 7;
  const lastDate    = new Date(year, month + 1, 0).getDate();

  const monthNames = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

  // Leading blank cells to align the 1st with the correct weekday column
  const blanks = Array.from({ length: firstDay }, () => "<td></td>").join("");

  // One <td> per day; today gets the "today" class
  const cells = Array.from({ length: lastDate }, (_, i) => {
    const day     = i + 1;
    const isToday = day === today ? "today" : "";
    return `<td class="${isToday}">${day}</td>`;
  }).join("");

  // Group cells into rows of 7
  const all  = blanks + cells;
  const rows = all.match(/(?:<td.*?<\/td>){1,7}/g)?.join("</tr><tr>") || "";

  el.innerHTML = `<table>
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