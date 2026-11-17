(function () {
  "use strict";

  const root = document.querySelector("[data-tool]");
  if (!root) return;

  const tool = root.getAttribute("data-tool");
  const jsonUrl = root.getAttribute("data-json") || `${tool}.json`;

  const searchInput = document.getElementById("filter-search");
  const disciplineSelect = document.getElementById("filter-discipline");
  const locationSelect = document.getElementById("filter-location");
  const remoteCheckbox = document.getElementById("filter-remote");
  const typeSelect = document.getElementById("filter-type");
  const paidSelect = document.getElementById("filter-paid");
  const dateRangeSelect = document.getElementById("filter-date-range");
  const statusEl = document.getElementById("status-bar");
  const updatedEl = document.getElementById("last-updated");
  const listEl = document.getElementById("listings");

  let allItems = [];

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML;
  }

  function isClosingSoon(closingDate) {
    if (!closingDate) return false;
    const target = new Date(closingDate);
    if (Number.isNaN(target.getTime())) return false;
    const now = new Date();
    const diffDays = (target.getTime() - now.getTime()) / (1000 * 60 * 60 * 24);
    return diffDays >= -0.5 && diffDays <= 7;
  }

  function formatDate(isoStr) {
    if (!isoStr) return "";
    const dt = new Date(isoStr);
    if (Number.isNaN(dt.getTime())) return isoStr;
    return dt.toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  }

  function populateDisciplineOptions(items) {
    if (!disciplineSelect) return;
    const disciplines = Array.from(
      new Set(
        items.flatMap((item) =>
          Array.isArray(item.category_tags) ? item.category_tags : []
        )
      )
    ).sort((a, b) => a.localeCompare(b));

    disciplines.forEach((disc) => {
      const opt = document.createElement("option");
      opt.value = disc;
      opt.textContent = disc;
      disciplineSelect.appendChild(opt);
    });
  }

  function populateLocationOptions(items) {
    if (!locationSelect) return;
    const locations = Array.from(
      new Set(items.map((item) => (item.location || "").trim()).filter(Boolean))
    ).sort((a, b) => a.localeCompare(b));

    locations.forEach((loc) => {
      const opt = document.createElement("option");
      opt.value = loc;
      opt.textContent = loc;
      locationSelect.appendChild(opt);
    });
  }

  function matchesDateRange(item, rangeValue) {
    if (!rangeValue || rangeValue === "all") return true;
    const raw = item.event_start || item.posted_date;
    if (!raw) return false;
    const dt = new Date(raw);
    if (Number.isNaN(dt.getTime())) return false;
    const now = new Date();
    const diffDays = (dt.getTime() - now.getTime()) / (1000 * 60 * 60 * 24);
    if (rangeValue === "7") return diffDays >= -0.5 && diffDays <= 7;
    if (rangeValue === "30") return diffDays >= -0.5 && diffDays <= 30;
    return true;
  }

  function render() {
    const query = (searchInput ? searchInput.value : "").trim().toLowerCase();
    const selectedDiscipline = disciplineSelect ? disciplineSelect.value : "";
    const selectedLocation = locationSelect ? locationSelect.value : "";
    const remoteOnly = remoteCheckbox ? remoteCheckbox.checked : false;
    const selectedType = typeSelect ? typeSelect.value : "";
    const selectedPaid = paidSelect ? paidSelect.value : "";
    const selectedRange = dateRangeSelect ? dateRangeSelect.value : "all";

    const filtered = allItems.filter((item) => {
      if (query) {
        const hay = [
          item.title,
          item.organisation,
          item.location,
          item.summary,
          (item.category_tags || []).join(" "),
        ]
          .join(" ")
          .toLowerCase();
        if (!hay.includes(query)) return false;
      }
      if (
        selectedDiscipline &&
        !(Array.isArray(item.category_tags) && item.category_tags.includes(selectedDiscipline))
      ) {
        return false;
      }
      if (selectedLocation && (item.location || "") !== selectedLocation) {
        return false;
      }
      if (remoteOnly && !item.remote) {
        return false;
      }
      if (selectedType && (item.type || "") !== selectedType) {
        return false;
      }
      if (selectedPaid && (item.paid || "not stated") !== selectedPaid) {
        return false;
      }
      if (!matchesDateRange(item, selectedRange)) {
        return false;
      }
      return true;
    });

    if (statusEl) {
      statusEl.textContent = `Showing ${filtered.length} of ${allItems.length} listings.`;
    }

    if (!listEl) return;
    if (filtered.length === 0) {
      listEl.innerHTML =
        '<li class="empty-state">No matching opportunities found. Try clearing a filter.</li>';
      return;
    }

    listEl.innerHTML = filtered
      .map((item) => {
        const soon = isClosingSoon(item.closing_date);
        const badges = [];
        if (item.is_new) {
          badges.push('<span class="badge badge-new">New this week</span>');
        }
        if (soon) {
          badges.push('<span class="badge badge-soon">Closing soon</span>');
        }
        if (item.remote) {
          badges.push('<span class="badge badge-remote">Remote</span>');
        }

        const metaParts = [];
        if (item.organisation) {
          metaParts.push(`<span><strong>Organisation:</strong> ${escapeHtml(item.organisation)}</span>`);
        }
        if (item.location) {
          metaParts.push(`<span><strong>Location:</strong> ${escapeHtml(item.location)}</span>`);
        }
        if (item.type && tool === "placements") {
          metaParts.push(`<span><strong>Type:</strong> ${escapeHtml(item.type)}</span>`);
        }
        if (item.paid && tool === "placements") {
          metaParts.push(`<span><strong>Pay:</strong> ${escapeHtml(item.paid)}</span>`);
        }
        if (item.event_start) {
          metaParts.push(`<span><strong>When:</strong> ${escapeHtml(formatDate(item.event_start))}</span>`);
        }
        if (item.cost) {
          metaParts.push(`<span><strong>Cost:</strong> ${escapeHtml(item.cost)}</span>`);
        }
        if (item.closing_date) {
          metaParts.push(`<span><strong>Closes:</strong> ${escapeHtml(formatDate(item.closing_date))}</span>`);
        }
        if (item.source_name) {
          metaParts.push(`<span><strong>Source:</strong> ${escapeHtml(item.source_name)}</span>`);
        }
        if (Array.isArray(item.category_tags) && item.category_tags.length > 0) {
          metaParts.push(
            `<span><strong>Disciplines:</strong> ${escapeHtml(item.category_tags.join(", "))}</span>`
          );
        }

        return `
          <li class="card${soon ? " closing-soon" : ""}">
            <div class="card-header">
              <h2 class="card-title">
                <a href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener noreferrer">
                  ${escapeHtml(item.title)}
                </a>
              </h2>
              ${badges.length ? `<div class="badges">${badges.join("")}</div>` : ""}
            </div>
            <div class="card-meta">${metaParts.join("")}</div>
            ${item.summary ? `<p class="card-summary">${escapeHtml(item.summary)}</p>` : ""}
          </li>
        `;
      })
      .join("");
  }

  function bindEvents() {
    [
      searchInput,
      disciplineSelect,
      locationSelect,
      remoteCheckbox,
      typeSelect,
      paidSelect,
      dateRangeSelect,
    ].forEach(
      (el) => {
        if (!el) return;
        el.addEventListener("input", render);
        el.addEventListener("change", render);
      }
    );
  }

  fetch(jsonUrl)
    .then((resp) => {
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      return resp.json();
    })
    .then((data) => {
      allItems = Array.isArray(data.items) ? data.items : [];
      if (updatedEl && data.last_updated) {
        updatedEl.textContent = `Last updated: ${formatDate(data.last_updated)}`;
      }
      populateDisciplineOptions(allItems);
      populateLocationOptions(allItems);
      bindEvents();
      render();
    })
    .catch(() => {
      if (statusEl) {
        statusEl.textContent = "Could not load listings right now.";
      }
    });
})();
