/* A small 3D view of the machine, written by hand.

   No library. The content security policy forbids loading one, and the
   geometry needed here is boxes and prisms, which is a few hundred lines of
   arithmetic. Faces are projected with a perspective camera, sorted back to
   front and filled flat. That is enough for solid shapes with no
   transparency, and it keeps the page dependency free.

   WHAT THIS IS AND IS NOT. The model underneath is planar: position, heading,
   steering angle and hitch angle. There is no roll, pitch or suspension, so
   this view shows a planar result in three dimensions rather than adding
   physics to it. The ground is tilted by the modelled side slope because that
   angle is a real input; the machine sits on the slope and does not lean
   relative to it, which is what the model says. */

(function () {
  "use strict";

  var COL = {
    ground: [214, 201, 172],
    grid: [190, 175, 143],
    line: [51, 41, 29],
    swath: [196, 150, 118],
    body: [76, 90, 58],
    cab: [96, 110, 76],
    glass: [173, 186, 160],
    tyre: [38, 33, 26],
    rim: [190, 175, 143],
    imp: [163, 90, 50],
    bar: [122, 66, 36]
  };
  var LIGHT = normalise([0.42, -0.55, 0.72]);

  function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
  function cross(a, b) {
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  }
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function normalise(v) {
    var n = Math.sqrt(dot(v, v)) || 1;
    return [v[0] / n, v[1] / n, v[2] / n];
  }
  function shade(rgb, n) {
    var k = 0.55 + 0.45 * Math.max(0, dot(n, LIGHT));
    return "rgb(" + Math.round(rgb[0] * k) + "," + Math.round(rgb[1] * k) + "," +
      Math.round(rgb[2] * k) + ")";
  }

  /* Place a point in machine coordinates into the world, then tilt the world
     by the side slope. Order matters: the machine is placed on flat ground and
     the whole scene is tilted, which is the same as driving across a slope. */
  function place(local, origin, yaw, tilt) {
    var c = Math.cos(yaw), s = Math.sin(yaw);
    var x = origin[0] + local[0] * c - local[1] * s;
    var y = origin[1] + local[0] * s + local[1] * c;
    var z = local[2];
    var ct = Math.cos(tilt), st = Math.sin(tilt);
    return [x, y * ct - z * st, y * st + z * ct];
  }

  function Scene(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.yaw = -0.72;
    this.pitch = 0.42;
    this.distance = 26;
    this.mode = "chase";
  }

  Scene.prototype.project = function (p, target, w, h) {
    var d = sub(p, target);
    var cy = Math.cos(this.yaw), sy = Math.sin(this.yaw);
    var x1 = d[0] * cy - d[1] * sy;
    var y1 = d[0] * sy + d[1] * cy;
    var cp = Math.cos(this.pitch), sp = Math.sin(this.pitch);
    var y2 = y1 * cp - d[2] * sp;
    var z2 = y1 * sp + d[2] * cp;
    var depth = z2 + this.distance;
    if (depth < 0.35) { return null; }
    var f = (h * 0.9) / depth;
    return { x: w / 2 + x1 * f, y: h / 2 - y2 * f, depth: depth };
  };

  Scene.prototype.draw = function (faces, target) {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    if (this.canvas.width !== w * dpr) {
      this.canvas.width = w * dpr;
      this.canvas.height = h * dpr;
    }
    var ctx = this.ctx;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "#EFE6D0";
    ctx.fillRect(0, 0, w, h);

    var self = this, drawable = [];
    faces.forEach(function (face) {
      var pts = [], sum = 0, ok = true;
      for (var i = 0; i < face.p.length; i++) {
        var q = self.project(face.p[i], target, w, h);
        if (!q) { ok = false; break; }
        pts.push(q);
        sum += q.depth;
      }
      if (!ok) { return; }
      drawable.push({ pts: pts, depth: sum / pts.length, face: face });
    });

    drawable.sort(function (a, b) { return b.depth - a.depth; });

    drawable.forEach(function (d) {
      var f = d.face, pts = d.pts;
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      for (var i = 1; i < pts.length; i++) { ctx.lineTo(pts[i].x, pts[i].y); }
      ctx.closePath();
      if (f.stroke) {
        ctx.strokeStyle = f.stroke;
        ctx.lineWidth = f.lineWidth || 1;
        ctx.stroke();
      } else {
        var n = normalise(cross(sub(f.p[1], f.p[0]), sub(f.p[2], f.p[0])));
        ctx.fillStyle = f.flat || shade(f.c, n);
        ctx.fill();
        if (f.edge) {
          ctx.strokeStyle = "rgba(35,28,20,0.28)";
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      }
    });
  };

  /* ---- primitives, in machine coordinates ---- */

  function box(out, cx, cy, cz, len, wid, hgt, colour, origin, yaw, tilt, localYaw) {
    var hx = len / 2, hy = wid / 2, hz = hgt / 2;
    var corners = [
      [-hx, -hy, -hz], [hx, -hy, -hz], [hx, hy, -hz], [-hx, hy, -hz],
      [-hx, -hy, hz], [hx, -hy, hz], [hx, hy, hz], [-hx, hy, hz]
    ].map(function (c) {
      var x = c[0], y = c[1];
      if (localYaw) {
        var cc = Math.cos(localYaw), ss = Math.sin(localYaw);
        x = c[0] * cc - c[1] * ss;
        y = c[0] * ss + c[1] * cc;
      }
      return place([cx + x, cy + y, cz + c[2]], origin, yaw, tilt);
    });
    [[0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 5, 4], [2, 3, 7, 6],
     [1, 2, 6, 5], [3, 0, 4, 7]].forEach(function (idx) {
      out.push({ p: idx.map(function (i) { return corners[i]; }), c: colour, edge: true });
    });
  }

  function wheel(out, cx, cy, radius, width, colour, origin, yaw, tilt, steer) {
    var sides = 12, hw = width / 2;
    var ring = [];
    for (var i = 0; i < sides; i++) {
      var a = (i / sides) * Math.PI * 2;
      ring.push([Math.cos(a) * radius, Math.sin(a) * radius]);
    }
    function pt(i, side) {
      var r = ring[i], x = r[0], y = side * hw;
      var cs = Math.cos(steer || 0), sn = Math.sin(steer || 0);
      return place([cx + x * cs - y * sn, cy + x * sn + y * cs, radius + r[1]],
        origin, yaw, tilt);
    }
    for (var j = 0; j < sides; j++) {
      var k = (j + 1) % sides;
      out.push({ p: [pt(j, -1), pt(k, -1), pt(k, 1), pt(j, 1)], c: colour });
    }
    out.push({ p: ring.map(function (_, i) { return pt(i, 1); }), c: COL.rim });
  }

  /* ---- the machine ---- */

  function buildMachine(out, g, pose, tilt) {
    var origin = [pose.x, pose.y];
    var yaw = pose.theta;
    var L = g.wheelbase.value;
    var track = g.track_width.value;
    var rw = g.rear_wheel, fw = g.front_wheel;
    var b = g.body;

    box(out, L * 0.46, 0, rw.diameter * 0.62, b.length * 0.72, b.width, b.height,
      COL.body, origin, yaw, tilt);
    box(out, L * 0.06, 0, rw.diameter * 0.62 + b.height * 0.78,
      b.length * 0.42, b.width * 0.94, b.height * 0.92, COL.cab, origin, yaw, tilt);
    box(out, L * 0.06, 0, rw.diameter * 0.62 + b.height * 1.34,
      b.length * 0.44, b.width * 0.98, 0.06, COL.glass, origin, yaw, tilt);

    wheel(out, 0, track / 2, rw.diameter / 2, rw.width, COL.tyre, origin, yaw, tilt, 0);
    wheel(out, 0, -track / 2, rw.diameter / 2, rw.width, COL.tyre, origin, yaw, tilt, 0);
    wheel(out, L, track / 2 * 0.92, fw.diameter / 2, fw.width, COL.tyre, origin, yaw, tilt, pose.delta);
    wheel(out, L, -track / 2 * 0.92, fw.diameter / 2, fw.width, COL.tyre, origin, yaw, tilt, pose.delta);

    if (!g.implement) { return; }

    var im = g.implement;
    var a = im.hitch_distance.value;
    var bb = im.implement_wheelbase.value;
    var width = im.working_width.value;
    var depth = im.frame_depth.value;

    // The hitch sits behind the rear axle in the tractor frame; the implement
    // hangs off it at its own heading, which is why it is built in world
    // coordinates rather than as a child of the tractor.
    var hx = pose.x - a * Math.cos(yaw);
    var hy = pose.y - a * Math.sin(yaw);
    var iyaw = pose.thetaImplement;
    var ix = hx - bb * Math.cos(iyaw);
    var iy = hy - bb * Math.sin(iyaw);

    box(out, bb / 2, 0, 0.55, bb, 0.18, 0.16, COL.bar, [hx, hy], iyaw, tilt, Math.PI);
    box(out, 0, 0, 0.62, depth, width, 0.28, COL.imp, [ix, iy], iyaw, tilt);
    box(out, 0, width / 2 - 0.12, 0.5, depth * 0.9, 0.24, 0.5, COL.bar, [ix, iy], iyaw, tilt);
    box(out, 0, -width / 2 + 0.12, 0.5, depth * 0.9, 0.24, 0.5, COL.bar, [ix, iy], iyaw, tilt);

    if (im.type === "trailed") {
      var tw = Math.min(width * 0.55, 3.2);
      wheel(out, -depth * 0.35, tw / 2, 0.52, 0.3, COL.tyre, [ix, iy], iyaw, tilt, 0);
      wheel(out, -depth * 0.35, -tw / 2, 0.52, 0.3, COL.tyre, [ix, iy], iyaw, tilt, 0);
    }
  }

  /* ---- ground, guidance line and worked swath ---- */

  function buildGround(out, centreX, tilt) {
    var half = 34, x0 = Math.floor((centreX - half) / 4) * 4;
    out.push({
      p: [place([x0 - 4, -half, 0], [0, 0], 0, tilt),
          place([x0 + half * 2, -half, 0], [0, 0], 0, tilt),
          place([x0 + half * 2, half, 0], [0, 0], 0, tilt),
          place([x0 - 4, half, 0], [0, 0], 0, tilt)],
      c: COL.ground
    });
    for (var gx = x0; gx < x0 + half * 2; gx += 4) {
      out.push({
        p: [place([gx, -half, 0.01], [0, 0], 0, tilt),
            place([gx, half, 0.01], [0, 0], 0, tilt)],
        stroke: "rgba(120,104,76,0.32)", lineWidth: 1
      });
    }
    for (var gy = -half; gy <= half; gy += 4) {
      out.push({
        p: [place([x0 - 4, gy, 0.01], [0, 0], 0, tilt),
            place([x0 + half * 2, gy, 0.01], [0, 0], 0, tilt)],
        stroke: "rgba(120,104,76,0.22)", lineWidth: 1
      });
    }
    for (var dx = x0; dx < x0 + half * 2; dx += 2) {
      out.push({
        p: [place([dx, 0, 0.03], [0, 0], 0, tilt),
            place([dx + 1.1, 0, 0.03], [0, 0], 0, tilt)],
        stroke: "rgba(35,28,20,0.85)", lineWidth: 2.5
      });
    }
  }

  function buildSwath(out, s, upTo, tilt, halfWidth) {
    var stepBack = Math.max(1, Math.floor(upTo / 160));
    for (var i = Math.max(0, upTo - 900); i < upTo - stepBack; i += stepBack) {
      var j = i + stepBack;
      var a = edgePair(s, i, halfWidth), b = edgePair(s, j, halfWidth);
      if (!a || !b) { continue; }
      out.push({
        p: [place([a.lx, a.ly, 0.02], [0, 0], 0, tilt),
            place([b.lx, b.ly, 0.02], [0, 0], 0, tilt),
            place([b.rx, b.ry, 0.02], [0, 0], 0, tilt),
            place([a.rx, a.ry, 0.02], [0, 0], 0, tilt)],
        flat: "rgba(163,90,50,0.30)"
      });
    }
  }

  function edgePair(s, i, halfWidth) {
    if (!s.theta_implement || s.x[i] === null) { return null; }
    var a = s.geomA, b = s.geomB;
    var th = s.theta[i], ti = s.theta_implement[i];
    var hx = s.x[i] - a * Math.cos(th), hy = s.y[i] - a * Math.sin(th);
    var ix = hx - b * Math.cos(ti), iy = hy - b * Math.sin(ti);
    var nx = -Math.sin(ti), ny = Math.cos(ti);
    return {
      lx: ix + nx * halfWidth, ly: iy + ny * halfWidth,
      rx: ix - nx * halfWidth, ry: iy - ny * halfWidth
    };
  }

  /* ---- public interface ---- */

  window.GuidanceScene = {
    create: function (canvas) { return new Scene(canvas); },
    render: function (scene, data, frame) {
      var s = data.series, g = data.scene.machine;
      var tilt = (data.scene.slope_deg || 0) * Math.PI / 180 * (data.scene.slope_sign || 1);
      var faces = [];

      var pose = {
        x: s.x[frame], y: s.y[frame], theta: s.theta[frame],
        delta: s.delta_rad[frame] || 0,
        thetaImplement: s.theta_implement ? s.theta_implement[frame] : s.theta[frame]
      };

      buildGround(faces, pose.x, tilt);
      if (g.implement) {
        s.geomA = g.implement.hitch_distance.value;
        s.geomB = g.implement.implement_wheelbase.value;
        buildSwath(faces, s, frame, tilt, g.implement.working_width.value / 2);
      }
      buildMachine(faces, g, pose, tilt);

      var target = place([pose.x, pose.y, 1.2], [0, 0], 0, tilt);
      if (scene.mode === "top") { scene.pitch = 1.45; }
      if (scene.mode === "side") { scene.pitch = 0.12; }
      scene.draw(faces, target);
      return pose;
    }
  };
})();
