/* Is the page's data stale, missing today's refresh, or from after the open?
 *
 * A static page is built once, so whether its data is stale depends on when someone
 * reads it. This runs in the reader's browser, in New York time, with the same rules
 * as src/morning_brief/runs.py (refresh_timing) and moves.py (is_fetch_stale).
 * web/test/timing.test.js checks the two agree on the same cases.
 */
(function (root) {
  "use strict";
  var NY = "America/New_York";
  var OPEN = 9 * 60 + 30;        // 9:30 AM
  var EXPECTED_BY = 8 * 60;      // 8:00 AM
  var DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  /* Calendar parts of an instant in New York: year, month (1-12), day, weekday (0=Sun), minutes after midnight. */
  function ny(date) {
    var parts = {};
    new Intl.DateTimeFormat("en-US", {
      timeZone: NY, year: "numeric", month: "numeric", day: "numeric",
      hour: "numeric", minute: "numeric", hourCycle: "h23", weekday: "short"
    }).formatToParts(date).forEach(function (p) { parts[p.type] = p.value; });
    var y = +parts.year, m = +parts.month, d = +parts.day;
    return { y: y, m: m, d: d, weekday: DAYS.indexOf(parts.weekday), minutes: (+parts.hour % 24) * 60 + +parts.minute,
             dayNumber: Date.UTC(y, m - 1, d) / 86400000 };
  }

  function pad(n) { return n < 10 ? "0" + n : "" + n; }

  /* "Wed Nov 04, 1:42 PM", like Python's %a %b %d, %-I:%M %p */
  function label(date) {
    var p = ny(date), h = Math.floor(p.minutes / 60), min = p.minutes % 60;
    var h12 = h % 12 === 0 ? 12 : h % 12;
    return DAYS[p.weekday] + " " + MONTHS[p.m - 1] + " " + pad(p.d) + ", " + h12 + ":" + pad(min) + " " + (h < 12 ? "AM" : "PM");
  }

  function weekdaysBetween(fromDay, toDay) {
    /* Weekdays strictly after fromDay up to and including toDay (day numbers since the epoch). */
    var n = 0;
    for (var d = fromDay + 1; d <= toDay; d++) {
      var wd = new Date(d * 86400000).getUTCDay();
      if (wd !== 0 && wd !== 6) n++;
    }
    return n;
  }

  function isStale(lastFetch, now) {
    if (!lastFetch) return true;
    return weekdaysBetween(ny(new Date(lastFetch)).dayNumber, ny(now).dayNumber) > 1;
  }

  /* {level: "ok" | "info" | "warn" | "fail", message} */
  function refreshTiming(lastFetch, now) {
    if (!lastFetch) return { level: "warn", message: "No refresh has run yet." };
    var fetchedAt = new Date(lastFetch);
    if (isStale(lastFetch, now)) {
      return { level: "fail", message: "Data is stale: last updated " + label(fetchedAt) + " ET. The refresh may have stopped running." };
    }
    var f = ny(fetchedAt), n = ny(now);
    if (n.weekday === 0 || n.weekday === 6) return { level: "ok", message: "" };
    if (f.dayNumber === n.dayNumber) {
      if (f.minutes >= OPEN) {
        return { level: "info", message: "Today's refresh ran at " + label(fetchedAt).split(", ")[1] +
          " ET, after the US open, so moves marked live are mid-session, not pre-open." };
      }
      return { level: "ok", message: "" };
    }
    if (n.minutes >= EXPECTED_BY) {
      return { level: "warn", message: "Today's pre-open refresh hasn't run (expected by 8:00 AM ET). Showing data from " +
        label(fetchedAt) + " ET." };
    }
    return { level: "ok", message: "" };
  }

  /* "3 hours ago" */
  function ago(lastFetch, now) {
    var mins = Math.max(0, Math.round((now - new Date(lastFetch)) / 60000));
    if (mins < 60) return mins === 1 ? "1 minute ago" : mins + " minutes ago";
    var hours = Math.round(mins / 60);
    if (hours < 48) return hours === 1 ? "1 hour ago" : hours + " hours ago";
    return Math.round(hours / 24) + " days ago";
  }

  var api = { refreshTiming: refreshTiming, isStale: isStale, label: label, ago: ago };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MBTiming = api;
})(this);
