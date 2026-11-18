"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const { monthDates, eventsOnDate } = require("../docs/calendar.js");
const { datePart } = require("../docs/listing-utils.js");

test("calendar dates start on Monday and handle leap years", () => {
  const dates = monthDates(2024, 1);
  assert.deepEqual(dates.slice(0, 5), [null, null, null, "2024-02-01", "2024-02-02"]);
  assert.equal(dates.at(-1), "2024-02-29");
  assert.equal(monthDates(2026, 11).at(-1), "2026-12-31");
});

test("calendar finds single and multi-day events without inventing dates", () => {
  const items = [
    { title: "Exhibition", event_start: "2026-12-30", event_end: "2027-01-02" },
    { title: "Talk", event_start: "2027-01-01T10:00:00Z" },
    { title: "Unknown", posted_date: "2027-01-01" },
    { title: "Invalid end", event_start: "2027-01-01", event_end: "2026-12-01" },
  ];
  assert.deepEqual(eventsOnDate(items, "2027-01-01", datePart).map((entry) => entry.index), [0, 1, 3]);
  assert.deepEqual(eventsOnDate(items, "2027-01-02", datePart).map((entry) => entry.index), [0]);
  assert.deepEqual(eventsOnDate(items, "2027-01-03", datePart), []);
});
