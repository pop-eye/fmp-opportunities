"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const { findPlace, groupItems, setup } = require("../docs/map.js");

test("finds recognised city centres without guessing regions or remote locations", () => {
  assert.equal(findPlace({ location: "Manchester Science Park, Manchester" })[0], "Manchester Science Park");
  assert.equal(findPlace({ location: "Rusholme, Manchester" })[0], "Rusholme");
  assert.equal(findPlace({ location: "Collyhurst, Manchester" })[0], "Collyhurst");
  assert.equal(findPlace({ location: "Trafford Park, Manchester" })[0], "Trafford Park");
  assert.equal(findPlace({ location: "Blackburn" })[0], "Blackburn");
  assert.equal(findPlace({ location: "Rusholme or London" }), null);
  assert.equal(findPlace({ location: "Trafford Park Road, Manchester" }), null);
  assert.equal(findPlace({ location: "Salford, Greater Manchester" })[0], "Salford");
  assert.equal(findPlace({ location: "Greater Manchester" }), null);
  assert.equal(findPlace({ location: "North West" }), null);
  assert.equal(findPlace({ location: "Manchester or London" }), null);
  assert.equal(findPlace({ location: "Manchester", remote: true }), null);
  assert.equal(findPlace({ location: "Manchester Road, London" }), null);
});

test("groups filtered listings at each city centre and keeps their list positions", () => {
  const groups = groupItems([
    { title: "First", location: "Manchester" },
    { title: "Remote", location: "UK", remote: true },
    { title: "Second", location: "Manchester" },
    { title: "Third", location: "Liverpool" },
  ]);
  assert.equal(groups.length, 2);
  assert.deepEqual(groups[0].items.map(({ index }) => index), [0, 2]);
  assert.equal(groups[1].place[0], "Liverpool");
});

test("opens a UK map with zoom controls and links to the current listings", async () => {
  const previousDocument = global.document;
  const previousLeaflet = global.L;
  const createdMarkers = [];
  const map = {
    setView: (centre, zoom) => {
      map.centre = centre;
      map.zoom = zoom;
      return map;
    },
    closePopup() {},
    invalidateSize() {},
  };
  const markers = { addTo: () => markers, clearLayers: () => { createdMarkers.length = 0; } };
  const details = {
    open: true,
    addEventListener: (_, listener) => { details.toggle = listener; },
  };
  global.document = {
    createElement: (tag) => ({
      tag,
      children: [],
      appendChild(child) { this.children.push(child); },
    }),
    head: { appendChild: (resource) => queueMicrotask(() => resource.onload()) },
  };
  global.L = {
    map: (_, options) => { map.options = options; return map; },
    tileLayer: () => ({ on() { return this; }, addTo() { return this; } }),
    layerGroup: () => markers,
    divIcon: (options) => options,
    marker: () => ({
      bindPopup(popup) { this.popup = popup; return this; },
      addTo() { createdMarkers.push(this); return this; },
    }),
  };
  try {
    const status = {};
    const update = setup(details, {}, status);
    update([{ title: "Video editor", location: "Rusholme, Manchester" }]);
    details.toggle();
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(map.centre, [54.5, -3.5]);
    assert.equal(map.zoom, 5);
    assert.equal(map.options.scrollWheelZoom, true);
    assert.equal(map.options.touchZoom, true);
    assert.equal(createdMarkers.length, 1);
    const link = createdMarkers[0].popup.children[1].children[0].children[0];
    assert.equal(link.href, "#listing-0");
    assert.equal(link.textContent, "View listing: Video editor");
    assert.match(status.textContent, /^1 of 1 listings/);
  } finally {
    global.document = previousDocument;
    global.L = previousLeaflet;
  }
});
