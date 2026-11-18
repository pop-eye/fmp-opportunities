(function () {
  "use strict";

  const root = document.querySelector("[data-tool]");
  if (!root) return;
  const tool = root.dataset.tool;
  const $ = (id) => document.getElementById(id);
  const controls = {
    search: $("filter-search"),
    discipline: $("filter-discipline"),
    location: $("filter-location"),
    remote: $("filter-remote"),
    northwest: $("filter-northwest"),
    type: $("filter-type"),
    paid: $("filter-paid"),
    dateRange: $("filter-date-range"),
    newOnly: $("filter-new"),
    closing: $("filter-closing"),
    saved: $("filter-saved"),
    sort: $("sort-order"),
  };
  const list = $("listings");
  const saveStatus = $("save-status");
  const storageKey = `fmp-saved-${tool}`;
  let saved = new Set();
  let storageAvailable = true;
  let allItems = [];
  let visibleItems = [];
  const mapDetails = $("map-details");
  const updateMap = mapDetails
    ? OpportunityMap.setup(mapDetails, $("map"), $("map-status"))
    : null;
  const updateCalendar = tool === "events" ? EventCalendar.setup() : null;

  try {
    const stored = JSON.parse(localStorage.getItem(storageKey) || "[]");
    if (!Array.isArray(stored) || stored.some((id) => typeof id !== "string")) {
      throw new Error("Invalid saved data");
    }
    saved = new Set(stored);
  } catch (error) {
    storageAvailable = false;
    saveStatus.textContent = "Saved opportunities are unavailable in this browser.";
    console.warn("Could not read saved opportunities.", error);
  }

  const view = new URLSearchParams(location.search).get("view");
  if (["new", "closing", "saved"].includes(view)) $("more-filters").open = true;
  if (view === "new") controls.newOnly.checked = true;
  if (view === "closing" && controls.closing) controls.closing.checked = true;
  if (view === "saved") controls.saved.checked = true;

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[char]);
  }

  function safeLink(value) {
    try {
      const url = new URL(value);
      return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
    } catch {
      return null;
    }
  }

  function formatDate(value, includeTime = false) {
    if (!ListingUtils.datePart(value)) return "Not stated";
    const hasTime = includeTime && /T\d{2}:\d{2}/.test(value);
    const date = new Date(hasTime ? value : `${value.slice(0, 10)}T12:00:00Z`);
    if (Number.isNaN(date.getTime())) return "Not stated";
    const options = { day: "numeric", month: "short", year: "numeric", timeZone: "Europe/London" };
    if (hasTime) {
      options.hour = "2-digit";
      options.minute = "2-digit";
    }
    return date.toLocaleString("en-GB", options);
  }

  function addOptions(select, values) {
    if (!select) return;
    [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b)).forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    });
  }

  function matchesRange(item, range) {
    if (!range || range === "all") return true;
    const start = ListingUtils.daysFromToday(item.event_start);
    const end = ListingUtils.daysFromToday(item.event_end);
    return start !== null && start <= Number(range) && (end !== null ? end >= 0 : start >= 0);
  }

  function sortItems(items) {
    const order = controls.sort.value;
    if (order === "recommended") return items;
    const field = order === "closing" ? "closing_date" : order === "event" ? "event_start" : "first_seen";
    return items.sort((a, b) => {
      const left = ListingUtils.datePart(a[field]);
      const right = ListingUtils.datePart(b[field]);
      if (!left) return right ? 1 : 0;
      if (!right) return -1;
      return order === "newest" ? right.localeCompare(left) : left.localeCompare(right);
    });
  }

  function render() {
    const query = controls.search.value.trim().toLowerCase();
    const current = allItems.filter((item) => !ListingUtils.isExpired(item, tool));
    visibleItems = sortItems(current.filter((item) => {
      const haystack = [item.title, item.organisation, item.location, item.summary, ...(item.category_tags || [])].join(" ").toLowerCase();
      if (query && !haystack.includes(query)) return false;
      if (controls.discipline.value && !(item.category_tags || []).includes(controls.discipline.value)) return false;
      if (controls.location.value && item.location !== controls.location.value) return false;
      if (controls.remote.checked && !item.remote) return false;
      if (controls.northwest.checked && !ListingUtils.northWest(item.location)) return false;
      if (controls.type && controls.type.value && item.type !== controls.type.value) return false;
      if (controls.paid && controls.paid.value && (item.paid || "not stated") !== controls.paid.value) return false;
      if (controls.dateRange && !matchesRange(item, controls.dateRange.value)) return false;
      if (controls.newOnly.checked && !ListingUtils.isNew(item)) return false;
      if (controls.closing && controls.closing.checked && !ListingUtils.closingSoon(item)) return false;
      if (controls.saved.checked && !saved.has(item.unique_id)) return false;
      return true;
    }));

    $("status-bar").textContent = `Showing ${visibleItems.length} of ${current.length} current listings.`;
    if (updateMap) updateMap(visibleItems);
    if (updateCalendar) updateCalendar(visibleItems);
    if (!visibleItems.length) {
      list.innerHTML = '<li class="empty-state">No matching opportunities. Try clearing the filters or check again later.</li>';
      return;
    }
    list.innerHTML = visibleItems.map((item, index) => {
      const link = safeLink(item.source_url);
      const badges = [
        ListingUtils.isNew(item) ? '<span class="badge badge-new">New this week</span>' : "",
        ListingUtils.closingSoon(item) ? '<span class="badge badge-soon">Closing soon</span>' : "",
        item.remote ? '<span class="badge badge-remote">Remote or online</span>' : "",
      ].join("");
      const details = [
        ["Organisation", item.organisation || "Not stated"],
        ["Location", item.location || "Not stated"],
      ];
      if (tool === "events") {
        details.push(["Date", formatDate(item.event_start, true)]);
        details.push(["Cost", item.cost || "Not stated"]);
      } else {
        details.push(["Closing date", formatDate(item.closing_date)]);
        if (tool === "placements") {
          details.push(["Placement type", item.type || "Not stated"]);
          details.push(["Pay", item.paid || "Not stated"]);
        }
      }
      if (item.source_name) details.push(["Source", item.source_name]);
      if (item.category_tags && item.category_tags.length) details.push(["Disciplines", item.category_tags.join(", ")]);
      const meta = details.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
      const isSaved = saved.has(item.unique_id);
      const button = item.unique_id && storageAvailable
        ? `<button type="button" class="button button-secondary save-button" data-index="${index}" aria-pressed="${isSaved}">${isSaved ? "Saved" : "Save"}</button>`
        : "";
      return `<li id="listing-${index}" tabindex="-1" class="card${ListingUtils.closingSoon(item) ? " closing-soon" : ""}">
        <div class="card-header"><h2 class="card-title">${escapeHtml(item.title)}</h2><div class="badges">${badges}</div></div>
        <dl class="card-details">${meta}</dl>
        ${item.summary ? `<p class="card-summary">${escapeHtml(item.summary)}</p>` : ""}
        <div class="card-actions">
          ${link ? `<a class="button button-primary" href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer">View opportunity <span class="visually-hidden">(opens in a new tab)</span></a>` : '<span>Original link not available</span>'}
          ${button}
        </div>
      </li>`;
    }).join("");
  }

  Object.values(controls).filter(Boolean).forEach((control) => {
    control.addEventListener("input", render);
    control.addEventListener("change", render);
  });
  $("reset-filters").addEventListener("click", () => {
    Object.values(controls).filter(Boolean).forEach((control) => {
      if (control.type === "checkbox") control.checked = false;
      else if (control.tagName === "SELECT") control.selectedIndex = 0;
      else control.value = "";
    });
    render();
  });
  list.addEventListener("click", (event) => {
    const button = event.target.closest(".save-button");
    if (!button) return;
    const item = visibleItems[Number(button.dataset.index)];
    if (!item || !item.unique_id) return;
    const next = new Set(saved);
    if (next.has(item.unique_id)) next.delete(item.unique_id);
    else next.add(item.unique_id);
    try {
      localStorage.setItem(storageKey, JSON.stringify([...next]));
      saved = next;
      saveStatus.textContent = next.has(item.unique_id) ? "Opportunity saved on this device." : "Opportunity removed from saved items.";
      render();
      const replacement = [...list.querySelectorAll(".save-button")].find((candidate) =>
        visibleItems[Number(candidate.dataset.index)]?.unique_id === item.unique_id
      );
      if (replacement) replacement.focus();
      else controls.saved.focus();
    } catch (error) {
      saveStatus.textContent = "Could not save this opportunity on this device.";
      console.warn("Could not save opportunity.", error);
    }
  });

  fetch(root.dataset.json || `${tool}.json`)
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then((data) => {
      if (!Array.isArray(data.items)) throw new Error("Invalid listings data");
      allItems = data.items;
      $("last-updated").textContent = `Last updated: ${formatDate(data.last_updated, true)}`;
      addOptions(controls.discipline, allItems.flatMap((item) => item.category_tags || []));
      addOptions(controls.location, allItems.map((item) => item.location));
      render();
    })
    .catch((error) => {
      $("status-bar").textContent = "Could not load opportunities. Please try again later.";
      console.error("Could not load listings.", error);
    });
})();
