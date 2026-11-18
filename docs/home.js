(function () {
  "use strict";
  ["jobs", "placements", "apprenticeships", "events"].forEach((tool) => {
    const output = document.getElementById(`count-${tool}`);
    fetch(`${tool}.json`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        if (!Array.isArray(data.items)) throw new Error("Invalid listings data");
        if (data.last_updated === null) {
          output.textContent = "Feed not generated yet";
          return;
        }
        const current = data.items.filter((item) => !ListingUtils.isExpired(item, tool));
        const fresh = current.filter((item) => ListingUtils.isNew(item)).length;
        const closing = tool === "events" ? "" : `, ${current.filter((item) => ListingUtils.closingSoon(item)).length} closing soon`;
        output.textContent = `${current.length} opportunities, ${fresh} new${closing}`;
      })
      .catch((error) => {
        output.textContent = "Could not load opportunities";
        console.error(`Could not load ${tool}.`, error);
      });
  });
})();
