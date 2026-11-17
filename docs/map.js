(function (global) {
  "use strict";

  const places = [
    ["Manchester", 53.4808, -2.2426],
    ["Salford", 53.4875, -2.2901],
    ["Stockport", 53.4106, -2.1575],
    ["Bolton", 53.5785, -2.4299],
    ["Oldham", 53.5409, -2.1114],
    ["Rochdale", 53.6159, -2.1558],
    ["Bury", 53.5933, -2.2966],
    ["Wigan", 53.5451, -2.6325],
    ["Warrington", 53.3900, -2.5969],
    ["Liverpool", 53.4084, -2.9916],
    ["Chester", 53.1934, -2.8931],
    ["Preston", 53.7632, -2.7031],
    ["Blackpool", 53.8175, -3.0357],
    ["Blackburn", 53.7486, -2.4875],
    ["Lancaster", 54.0470, -2.8010],
    ["Leeds", 53.8008, -1.5491],
    ["Sheffield", 53.3811, -1.4701],
    ["Bradford", 53.7960, -1.7594],
    ["Birmingham", 52.4862, -1.8904],
    ["London", 51.5072, -0.1276],
    ["Bristol", 51.4545, -2.5879],
    ["Cardiff", 51.4816, -3.1791],
    ["Edinburgh", 55.9533, -3.1883],
    ["Glasgow", 55.8642, -4.2518],
    ["Newcastle", 54.9783, -1.6178],
    ["Nottingham", 52.9548, -1.1581],
    ["Oxford", 51.7520, -1.2577],
    ["Cambridge", 52.2053, 0.1218],
  ];

  const manchesterAreas = [
    ["Rusholme", 53.4519, -2.2078],
    ["Collyhurst", 53.4961, -2.2211],
    ["Trafford Park", 53.4688, -2.3119],
    ["Manchester Science Park", 53.4641, -2.2363],
  ];

  function findPlace(item) {
    if (item.remote || typeof item.location !== "string") return null;
    const location = item.location.toLowerCase().trim();
    const area = manchesterAreas.find(([name]) =>
      new RegExp(`^${name.toLowerCase()}(?:\\s*,\\s*manchester)?(?:\\s*,\\s*greater manchester)?$`).test(location)
    );
    if (area) return area;
    if (manchesterAreas.some(([name]) =>
      new RegExp(`(^|[^a-z])${name.toLowerCase()}([^a-z]|$)`).test(location)
    )) return null;
    const cityLocation = location.replace(/\bgreater manchester\b/g, "");
    const matches = places.filter(([name]) =>
      new RegExp(`(^|[^a-z])${name.toLowerCase()}([^a-z]|$)`).test(cityLocation)
    );
    return matches.length === 1 ? matches[0] : null;
  }

  function groupItems(items) {
    const groups = new Map();
    items.forEach((item, index) => {
      const place = findPlace(item);
      if (!place) return;
      if (!groups.has(place[0])) groups.set(place[0], { place, items: [] });
      groups.get(place[0]).items.push({ item, index });
    });
    return Array.from(groups.values());
  }

  function setup(details, mapElement, status) {
    let map;
    let markers;
    let latest = [];
    let loading = false;

    function render() {
      if (!map || !details.open) return;
      map.closePopup();
      markers.clearLayers();
      const groups = groupItems(latest);
      let mapped = 0;
      groups.forEach(({ place, items }) => {
        mapped += items.length;
        const popup = document.createElement("div");
        const heading = document.createElement("strong");
        heading.textContent = `${place[0]} area`;
        popup.appendChild(heading);
        const list = document.createElement("ul");
        items.forEach(({ item, index }) => {
          const entry = document.createElement("li");
          const link = document.createElement("a");
          link.href = `#listing-${index}`;
          link.textContent = `View listing: ${item.title}`;
          entry.appendChild(link);
          list.appendChild(entry);
        });
        popup.appendChild(list);
        const icon = global.L.divIcon({
          className: "map-marker",
          html: `<span aria-hidden="true">${items.length}</span>`,
          iconSize: [36, 36],
          iconAnchor: [18, 18],
        });
        global.L.marker([place[1], place[2]], {
          icon,
          title: `${place[0]}: ${items.length} listings`,
          alt: `${place[0]}: ${items.length} listings`,
        }).bindPopup(popup).addTo(markers);
      });
      status.textContent = `${mapped} of ${latest.length} listings shown on the map. Remote and unrecognised locations remain in the list.`;
      map.invalidateSize();
    }

    details.addEventListener("toggle", () => {
      if (!details.open) return;
      if (map) {
        render();
        return;
      }
      if (loading) return;
      loading = true;
      status.textContent = "Loading the map.";
      const css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
      css.integrity = "sha384-sHL9NAb7lN7rfvG5lfHpm643Xkcjzp4jFvuavGOndn6pjVqS6ny56CAt3nsEVT4H";
      css.crossOrigin = "anonymous";
      const script = document.createElement("script");
      script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
      script.integrity = "sha384-cxOPjt7s7Iz04uaHJceBmS+qpjv2JkIHNVcuOrM+YHwZOmJGBXI00mdUXEq65HTH";
      script.crossOrigin = "anonymous";
      const loadResource = (element) => new Promise((resolve, reject) => {
        element.onload = resolve;
        element.onerror = reject;
        document.head.appendChild(element);
      });
      Promise.all([loadResource(css), loadResource(script)]).then(() => {
        loading = false;
        map = global.L.map(mapElement, { scrollWheelZoom: true, touchZoom: true }).setView([54.5, -3.5], 5);
        global.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
          maxZoom: 19,
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        }).on("tileerror", () => {
          status.textContent = "Some map tiles could not be loaded. The listings remain available below.";
        }).addTo(map);
        markers = global.L.layerGroup().addTo(map);
        render();
      }).catch(() => {
        loading = false;
        css.remove();
        script.remove();
        status.textContent = "The map could not be loaded. Close and reopen it to retry. The listings remain available below.";
      });
    });

    return (items) => {
      latest = items;
      render();
    };
  }

  const api = { findPlace, groupItems, setup };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else global.OpportunityMap = api;
})(typeof window === "undefined" ? globalThis : window);
