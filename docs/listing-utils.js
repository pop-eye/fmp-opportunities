(function (global) {
  "use strict";

  const ukDateFormatter = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/London",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });

  function ukToday(now = new Date()) {
    const parts = Object.fromEntries(ukDateFormatter.formatToParts(now).map((part) => [part.type, part.value]));
    return `${parts.year}-${parts.month}-${parts.day}`;
  }

  function datePart(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}(?:$|T|\s)/.test(value)) return null;
    const date = value.slice(0, 10);
    const parsed = new Date(`${date}T00:00:00Z`);
    return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === date ? date : null;
  }

  function daysFromToday(value, now = new Date()) {
    const date = datePart(value);
    if (!date) return null;
    return (Date.parse(`${date}T00:00:00Z`) - Date.parse(`${ukToday(now)}T00:00:00Z`)) / 86400000;
  }

  function isExpired(item, tool, now = new Date()) {
    const closing = daysFromToday(item.closing_date, now);
    if (closing !== null && closing < 0) return true;
    if (tool !== "events") return false;
    const end = daysFromToday(item.event_end, now);
    const start = daysFromToday(item.event_start, now);
    return end !== null ? end < 0 : start !== null && start < 0;
  }

  function isNew(item, now = new Date()) {
    const days = daysFromToday(item.first_seen, now);
    return days !== null && days <= 0 && days >= -6;
  }

  function closingSoon(item, now = new Date()) {
    const days = daysFromToday(item.closing_date, now);
    return days !== null && days >= 0 && days <= 7;
  }

  function northWest(location) {
    return /\b(manchester|salford|liverpool|merseyside|cheshire|lancashire|cumbria|north west|bolton|stockport|bury|rochdale|oldham|wigan|preston|blackpool|chester|warrington|blackburn|lancaster)\b/i.test(location || "");
  }

  const api = { ukToday, datePart, daysFromToday, isExpired, isNew, closingSoon, northWest };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else global.ListingUtils = api;
})(typeof window === "undefined" ? globalThis : window);
