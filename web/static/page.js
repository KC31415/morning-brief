/* Charts, the demo picker, the copy button and the freshness banner.
 * All numbers come from the JSON the build embedded in the page; nothing is fetched. */
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("page-data").textContent);
  var css = getComputedStyle(document.documentElement);
  function v(name) { return css.getPropertyValue(name).trim(); }

  // ---- freshness, judged now, in the reader's browser ----
  if (data.last_fetch) {
    var ago = document.getElementById("ago");
    if (ago) ago.textContent = "(" + MBTiming.ago(data.last_fetch, new Date()) + ")";
  }
  var timing = document.getElementById("timing");
  if (timing && data.mode === "latest") {
    var t = MBTiming.refreshTiming(data.last_fetch, new Date());
    if (t.level !== "ok") {
      timing.textContent = t.message;
      timing.className = "notice " + (t.level === "info" ? "" : t.level);
      timing.hidden = false;
    }
  }

  // ---- copy the morning note ----
  document.querySelectorAll("button.copy").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var text = document.getElementById(btn.dataset.copy).textContent;
      var done = function () { btn.textContent = "Copied"; setTimeout(function () { btn.textContent = "Copy note"; }, 1500); };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, function () { btn.textContent = "Select the text to copy"; });
      else btn.textContent = "Select the text to copy";
    });
  });

  // ---- demo: precomputed results of the real checks ----
  var demo = data.demo;
  var instSel = document.getElementById("demo-instrument");
  if (demo && instSel) {
    var faultSel = document.getElementById("demo-fault");
    var result = document.getElementById("demo-result");
    var names = Object.keys(demo);
    names.forEach(function (n) { instSel.add(new Option(n, n)); });
    if (names.indexOf("Gold") >= 0) instSel.value = "Gold";
    var fillFaults = function () {
      faultSel.innerHTML = "";
      Object.keys(demo[instSel.value]).forEach(function (f) { faultSel.add(new Option(f, f)); });
      result.innerHTML = "";
    };
    instSel.addEventListener("change", fillFaults);
    faultSel.addEventListener("change", function () { result.innerHTML = ""; });
    fillFaults();
    document.getElementById("demo-run").addEventListener("click", function () {
      var r = demo[instSel.value][faultSel.value];
      var cls = { OK: "ok", WARN: "warn", FAIL: "fail" }[r.status];
      var esc = function (s) { var d = document.createElement("div"); d.textContent = s; return d.innerHTML; };
      // findings and row are HTML the build escaped and formatted; banner and message are plain text
      result.innerHTML = "<p><strong>Simulated result. Real data is unchanged.</strong></p>" +
        '<div class="status ' + cls + '">' + esc(r.banner) + "</div>" +
        (r.findings.length ? "<ul>" + r.findings.map(function (f) { return "<li>" + f + "</li>"; }).join("") + "</ul>"
                           : '<p class="notice">' + esc(r.message) + "</p>") +
        "<p>" + r.row + "</p>";
    });
  }

  if (typeof Chart === "undefined") return;  // the tables still carry every number
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.color = v("--muted");
  Chart.defaults.borderColor = v("--line");

  // ---- ranking: bars in robust σ, with WARN and FAIL lines ----
  var rk = document.getElementById("ranking-chart");
  if (rk && data.ranking && data.ranking.length) {
    var warn = data.thresholds.warn, fail = data.thresholds.fail;
    var maxZ = Math.max.apply(null, data.ranking.map(function (r) { return r.z; }));
    var top = Math.max(warn * 1.25, maxZ * 1.1);
    var failInView = fail <= top;
    if (failInView) top = Math.max(top, fail * 1.05);
    var lines = [{ z: warn, text: "WARN " + warn + "σ" }].concat(failInView ? [{ z: fail, text: "FAIL " + fail + "σ" }] : []);
    var thresholds = {
      id: "thresholds",
      afterDatasetsDraw: function (chart) {
        var ctx = chart.ctx, x = chart.scales.x, area = chart.chartArea;
        ctx.save();
        ctx.strokeStyle = v("--muted"); ctx.fillStyle = v("--muted"); ctx.setLineDash([4, 4]); ctx.font = "12px " + Chart.defaults.font.family;
        lines.forEach(function (l) {
          var px = x.getPixelForValue(l.z);
          ctx.beginPath(); ctx.moveTo(px, area.top); ctx.lineTo(px, area.bottom); ctx.stroke();
          ctx.textAlign = "left"; ctx.fillText(l.text, px + 4, area.top + 12);
        });
        if (!failInView) { ctx.textAlign = "right"; ctx.fillText("FAIL " + fail + "σ →", area.right, area.top + 12); }
        ctx.restore();
      }
    };
    new Chart(rk, {
      type: "bar",
      data: {
        labels: data.ranking.map(function (r) { return r.name + " " + r.change + ", " + r.z.toFixed(1) + "σ"; }),
        datasets: [{ data: data.ranking.map(function (r) { return r.z; }), backgroundColor: v("--bar"), borderRadius: 4, barThickness: 14 }]
      },
      options: {
        indexAxis: "y", maintainAspectRatio: false, animation: false,
        layout: { padding: { top: 18 } },
        scales: {
          x: { min: 0, max: top, title: { display: true, text: "Latest move ÷ its own robust volatility (σ)" }, grid: { display: false } },
          y: { grid: { display: false }, ticks: { color: v("--ink"), autoSkip: false } }
        },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: function (c) { return "Robust σ: " + c.parsed.x.toFixed(2); } } }
        }
      },
      plugins: [thresholds]
    });
  }

  // ---- history: stored closes for one instrument at a time ----
  var hc = document.getElementById("history-chart");
  var hsel = document.getElementById("history-instrument");
  if (hc && hsel && data.history) {
    Object.keys(data.history).forEach(function (n) { hsel.add(new Option(n, n)); });
    if (data.history["S&P 500 futures"]) hsel.value = "S&P 500 futures";
    var hist = new Chart(hc, {
      type: "line",
      data: { labels: [], datasets: [{ data: [], borderColor: v("--bar"), borderWidth: 1.8, pointRadius: 0, tension: 0.1 }] },
      options: {
        maintainAspectRatio: false, animation: false,
        interaction: { mode: "index", intersect: false },
        scales: { x: { ticks: { maxTicksLimit: 8 }, grid: { display: false } }, y: { grace: "5%" } },
        plugins: { legend: { display: false } }
      }
    });
    var show = function () {
      var s = data.history[hsel.value];
      hist.data.labels = s.dates; hist.data.datasets[0].data = s.closes; hist.data.datasets[0].label = hsel.value;
      hist.update();
    };
    hsel.addEventListener("change", show);
    show();
  }
})();
