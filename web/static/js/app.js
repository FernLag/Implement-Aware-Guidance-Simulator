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
    })
    .catch(function () {
      formError.hidden = false;
      formError.textContent =
        "The equipment catalog could not be loaded. Reload the page to try again.";
    });

  function describeTractor() {
    if (!catalogData) { return; }
    var t = catalogData.tractors.filter(function (x) { return x.id === tractorSel.value; })[0];
    if (!t) { tractorHint.textContent = ""; return; }
    tractorHint.textContent = t.manufacturer + ", " + t.years +
      ". Wheelbase " + t.wheelbase.value.toFixed(3) + " m" +
      (t.wheelbase.assumed ? " (assumed)" : " (sourced)") + ".";
  }
  tractorSel.addEventListener("change", describeTractor);

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
    statusBox.textContent = "Running the pass. This usually takes a moment.";
    resultsBox.hidden = true;

    var controller = form.querySelector('input[name="controller"]:checked').value;
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
      actuator: document.getElementById("actuator").checked
    };

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

  function render(data) {
    var s = data.series;
    var m = data.summary;

    statusBox.hidden = true;
    resultsBox.hidden = false;

    var lines = [{ key: "cross_track", label: "Tractor cross-track error", colour: COLOURS.tractor, dash: null }];
    if (s.implement_cross_track) {
      lines.push({ key: "implement_cross_track", label: "Implement centreline", colour: COLOURS.centre, dash: "5 4" });
      lines.push({ key: "worst_edge", label: "Worst implement edge", colour: COLOURS.implement, dash: null });
    }

    setupScene(data);
    drawChart(s, lines);
    drawLegend(lines);
    drawMetrics(data, m);
    drawTable(s, lines);

    var summary = "Over " + fmt(s.t[s.t.length - 1], 0) + " seconds the tractor settles at " +
      fmt(m.final_cross_track) + " metres from the line, with a peak of " +
      fmt(m.peak_cross_track) + " metres.";
    if (m.final_worst_edge !== undefined) {
      summary += " The worst implement edge settles at " + fmt(m.final_worst_edge) +
        " metres, which is " + (Math.abs(m.final_worst_edge / (m.final_cross_track || 1))).toFixed(2) +
        " times the tractor figure. Skip between adjacent passes averages " +
        fmt(m.rms_skip_m * 100, 1) + " centimetres, " + fmt(m.rms_skip_percent, 2) +
        " percent of the working width.";
    }
    document.getElementById("chart-summary").textContent = summary;
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
      return '<li><span class="swatch" style="background:' + ln.colour + '"></span>' + ln.label + "</li>";
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

  /* ---------- 3D playback ---------- */

  var scene = null, sceneData = null, frame = 0, playing = false, rafId = null;
  var terrain = null, fieldInfo = null;
  var reduceMotion = window.matchMedia
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function setupScene(data) {
    var canvas = document.getElementById("scene");
    if (!canvas || !window.GuidanceScene) { return; }

    sceneData = data;
    frame = 0;
    if (!scene) {
      scene = window.GuidanceScene.create(canvas);
      attachSceneControls(canvas);
    }

    var slider = document.getElementById("scene-time");
    slider.max = String(data.series.t.length - 1);
    slider.value = "0";

    var g = data.scene.machine;
    var parts = [];
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
    window.GuidanceScene.render(scene, sceneData, frame, terrain);

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
          document.getElementById("slope_deg").value = info.side_slope_deg.toFixed(2);
          note.textContent =
            "Ground at " + info.elevation_m.toFixed(0) + " m. Driving on a heading of " +
            heading + " degrees gives a side slope of " + info.side_slope_deg.toFixed(2) +
            " degrees and " + Math.abs(info.along_slope_deg).toFixed(2) +
            " degrees along the line. Sampled from " + info.samples +
            " points at " + info.resolution_m + " m resolution. " + info.attribution + ".";
          var travel = parseFloat(document.getElementById("speed").value || 3) * 60;
          return window.GuidanceTerrain.loadImagery(here.lat, here.lon, travel);
        })
        .then(function (patch) {
          terrain = { patch: patch, map: window.GuidanceTerrain.mapper(patch, heading) };
          if (patch.tilesLoaded === 0) {
            terrain = null;
            document.getElementById("field-note").textContent +=
              " No imagery tiles were available, so the ground stays plain.";
          }
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
      scene.distance = Math.max(6, Math.min(120, scene.distance + ev.deltaY * 0.04));
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
