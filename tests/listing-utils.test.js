"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const u = require("../docs/listing-utils.js");
const now = new Date("2026-11-17T12:00:00Z");

test("keeps closing dates inclusive and marks unknown dates honestly", () => {
  assert.equal(u.isExpired({ closing_date: "2026-11-16" }, "jobs", now), true);
  assert.equal(u.isExpired({ closing_date: "2026-11-17" }, "jobs", now), false);
  assert.equal(u.isExpired({ closing_date: "invalid" }, "jobs", now), false);
  assert.equal(u.closingSoon({ closing_date: "2026-11-24" }, now), true);
  assert.equal(u.closingSoon({ closing_date: "2026-11-25" }, now), false);
});

test("uses event end when known and never treats posting dates as event dates", () => {
  assert.equal(u.isExpired({ event_start: "2026-11-15", event_end: "2026-11-18" }, "events", now), false);
  assert.equal(u.isExpired({ event_start: "2026-11-15" }, "events", now), true);
  assert.equal(u.isExpired({ posted_date: "2026-01-01" }, "events", now), false);
});

test("new this week changes with time and regional matches use location only", () => {
  assert.equal(u.isNew({ first_seen: "2026-11-11T12:00:00Z" }, now), true);
  assert.equal(u.isNew({ first_seen: "2026-11-10T12:00:00Z" }, now), false);
  assert.equal(u.northWest("Stockport, Greater Manchester"), true);
  assert.equal(u.northWest("London"), false);
});
