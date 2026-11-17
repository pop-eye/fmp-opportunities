"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const { findPlace, groupItems } = require("../docs/map.js");

test("finds recognised city centres without guessing regions or remote locations", () => {
  assert.equal(findPlace({ location: "Manchester Science Park, Manchester" })[0], "Manchester");
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
