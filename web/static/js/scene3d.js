/* A 3D view of the machine, written by hand.

   No library: the content security policy forbids loading one, and the shapes
   needed here are boxes and prisms.

   CAMERA. An earlier version rotated points by yaw and pitch directly and got
   both the views and the clipping wrong: "above" collapsed sixty metres of
   field into a few pixels, and depths could land near the clip plane where the
   projection scale runs to a thousand pixels per metre, so one dark tyre face
   would fill the screen. This builds a proper camera basis instead, and clips
   polygons against the near plane rather than discarding whole faces.

   WHAT THIS SHOWS. The model underneath is planar: position, heading, steering
   angle, hitch angle. There is no roll, pitch or suspension. The ground tilts
   because side slope is a real modelled input; the machine sits on the slope
   and does not lean relative to it, which is what the model says. */

(function () {
  "use strict";

  var NEAR = 0.6;

  var COL = {
    soil:      [206, 191, 160],
    soilWork:  [150, 124, 92],
    soilDark:  [186, 169, 137],
    line:      [46, 37, 26],
    body:      [74, 88, 56],
    bodyDark:  [58, 70, 44],
    hood:      [86, 100, 64],
    cab:       [64, 76, 50],
    glass:     [176, 190, 168],
    post:      [44, 52, 34],
    roof:      [92, 106, 70],
    tyre:      [46, 40, 32],
    lug:       [34, 29, 23],
    rim:       [176, 158, 120],
    hub:       [140, 124, 94],
    steel:     [108, 98, 82],
    imp:       [163, 90, 50],
    impDark:   [126, 68, 37],
    tool:      [78, 72, 62],
    shadow:    [120, 108, 86]
  };
  var LIGHT = unit([0.38, -0.48, 0.79]);

  function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
  function add(a, b) { return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]; }
  function mul(a, k) { return [a[0] * k, a[1] * k, a[2] * k]; }
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function cross(a, b) {
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  }
  function unit(v) { var n = Math.sqrt(dot(v, v)) || 1; return mul(v, 1 / n); }

  var SKY = [231, 220, 196];

  function hex(h) {
    if (!h) { return [110, 107, 100]; }
    h = h.replace("#", "");
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16),
            parseInt(h.slice(4, 6), 16)];
  }

  function mix(a, b, t) {
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
  }

  /* Lambert term, then a wash toward the background with distance. Without the
     wash every surface reads at full strength however far away it is, which is
     most of what made the first version look flat and toy-like. */
  function shade(rgb, n, k, depth) {
    var l = 0.46 + 0.54 * Math.max(0, dot(n, LIGHT));
    l *= (k === undefined ? 1 : k);
    var c = [rgb[0] * l, rgb[1] * l, rgb[2] * l];
    var fade = Math.min(0.5, Math.max(0, (depth - 12) / 150));
    c = mix(c, SKY, fade);
    return "rgb(" + Math.round(c[0]) + "," + Math.round(c[1]) + "," + Math.round(c[2]) + ")";
  }

  /* Machine coordinates into the world, then tilt the world by the slope. */
  function place(local, origin, yaw, tilt) {
    var c = Math.cos(yaw), s = Math.sin(yaw);
    var x = origin[0] + local[0] * c - local[1] * s;
    var y = origin[1] + local[0] * s + local[1] * c;
    var z = local[2];
    var ct = Math.cos(tilt), st = Math.sin(tilt);
    return [x, y * ct - z * st, y * st + z * ct];
  }

  /* ---------------- camera ---------------- */

  function Scene(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.mode = "chase";
    this.applyPreset("chase");
  }

  Scene.prototype.applyPreset = function (mode) {
    this.mode = mode;
    if (mode === "chase") { this.yaw = 0.0; this.pitch = 0.30; this.distance = 22; }
    if (mode === "side")  { this.yaw = Math.PI / 2; this.pitch = 0.06; this.distance = 32; }
    if (mode === "top")   { this.yaw = 0.0; this.pitch = 1.40; this.distance = 46; }
  };

  Scene.prototype.basis = function (target) {
    // Pitch is elevation above the horizon. Clamped below a right angle so the
    // right vector never degenerates when looking straight down.
    var pitch = Math.max(0.03, Math.min(1.48, this.pitch));
    var cp = Math.cos(pitch), sp = Math.sin(pitch);
    var eye = [
      target[0] - this.distance * cp * Math.cos(this.yaw),
      target[1] - this.distance * cp * Math.sin(this.yaw),
      target[2] + this.distance * sp
    ];
    var f = unit(sub(target, eye));
    var r = unit(cross(f, [0, 0, 1]));
    var u = cross(r, f);
    return { eye: eye, f: f, r: r, u: u };
  };

  /* Camera space, then Sutherland-Hodgman against the near plane, so a face
     that straddles the camera is trimmed rather than dropped or exploded. */
  function toCamera(p, b) {
    var v = sub(p, b.eye);
    return { x: dot(v, b.r), y: dot(v, b.u), z: dot(v, b.f) };
  }

  function clipNear(poly) {
    var out = [];
    for (var i = 0; i < poly.length; i++) {
      var a = poly[i], c = poly[(i + 1) % poly.length];
      var ain = a.z >= NEAR, cin = c.z >= NEAR;
      if (ain) { out.push(a); }
      if (ain !== cin) {
        var t = (NEAR - a.z) / (c.z - a.z);
        out.push({ x: a.x + (c.x - a.x) * t, y: a.y + (c.y - a.y) * t, z: NEAR });
      }
    }
    return out;
  }

  /* Paint a source triangle of the imagery onto a destination triangle.
     Canvas 2D only does affine transforms, so the ground is subdivided and
     each piece approximated. Small enough pieces and the perspective error
     disappears. */
  function texTriangle(ctx, img, s0, s1, s2, d0, d1, d2) {
    var du1 = s1[0] - s0[0], dv1 = s1[1] - s0[1];
    var du2 = s2[0] - s0[0], dv2 = s2[1] - s0[1];
    var det = du1 * dv2 - du2 * dv1;
    if (Math.abs(det) < 1e-9) { return; }
    var dx1 = d1[0] - d0[0], dy1 = d1[1] - d0[1];
    var dx2 = d2[0] - d0[0], dy2 = d2[1] - d0[1];
    var a = (dx1 * dv2 - dx2 * dv1) / det;
    var c = (du1 * dx2 - du2 * dx1) / det;
    var b = (dy1 * dv2 - dy2 * dv1) / det;
    var d = (du1 * dy2 - du2 * dy1) / det;
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(d0[0], d0[1]);
    ctx.lineTo(d1[0], d1[1]);
    ctx.lineTo(d2[0], d2[1]);
    ctx.closePath();
    ctx.clip();
    ctx.transform(a, b, c, d, d0[0] - a * s0[0] - c * s0[1], d0[1] - b * s0[0] - d * s0[1]);
    ctx.drawImage(img, 0, 0);
    ctx.restore();
  }

  /* The aerial photograph, drawn before everything else because it is the
     ground plane and nothing can be under it. */
  Scene.prototype.drawGround = function (ctx, terrain, b, focal, w, h, cx, tilt) {
    var step = 8, halfY = 56, back = 55, fwd = 120;
    var map = terrain.map, img = terrain.patch.image;
    var maxU = terrain.patch.pixels, maxV = terrain.patch.pixels;

    function screen(x, y) {
      var p = place([x, y, 0], [0, 0], 0, tilt);
      var v = sub(p, b.eye);
      var z = dot(v, b.f);
      if (z < NEAR) { return null; }
      return [w / 2 + dot(v, b.r) * focal / z, h / 2 - dot(v, b.u) * focal / z];
    }

    // The far field, under the photograph rather than over it, so the ground
    // still reaches the horizon where the imagery runs out.
    var far = [screen(cx - 400, -400), screen(cx + 400, -400),
               screen(cx + 400, 400), screen(cx - 400, 400)];
    if (far.every(Boolean)) {
      ctx.beginPath();
      ctx.moveTo(far[0][0], far[0][1]);
      for (var f = 1; f < far.length; f++) { ctx.lineTo(far[f][0], far[f][1]); }
      ctx.closePath();
      ctx.fillStyle = "rgb(185,172,144)";
      ctx.fill();
    }

    for (var x = cx - back; x < cx + fwd; x += step) {
      for (var y = -halfY; y < halfY; y += step) {
        var s00 = map(x, y), s10 = map(x + step, y);
        var s11 = map(x + step, y + step), s01 = map(x, y + step);
        if (Math.min(s00[0], s10[0], s11[0], s01[0]) < 0 ||
            Math.max(s00[0], s10[0], s11[0], s01[0]) > maxU ||
            Math.min(s00[1], s10[1], s11[1], s01[1]) < 0 ||
            Math.max(s00[1], s10[1], s11[1], s01[1]) > maxV) { continue; }
        var d00 = screen(x, y), d10 = screen(x + step, y);
        var d11 = screen(x + step, y + step), d01 = screen(x, y + step);
        if (!d00 || !d10 || !d11 || !d01) { continue; }
        texTriangle(ctx, img, s00, s10, s11, d00, d10, d11);
        texTriangle(ctx, img, s00, s11, s01, d00, d11, d01);
      }
    }
  };

  Scene.prototype.draw = function (faces, target, terrain, cx, tilt) {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    if (!w || !h) { return; }
    if (this.canvas.width !== Math.round(w * dpr)) {
      this.canvas.width = Math.round(w * dpr);
      this.canvas.height = Math.round(h * dpr);
    }
    var ctx = this.ctx;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#E7DCC4";
    ctx.fillRect(0, 0, w, h);

    var b = this.basis(target);
    var focal = h * 0.86;

    if (terrain && terrain.patch && terrain.map) {
      this.drawGround(ctx, terrain, b, focal, w, h, cx, tilt);
    }

    var list = [];

    for (var i = 0; i < faces.length; i++) {
      var face = faces[i];
      var cam = [];
      for (var j = 0; j < face.p.length; j++) { cam.push(toCamera(face.p[j], b)); }

      if (face.cull !== false && face.p.length >= 3) {
        // Backface culling. With painter's algorithm this removes most of the
        // overdraw that made interior faces flicker through the surface.
        var n = cross(sub(face.p[1], face.p[0]), sub(face.p[2], face.p[0]));
        if (dot(n, sub(face.p[0], b.eye)) > 0) { continue; }
      }

      var poly = face.line ? cam.filter(function (q) { return q.z >= NEAR; }) : clipNear(cam);
      if (poly.length < (face.line ? 2 : 3)) { continue; }

      var pts = [], zsum = 0;
      for (var k = 0; k < poly.length; k++) {
        var q = poly[k];
        pts.push({ x: w / 2 + q.x * focal / q.z, y: h / 2 - q.y * focal / q.z });
        zsum += q.z;
      }
      list.push({ pts: pts, depth: zsum / poly.length, face: face });
    }

    list.sort(function (a, b2) { return b2.depth - a.depth; });

    for (var m = 0; m < list.length; m++) {
      var d = list[m], f = d.face, pts = d.pts;
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      for (var q2 = 1; q2 < pts.length; q2++) { ctx.lineTo(pts[q2].x, pts[q2].y); }
      if (f.line) {
        ctx.strokeStyle = f.stroke;
        ctx.lineWidth = f.width || 1;
        ctx.stroke();
      } else {
        ctx.closePath();
        if (f.flat) {
          ctx.fillStyle = f.flat;
        } else {
          var nn = unit(cross(sub(f.p[1], f.p[0]), sub(f.p[2], f.p[0])));
          ctx.fillStyle = shade(f.c, nn, f.k, d.depth);
        }
        ctx.fill();
      }
    }
  };

  /* ---------------- primitives ---------------- */

  function quad(out, a, b, c, d, colour, k) {
    out.push({ p: [a, b, c, d], c: colour, k: k });
  }

  /* A box, optionally tapered along its length, which is what makes a bonnet
     read as a bonnet rather than a crate. */
  function box(out, o, yaw, tilt, cx, cy, cz, len, wid, hgt, colour, opts) {
    opts = opts || {};
    var taper = opts.taper === undefined ? 1 : opts.taper;
    var drop = opts.drop || 0;
    var hx = len / 2, hy = wid / 2;
    function v(sx, sy, sz) {
      var t = sx > 0 ? taper : 1;
      var top = sz > 0 ? hgt - (sx > 0 ? drop : 0) : 0;
      return place([cx + sx * hx, cy + sy * hy * t, cz + top], o, yaw, tilt);
    }
    var p000 = v(-1, -1, 0), p100 = v(1, -1, 0), p110 = v(1, 1, 0), p010 = v(-1, 1, 0);
    var p001 = v(-1, -1, 1), p101 = v(1, -1, 1), p111 = v(1, 1, 1), p011 = v(-1, 1, 1);
    quad(out, p010, p110, p100, p000, colour, 0.72);
    quad(out, p001, p101, p111, p011, colour, 1.0);
    quad(out, p000, p100, p101, p001, colour, 0.86);
    quad(out, p110, p010, p011, p111, colour, 0.86);
    quad(out, p100, p110, p111, p101, colour, 0.94);
    quad(out, p010, p000, p001, p011, colour, 0.78);
  }

  /* A wheel with tread lugs and a visible rim. */
  function wheel(out, o, yaw, tilt, cx, cy, radius, width, steer, detail, rimCol) {
    var sides = detail ? 16 : 10, hw = width / 2;
    var c = Math.cos(steer || 0), s = Math.sin(steer || 0);
    function pt(ang, r, side) {
      var x = Math.cos(ang) * r, z = Math.sin(ang) * r, y = side * hw;
      return place([cx + x * c - y * s, cy + x * s + y * c, radius + z], o, yaw, tilt);
    }
    for (var i = 0; i < sides; i++) {
      var a0 = (i / sides) * Math.PI * 2, a1 = ((i + 1) / sides) * Math.PI * 2;
      quad(out, pt(a0, radius, -1), pt(a1, radius, -1), pt(a1, radius, 1), pt(a0, radius, 1),
        COL.tyre, 0.95);
      if (detail && i % 2 === 0) {
        // Lugs, angled the way an agricultural tread is.
        var lr = radius * 1.055;
        quad(out, pt(a0, lr, -0.98), pt(a1, lr, -0.2), pt(a1, radius, -0.2), pt(a0, radius, -0.98),
          COL.lug, 1.0);
        quad(out, pt(a0, radius, 0.2), pt(a1, radius, 0.98), pt(a1, lr, 0.98), pt(a0, lr, 0.2),
          COL.lug, 1.0);
      }
    }
    var rimR = radius * 0.58, face = [], hubFace = [];
    for (var j = 0; j < sides; j++) {
      face.push(pt((j / sides) * Math.PI * 2, rimR, 1.01));
      hubFace.push(pt((j / sides) * Math.PI * 2, rimR * 0.34, 1.02));
    }
    out.push({ p: face, c: rimCol || COL.rim, k: 1.0, cull: false });
    out.push({ p: hubFace, c: mix(rimCol || COL.rim, [0, 0, 0], 0.35), k: 1.0, cull: false });
  }

  /* ---------------- the tractor ---------------- */

  /* Laid out from the two things that are actually known: the wheelbase and
     the wheel diameters. Everything is placed relative to the axles, because
     that is how a tractor is arranged. An earlier version measured the bonnet
     from its own length and pushed the grille more than a metre in front of
     the front wheels. */
  function buildTractor(out, g, pose, tilt) {
    var o = [pose.x, pose.y], yaw = pose.theta;
    var L = g.wheelbase.value, track = g.track_width.value;
    var rw = g.rear_wheel, fw = g.front_wheel;
    var pr = g.profile || {};

    var body = hex(g.livery.body);
    var trim = hex(g.livery.trim);
    var rim = hex(g.livery.wheel);
    var roof = hex(g.livery.roof);
    var bodyLit = mix(body, [255, 255, 255], 0.12);
    var bodyLow = mix(body, [0, 0, 0], 0.30);

    var rAxle = rw.diameter / 2, fAxle = fw.diameter / 2;
    var deck = rAxle * 0.80;                    // top of the chassis rails
    var hoodW = track * 0.54;
    var hoodH = Math.max(0.62, rAxle * 0.78);
    var cabW = track * 0.76;
    var cabH = (pr.cab_height || 1.18) * rAxle * 1.35;

    // Chassis, from behind the rear axle to the front axle.
    box(out, o, yaw, tilt, L * 0.42, 0, deck * 0.46, L * 1.30, track * 0.34,
      deck * 0.42, trim);

    // Bonnet: from the front of the cab to the front axle, and no further.
    var hoodBack = L * 0.50, hoodFront = L * 1.00;
    var hoodLen = hoodFront - hoodBack;
    box(out, o, yaw, tilt, (hoodBack + hoodFront) / 2, 0, deck, hoodLen, hoodW, hoodH,
      body, { taper: pr.bonnet_taper || 0.78, drop: hoodH * (pr.bonnet_drop || 0.28) });
    // Top panel, so the bonnet has a shoulder instead of one flat face.
    box(out, o, yaw, tilt, (hoodBack + hoodFront) / 2 - hoodLen * 0.08, 0,
      deck + hoodH * 0.86, hoodLen * 0.72, hoodW * 0.86, hoodH * 0.2, bodyLit);

    // Grille and lamps at the nose, level with the front axle.
    box(out, o, yaw, tilt, hoodFront + 0.06, 0, deck + hoodH * 0.18, 0.1,
      hoodW * 0.82, hoodH * 0.52, trim);
    [1, -1].forEach(function (side) {
      box(out, o, yaw, tilt, hoodFront + 0.04, side * hoodW * 0.3,
        deck + hoodH * 0.7, 0.09, 0.16, 0.11, [244, 238, 208]);
    });
    if (pr.front_weights) {
      box(out, o, yaw, tilt, L * 1.16, 0, deck * 0.72, 0.32, hoodW * 0.9,
        hoodH * 0.5, trim);
    }

    // Cab, sitting between the axles and over the rear one.
    var cabLen = L * 0.50, cabX = L * 0.22, cabZ = deck + hoodH * 0.16;
    box(out, o, yaw, tilt, cabX, 0, cabZ, cabLen, cabW, 0.09, bodyLow);
    [[cabLen / 2, cabW / 2], [cabLen / 2, -cabW / 2],
     [-cabLen / 2, cabW / 2], [-cabLen / 2, -cabW / 2]].forEach(function (c) {
      box(out, o, yaw, tilt, cabX + c[0], c[1], cabZ, 0.075, 0.075, cabH, trim);
    });
    function pane(ax, ay, bx, by) {
      quad(out,
        place([ax, ay, cabZ + 0.09], o, yaw, tilt),
        place([bx, by, cabZ + 0.09], o, yaw, tilt),
        place([bx, by, cabZ + cabH * 0.94], o, yaw, tilt),
        place([ax, ay, cabZ + cabH * 0.94], o, yaw, tilt), COL.glass, 0.95);
    }
    pane(cabX + cabLen / 2, cabW / 2, cabX + cabLen / 2, -cabW / 2);
    pane(cabX - cabLen / 2, -cabW / 2, cabX - cabLen / 2, cabW / 2);
    pane(cabX - cabLen / 2, cabW / 2, cabX + cabLen / 2, cabW / 2);
    pane(cabX + cabLen / 2, -cabW / 2, cabX - cabLen / 2, -cabW / 2);
    box(out, o, yaw, tilt, cabX, 0, cabZ + cabH * 0.94, cabLen * 1.14, cabW * 1.16,
      0.11, roof);
    box(out, o, yaw, tilt, cabX + cabLen * 0.42, 0, cabZ + cabH * 0.94 + 0.11,
      0.1, 0.1, 0.09, [216, 152, 42]);

    // Exhaust up the right of the bonnet, against the cab pillar.
    if (pr.exhaust === "stack" || pr.exhaust === "stack_short") {
      var eh = cabH * (pr.exhaust === "stack" ? 0.82 : 0.5);
      box(out, o, yaw, tilt, hoodBack + 0.12, hoodW * 0.46, deck + hoodH * 0.5,
        0.1, 0.1, eh, trim);
    }

    if (pr.fenders !== false) {
      [1, -1].forEach(function (side) {
        box(out, o, yaw, tilt, 0, side * (track / 2 - rw.width * 0.06), rAxle * 1.06,
          rw.diameter * 0.96, rw.width * 1.28, 0.1, bodyLow);
      });
    }

    // Drawbar behind the rear axle.
    box(out, o, yaw, tilt, -L * 0.20, 0, deck * 0.36, L * 0.40, 0.12, 0.1, trim);

    wheel(out, o, yaw, tilt, 0, track / 2, rAxle, rw.width, 0, true, rim);
    wheel(out, o, yaw, tilt, 0, -track / 2, rAxle, rw.width, 0, true, rim);
    wheel(out, o, yaw, tilt, L, track / 2 * 0.88, fAxle, fw.width, pose.delta, true, rim);
    wheel(out, o, yaw, tilt, L, -track / 2 * 0.88, fAxle, fw.width, pose.delta, true, rim);
  }

  /* A soft footprint on the ground. Without it the machine reads as floating,
     which was most of the remaining toy-like quality. */
  function buildShadow(out, o, yaw, tilt, len, wid, cx) {
    var off = 0.35;
    function s2(x, y) { return place([cx + x + off, y - off, 0.045], o, yaw, tilt); }
    out.push({ p: [s2(-len / 2, -wid / 2), s2(len / 2, -wid / 2),
                   s2(len / 2, wid / 2), s2(-len / 2, wid / 2)],
               flat: "rgba(72,58,40,0.22)", cull: false });
  }

  /* ---------------- the implement ---------------- */

  function buildImplement(out, im, hx, hy, ix, iy, yawT, yawI, tilt) {
    var lv = im.livery || {};
    var main = hex(lv.body || "#A35A32");
    var dark = mix(main, [0, 0, 0], 0.32);
    var steel = hex(lv.trim || "#6C6252");
    var width = im.working_width.value;
    var depth = im.frame_depth.value;
    var bb = im.implement_wheelbase.value;
    var o = [ix, iy];

    // Drawbar from the tractor hitch back to the implement frame, drawn in the
    // implement frame so it swings with the hitch angle.
    box(out, [hx, hy], yawI, tilt, -bb / 2, 0, 0.62, bb, 0.16, 0.14, dark);
    // Hitch clevis at the tractor end.
    box(out, [hx, hy], yawT, tilt, 0.06, 0, 0.6, 0.24, 0.2, 0.2, steel);

    // Main frame and the two wing spars.
    box(out, o, yawI, tilt, 0, 0, 0.66, depth * 0.5, width, 0.22, main);
    box(out, o, yawI, tilt, depth * 0.42, 0, 0.7, 0.18, width * 0.96, 0.16, dark);
    box(out, o, yawI, tilt, -depth * 0.42, 0, 0.7, 0.16, width * 0.96, 0.16, dark);

    // Working tools along the bar. The count scales with width, capped so a
    // twenty metre machine does not cost a thousand faces.
    var kind = (im.draft_class || "") + " " + (im.type || "");
    var n = Math.max(6, Math.min(28, Math.round(width * 1.6)));
    for (var i = 0; i < n; i++) {
      var y = -width / 2 + (i + 0.5) * (width / n);
      if (/planter/.test(kind)) {
        // Row unit: a body hanging off the bar with an opener disc.
        box(out, o, yawI, tilt, -depth * 0.22, y, 0.26, depth * 0.46, 0.26, 0.44, dark);
        wheel(out, o, yawI, tilt, -depth * 0.44, y, 0.22, 0.06, 0, false, steel);
      } else if (/disk|disc|catros|joker|turbomax|excelerator/.test(kind)) {
        wheel(out, o, yawI, tilt, depth * 0.2, y, 0.28, 0.045, 0.32, false, steel);
        wheel(out, o, yawI, tilt, -depth * 0.24, y, 0.28, 0.045, -0.32, false, steel);
      } else if (/laserweeder|verdant|sharpshooter/.test(kind)) {
        box(out, o, yawI, tilt, 0, y, 0.74, depth * 0.58, width / n * 0.78, 0.32, dark);
      } else {
        box(out, o, yawI, tilt, -depth * 0.1, y, 0.14, 0.1, 0.09, 0.52, dark);
        box(out, o, yawI, tilt, -depth * 0.14, y, 0.05, 0.26, 0.12, 0.1, steel);
      }
    }

    if (im.type === "trailed") {
      var tw = Math.min(width * 0.5, 3.4);
      wheel(out, o, yawI, tilt, -depth * 0.55, tw / 2, 0.55, 0.32, 0, true, steel);
      wheel(out, o, yawI, tilt, -depth * 0.55, -tw / 2, 0.55, 0.32, 0, true, steel);
    }

    // Edge markers, so the working edge the metric refers to is visible.
    [1, -1].forEach(function (side) {
      box(out, o, yawI, tilt, 0, side * width / 2, 0.66, depth * 0.6, 0.1, 0.95, dark);
    });
  }

  /* ---------------- ground ---------------- */

  function buildGround(out, cx, tilt, width, textured) {
    var half = 60, x0 = Math.floor((cx - 50) / 5) * 5;
    var x1 = x0 + 190;
    function g(x, y, z) { return place([x, y, z || 0], [0, 0], 0, tilt); }

    // A large base plane, so the drawn field does not simply stop with the
    // page background showing through as a pale ridge along both sides.
    //
    // ONLY when there is no photograph. This quad is opaque and lives in the
    // depth-sorted list, which is drawn AFTER the imagery background pass, so
    // including it here painted straight over the aerial photograph and made
    // the imagery look as though it had never loaded.
    if (!textured) {
      out.push({ p: [g(cx - 400, -400, -0.02), g(cx + 400, -400, -0.02),
                     g(cx + 400, 400, -0.02), g(cx - 400, 400, -0.02)],
                 c: COL.soil, k: 0.9, cull: false });
    }

    if (!textured) {
      for (var gx = x0; gx < x1; gx += 8) {
        for (var gy = -half; gy < half; gy += 8) {
          var band = Math.abs(gy) < (width || 0) / 2 ? COL.soilDark : COL.soil;
          out.push({ p: [g(gx, gy), g(gx + 8, gy), g(gx + 8, gy + 8), g(gx, gy + 8)],
                     c: band, k: 0.97 + ((gx + gy) % 16 === 0 ? 0.03 : 0), cull: false });
        }
      }
      // Drill rows, for a sense of scale and direction of travel.
      for (var ry = -half; ry <= half; ry += 0.76) {
        out.push({ p: [g(x0, ry, 0.012), g(x1, ry, 0.012)], line: true,
                   stroke: "rgba(120,100,72,0.16)", width: 1 });
      }
    }
    // The guidance line, dashed.
    for (var dx = x0; dx < x1; dx += 2.4) {
      out.push({ p: [g(dx, 0, 0.05), g(dx + 1.3, 0, 0.05)], line: true,
                 stroke: "rgba(40,32,22,0.92)", width: 3 });
    }
    // Where the neighbouring passes should meet this one.
    if (width) {
      [width / 2, -width / 2].forEach(function (y) {
        out.push({ p: [g(x0, y, 0.04), g(x1, y, 0.04)], line: true,
                   stroke: "rgba(40,32,22,0.34)", width: 1.6 });
      });
    }
  }

  function edgePair(s, i, a, b, halfWidth) {
    if (s.x[i] === null || !s.theta_implement) { return null; }
    var th = s.theta[i], ti = s.theta_implement[i];
    var hx = s.x[i] - a * Math.cos(th), hy = s.y[i] - a * Math.sin(th);
    var ix = hx - b * Math.cos(ti), iy = hy - b * Math.sin(ti);
    var nx = -Math.sin(ti), ny = Math.cos(ti);
    return { lx: ix + nx * halfWidth, ly: iy + ny * halfWidth,
             rx: ix - nx * halfWidth, ry: iy - ny * halfWidth };
  }

  function buildSwath(out, s, upTo, tilt, a, b, halfWidth) {
    var step = Math.max(1, Math.floor(upTo / 130));
    for (var i = Math.max(0, upTo - 1100); i < upTo - step; i += step) {
      var p = edgePair(s, i, a, b, halfWidth), q = edgePair(s, i + step, a, b, halfWidth);
      if (!p || !q) { continue; }
      out.push({
        p: [place([p.lx, p.ly, 0.03], [0, 0], 0, tilt),
            place([q.lx, q.ly, 0.03], [0, 0], 0, tilt),
            place([q.rx, q.ry, 0.03], [0, 0], 0, tilt),
            place([p.rx, p.ry, 0.03], [0, 0], 0, tilt)],
        c: COL.soilWork, k: 1.0, cull: false
      });
    }
  }

  function buildTracks(out, s, upTo, tilt, track) {
    var step = Math.max(1, Math.floor(upTo / 90));
    for (var i = Math.max(0, upTo - 900); i < upTo - step; i += step) {
      if (s.x[i] === null) { continue; }
      [1, -1].forEach(function (side) {
        var th = s.theta[i], th2 = s.theta[i + step];
        var nx = -Math.sin(th) * side * track / 2, ny = Math.cos(th) * side * track / 2;
        var mx = -Math.sin(th2) * side * track / 2, my = Math.cos(th2) * side * track / 2;
        out.push({
          p: [place([s.x[i] + nx, s.y[i] + ny, 0.035], [0, 0], 0, tilt),
              place([s.x[i + step] + mx, s.y[i + step] + my, 0.035], [0, 0], 0, tilt)],
          line: true, stroke: "rgba(92,74,51,0.5)", width: 3
        });
      });
    }
  }

  /* ---------------- public interface ---------------- */

  window.GuidanceScene = {
    create: function (canvas) { return new Scene(canvas); },
    render: function (scene, data, frame, terrain) {
      var s = data.series, g = data.scene.machine;
      var tilt = (data.scene.slope_deg || 0) * Math.PI / 180 * (data.scene.slope_sign || 1);
      var faces = [];
      var im = g.implement;

      var pose = {
        x: s.x[frame], y: s.y[frame], theta: s.theta[frame],
        delta: s.delta_rad[frame] || 0,
        thetaImplement: s.theta_implement ? s.theta_implement[frame] : s.theta[frame]
      };

      var textured = !!(terrain && terrain.patch && terrain.map);
      buildGround(faces, pose.x, tilt, im ? im.working_width.value : 0, textured);
      if (im) {
        buildSwath(faces, s, frame, tilt, im.hitch_distance.value,
          im.implement_wheelbase.value, im.working_width.value / 2);
      }
      buildTracks(faces, s, frame, tilt, g.track_width.value);
      buildShadow(faces, [pose.x, pose.y], pose.theta, tilt,
        g.wheelbase.value * 1.7, g.track_width.value * 1.05, g.wheelbase.value * 0.45);
      buildTractor(faces, g, pose, tilt);

      if (im) {
        var a = im.hitch_distance.value, b = im.implement_wheelbase.value;
        var hx = pose.x - a * Math.cos(pose.theta), hy = pose.y - a * Math.sin(pose.theta);
        var ix = hx - b * Math.cos(pose.thetaImplement);
        var iy = hy - b * Math.sin(pose.thetaImplement);
        buildShadow(faces, [ix, iy], pose.thetaImplement, tilt,
          im.frame_depth.value * 1.2, im.working_width.value, 0);
        buildImplement(faces, im, hx, hy, ix, iy, pose.theta, pose.thetaImplement, tilt);
      }

      var back = im ? (im.hitch_distance.value + im.implement_wheelbase.value) * 0.5 : 0;
      var target = place([pose.x - back * Math.cos(pose.theta),
                          pose.y - back * Math.sin(pose.theta), 1.4], [0, 0], 0, tilt);
      scene.draw(faces, target, terrain, pose.x, tilt);
      return pose;
    }
  };
})();
