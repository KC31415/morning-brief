// node --test web/test/timing.test.js
// The same cases as tests/test_runs.py, so the browser and Python agree.
// Nov 5 2026 is a Thursday; New York is UTC-5 after Nov 1.
const test = require("node:test");
const assert = require("node:assert/strict");
const T = require("../static/timing.js");

const at = (s) => new Date(s);

test("on-time pre-open refresh is quiet", () => {
  assert.equal(T.refreshTiming("2026-11-05T11:06:00+00:00", at("2026-11-05T15:00:00Z")).level, "ok");
});

test("missing refresh warns once it was expected (8:00am NY = 13:00 UTC in winter)", () => {
  assert.equal(T.refreshTiming("2026-11-04T11:06:00+00:00", at("2026-11-05T12:59:00Z")).level, "ok");
  const t = T.refreshTiming("2026-11-04T11:06:00+00:00", at("2026-11-05T13:00:00Z"));
  assert.equal(t.level, "warn");
  assert.equal(t.message, "Today's pre-open refresh hasn't run (expected by 8:00 AM ET). Showing data from Wed Nov 04, 6:06 AM ET.");
});

test("refresh after the open is labeled", () => {
  const t = T.refreshTiming("2026-11-04T18:42:00+00:00", at("2026-11-04T19:00:00Z"));
  assert.equal(t.level, "info");
  assert.match(t.message, /^Today's refresh ran at 1:42 PM ET, after the US open/);
});

test("weekend is quiet", () => {
  assert.equal(T.refreshTiming("2026-11-06T11:06:00+00:00", at("2026-11-07T15:00:00Z")).level, "ok");
});

test("summer uses New York daylight time (8:00am = 12:00 UTC)", () => {
  assert.equal(T.refreshTiming("2026-06-30T11:06:00+00:00", at("2026-07-01T12:01:00Z")).level, "warn");
  assert.equal(T.refreshTiming("2026-07-01T11:06:00+00:00", at("2026-07-01T12:01:00Z")).level, "ok");
});

test("stale after more than one weekday, like moves.is_fetch_stale", () => {
  // Friday fetch: fine on Monday, stale on Tuesday
  assert.equal(T.isStale("2026-11-06T11:06:00+00:00", at("2026-11-09T15:00:00Z")), false);
  assert.equal(T.isStale("2026-11-06T11:06:00+00:00", at("2026-11-10T15:00:00Z")), true);
  const t = T.refreshTiming("2026-11-06T11:06:00+00:00", at("2026-11-10T15:00:00Z"));
  assert.equal(t.level, "fail");
  assert.match(t.message, /^Data is stale: last updated Fri Nov 06, 6:06 AM ET/);
});

test("no refresh ever", () => {
  assert.equal(T.refreshTiming(null, at("2026-11-05T15:00:00Z")).level, "warn");
});

test("label matches Python's as-of format, including midnight and noon", () => {
  assert.equal(T.label(at("2026-11-05T05:05:00Z")), "Thu Nov 05, 12:05 AM");
  assert.equal(T.label(at("2026-11-05T17:00:00Z")), "Thu Nov 05, 12:00 PM");
});

test("ago", () => {
  assert.equal(T.ago("2026-11-05T11:00:00Z", at("2026-11-05T11:01:00Z")), "1 minute ago");
  assert.equal(T.ago("2026-11-05T11:00:00Z", at("2026-11-05T14:10:00Z")), "3 hours ago");
  assert.equal(T.ago("2026-11-01T11:00:00Z", at("2026-11-05T11:00:00Z")), "4 days ago");
});
