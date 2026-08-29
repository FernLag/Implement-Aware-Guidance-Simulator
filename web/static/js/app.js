/* Implement-Aware Guidance Simulator, client behaviour.
   No external libraries. The chart is drawn as inline SVG so it inherits the
   page palette, scales with the container, and needs no network request. */

(function () {
  "use strict";

  var COLOURS = {
    tractor: "#4C5A3A",
    implement: "#A35A32",
    centre: "#C08A63",
    rule: "#CFC1A3",
    ink: "#33291D",
    faint: "#8A7659"
  };

  /* ---------- cookie consent ---------- */

  var banner = document.getElementById("cookie-banner");
  if (banner) {
    var STORE = "aggsim.analytics-consent";
    var saved = null;
    try { saved = window.localStorage.getItem(STORE); } catch (e) { saved = null; }
    if (saved !== "yes" && saved !== "no") {
      banner.hidden = false;
    }
    banner.addEventListener("click", function (ev) {
      var choice = ev.target.getAttribute("data-cookie");
      if (!choice) { return; }
      try { window.localStorage.setItem(STORE, choice); } catch (e) { /* private mode */ }
      banner.hidden = true;
      if (choice === "no") {
        // Remove anything already stored so declining actually clears state.
        document.cookie.split(";").forEach(function (c) {
          var name = c.split("=")[0].trim();
          if (name && name !== "session") {
            document.cookie = name + "=; Max-Age=0; path=/";
          }
        });
      }
    });
  }

  /* ---------- simulator ---------- */

  var form = document.getElementById("sim-form");
  if (!form) { return; }

  var tractorSel = document.getElementById("tractor");
  var implementSel = document.getElementById("implement");
  var tractorHint = document.getElementById("tractor-hint");
  var runBtn = document.getElementById("run-btn");
  var statusBox = document.getElementById("results-status");
  var resultsBox = document.getElementById("results");
  var formError = document.getElementById("form-error");
  var catalogData = null;

  function clearErrors() {
    form.querySelectorAll(".error").forEach(function (el) { el.textContent = ""; });
    form.querySelectorAll("[aria-invalid]").forEach(function (el) {
      el.removeAttribute("aria-invalid");
    });
    formError.hidden = true;
    formError.textContent = "";
  }

  function showFieldError(field, message) {
    var box = document.getElementById(field + "-error");
    var input = document.getElementById(field);
    if (box) { box.textContent = message; }
    if (input) { input.setAttribute("aria-invalid", "true"); }
    if (!box && !input) {
      formError.hidden = false;
      formError.textContent = message;
    }
  }

  function setBusy(busy) {
    runBtn.setAttribute("aria-busy", busy ? "true" : "false");
    runBtn.disabled = busy;
    runBtn.querySelector(".btn-label").textContent = busy ? "Running" : "Run the pass";
  }

  /* ---------- catalog ---------- */

  fetch("/api/catalog", { headers: { Accept: "application/json" } })
    .then(function (r) { if (!r.ok) { throw new Error("catalog"); } return r.json(); })
    .then(function (data) {
      catalogData = data;
      data.tractors.forEach(function (t) {
        var opt = document.createElement("option");
        opt.value = t.id;
        opt.textContent = t.name + "  (" + t.wheelbase.value.toFixed(2) + " m wheelbase)";
        if (!t.simulatable) {
          opt.disabled = true;
          opt.textContent += "  articulated, not simulatable";
        }
        if (t.id === "jd_6145r") { opt.selected = true; }
        tractorSel.appendChild(opt);
      });

      var none = document.createElement("option");
      none.value = "";
      none.textContent = "No implement, tractor only";
      implementSel.appendChild(none);
      data.implements.forEach(function (i) {
        var opt = document.createElement("option");
        opt.value = i.id;
        opt.textContent = i.name + "  (" + i.working_width.value.toFixed(2) + " m, " + i.type + ")";
        if (i.id === "jd_1775nt_16row30") { opt.selected = true; }
        implementSel.appendChild(opt);
      });
      describeTractor();
      if (applyUrlSettings()) {
        describeTractor();
        // A shared link should show its result, not an empty page.
        form.dispatchEvent(new Event("submit", { cancelable: true }));
      }
    })
    .catch(function () {
      formError.hidden = false;
      formError.textContent =
        "The equipment catalog could not be loaded. Reload the page to try again.";
    });

  function currentTractor() {
    if (!catalogData) { return null; }
    return catalogData.tractors.filter(function (x) {
      return x.id === tractorSel.value;
    })[0] || null;
  }

  function describeTractor() {
    var t = currentTractor();
    if (!t) { tractorHint.textContent = ""; return; }
    tractorHint.textContent = t.manufacturer + ", " + t.years +
      ". Wheelbase " + t.wheelbase.value.toFixed(3) + " m" +
      (t.wheelbase.assumed ? " (assumed)" : " (sourced)") +
      ", drawbar " + (t.drawbar_power_w / 1000).toFixed(0) + " kW.";
    markFeasibility();
  }

  /* A pairing the tractor cannot pull is not a simulation worth running: the
     model will happily produce numbers for a machine that could not move. The
     catalog already works this out, so the picker says so. */
  function markFeasibility() {
    var t = currentTractor();
    if (!t || !catalogData) { return; }
    Array.prototype.forEach.call(implementSel.options, function (opt) {
      if (!opt.value) { return; }
      var i = catalogData.implements.filter(function (x) {
        return x.id === opt.value;
      })[0];
      if (!i || !i.draft_power_w) { return; }
      var over = i.draft_power_w > t.drawbar_power_w;
      var base = opt.getAttribute("data-label") || opt.textContent;
      opt.setAttribute("data-label", base);
      opt.textContent = base + (over ? "  needs more power than this tractor" : "");
    });
    describeImplement();
  }

  function describeImplement() {
    var t = currentTractor();
    var hint = document.getElementById("implement-hint");
    if (!t || !catalogData || !implementSel.value) {
      hint.textContent = "Leave unset to measure the tractor alone.";
      hint.classList.remove("is-warning");
      return;
    }
    var i = catalogData.implements.filter(function (x) {
      return x.id === implementSel.value;
    })[0];
    if (!i || !i.draft_power_w) { return; }
    var need = i.draft_power_w / 1000, have = t.drawbar_power_w / 1000;
    if (need > have) {
      hint.classList.add("is-warning");
      hint.textContent = "This pairing needs about " + need.toFixed(0) +
        " kW at the drawbar and the " + t.name + " delivers " + have.toFixed(0) +
        " kW. It will still simulate, because the guidance model does not care " +
        "about draft, but no such outfit would work in a field.";
    } else {
      hint.classList.remove("is-warning");
      hint.textContent = "Needs about " + need.toFixed(0) + " kW of " +
        have.toFixed(0) + " kW available, " +
        Math.round(100 * need / have) + " percent of the drawbar.";
    }
  }

  tractorSel.addEventListener("change", describeTractor);
  implementSel.addEventListener("change", describeImplement);

  /* ---------- controller fields ---------- */

  form.querySelectorAll('input[name="controller"]').forEach(function (radio) {
    radio.addEventListener("change", function () {
      form.querySelectorAll("[data-for]").forEach(function (el) {
        el.hidden = el.getAttribute("data-for") !== radio.value;
      });
    });
  });

  /* ---------- run ---------- */

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    clearErrors();
    setBusy(true);
    statusBox.hidden = false;
    statusBox.textContent =
      (parseInt(document.getElementById("passes").value, 10) || 1) > 1
        ? "Working the field. Several passes take a little longer."
        : "Running the pass. This usually takes a moment.";
    resultsBox.hidden = true;

    // Caught here rather than by the server, because the answer is already on
    // the page: passes are spaced by the implement's working width, and with
    // no implement there is no spacing.
    var passCount = parseInt(document.getElementById("passes").value, 10) || 1;
    if (passCount > 1 && !implementSel.value) {
      setBusy(false);
      statusBox.hidden = true;
      showFieldError("passes",
        "Working more than one pass needs an implement: the spacing between " +
        "passes is the implement's working width.");
      return;
    }

    var controller = form.querySelector('input[name="controller"]:checked').value;
    var useField = document.getElementById("use_field");
    var payload = {
      tractor: tractorSel.value,
      implement: implementSel.value || null,
      controller: controller,
      speed: parseFloat(document.getElementById("speed").value),
      slope_deg: parseFloat(document.getElementById("slope_deg").value),
      slip: parseFloat(document.getElementById("slip").value),
      initial_offset: parseFloat(document.getElementById("initial_offset").value),
      lookahead_gain: parseFloat(document.getElementById("lookahead_gain").value),
      stanley_gain: parseFloat(document.getElementById("stanley_gain").value),
      actuator: document.getElementById("actuator").checked,
      passes: parseInt(document.getElementById("passes").value, 10) || 1,
      pass_length: parseFloat(document.getElementById("pass_length").value),
      headland: parseFloat(document.getElementById("headland").value)
    };
    if (useField && useField.checked && fieldInfo && lastPlace) {
      payload.field = {
        lat: lastPlace.lat, lon: lastPlace.lon,
        heading_deg: parseFloat(document.getElementById("heading").value) || 0
      };
    }

    lastPayload = payload;
    fetch("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, status: r.status, body: b }; }); })
      .then(function (res) {
        setBusy(false);
        if (res.ok) { render(res.body); return; }

        if (res.body && res.body.fields) {
          res.body.fields.forEach(function (f) { showFieldError(f.field, f.message); });
          statusBox.textContent = "Some values need attention. See the messages beside each field.";
          return;
        }
        formError.hidden = false;
        formError.textContent = (res.body && res.body.message) ||
          "The pass could not be run. Please adjust the settings and try again.";
        statusBox.textContent = "No results. See the message above the button.";
      })
      .catch(function () {
        setBusy(false);
        formError.hidden = false;
        formError.textContent = "Could not reach the server. Check your connection and try again.";
        statusBox.textContent = "No results.";
      });
  });

  /* ---------- rendering ---------- */

  function fmt(v, dp) { return (v === null || v === undefined) ? "n/a" : v.toFixed(dp === undefined ? 3 : dp); }

  var lastPayload = null;

  function render(data) {
    var s = data.series;
    var m = data.summary;

    statusBox.hidden = true;
    resultsBox.hidden = false;

    // A pairing no tractor in the catalog could pull still produces numbers,
    // because the guidance model does not know about draft. Say so on the
    // result rather than only in the picker.
    var warn = document.getElementById("pairing-warning");
    if (data.pairing && !data.pairing.feasible) {
      warn.hidden = false;
      warn.textContent = "This outfit is not physically feasible: it needs " +
        data.pairing.required_kw + " kW at the drawbar and the tractor delivers " +
        data.pairing.available_kw + " kW. The guidance figures below are still " +
        "computed correctly, but no such combination would work in a field.";
    } else {
      warn.hidden = true;
    }

    var lines = [{ key: "cross_track", label: "Tractor cross-track error",
                   colour: COLOURS.tractor, cls: "swatch-tractor", dash: null }];
    if (s.implement_cross_track) {
      lines.push({ key: "implement_cross_track", label: "Implement centreline",
                   colour: COLOURS.centre, cls: "swatch-centre", dash: "5 4" });
      lines.push({ key: "worst_edge", label: "Worst implement edge",
                   colour: COLOURS.implement, cls: "swatch-implement", dash: null });
    }

    setupScene(data);
    drawPasses(data);
    drawProfile(data.field);
    drawChart(s, lines);
    drawLegend(lines);
    drawMetrics(data, m);
    drawTable(s, lines);

    if (m.jackknifed) {
      formError.hidden = false;
      formError.textContent = "The hitch reached its stop after " +
        fmt(m.jackknife_time, 1) + " seconds. Past that angle a drawbar cannot " +
        "fold any further and this model no longer describes the machine, so " +
        "treat the implement figures after that point as invalid.";
    }

    var summary = "Over " + fmt(s.t[s.t.length - 1], 0) + " seconds the tractor settles at " +
      fmt(m.final_cross_track) + " metres from the line, with a peak of " +
      fmt(m.peak_cross_track) + " metres.";
    if (m.final_worst_edge !== undefined) {
      summary += " The worst implement edge settles at " + fmt(m.final_worst_edge) +
        " metres, which is " + (Math.abs(m.final_worst_edge / (m.final_cross_track || 1))).toFixed(2) +
        " times the tractor figure.";
      if (m.rms_skip_m !== undefined) {
        summary += " Skip between adjacent passes averages " +
          fmt(m.rms_skip_m * 100, 1) + " centimetres, " + fmt(m.rms_skip_percent, 2) +
          " percent of the working width, " + (m.coverage_basis || "") + ".";
      }
    }
    document.getElementById("chart-summary").textContent = summary;
  }

  /* What the field cost, pass by pass. Only meaningful once there is more
     than one pass, because a neighbour is what skip and overlap are measured
     against. */
  function drawPasses(data) {
    var card = document.getElementById("passes-card");
    var p = data.passes;
    if (!p) { card.hidden = true; return; }
    card.hidden = false;

    var body = document.getElementById("passes-body");
    body.textContent = "";
    p.detail.forEach(function (d) {
      var tr = document.createElement("tr");
      [String(d.index + 1),
       d.forward ? "out" : "back",
       fmt(d.entry_error),
       fmt(d.settled_error),
       d.rms_edge === undefined ? "\u2014" : fmt(d.rms_edge),
       d.peak_edge === undefined ? "\u2014" : fmt(d.peak_edge),
       fmt(d.turn_peak, 1)].forEach(function (text, i) {
        var cell = document.createElement(i === 0 ? "th" : "td");
        if (i === 0) { cell.scope = "row"; }
        cell.textContent = text;
        tr.appendChild(cell);
      });
      body.appendChild(tr);
    });

    var bBody = document.getElementById("boundaries-body");
    bBody.textContent = "";
    (data.summary.boundaries || []).forEach(function (b) {
      var tr = document.createElement("tr");
      [b.between[0] + 1 + " and " + (b.between[1] + 1),
       b.mean_skip_cm.toFixed(1),
       b.worst_gap_cm.toFixed(1),
       b.worst_overlap_cm.toFixed(1),
       b.gap_area_m2_per_100m.toFixed(2)].forEach(function (text, i) {
        var cell = document.createElement(i === 0 ? "th" : "td");
        if (i === 0) { cell.scope = "row"; }
        cell.textContent = text;
        tr.appendChild(cell);
      });
      bBody.appendChild(tr);
    });

    var plan = p.plan;
    var text = "Worked " + p.worked + " of " + plan.passes + " passes, " +
      plan.length + " metres long and " + plan.working_width.toFixed(2) +
      " metres apart, covering " + plan.worked_area_ha.toFixed(2) + " hectares.";
    if (!p.complete) {
      text += " The run reached its time limit before the field was finished, " +
        "so the last passes are missing.";
    }
    var settled = p.detail.map(function (d) { return d.settled_error; });
    var flips = settled.filter(function (v, i) {
      return i > 0 && v * settled[i - 1] < 0;
    }).length;
    if (flips === settled.length - 1 && settled.length > 1 &&
        Math.abs(settled[0]) > 0.02) {
      text += " The settled offset changes sign on every pass: the hillside has " +
        "not moved, but the machine has turned round, so the drift that pushed " +
        "it one way going out pushes it the other way coming back.";
    }
    document.getElementById("passes-summary").textContent = text;
  }

  /* The ground itself, drawn against distance rather than time, because that
     is the axis the terrain lives on. */
  function drawProfile(field) {
    var card = document.getElementById("profile-card");
    if (!field) { card.hidden = true; return; }
    card.hidden = false;

    var W = 760, H = 210, padL = 58, padR = 18, padT = 14, padB = 42;
    var xs = field.positions_m, ys = field.side_slope_deg;
    var xMax = xs[xs.length - 1] || 1;
    var lo = Math.min.apply(null, ys), hi = Math.max.apply(null, ys);
    var pad = Math.max(0.5, (hi - lo) * 0.15);
    lo -= pad; hi += pad;

    function X(v) { return padL + (v / xMax) * (W - padL - padR); }
    function Y(v) { return padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB); }

    var svg = ['<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" focusable="false">'];
    svg.push('<rect width="' + W + '" height="' + H + '" fill="#F6F1E7"/>');
    for (var i = 0; i <= 4; i++) {
      var v = lo + (hi - lo) * (i / 4);
      svg.push('<line x1="' + padL + '" y1="' + Y(v).toFixed(1) + '" x2="' + (W - padR) +
        '" y2="' + Y(v).toFixed(1) + '" stroke="#CFC1A3"/>');
      svg.push('<text x="' + (padL - 8) + '" y="' + (Y(v) + 4).toFixed(1) +
        '" text-anchor="end" font-size="11" font-family="ui-monospace, monospace" fill="#8A7659">' +
        v.toFixed(1) + '</text>');
    }
    svg.push('<line x1="' + padL + '" y1="' + Y(0).toFixed(1) + '" x2="' + (W - padR) +
      '" y2="' + Y(0).toFixed(1) + '" stroke="#33291D" stroke-width="1.5" stroke-dasharray="6 4"/>');

    var area = ["M" + X(xs[0]).toFixed(1) + " " + Y(0).toFixed(1)];
    var line = [];
    for (var k = 0; k < xs.length; k++) {
      area.push("L" + X(xs[k]).toFixed(1) + " " + Y(ys[k]).toFixed(1));
      line.push((k ? "L" : "M") + X(xs[k]).toFixed(1) + " " + Y(ys[k]).toFixed(1));
    }
    area.push("L" + X(xs[xs.length - 1]).toFixed(1) + " " + Y(0).toFixed(1) + "Z");
    svg.push('<path d="' + area.join(" ") + '" fill="rgba(139,102,66,0.22)"/>');
    svg.push('<path d="' + line.join(" ") + '" fill="none" stroke="#8A4826" stroke-width="2.4"/>');
    svg.push('<text x="' + ((W - padL) / 2 + padL) + '" y="' + (H - 8) +
      '" text-anchor="middle" font-size="12" fill="#33291D">distance along the pass (m)</text>');
    svg.push('<text transform="translate(14,' + (H / 2) +
      ') rotate(-90)" text-anchor="middle" font-size="12" fill="#33291D">side slope (deg)</text>');
    svg.push("</svg>");
    document.getElementById("profile-chart").innerHTML = svg.join("");

    document.getElementById("profile-summary").textContent =
      "Measured from USGS elevation at " + field.resolution_m + " m resolution, " +
      field.stations + " stations every " + field.spacing_m + " m. The side slope runs from " +
      field.min_deg.toFixed(2) + " to " + field.max_deg.toFixed(2) +
      " degrees and the ground rises and falls " + field.elevation_change_m +
      " m along the pass. Positive means the ground falls to the left of travel.";
  }

  function drawChart(s, lines) {
    var W = 760, H = 380, padL = 62, padR = 18, padT = 16, padB = 46;
    var t = s.t;
    var tMax = t[t.length - 1] || 1;

    var lo = 0, hi = 0;
    lines.forEach(function (ln) {
      (s[ln.key] || []).forEach(function (v) {
        if (v === null) { return; }
        if (v < lo) { lo = v; }
        if (v > hi) { hi = v; }
      });
    });
    var span = (hi - lo) || 1;
    lo -= span * 0.12; hi += span * 0.12;

    function X(v) { return padL + (v / tMax) * (W - padL - padR); }
    function Y(v) { return padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB); }

    var svg = ['<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" focusable="false">'];
    svg.push('<rect width="' + W + '" height="' + H + '" fill="#F6F1E7"/>');

    var ticks = 5, i, val;
    for (i = 0; i <= ticks; i++) {
      val = lo + (hi - lo) * (i / ticks);
      svg.push('<line x1="' + padL + '" y1="' + Y(val).toFixed(1) + '" x2="' + (W - padR) +
        '" y2="' + Y(val).toFixed(1) + '" stroke="' + COLOURS.rule + '" stroke-width="1"/>');
      svg.push('<text x="' + (padL - 8) + '" y="' + (Y(val) + 4).toFixed(1) +
        '" text-anchor="end" font-size="11" font-family="ui-monospace, monospace" fill="' +
        COLOURS.faint + '">' + val.toFixed(2) + '</text>');
    }
    for (i = 0; i <= 6; i++) {
      val = tMax * (i / 6);
      svg.push('<text x="' + X(val).toFixed(1) + '" y="' + (H - padB + 20) +
        '" text-anchor="middle" font-size="11" font-family="ui-monospace, monospace" fill="' +
        COLOURS.faint + '">' + val.toFixed(0) + '</text>');
    }
    svg.push('<line x1="' + padL + '" y1="' + Y(0).toFixed(1) + '" x2="' + (W - padR) +
      '" y2="' + Y(0).toFixed(1) + '" stroke="' + COLOURS.ink + '" stroke-width="1.5" stroke-dasharray="6 4"/>');

    svg.push('<text x="' + ((W - padL) / 2 + padL) + '" y="' + (H - 6) +
      '" text-anchor="middle" font-size="12" fill="' + COLOURS.ink + '">time (seconds)</text>');
    svg.push('<text transform="translate(16,' + (H / 2) + ') rotate(-90)" text-anchor="middle" font-size="12" fill="' +
      COLOURS.ink + '">error (metres)</text>');

    lines.forEach(function (ln) {
      var arr = s[ln.key];
      if (!arr) { return; }
      var d = [], started = false;
      for (var k = 0; k < arr.length; k++) {
        if (arr[k] === null) { started = false; continue; }
        d.push((started ? "L" : "M") + X(t[k]).toFixed(1) + " " + Y(arr[k]).toFixed(1));
        started = true;
      }
      svg.push('<path d="' + d.join(" ") + '" fill="none" stroke="' + ln.colour +
        '" stroke-width="2.4"' + (ln.dash ? ' stroke-dasharray="' + ln.dash + '"' : "") + "/>");
    });

    svg.push("</svg>");
    document.getElementById("chart").innerHTML = svg.join("");
  }

  function drawLegend(lines) {
    document.getElementById("legend").innerHTML = lines.map(function (ln) {
      return '<li><span class="swatch ' + ln.cls + '"></span>' + ln.label + "</li>";
    }).join("");
  }

  function drawMetrics(data, m) {
    var cards = [
      { cls: "is-tractor", label: "Tractor, settled", value: fmt(m.final_cross_track) + " m", note: "distance from the guidance line" },
      { cls: "is-tractor", label: "Tractor, RMS", value: fmt(m.rms_cross_track) + " m", note: "over the whole pass" }
    ];
    if (m.final_worst_edge !== undefined) {
      cards.push({ cls: "is-implement", label: "Implement edge, settled", value: fmt(m.final_worst_edge) + " m", note: "worst of the two working edges" });
      cards.push({ cls: "is-implement", label: "Implement edge, RMS", value: fmt(m.rms_worst_edge) + " m", note: "over the whole pass" });
      cards.push({ cls: "is-implement", label: "Skip between passes", value: fmt(m.rms_skip_m * 100, 1) + " cm", note: fmt(m.rms_skip_percent, 2) + " percent of " + fmt(m.working_width, 2) + " m width" });
    }
    cards.push({ cls: "", label: "Timestep used", value: fmt(m.dt, 4) + " s", note: m.steps + " integration steps" });

    document.getElementById("metrics").innerHTML = cards.map(function (c) {
      return '<dl class="metric ' + c.cls + '"><dt>' + c.label + "</dt><dd>" + c.value +
        '<span class="metric-note">' + c.note + "</span></dd></dl>";
    }).join("");
  }

  /* ---------- export and sharing ---------- */

  function currentPayload() { return lastPayload; }

  function download(name, text) {
    var blob = new Blob([text], { type: "text/csv" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  var shareNote = document.getElementById("share-note");

  document.getElementById("download-csv").addEventListener("click", function () {
    var payload = currentPayload();
    if (!payload) { return; }
    shareNote.textContent = "Preparing the file.";
    fetch("/api/simulate.csv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.ok ? r.text() : Promise.reject(); })
      .then(function (text) {
        download("guidance-run.csv", text);
        shareNote.textContent = "Downloaded.";
      })
      .catch(function () { shareNote.textContent = "The file could not be prepared."; });
  });

  document.getElementById("copy-link").addEventListener("click", function () {
    var payload = currentPayload();
    if (!payload) { return; }
    var params = new URLSearchParams();
    Object.keys(payload).forEach(function (k) {
      if (payload[k] === null || typeof payload[k] === "object") { return; }
      params.set(k, String(payload[k]));
    });
    var url = window.location.origin + window.location.pathname + "?" + params.toString();
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(function () {
        shareNote.textContent = "Link copied.";
      }, function () {
        shareNote.textContent = url;
      });
    } else {
      shareNote.textContent = url;
    }
    window.history.replaceState(null, "", "?" + params.toString());
  });

  /* Settings arriving in the address bar, so a shared link opens the same run. */
  function applyUrlSettings() {
    var params = new URLSearchParams(window.location.search);
    if (!params.toString()) { return false; }
    [["speed", "speed"], ["slope_deg", "slope_deg"], ["slip", "slip"],
     ["initial_offset", "initial_offset"], ["lookahead_gain", "lookahead_gain"],
     ["stanley_gain", "stanley_gain"], ["passes", "passes"],
     ["pass_length", "pass_length"], ["headland", "headland"]].forEach(function (pair) {
      var v = params.get(pair[0]);
      var el = document.getElementById(pair[1]);
      if (v !== null && el) { el.value = v; }
    });
    if (params.get("tractor")) { tractorSel.value = params.get("tractor"); }
    if (params.get("implement")) { implementSel.value = params.get("implement"); }
    var controller = params.get("controller");
    if (controller) {
      var radio = form.querySelector('input[name="controller"][value="' + controller + '"]');
      if (radio) { radio.checked = true; radio.dispatchEvent(new Event("change")); }
    }
    if (params.get("actuator") !== null) {
      document.getElementById("actuator").checked = params.get("actuator") === "true";
    }
    return true;
  }

  /* ---------- scale annotations ----------
     Dimension lines and a scale bar, drawn as SVG on top of the canvas.

     Text baked into a WebGL texture is blurry when zoomed and invisible to a
     screen reader. Real SVG text is crisp at any size and quotes the catalog's
     own figures, which is the point: this tool's whole claim is that the
     dimensions are real, so it should be able to say what they are. */

  var overlay = document.getElementById("scene-overlay");
  var showScale = document.getElementById("show_scale");
  if (showScale) {
    showScale.addEventListener("change", function () {
      if (scene) { scene.showGrid = showScale.checked; }
      drawFrame(frame);
    });
  }

  function svg(tag, attrs, text) {
    var el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attrs).forEach(function (k) { el.setAttribute(k, attrs[k]); });
    if (text !== undefined) { el.textContent = text; }
    return el;
  }

  function dimension(parent, a, b, label, cls) {
    if (!a || !b) { return; }
    var mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    var dx = b.x - a.x, dy = b.y - a.y;
    var len = Math.hypot(dx, dy);
    if (len < 26) { return; }
    var nx = -dy / len * 6, ny = dx / len * 6;

    parent.appendChild(svg("path", {
      class: "dim " + (cls || ""),
      d: "M" + (a.x + nx) + " " + (a.y + ny) + "L" + (a.x - nx) + " " + (a.y - ny) +
         "M" + a.x + " " + a.y + "L" + b.x + " " + b.y +
         "M" + (b.x + nx) + " " + (b.y + ny) + "L" + (b.x - nx) + " " + (b.y - ny)
    }));
    parent.appendChild(svg("text", {
      x: mx, y: my - 8, "text-anchor": "middle"
    }, label));
  }

  function drawAnnotations(pose) {
    if (!overlay) { return; }
    overlay.innerHTML = "";
    if (!pose || !pose.anchors || (showScale && !showScale.checked)) { return; }

    var a = pose.anchors;
    var w = document.getElementById("scene").clientWidth;
    var h = document.getElementById("scene").clientHeight;
    overlay.setAttribute("viewBox", "0 0 " + w + " " + h);

    dimension(overlay, scene.project(a.rearAxle), scene.project(a.frontAxle),
      a.wheelbase.toFixed(2) + " m wheelbase");

    if (a.workingWidth) {
      dimension(overlay, scene.project(a.edgeLeft), scene.project(a.edgeRight),
        a.workingWidth.toFixed(2) + " m working width", "dim-implement");
    }

    var head = scene.project(a.figure), feet = scene.project(a.figureBase);
    if (head && feet && Math.abs(feet.y - head.y) > 14) {
      overlay.appendChild(svg("path", {
        class: "dim",
        d: "M" + (head.x + 14) + " " + head.y + "L" + (feet.x + 14) + " " + feet.y
      }));
      overlay.appendChild(svg("text", {
        x: head.x + 20, y: (head.y + feet.y) / 2, "text-anchor": "start"
      }, "1.75 m"));
    }

    // A scale bar, sized at the depth being looked at, rounded to a figure a
    // person can actually use rather than whatever the arithmetic produced.
    var ppm = a.pixelsPerMetre;
    if (ppm && ppm > 0.4) {
      var candidates = [1, 2, 5, 10, 20, 50, 100];
      var metres = candidates[candidates.length - 1];
      for (var i = 0; i < candidates.length; i++) {
        if (candidates[i] * ppm > w * 0.16) { metres = candidates[i]; break; }
      }
      var px = metres * ppm;
      var x0 = 18, y0 = h - 22;
      overlay.appendChild(svg("path", {
        class: "bar",
        d: "M" + x0 + " " + (y0 - 6) + "L" + x0 + " " + (y0 + 6) +
           "M" + x0 + " " + y0 + "L" + (x0 + px) + " " + y0 +
           "M" + (x0 + px) + " " + (y0 - 6) + "L" + (x0 + px) + " " + (y0 + 6)
      }));
      overlay.appendChild(svg("text", {
        x: x0 + px / 2, y: y0 - 10, "text-anchor": "middle"
      }, metres + " m"));
      overlay.appendChild(svg("text", {
        x: x0, y: y0 + 20, "text-anchor": "start"
      }, "grid squares are 5 m"));
    }
  }

  /* ---------- 3D playback ---------- */

  var scene = null, sceneData = null, frame = 0, playing = false, rafId = null;
  var terrain = null, fieldInfo = null, lastPlace = null;
  var reduceMotion = window.matchMedia
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function setupScene(data) {
    var canvas = document.getElementById("scene");
    if (!canvas || !window.GuidanceScene) { return; }

    sceneData = data;
    frame = 0;
    if (!scene) {
      try {
        scene = window.GuidanceScene.create(canvas);
      } catch (err) {
        // Without WebGL the chart, the metrics and the data table still carry
        // every number, so the page degrades rather than breaking.
        canvas.hidden = true;
        document.getElementById("scene-caveat").textContent =
          "The 3D view needs WebGL, which this browser did not provide. " +
          "Every figure is still shown in the chart and the table below.";
        document.querySelectorAll(".scene-controls, .scene-views").forEach(function (el) {
          el.hidden = true;
        });
        return;
      }
      attachSceneControls(canvas);
    }

    var slider = document.getElementById("scene-time");
    slider.max = String(data.series.t.length - 1);
    slider.value = "0";

    var g = data.scene.machine;
    var parts = [];
    if (terrain) {
      parts.push("Ground: USGS aerial photograph of the field you loaded.");
    } else {
      parts.push("Ground: plain soil. To put the real aerial photograph of a " +
        "field under the machine, enter a location under Real field and press " +
        "Read slope from this field.");
    }
    if (g.rear_wheel.code) {
      parts.push("Rear tyre " + g.rear_wheel.code + " gives a " +
        g.rear_wheel.diameter.toFixed(2) + " m rolling diameter, and the wheelbase is " +
        g.wheelbase.value.toFixed(2) + " m. Both are from the catalog.");
    }
    if (g.livery && g.livery.verified) {
      parts.push("Livery is " + g.manufacturer + "'s published brand palette. " +
        "A brand palette is the logo colour rather than a paint code, so it " +
        "identifies the machine without being a paint match.");
    } else if (g.livery) {
      parts.push("Livery for " + g.manufacturer + " is recognisable rather than " +
        "verified: no published palette was found, so the colour is not sourced.");
    }
    parts.push("Body proportions, track width and hitch geometry are published by " +
      "nobody here and are drawn to plausible shape. None of them affect the numbers.");
    document.getElementById("scene-caveat").textContent = parts.join(" ");

    drawFrame(0);
    // Autoplay is motion the visitor did not ask for, so it waits when the
    // system says to reduce motion.
    setPlaying(!reduceMotion);
  }

  function drawFrame(i) {
    if (!scene || !sceneData) { return; }
    var s = sceneData.series;
    frame = Math.max(0, Math.min(i, s.t.length - 1));
    var pose = window.GuidanceScene.render(scene, sceneData, frame, terrain);
    drawAnnotations(pose);

    document.getElementById("scene-clock").textContent = fmt(s.t[frame], 1) + " s";
    document.getElementById("scene-time").value = String(frame);

    var alt = "At " + fmt(s.t[frame], 1) + " seconds the tractor is " +
      fmt(s.cross_track[frame]) + " metres from the guidance line";
    if (s.worst_edge) {
      alt += " and the worst implement edge is " + fmt(s.worst_edge[frame]) + " metres out";
    }
    document.getElementById("scene-alt").textContent = alt + ".";
    document.getElementById("scene").setAttribute("aria-label", alt + ".");
  }

  function setPlaying(on) {
    playing = on;
    var btn = document.getElementById("scene-play");
    btn.textContent = on ? "Pause" : "Play";
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
    if (on) { rafId = requestAnimationFrame(tick); }
  }

  var lastTime = 0;
  function tick(now) {
    if (!playing || !sceneData) { return; }
    if (now - lastTime > 40) {
      lastTime = now;
      var next = frame + 1;
      if (next >= sceneData.series.t.length) { next = 0; }
      drawFrame(next);
    }
    rafId = requestAnimationFrame(tick);
  }

  /* ---------- real field ---------- */

  var fieldBtn = document.getElementById("read-field");
  if (fieldBtn && window.GuidanceTerrain) {
    document.querySelectorAll("[data-place]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.getElementById("latlon").value =
          btn.getAttribute("data-place").replace(",", ", ");
        // Each preset comes with the heading that runs along its field, since
        // driving across a slope and driving up it are different problems.
        var heading = btn.getAttribute("data-heading");
        if (heading !== null) { document.getElementById("heading").value = heading; }
      });
    });

    fieldBtn.addEventListener("click", function () {
      var note = document.getElementById("field-note");
      var err = document.getElementById("latlon-error");
      err.textContent = "";
      note.classList.remove("is-error");

      var here = window.GuidanceTerrain.parseLatLon(document.getElementById("latlon").value);
      if (!here) {
        err.textContent = "Enter a latitude and longitude, for example 42.03, -93.65.";
        return;
      }
      var heading = parseFloat(document.getElementById("heading").value) || 0;

      fieldBtn.setAttribute("aria-busy", "true");
      fieldBtn.disabled = true;
      note.textContent = "Reading elevation and imagery for that location.";

      window.GuidanceTerrain.readField(here.lat, here.lon, heading)
        .then(function (info) {
          fieldInfo = info;
          lastPlace = here;
          var wrap = document.getElementById("use-field-wrap");
          wrap.hidden = false;
          document.getElementById("use_field").checked = true;
          document.getElementById("slope_deg").value = info.side_slope_deg.toFixed(2);
          note.textContent =
            "Ground at " + info.elevation_m.toFixed(0) + " m. Driving on a heading of " +
            heading + " degrees gives a side slope of " + info.side_slope_deg.toFixed(2) +
            " degrees and " + Math.abs(info.along_slope_deg).toFixed(2) +
            " degrees along the line. Sampled from " + info.samples +
            " points at " + info.resolution_m + " m resolution. " + info.attribution + ".";
          var travel = (parseFloat(document.getElementById("speed").value) || 3) * 60;
          return window.GuidanceTerrain.loadImagery(here.lat, here.lon, heading, travel);
        })
        .then(function (patch) {
          terrain = { patch: patch, map: window.GuidanceTerrain.mapper(patch, heading) };
          note.textContent += " Aerial photograph loaded at " +
            patch.metresPerPixel.toFixed(2) + " m per pixel, covering " +
            Math.round(patch.extentM) + " m of ground.";
          if (sceneData) { drawFrame(frame); }

          // The photograph on its own is a flat picture of rolling ground.
          // Reading the height as well lets it be draped over the shape it
          // was taken of. Failing here costs the relief, not the imagery.
          var travel = (parseFloat(document.getElementById("speed").value) || 3) * 60;
          return window.GuidanceTerrain.loadHeights(here.lat, here.lon, heading,
                                                    travel, patch)
            .then(function (grid) {
              terrain.heights = grid;
              terrain.height = grid.height;
              note.textContent += " Ground height sampled over " +
                Math.round(grid.half_m * 2) + " m at " + grid.step_m.toFixed(0) +
                " m spacing, showing " + grid.relief_m.toFixed(1) +
                " m of relief.";
              if (sceneData) { drawFrame(frame); }
            })
            .catch(function () {
              note.textContent += " Ground height could not be read, so the " +
                "photograph is drawn on a flat plane.";
            });
        })
        .catch(function (e) {
          // The slope was read even if the photograph was not, and that is
          // worth keeping rather than discarding with the imagery.
          terrain = null;
          note.textContent += " " + (e && e.message ? e.message :
            "The aerial photograph could not be loaded.") +
            " The slope figures above are still real.";
          if (sceneData) { drawFrame(frame); }
        })
        .catch(function (e) {
          note.classList.add("is-error");
          note.textContent = e.message ||
            "That location could not be read. USGS elevation covers the United States only.";
        })
        .then(function () {
          fieldBtn.setAttribute("aria-busy", "false");
          fieldBtn.disabled = false;
        });
    });
  }

  function attachSceneControls(canvas) {
    document.getElementById("scene-play").addEventListener("click", function () {
      setPlaying(!playing);
    });

    document.getElementById("scene-time").addEventListener("input", function (ev) {
      setPlaying(false);
      drawFrame(parseInt(ev.target.value, 10));
    });

    document.querySelectorAll("[data-view]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll("[data-view]").forEach(function (b) {
          b.setAttribute("aria-pressed", "false");
        });
        btn.setAttribute("aria-pressed", "true");
        scene.applyPreset(btn.getAttribute("data-view"));
        drawFrame(frame);
      });
    });

    var dragging = false, lastX = 0, lastY = 0;
    canvas.addEventListener("pointerdown", function (ev) {
      dragging = true; lastX = ev.clientX; lastY = ev.clientY;
      canvas.setPointerCapture(ev.pointerId);
    });
    canvas.addEventListener("pointermove", function (ev) {
      if (!dragging) { return; }
      scene.yaw += (ev.clientX - lastX) * 0.008;
      scene.pitch = Math.max(0.03, Math.min(1.48, scene.pitch + (ev.clientY - lastY) * 0.006));
      lastX = ev.clientX; lastY = ev.clientY;
      scene.mode = "free";
      // Dragging leaves the presets, so none of them should read as active.
      document.querySelectorAll("[data-view]").forEach(function (b) {
        b.setAttribute("aria-pressed", "false");
      });
      drawFrame(frame);
    });
    canvas.addEventListener("pointerup", function (ev) {
      dragging = false;
      canvas.releasePointerCapture(ev.pointerId);
    });
    canvas.addEventListener("wheel", function (ev) {
      ev.preventDefault();
      scene.autoFit = false;
      scene.distance = Math.max(6, Math.min(200, scene.distance + ev.deltaY * 0.05));
      drawFrame(frame);
    }, { passive: false });

    window.addEventListener("resize", function () { drawFrame(frame); });
  }

  function drawTable(s, lines) {
    var head = ["Time (s)"].concat(lines.map(function (l) { return l.label + " (m)"; }));
    document.getElementById("data-head").innerHTML =
      head.map(function (h) { return "<th scope=\"col\">" + h + "</th>"; }).join("");

    var step = Math.max(1, Math.floor(s.t.length / 40)), rows = [];
    for (var i = 0; i < s.t.length; i += step) {
      var cells = ['<th scope="row">' + fmt(s.t[i], 1) + "</th>"];
      lines.forEach(function (ln) { cells.push("<td>" + fmt((s[ln.key] || [])[i], 4) + "</td>"); });
      rows.push("<tr>" + cells.join("") + "</tr>");
    }
    document.getElementById("data-body").innerHTML = rows.join("");
  }
})();
