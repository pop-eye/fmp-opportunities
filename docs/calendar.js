(function (global) {
  "use strict";

  function monthDates(year, month) {
    const first = new Date(Date.UTC(year, month, 1));
    const offset = (first.getUTCDay() + 6) % 7;
    const days = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
    return Array(offset).fill(null).concat(
      Array.from({ length: days }, (_, index) =>
        new Date(Date.UTC(year, month, index + 1)).toISOString().slice(0, 10)
      )
    );
  }

  function eventsOnDate(items, date, datePart) {
    return items.flatMap((item, index) => {
      const start = datePart(item.event_start);
      const end = datePart(item.event_end);
      return start && start <= date && date <= (end && end >= start ? end : start)
        ? [{ item, index }]
        : [];
    });
  }

  function setup() {
    const $ = (id) => document.getElementById(id);
    const today = ListingUtils.ukToday();
    let year = Number(today.slice(0, 4));
    let month = Number(today.slice(5, 7)) - 1;
    let selected = null;
    let items = [];
    const monthHeading = $("calendar-month");
    const days = $("calendar-days");
    const selection = $("calendar-selection");
    const fullDate = new Intl.DateTimeFormat("en-GB", {
      weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
    });

    function render() {
      monthHeading.textContent = new Intl.DateTimeFormat("en-GB", {
        month: "long", year: "numeric", timeZone: "UTC",
      }).format(new Date(Date.UTC(year, month, 1)));
      days.replaceChildren();
      const dates = monthDates(year, month);
      for (let week = 0; week < Math.ceil(dates.length / 7); week++) {
        const row = document.createElement("tr");
        for (let day = 0; day < 7; day++) {
          const date = dates[week * 7 + day];
          const cell = document.createElement("td");
          if (date) {
            const matching = eventsOnDate(items, date, ListingUtils.datePart);
            const button = document.createElement("button");
            button.type = "button";
            button.className = `calendar-day${matching.length ? " has-events" : ""}`;
            button.disabled = !matching.length;
            button.setAttribute("aria-label", `${fullDate.format(new Date(`${date}T12:00:00Z`))}: ${matching.length} ${matching.length === 1 ? "event" : "events"}`);
            if (matching.length) button.setAttribute("aria-pressed", String(selected === date));
            button.textContent = String(Number(date.slice(8)));
            if (matching.length) {
              const count = document.createElement("span");
              count.className = "calendar-count";
              count.setAttribute("aria-hidden", "true");
              count.textContent = String(matching.length);
              button.appendChild(count);
              button.addEventListener("click", () => {
                selected = date;
                render();
                days.querySelector(`[data-date="${date}"]`).focus();
              });
              button.dataset.date = date;
            }
            cell.appendChild(button);
          }
          row.appendChild(cell);
        }
        days.appendChild(row);
      }

      selection.replaceChildren();
      if (!selected) {
        selection.textContent = "Choose a highlighted date to see events.";
        return;
      }
      const matching = eventsOnDate(items, selected, ListingUtils.datePart);
      const heading = document.createElement("strong");
      heading.textContent = `${fullDate.format(new Date(`${selected}T12:00:00Z`))}: ${matching.length} ${matching.length === 1 ? "event" : "events"}`;
      selection.appendChild(heading);
      const list = document.createElement("ul");
      matching.forEach(({ item, index }) => {
        const entry = document.createElement("li");
        const link = document.createElement("a");
        link.href = `#listing-${index}`;
        link.textContent = item.title;
        link.addEventListener("click", (event) => {
          const target = document.getElementById(`listing-${index}`);
          if (!target) return;
          event.preventDefault();
          target.scrollIntoView();
          target.focus({ preventScroll: true });
        });
        entry.appendChild(link);
        list.appendChild(entry);
      });
      if (matching.length) selection.appendChild(list);
    }

    function changeMonth(delta) {
      const next = new Date(Date.UTC(year, month + delta, 1));
      year = next.getUTCFullYear();
      month = next.getUTCMonth();
      selected = null;
      render();
    }
    $("calendar-previous").addEventListener("click", () => changeMonth(-1));
    $("calendar-next").addEventListener("click", () => changeMonth(1));
    render();
    return (visibleItems) => {
      items = visibleItems;
      render();
    };
  }

  const api = { monthDates, eventsOnDate, setup };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else global.EventCalendar = api;
})(typeof window === "undefined" ? globalThis : window);
