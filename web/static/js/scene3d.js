/* WebGL view of the machine, written by hand.

   This replaces a canvas 2D renderer that had reached its ceiling. That one
   sorted faces by centroid and filled each as a path, which meant three
   standing problems: intersecting geometry could sort wrongly, every surface
   was shaded flat, and the aerial photograph had to be mapped affinely over
   small quads because canvas has no projective transform. It was also slow,
   because a frame was a thousand path fills.

   A depth buffer fixes the sorting, a fragment shader gives per-pixel
   lighting, texture coordinates are perspective correct for free, and the
   whole frame is four draw calls instead of a thousand fills.

   No library. The maths it needs is in glmath.js and comes to seventy lines.

   WHAT THIS SHOWS. The model underneath is planar: position, heading, steering
   angle, hitch angle. There is no roll, pitch or suspension. The ground tilts
   because side slope is a real modelled input; the machine sits on the slope
   and does not lean relative to it, which is what the model says. */

(function () {
  "use strict";

  var SOLID_VS = [
    "attribute vec3 aPos; attribute vec3 aNormal; attribute vec3 aColour;",
    "uniform mat4 uViewProj;",
    "varying vec3 vNormal; varying vec3 vColour; varying float vDepth;",
    "void main() {",
    "  vNormal = aNormal; vColour = aColour;",
    "  vec4 clip = uViewProj * vec4(aPos, 1.0);",
    "  vDepth = clip.w;",
    "  gl_Position = clip;",
    "}"
  ].join("\n");

  var SOLID_FS = [
    "precision mediump float;",
    "uniform vec3 uLight; uniform vec3 uFog; uniform float uFogStart;",
    "uniform float uFogRange;",
    "varying vec3 vNormal; varying vec3 vColour; varying float vDepth;",
    "void main() {",
    "  vec3 n = normalize(vNormal);",
    // Two sided, because faces are not culled: a back face lit from
    // behind would otherwise render black.
    "  if (!gl_FrontFacing) { n = -n; }",
    "  float lambert = max(dot(n, uLight), 0.0);",
    "  vec3 base = vColour * (0.42 + 0.58 * lambert);",
    // A sky term, so upward faces pick up light even when facing away.
    "  base += vColour * 0.10 * max(n.z, 0.0);",
    "  float spec = pow(lambert, 26.0) * 0.35;",
    "  base += vec3(spec);",
    "  float fog = clamp((vDepth - uFogStart) / uFogRange, 0.0, 0.45);",
    "  gl_FragColor = vec4(mix(base, uFog, fog), 1.0);",
    "}"
  ].join("\n");

  var GROUND_VS = [
    "attribute vec3 aPos; attribute vec3 aNormal; attribute vec2 aUV;",
    "uniform mat4 uViewProj;",
    "varying vec3 vNormal; varying vec2 vUV; varying float vDepth;",
    "varying vec2 vWorld;",
    "void main() {",
    "  vNormal = aNormal; vUV = aUV; vWorld = aPos.xy;",
    "  vec4 clip = uViewProj * vec4(aPos, 1.0);",
    "  vDepth = clip.w;",
    "  gl_Position = clip;",
    "}"
  ].join("\n");

  var GROUND_FS = [
    "precision mediump float;",
    "uniform sampler2D uTex; uniform vec3 uLight; uniform vec3 uFog;",
    "uniform float uFogStart; uniform vec3 uTint; uniform float uUseTex;",
    "uniform float uGrid; uniform float uFogRange;",
    "varying vec3 vNormal; varying vec2 vUV; varying float vDepth;",
    "varying vec2 vWorld;",
    // A five metre grid, drawn from world position so it is a real measure of
    // the ground rather than a texture that happens to have lines on it. The
    // line fades with distance so it never turns the far field into moire.
    "float gridLine(vec2 p, float spacing) {",
    "  vec2 g = abs(fract(p / spacing - 0.5) - 0.5) * spacing;",
    "  float d = min(g.x, g.y);",
    "  return 1.0 - smoothstep(0.0, 0.16, d);",
    "}",
    "void main() {",
    "  vec3 n = normalize(vNormal);",
    "  vec3 albedo = mix(uTint, texture2D(uTex, vUV).rgb, uUseTex);",
    // Standing stubble on ground that has not been worked. Two combed bands at
    // an angle to each other break up what was otherwise a flat wash of one
    // colour across hundreds of metres. Skipped entirely where a real
    // photograph is draped, because the photograph already has ground in it.
    // Faded out with distance. A 20 cm pattern seen from 300 m is finer than
    // a pixel, and drawing it anyway turns the far field into a shimmering
    // moire that moves when the camera does.
    "  if (uUseTex < 0.5) {",
    "    float near = 1.0 - clamp(vDepth / (uFogStart * 1.8), 0.0, 1.0);",
    "    float c = sin(vWorld.y * 5.6) * 0.5 + sin(vWorld.x * 0.9 + vWorld.y * 3.1) * 0.5;",
    "    albedo *= 1.0 + 0.06 * c * near;",
    "  }",
    "  float g = gridLine(vWorld, 5.0) * uGrid * (1.0 - clamp(vDepth / (uFogStart * 2.6), 0.0, 0.85));",
    "  albedo = mix(albedo, vec3(0.98, 0.96, 0.90), g * 0.30);",
    "  float lambert = max(dot(n, uLight), 0.0);",
    "  vec3 base = albedo * (0.55 + 0.45 * lambert);",
    "  float fog = clamp((vDepth - uFogStart) / uFogRange, 0.0, 0.45);",
    "  gl_FragColor = vec4(mix(base, uFog, fog), 1.0);",
    "}"
  ].join("\n");

  /* A graded sky. A single flat clear colour met the ground in a hard line
     that read as the edge of the model rather than as distance. */
  var SKY_VS = [
    "attribute vec2 aPos; varying float vY;",
    "void main() { vY = aPos.y * 0.5 + 0.5; gl_Position = vec4(aPos, 0.999, 1.0); }"
  ].join("\n");

  var SKY_FS = [
    "precision mediump float; varying float vY;",
    "uniform vec3 uLow; uniform vec3 uHigh;",
    "void main() { gl_FragColor = vec4(mix(uLow, uHigh, pow(vY, 0.75)), 1.0); }"
  ].join("\n");

  var FLAT_VS = [
    "attribute vec3 aPos; uniform mat4 uViewProj;",
    "void main() { gl_Position = uViewProj * vec4(aPos, 1.0); }"
  ].join("\n");

  var FLAT_FS = [
    "precision mediump float; uniform vec4 uColour;",
    "void main() { gl_FragColor = uColour; }"
  ].join("\n");

  var LIGHT = normalise([0.40, -0.46, 0.79]);
  var FOG = [0.80, 0.83, 0.79];
  // The horizon matches the fog exactly, so ground and sky meet without a seam.
  var SKY_LOW = FOG;
  var SKY_HIGH = [0.56, 0.68, 0.80];

  var COL = {
    soil: [0.74, 0.69, 0.58],
    // Freshly worked ground is much darker than the stubble beside it. The two
    // were close enough in value that on a wide shot, once fog had washed both
    // toward grey, the worked strip and the unworked strip read as one colour
    // and the whole point of the picture was lost.
    worked: [0.31, 0.24, 0.17],
    glass: [0.62, 0.68, 0.62],
    tyre: [0.13, 0.11, 0.09],
    lug: [0.09, 0.08, 0.06],
    steel: [0.42, 0.39, 0.33],
    lamp: [0.96, 0.93, 0.80],
    beacon: [0.85, 0.60, 0.16],
    // The same olive and clay the charts use, so a colour means one thing
    // everywhere in this interface.
    guide: [0.99, 0.85, 0.28],      // the line being followed right now
    guideIdle: [0.86, 0.82, 0.70],  // the lines waiting their turn
    headland: [0.52, 0.44, 0.31],
    row: [0.21, 0.16, 0.11],
    trackTractor: [0.24, 0.33, 0.16],
    trackImplement: [0.55, 0.24, 0.09]
  };

  function normalise(v) {
    var n = Math.hypot(v[0], v[1], v[2]) || 1;
    return [v[0] / n, v[1] / n, v[2] / n];
  }
  function hex(h) {
    if (!h) { return [0.43, 0.42, 0.39]; }
    h = h.replace("#", "");
    return [parseInt(h.slice(0, 2), 16) / 255, parseInt(h.slice(2, 4), 16) / 255,
            parseInt(h.slice(4, 6), 16) / 255];
  }
  function mixc(a, b, t) {
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
  }

  /* Machine coordinates into the world, then tilt the world by the slope. */
  /* Real ground height, when a field has been read. Held at module scope
     because every placement has to agree about where the ground is: if the
     swath used the terrain and the tracks did not, they would separate.

     HEIGHT_LOCK pins the height to a single value while the machine is being
     built. Sampling per vertex there would bend the tractor over the hill it
     is standing on; a machine is rigid and sits at one height. */
  var HEIGHT_AT = null;
  var HEIGHT_LOCK = null;
  var MESH = null;
  var BODY_PLANE = null;

  /* A rigid machine standing on sloping ground.

     Pinning the whole outfit to the height under the rear axle is right for
     the height and wrong for everything else: at nine degrees the ground under
     the front axle is 0.44 m from the ground under the rear, and a wheel is
     about a metre across, so the front tyres bury themselves to the hub. The
     implement, six metres further back again, is worse.

     So the outfit stands on a PLANE fitted to the ground beneath it, rather
     than on a single number. One plane for the whole outfit, not one per body:
     a tractor and its implement are coupled, and giving them separate heights
     tears the drawbar in half at the hitch. A real drawbar does articulate
     vertically, but it does not come apart. */
  /* Where the ground mesh will be built. Everything laid on the ground reads
     its height through the SAME triangulation the ground is tessellated with,
     so a point on a facet gets exactly that facet's height.

     The height data is smooth, but the ground is drawn as flat triangles
     between samples, and over real terrain a flat triangle departs from the
     smooth surface by a long way -- measured at up to 81 cm on the Palouse
     grid. Matching the interpolation removes that; refining the mesh only
     shrinks it. */
  function meshFor(cx, plan, reach) {
    var half = 150, span = 320, cxUse = cx, cy = 0;
    if (plan) {
      var fieldSpan = Math.max(plan.length, plan.passes * plan.working_width);
      span = Math.max(320, fieldSpan * 3.0);
      half = Math.max(150, fieldSpan * 1.7);
      cxUse = plan.length / 2;
      cy = -(plan.passes - 1) * plan.working_width / 2;
    }
    // Bounded cell count, so a large field costs the same as a small one.
    var step = Math.max(4.0, Math.max(span, 2 * half) / 90);
    return {
      step: step,
      x0: Math.round((cxUse - span * 0.5) / step) * step,
      y0: Math.round((cy - half) / step) * step,
      span: span, half: half
    };
  }

  function groundHeight(x, y) {
    // A machine standing on the ground rides the plane fitted under it, so
    // every wheel touches down and the outfit stays in one piece.
    if (BODY_PLANE) {
      return BODY_PLANE.h0 + BODY_PLANE.gx * (x - BODY_PLANE.x0)
                           + BODY_PLANE.gy * (y - BODY_PLANE.y0);
    }
    if (HEIGHT_LOCK !== null) { return HEIGHT_LOCK; }
    if (!HEIGHT_AT) { return 0; }
    if (!MESH) { return HEIGHT_AT(x, y); }

    var st = MESH.step;
    var fx = (x - MESH.x0) / st, fy = (y - MESH.y0) / st;
    var i = Math.floor(fx), j = Math.floor(fy);
    var tx = fx - i, ty = fy - j;
    var X = MESH.x0 + i * st, Y = MESH.y0 + j * st;
    var h00 = HEIGHT_AT(X, Y), h10 = HEIGHT_AT(X + st, Y);
    var h11 = HEIGHT_AT(X + st, Y + st), h01 = HEIGHT_AT(X, Y + st);
    // buildGround emits (a,b,c) and (a,c,d) with a=(0,0) b=(1,0) c=(1,1)
    // d=(0,1), so the diagonal runs a-c and the halves split on tx vs ty.
    if (tx >= ty) { return h00 + (h10 - h00) * tx + (h11 - h10) * ty; }
    return h00 + (h11 - h01) * tx + (h01 - h00) * ty;
  }

  function fitGroundPlane(points) {
    // Least squares z = a + b x + c y over the machine's own footprint.
    var n = points.length;
    var sx = 0, sy = 0, sz = 0, sxx = 0, syy = 0, sxy = 0, sxz = 0, syz = 0;
    for (var i = 0; i < n; i++) {
      var x = points[i][0], y = points[i][1], z = HEIGHT_AT(x, y);
      sx += x; sy += y; sz += z;
      sxx += x * x; syy += y * y; sxy += x * y;
      sxz += x * z; syz += y * z;
    }
    var cxx = sxx - sx * sx / n, cyy = syy - sy * sy / n;
    var cxy = sxy - sx * sy / n;
    var cxz = sxz - sx * sz / n, cyz = syz - sy * sz / n;
    var det = cxx * cyy - cxy * cxy;
    var gx = 0, gy = 0;
    if (Math.abs(det) > 1e-9) {
      gx = (cxz * cyy - cyz * cxy) / det;
      gy = (cyz * cxx - cxz * cxy) / det;
    }
    var x0 = sx / n, y0 = sy / n;
    return { x0: x0, y0: y0, h0: sz / n, gx: gx, gy: gy };
  }

  /* Where the outfit touches down: both axles, both tracks, and the implement
     axle if there is one. Fitting to these rather than to a fixed square means
     the plane follows the machine that is actually standing on it. */
  function outfitFootprint(pose, g, im) {
    var c = Math.cos(pose.theta), s = Math.sin(pose.theta);
    var L = g.wheelbase.value, half = (g.track_width.value || 2.2) / 2;
    var pts = [];
    [0, L].forEach(function (ax) {
      [-half, half].forEach(function (side) {
        pts.push([pose.x + ax * c - side * s, pose.y + ax * s + side * c]);
      });
    });
    if (im) {
      var a = im.hitch_distance.value;
      var reach = im.type === "trailed" ? im.implement_wheelbase.value
                                        : MOUNTED_LINKAGE_M;
      var hx = pose.x - a * Math.cos(pose.theta);
      var hy = pose.y - a * Math.sin(pose.theta);
      var ix = hx - reach * Math.cos(pose.thetaImplement);
      var iy = hy - reach * Math.sin(pose.thetaImplement);
      var w = im.working_width.value / 2;
      var ic = Math.cos(pose.thetaImplement), is = Math.sin(pose.thetaImplement);
      pts.push([ix - w * is * 0.5, iy + w * ic * 0.5]);
      pts.push([ix + w * is * 0.5, iy - w * ic * 0.5]);
    }
    return pts;
  }

  function place(local, origin, yaw, tilt) {
    var c = Math.cos(yaw), s = Math.sin(yaw);
    var x = origin[0] + local[0] * c - local[1] * s;
    var y = origin[1] + local[0] * s + local[1] * c;
    var z = local[2] + groundHeight(x, y);
    var ct = Math.cos(tilt), st = Math.sin(tilt);
    return [x, y * ct - z * st, y * st + z * ct];
  }

  /* ---------------- triangle accumulation ---------------- */

  function Builder() { this.data = []; }

  Builder.prototype.tri = function (a, b, c, colour) {
    var ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2];
    var vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2];
    var n = normalise([uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx]);
    var d = this.data;
    [a, b, c].forEach(function (p) {
      d.push(p[0], p[1], p[2], n[0], n[1], n[2], colour[0], colour[1], colour[2]);
    });
  };

  Builder.prototype.quad = function (a, b, c, d, colour) {
    this.tri(a, b, c, colour);
    this.tri(a, c, d, colour);
  };

  Builder.prototype.fan = function (ring, colour, reverse) {
    for (var i = 1; i < ring.length - 1; i++) {
      if (reverse) { this.tri(ring[0], ring[i + 1], ring[i], colour); }
      else { this.tri(ring[0], ring[i], ring[i + 1], colour); }
    }
  };

  Builder.prototype.box = function (o, yaw, tilt, cx, cy, cz, len, wid, hgt, colour, opts) {
    opts = opts || {};
    var taper = opts.taper === undefined ? 1 : opts.taper;
    var drop = opts.drop || 0;
    var hx = len / 2, hy = wid / 2;
    function v(sx, sy, sz) {
      var t = sx > 0 ? taper : 1;
      var top = sz > 0 ? hgt - (sx > 0 ? drop : 0) : 0;
      return place([cx + sx * hx, cy + sy * hy * t, cz + top], o, yaw, tilt);
    }
    var a = v(-1, -1, 0), b = v(1, -1, 0), c = v(1, 1, 0), d = v(-1, 1, 0);
    var e = v(-1, -1, 1), f = v(1, -1, 1), g = v(1, 1, 1), h = v(-1, 1, 1);
    this.quad(d, c, b, a, colour);
    this.quad(e, f, g, h, colour);
    this.quad(a, b, f, e, colour);
    this.quad(c, d, h, g, colour);
    this.quad(b, c, g, f, colour);
    this.quad(d, a, e, h, colour);
  };

  /* A closed wheel.
   *
   * The tread band alone leaves the sides open between the rim and the tyre
   * radius, so you could see straight into it. A wheel needs a sidewall
   * annulus on BOTH faces, a rim disc on both, and a hub, or it is a hoop. */
  Builder.prototype.wheel = function (o, yaw, tilt, cx, cy, radius, width, steer,
                                      sides, rimCol, spin) {
    var hw = width / 2, cs = Math.cos(steer || 0), sn = Math.sin(steer || 0);
    var roll = spin || 0;
    var rim = rimCol || COL.steel;
    var wall = mixc(COL.tyre, [1, 1, 1], 0.08);
    var self = this;

    function pt(ang, r, side) {
      ang += roll;
      var x = Math.cos(ang) * r, z = Math.sin(ang) * r, y = side * hw;
      return place([cx + x * cs - y * sn, cy + x * sn + y * cs, radius + z], o, yaw, tilt);
    }

    var rimR = radius * 0.58;
    for (var i = 0; i < sides; i++) {
      var a0 = (i / sides) * Math.PI * 2, a1 = ((i + 1) / sides) * Math.PI * 2;

      self.quad(pt(a0, radius, -1), pt(a1, radius, -1), pt(a1, radius, 1),
        pt(a0, radius, 1), COL.tyre);
      // Sidewalls, the pieces that were missing.
      self.quad(pt(a0, rimR, -1), pt(a1, rimR, -1), pt(a1, radius, -1),
        pt(a0, radius, -1), wall);
      self.quad(pt(a0, radius, 1), pt(a1, radius, 1), pt(a1, rimR, 1),
        pt(a0, rimR, 1), wall);

      if (i % 2 === 0) {
        var lr = radius * 1.05;
        self.quad(pt(a0, lr, -0.95), pt(a1, lr, -0.2), pt(a1, radius, -0.2),
          pt(a0, radius, -0.95), COL.lug);
        self.quad(pt(a0, radius, 0.2), pt(a1, radius, 0.95), pt(a1, lr, 0.95),
          pt(a0, lr, 0.2), COL.lug);
      }
    }

    [1, -1].forEach(function (side) {
      var disc = [], hub = [];
      for (var j = 0; j < sides; j++) {
        var a = (j / sides) * Math.PI * 2;
        disc.push(pt(a, rimR, side * 1.005));
        hub.push(pt(a, rimR * 0.34, side * 1.02));
      }
      self.fan(disc, rim, side < 0);
      self.fan(hub, mixc(rim, [0, 0, 0], 0.4), side < 0);
    });
  };

  /* Something of known size, so the machine has a scale.
   *
   * A tractor alone in an empty field could be any size at all. A 1.75 m
   * figure is the cheapest way to say how big it really is, and the whole
   * point of this catalog is that the sizes are real.
   *
   * These STAND STILL. An earlier version placed one relative to the machine,
   * so it slid along the field keeping station with the tractor, which is
   * exactly what a scale reference must not do: something that moves with the
   * thing it is measuring tells you nothing. They are now pegged to fixed
   * world positions along the headland and the machine drives past them. */
  var FIGURE_SPACING_M = 50;
  var FIGURE_OFFSET_M = 16;

  function figurePositions(cx) {
    var out = [];
    var first = Math.floor((cx - 60) / FIGURE_SPACING_M) * FIGURE_SPACING_M;
    for (var x = first; x < cx + 140; x += FIGURE_SPACING_M) {
      out.push([x, FIGURE_OFFSET_M]);
    }
    return out;
  }

  function buildScaleFigure(mb, x, y, tilt) {
    var o = [x, y], skin = [0.76, 0.62, 0.50], cloth = [0.24, 0.30, 0.42];
    mb.box(o, 0, tilt, 0, 0.09, 0, 0.16, 0.13, 0.86, cloth);
    mb.box(o, 0, tilt, 0, -0.09, 0, 0.16, 0.13, 0.86, cloth);
    mb.box(o, 0, tilt, 0, 0, 0.86, 0.24, 0.42, 0.56, cloth);
    mb.box(o, 0, tilt, 0, 0, 1.42, 0.2, 0.2, 0.24, skin);
    mb.box(o, 0, tilt, 0, 0, 1.66, 0.24, 0.26, 0.06, [0.30, 0.34, 0.30]);
  }

  /* ---------------- the machine ---------------- */

  function buildTractor(mb, g, pose, tilt) {
    var o = [pose.x, pose.y], yaw = pose.theta;
    var L = g.wheelbase.value, track = g.track_width.value;
    var rw = g.rear_wheel, fw = g.front_wheel, pr = g.profile || {};

    var body = hex(g.livery.body), trim = hex(g.livery.trim);
    var rim = hex(g.livery.wheel), roof = hex(g.livery.roof);
    var bodyLit = mixc(body, [1, 1, 1], 0.12), bodyLow = mixc(body, [0, 0, 0], 0.30);

    var rAxle = rw.diameter / 2, fAxle = fw.diameter / 2;
    var deck = rAxle * 0.80;
    var hoodW = track * 0.54, hoodH = Math.max(0.62, rAxle * 0.78);
    var cabW = track * 0.76, cabH = (pr.cab_height || 1.18) * rAxle * 1.35;

    mb.box(o, yaw, tilt, L * 0.42, 0, deck * 0.46, L * 1.30, track * 0.34,
      deck * 0.42, trim);

    // Bonnet in segments on an elliptical falloff, so the shoulder curves.
    var hoodBack = L * 0.50, hoodFront = L * 1.00, hoodLen = hoodFront - hoodBack;
    var segs = 6, drop = hoodH * (pr.bonnet_drop || 0.28);
    for (var hs = 0; hs < segs; hs++) {
      var tm = (hs + 0.5) / segs;
      var shrink = Math.sqrt(Math.max(0.04, 1 - tm * tm * 0.55));
      mb.box(o, yaw, tilt, hoodBack + hoodLen * tm, 0, deck,
        hoodLen / segs * 1.05, hoodW * (0.99 - 0.30 * tm * tm),
        hoodH * shrink - drop * tm * 0.55, hs === segs - 1 ? bodyLit : body);
    }

    mb.box(o, yaw, tilt, hoodFront + 0.06, 0, deck + hoodH * 0.18, 0.1,
      hoodW * 0.82, hoodH * 0.52, trim);
    [1, -1].forEach(function (side) {
      mb.box(o, yaw, tilt, hoodFront + 0.04, side * hoodW * 0.3,
        deck + hoodH * 0.7, 0.09, 0.16, 0.11, COL.lamp);
    });
    if (pr.front_weights) {
      mb.box(o, yaw, tilt, L * 1.16, 0, deck * 0.72, 0.32, hoodW * 0.9,
        hoodH * 0.5, trim);
    }

    var cabLen = L * 0.50, cabX = L * 0.22, cabZ = deck + hoodH * 0.16;
    mb.box(o, yaw, tilt, cabX, 0, cabZ, cabLen, cabW, 0.09, bodyLow);
    [[cabLen / 2, cabW / 2], [cabLen / 2, -cabW / 2],
     [-cabLen / 2, cabW / 2], [-cabLen / 2, -cabW / 2]].forEach(function (c) {
      mb.box(o, yaw, tilt, cabX + c[0], c[1], cabZ, 0.075, 0.075, cabH, trim);
    });
    // Glazing as four thin panels between the posts. A single solid box the
    // size of the cab, which is what was here, just reads as a grey crate: the
    // frame has to be visible against the glass for it to look like a cab.
    var glassZ = cabZ + 0.09, glassH = cabH * 0.82, t = 0.05;
    mb.box(o, yaw, tilt, cabX + cabLen / 2, 0, glassZ, t, cabW * 0.9, glassH, COL.glass);
    mb.box(o, yaw, tilt, cabX - cabLen / 2, 0, glassZ, t, cabW * 0.9, glassH, COL.glass);
    mb.box(o, yaw, tilt, cabX, cabW / 2, glassZ, cabLen * 0.9, t, glassH, COL.glass);
    mb.box(o, yaw, tilt, cabX, -cabW / 2, glassZ, cabLen * 0.9, t, glassH, COL.glass);
    // Interior, so the cab is not hollow when seen through the glazing.
    mb.box(o, yaw, tilt, cabX - cabLen * 0.16, 0, glassZ, cabLen * 0.34,
      cabW * 0.45, glassH * 0.55, mixc(trim, [1, 1, 1], 0.12));
    mb.box(o, yaw, tilt, cabX, 0, cabZ + cabH * 0.94, cabLen * 1.14, cabW * 1.16,
      0.11, roof);
    mb.box(o, yaw, tilt, cabX + cabLen * 0.42, 0, cabZ + cabH * 0.94 + 0.11,
      0.1, 0.1, 0.09, COL.beacon);

    if (pr.exhaust === "stack" || pr.exhaust === "stack_short") {
      mb.box(o, yaw, tilt, hoodBack + 0.12, hoodW * 0.46, deck + hoodH * 0.5,
        0.1, 0.1, cabH * (pr.exhaust === "stack" ? 0.82 : 0.5), trim);
    }

    if (pr.fenders !== false) {
      // A continuous curved strip over the wheel. Built as quads following the
      // arc rather than axis-aligned boxes placed along it, which is what made
      // the old fenders read as debris scattered round the tyre.
      [1, -1].forEach(function (side) {
        var y = side * (track / 2 - rw.width * 0.06);
        var hwid = rw.width * 0.62, r = rAxle * 1.16, steps = 11;
        for (var fs = 0; fs < steps; fs++) {
          var a0 = Math.PI * (0.14 + 0.72 * (fs / steps));
          var a1 = Math.PI * (0.14 + 0.72 * ((fs + 1) / steps));
          function arc(ang, dy) {
            // Centred on the AXLE, at height rAxle. Centring it on the ground
            // put the hoop a whole wheel radius too low, so it cut straight
            // through the tyre.
            return place([-Math.cos(ang) * r, y + dy, rAxle + Math.sin(ang) * r],
              o, yaw, tilt);
          }
          mb.quad(arc(a0, -hwid), arc(a1, -hwid), arc(a1, hwid), arc(a0, hwid), bodyLow);
        }
      });
    }

    mb.box(o, yaw, tilt, -L * 0.20, 0, deck * 0.36, L * 0.40, 0.12, 0.1, trim);

    // Wheels turn with distance travelled, and turn FASTER than the ground
    // goes by when there is slip, which is the one place the model's travel
    // reduction is visible rather than merely tabulated.
    [[0, track / 2, rAxle, rw.width, 0], [0, -track / 2, rAxle, rw.width, 0],
     [L, track / 2 * 0.88, fAxle, fw.width, pose.delta],
     [L, -track / 2 * 0.88, fAxle, fw.width, pose.delta]].forEach(function (c) {
      mb.wheel(o, yaw, tilt, c[0], c[1], c[2], c[3], c[4], 22, rim,
        -pose.travel / (c[2] * Math.max(0.15, 1 - (pose.slip || 0))));
    });
  }

  // A mounted implement carries no hitch geometry in the catalog, because it
  // has no hitch degree of freedom. Drawn at zero offset it lands inside the
  // tractor and disappears, which is exactly what happened. A three point
  // linkage puts it behind the rear axle where it actually hangs.
  var MOUNTED_LINKAGE_M = 1.15;

  function buildImplement(mb, im, hx, hy, ix, iy, yawT, yawI, tilt) {
    var lv = im.livery || {};
    var main = hex(lv.body || "#A35A32");
    var dark = mixc(main, [0, 0, 0], 0.32);
    var steel = hex(lv.trim || "#6C6252");
    var width = im.working_width.value;
    var depth = im.frame_depth.value;
    var bb = im.implement_wheelbase.value;
    var o = [ix, iy];

    if (im.type === "trailed") {
      mb.box([hx, hy], yawI, tilt, -bb / 2, 0, 0.62, bb, 0.16, 0.14, dark);
      mb.box([hx, hy], yawT, tilt, 0.06, 0, 0.6, 0.24, 0.2, 0.2, steel);
    } else {
      // Lower links and a top link, which is what a mounted implement hangs on.
      [0.42, -0.42].forEach(function (dy) {
        mb.box([hx, hy], yawI, tilt, -MOUNTED_LINKAGE_M / 2, dy, 0.42,
          MOUNTED_LINKAGE_M, 0.09, 0.09, steel);
      });
      mb.box([hx, hy], yawI, tilt, -MOUNTED_LINKAGE_M * 0.45, 0, 0.95,
        MOUNTED_LINKAGE_M * 0.8, 0.07, 0.07, steel);
    }

    mb.box(o, yawI, tilt, 0, 0, 0.66, depth * 0.5, width, 0.22, main);
    mb.box(o, yawI, tilt, depth * 0.42, 0, 0.7, 0.18, width * 0.96, 0.16, dark);
    mb.box(o, yawI, tilt, -depth * 0.42, 0, 0.7, 0.18, width * 0.96, 0.16, dark);

    var kind = (im.draft_class || "") + " " + (im.type || "");
    var n = Math.max(6, Math.min(30, Math.round(width * 1.7)));
    for (var i = 0; i < n; i++) {
      var y = -width / 2 + (i + 0.5) * (width / n);
      if (/planter/.test(kind)) {
        mb.box(o, yawI, tilt, -depth * 0.22, y, 0.26, depth * 0.46, 0.26, 0.44, dark);
        mb.wheel(o, yawI, tilt, -depth * 0.44, y, 0.22, 0.06, 0, 10, steel);
      } else if (/disk|disc|catros|joker|turbomax|excelerator/.test(kind)) {
        mb.wheel(o, yawI, tilt, depth * 0.2, y, 0.28, 0.045, 0.32, 12, steel);
        mb.wheel(o, yawI, tilt, -depth * 0.24, y, 0.28, 0.045, -0.32, 12, steel);
      } else if (/laserweeder|verdant|sharpshooter/.test(kind)) {
        mb.box(o, yawI, tilt, 0, y, 0.74, depth * 0.58, width / n * 0.78, 0.32, dark);
      } else {
        mb.box(o, yawI, tilt, -depth * 0.1, y, 0.14, 0.1, 0.09, 0.52, dark);
        mb.box(o, yawI, tilt, -depth * 0.14, y, 0.05, 0.26, 0.12, 0.1, steel);
      }
    }

    if (im.type === "trailed") {
      var tw = Math.min(width * 0.5, 3.4);
      mb.wheel(o, yawI, tilt, -depth * 0.55, tw / 2, 0.55, 0.32, 0, 16, steel);
      mb.wheel(o, yawI, tilt, -depth * 0.55, -tw / 2, 0.55, 0.32, 0, 16, steel);
    }

    [1, -1].forEach(function (side) {
      mb.box(o, yawI, tilt, 0, side * width / 2, 0.66, depth * 0.6, 0.1, 0.95, dark);
    });
  }

  /* ---------------- ground, swath, shadow ---------------- */

  function buildGround(mb, mesh, tilt, terrain) {
    // Perspective-correct texturing is free here, so the grid exists only to
    // follow the tilt, not to hide affine distortion.
    //
    // Sized and positioned by meshFor, which every ground-height lookup also
    // consults, so the surface drawn here and the surface everything else is
    // laid on cannot disagree.
    var step = mesh.step, span = mesh.span, half = mesh.half;
    var x0 = mesh.x0, y0 = mesh.y0;
    var map = terrain && terrain.map;
    var pixels = terrain && terrain.patch ? terrain.patch.pixels : 1;
    var flatNx = 0, flatNy = -Math.sin(tilt), flatNz = Math.cos(tilt);
    var ct = Math.cos(tilt), st = Math.sin(tilt);

    function vertex(x, y) {
      var p = place([x, y, 0], [0, 0], 0, tilt);
      var uv = map ? map(x, y) : [0, 0];
      var nx = flatNx, ny = flatNy, nz = flatNz;
      if (HEIGHT_AT) {
        // Slope of the real surface by central difference, then rotated into
        // the same frame the flat normal lives in. Without this the relief is
        // visible in silhouette but shades as if it were still flat, which
        // reads as a printed picture rather than as ground.
        var d = step * 0.5;
        var gx = (HEIGHT_AT(x + d, y) - HEIGHT_AT(x - d, y)) / (2 * d);
        var gy = (HEIGHT_AT(x, y + d) - HEIGHT_AT(x, y - d)) / (2 * d);
        var ux = -gx, uy = -gy, uz = 1.0;
        var len = Math.hypot(ux, uy, uz) || 1;
        ux /= len; uy /= len; uz /= len;
        nx = ux; ny = uy * ct - uz * st; nz = uy * st + uz * ct;
      }
      return { p: p, u: uv[0] / pixels, v: uv[1] / pixels,
               nx: nx, ny: ny, nz: nz };
    }
    for (var gx = x0; gx < x0 + span; gx += step) {
      for (var gy = y0; gy < y0 + 2 * half; gy += step) {
        var a = vertex(gx, gy), b = vertex(gx + step, gy);
        var c = vertex(gx + step, gy + step), d = vertex(gx, gy + step);
        // On flat ground the normal is (0, -sin t, cos t) everywhere; over
        // real terrain each vertex carries its own.
        [[a, b, c], [a, c, d]].forEach(function (t) {
          t.forEach(function (q) {
            mb.data.push(q.p[0], q.p[1], q.p[2], q.nx, q.ny, q.nz, q.u, q.v);
          });
        });
      }
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

  /* The three tracks the whole project is about, laid on the ground:
     where the guidance line is, where the tractor actually went, and where the
     implement centre actually went. Drawn as thin ribbons rather than lines,
     because a GL line has no width you can rely on. */
  /* Longest piece of ground overlay that may be drawn as one flat quad.
     Placing the CORNERS on the surface is not enough: a flat quad spanning
     several curved cells still cuts underneath every ridge between them, and
     the ground shows through in ragged holes. Anything longer than about half
     a mesh cell gets subdivided. */
  function maxSegment() {
    return (HEIGHT_AT && MESH) ? MESH.step * 0.5 : Infinity;
  }

  function ribbon(mb, points, tilt, halfWidth, colour, height) {
    var limit = maxSegment();
    for (var i = 0; i < points.length - 1; i++) {
      var p0 = points[i], q0 = points[i + 1];
      var span = Math.hypot(q0[0] - p0[0], q0[1] - p0[1]);
      var pieces = Math.max(1, Math.ceil(span / limit));
      for (var k = 0; k < pieces; k++) {
        var t0 = k / pieces, t1 = (k + 1) / pieces;
        var p = [p0[0] + (q0[0] - p0[0]) * t0, p0[1] + (q0[1] - p0[1]) * t0];
        var q = [p0[0] + (q0[0] - p0[0]) * t1, p0[1] + (q0[1] - p0[1]) * t1];
        ribbonSegment(mb, p, q, tilt, halfWidth, colour, height);
      }
    }
  }

  function ribbonSegment(mb, p, q, tilt, halfWidth, colour, height) {
    {
      var dx = q[0] - p[0], dy = q[1] - p[1];
      var len = Math.hypot(dx, dy);
      if (len < 1e-6) { return; }
      var nx = -dy / len * halfWidth, ny = dx / len * halfWidth;
      mb.quad(place([p[0] + nx, p[1] + ny, height], [0, 0], 0, tilt),
              place([q[0] + nx, q[1] + ny, height], [0, 0], 0, tilt),
              place([q[0] - nx, q[1] - ny, height], [0, 0], 0, tilt),
              place([p[0] - nx, p[1] - ny, height], [0, 0], 0, tilt), colour);
    }
  }

  /* The lines the operator asked for. With a field plan there is one per
     pass, spaced a working width apart and bounded by the headlands, so the
     turns and the offset the machine holds on each pass are both visible
     against the line that pass was actually following. */
  function buildPassLines(mb, tilt, plan, active) {
    var len = plan.length, w = plan.working_width;
    for (var i = 0; i < plan.passes; i += 1) {
      var y = -i * w;
      ribbon(mb, [[0, y], [len, y]], tilt, 0.09,
             i === active ? COL.guide : COL.guideIdle,
             i === active ? 0.055 : 0.035);
    }
    // Where the turns happen. Marking them keeps the swath that appears out
    // there from reading as worked ground.
    var edge = -(plan.passes - 1) * w - w * 0.6;
    [[0, w * 0.6], [len, -0.0]].forEach(function (unused, k) {
      var x = k === 0 ? 0 : len;
      ribbon(mb, [[x, w * 0.6], [x, edge]], tilt, 0.06, COL.headland, 0.02);
    });
  }

  function buildTracks(mb, s, upTo, tilt, im, plan) {
    var step = Math.max(1, Math.floor(upTo / (plan ? 420 : 200)));
    var tractor = [], implement = [];
    // Over a field the whole worked pattern is the point, so the trail keeps
    // its full history; on a single endless line only the recent stretch is
    // ever on screen, and holding more of it is wasted geometry.
    var from = plan ? 0 : Math.max(0, upTo - 2600);
    for (var i = from; i <= upTo; i += step) {
      if (s.x[i] === null) { continue; }
      tractor.push([s.x[i], s.y[i]]);
      if (im && s.theta_implement) {
        var a = im.hitch_distance.value;
        var reach = im.type === "trailed" ? im.implement_wheelbase.value : 1.15;
        var hx = s.x[i] - a * Math.cos(s.theta[i]);
        var hy = s.y[i] - a * Math.sin(s.theta[i]);
        implement.push([hx - reach * Math.cos(s.theta_implement[i]),
                        hy - reach * Math.sin(s.theta_implement[i])]);
      }
    }
    if (plan) {
      buildPassLines(mb, tilt, plan,
        s.pass_index ? s.pass_index[Math.min(upTo, s.pass_index.length - 1)] : 0);
    } else if (tractor.length) {
      // A single endless line, drawn to run off both ends of the view.
      var x0 = tractor[0][0], x1 = tractor[tractor.length - 1][0] + 90;
      ribbon(mb, [[x0 - 40, 0], [x1, 0]], tilt, 0.09, COL.guide, 0.055);
    }
    ribbon(mb, tractor, tilt, 0.11, COL.trackTractor, 0.05);
    if (implement.length) {
      ribbon(mb, implement, tilt, 0.11, COL.trackImplement, 0.05);
    }
  }

  /* The rows themselves, where the implement's maker publishes a spacing.
     Each row is where one row unit ran, so the rows follow the implement's
     yaw rather than the guidance line, and a trailed implement swinging
     through a correction bends every row with it. That is the whole argument
     of the project drawn on the ground.

     Coarser along the path than the swath is: a row is a straight-ish line and
     does not need a vertex every sample to read as one. */
  function buildRows(mb, s, upTo, tilt, a, b, halfWidth, spacing, plan) {
    var rows = Math.floor((halfWidth * 2) / spacing);
    if (rows < 2 || rows > 64) { return; }
    var step = Math.max(1, Math.floor(upTo / (plan ? 220 : 120)));
    var from = plan ? 0 : Math.max(0, upTo - 2200);
    // Offsets of each row unit from the implement centre.
    var offsets = [];
    for (var r = 0; r < rows; r++) {
      offsets.push(-halfWidth + spacing * (r + 0.5));
    }
    for (var i = from; i < upTo - step; i += step) {
      var p = edgePair(s, i, a, b, halfWidth);
      var q = edgePair(s, i + step, a, b, halfWidth);
      if (!p || !q) { continue; }
      for (var k = 0; k < offsets.length; k++) {
        // Interpolate across the swath: 0 at the left edge, 1 at the right.
        var f = (offsets[k] + halfWidth) / (halfWidth * 2);
        var px = p.lx + (p.rx - p.lx) * f, py = p.ly + (p.ry - p.ly) * f;
        var qx = q.lx + (q.rx - q.lx) * f, qy = q.ly + (q.ry - q.ly) * f;
        ribbon(mb, [[px, py], [qx, qy]], tilt, 0.055, COL.row, 0.045);
      }
    }
  }

  /* The worked ground.
     THIS IS THE ONE THAT TORE. The swath is as wide as the implement -- over
     twelve metres for a big planter -- and it was emitted as a single flat
     quad per step. Over real terrain that quad spans a couple of ground cells
     across, so it passed underneath every ridge between them and the hillside
     showed through the worked ground in ragged holes. Putting the corners on
     the surface never addressed it, because the hole is in the middle of the
     quad, not at its corners.

     The swath is now a grid: divided across its width and along its length so
     that no piece is bigger than about half a ground cell. On flat ground
     nothing subdivides and the cost is what it always was. */
  function buildSwath(mb, s, upTo, tilt, a, b, halfWidth, plan) {
    var step = Math.max(1, Math.floor(upTo / (plan ? 320 : 220)));
    var from = plan ? 0 : Math.max(0, upTo - 2200);
    var limit = maxSegment();
    var strips = Math.max(1, Math.min(10, Math.ceil((halfWidth * 2) / limit)));

    for (var i = from; i < upTo - step; i += step) {
      var p = edgePair(s, i, a, b, halfWidth), q = edgePair(s, i + step, a, b, halfWidth);
      if (!p || !q) { continue; }

      var travel = Math.hypot((q.lx + q.rx) / 2 - (p.lx + p.rx) / 2,
                              (q.ly + q.ry) / 2 - (p.ly + p.ry) / 2);
      var runs = Math.max(1, Math.min(6, Math.ceil(travel / limit)));

      for (var r = 0; r < runs; r++) {
        var f0 = r / runs, f1 = (r + 1) / runs;
        for (var c = 0; c < strips; c++) {
          var u0 = c / strips, u1 = (c + 1) / strips;
          mb.quad(place(swathPoint(p, q, f0, u0), [0, 0], 0, tilt),
                  place(swathPoint(p, q, f1, u0), [0, 0], 0, tilt),
                  place(swathPoint(p, q, f1, u1), [0, 0], 0, tilt),
                  place(swathPoint(p, q, f0, u1), [0, 0], 0, tilt), COL.worked);
        }
      }
    }
  }

  /* A point on the worked strip: f along the two edge pairs, u across from the
     left edge to the right. */
  function swathPoint(p, q, f, u) {
    var lx = p.lx + (q.lx - p.lx) * f, ly = p.ly + (q.ly - p.ly) * f;
    var rx = p.rx + (q.rx - p.rx) * f, ry = p.ry + (q.ry - p.ry) * f;
    return [lx + (rx - lx) * u, ly + (ry - ly) * u, 0.03];
  }

  /* Planar shadow: every machine vertex dropped onto the ground along the
     light. Drawn through the stencil buffer so overlapping geometry darkens
     the ground once rather than compounding into a black blob. */
  function shadowVertices(machineData, tilt, floor) {
    var out = [], st = Math.sin(tilt), ct = Math.cos(tilt);
    var base = (floor || 0) + 0.02;
    var kx = LIGHT[0] / LIGHT[2], ky = LIGHT[1] / LIGHT[2];
    for (var i = 0; i < machineData.length; i += 9) {
      var x = machineData[i], wy = machineData[i + 1], wz = machineData[i + 2];
      var y = wy * ct + wz * st;
      var z = -wy * st + wz * ct;
      if (z < base) { z = base; }
      var gx = x + (z - base) * kx, gy = y + (z - base) * ky;
      out.push(gx, gy * ct - base * st, gy * st + base * ct);
    }
    return out;
  }

  /* ---------------- GL plumbing ---------------- */

  function compile(gl, type, source) {
    var sh = gl.createShader(type);
    gl.shaderSource(sh, source);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      throw new Error("shader: " + gl.getShaderInfoLog(sh));
    }
    return sh;
  }

  function program(gl, vs, fs) {
    var p = gl.createProgram();
    gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, vs));
    gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
      throw new Error("link: " + gl.getProgramInfoLog(p));
    }
    return p;
  }

  function Scene(canvas) {
    this.canvas = canvas;
    var opts = { antialias: true, stencil: true, depth: true, alpha: false,
                 preserveDrawingBuffer: false, powerPreference: "high-performance" };
    var gl = canvas.getContext("webgl", opts) || canvas.getContext("experimental-webgl", opts);
    if (!gl) { throw new Error("WebGL is not available in this browser."); }
    this.gl = gl;

    this.solid = program(gl, SOLID_VS, SOLID_FS);
    this.ground = program(gl, GROUND_VS, GROUND_FS);
    this.flat = program(gl, FLAT_VS, FLAT_FS);
    this.sky = program(gl, SKY_VS, SKY_FS);

    this.buffers = {
      solid: gl.createBuffer(), ground: gl.createBuffer(),
      swath: gl.createBuffer(), shadow: gl.createBuffer(),
      sky: gl.createBuffer()
    };
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.sky);
    gl.bufferData(gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    this.texture = null;
    this.textureSource = null;

    this.mode = "chase";
    this.applyPreset("chase");

    gl.enable(gl.DEPTH_TEST);
    // Backface culling is deliberately OFF. The depth buffer already hides
    // what is behind, and culling would additionally demand that every quad in
    // this file is wound consistently. One mistake there silently deletes a
    // face, which is a bad trade for a little fill rate.
    gl.disable(gl.CULL_FACE);
    gl.clearColor(FOG[0], FOG[1], FOG[2], 1);
  }

  Scene.prototype.applyPreset = function (mode) {
    this.mode = mode;
    // Framing follows the machine's size until the visitor zooms, at which
    // point their choice wins. A 21 m cultivator and a 1.5 m mower cannot
    // share one camera distance.
    this.autoFit = true;
    if (mode === "chase") { this.yaw = 0.0; this.pitch = 0.30; this.baseDistance = 20; }
    if (mode === "side") { this.yaw = Math.PI / 2; this.pitch = 0.08; this.baseDistance = 26; }
    if (mode === "top") { this.yaw = 0.0; this.pitch = 1.40; this.baseDistance = 34; }
    this.distance = this.baseDistance;
  };

  Scene.prototype.frame = function (span) {
    if (!this.autoFit) { return; }
    // Enough to hold the machine's longest dimension with room around it.
    this.distance = Math.max(this.baseDistance || 20, span * 1.55 + 8);
  };

  Scene.prototype.eyeFor = function (target) {
    var pitch = Math.max(0.03, Math.min(1.48, this.pitch));
    var cp = Math.cos(pitch), sp = Math.sin(pitch);
    return [target[0] - this.distance * cp * Math.cos(this.yaw),
            target[1] - this.distance * cp * Math.sin(this.yaw),
            target[2] + this.distance * sp];
  };

  Scene.prototype.useTexture = function (image) {
    var gl = this.gl;
    // "No image" must be answered before "same image as last time". With the
    // order reversed, a run with no field loaded hit null === null, reported
    // itself as textured, and the ground sampled an unbound texture unit --
    // which returns black. The default ground rendered near-black instead of
    // soil, and only distance fog made it look like anything at all.
    if (!image) { this.textureSource = null; return false; }
    if (this.textureSource === image) { return true; }
    if (!this.texture) { this.texture = gl.createTexture(); }
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, image);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.generateMipmap(gl.TEXTURE_2D);
    this.textureSource = image;
    return true;
  };

  function bindAttribs(gl, prog, stride, specs) {
    specs.forEach(function (spec) {
      var loc = gl.getAttribLocation(prog, spec[0]);
      if (loc < 0) { return; }
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, spec[1], gl.FLOAT, false, stride * 4, spec[2] * 4);
    });
  }

  /* World point to CSS pixels, for the annotation overlay.
   *
   * Text in WebGL means baking glyphs into textures. Text in the DOM is crisp
   * at any zoom, selectable, and readable by a screen reader, so the labels
   * live in an SVG on top and only need to know where things landed. */
  Scene.prototype.project = function (p) {
    if (!this.lastViewProj) { return null; }
    var m = this.lastViewProj;
    var x = m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12];
    var y = m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13];
    var w = m[3] * p[0] + m[7] * p[1] + m[11] * p[2] + m[15];
    if (w <= 0.001) { return null; }
    return {
      x: (x / w * 0.5 + 0.5) * this.cssWidth,
      y: (0.5 - y / w * 0.5) * this.cssHeight,
      depth: w
    };
  };

  /* How many pixels a metre spans at the point being looked at, which is what
     a scale bar needs. */
  Scene.prototype.pixelsPerMetre = function (target) {
    var a = this.project(target);
    var b = this.project([target[0], target[1] + 1, target[2]]);
    if (!a || !b) { return null; }
    return Math.hypot(b.x - a.x, b.y - a.y);
  };

  Scene.prototype.draw = function (parts, target, tilt) {
    var gl = this.gl;
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    if (!w || !h) { return; }
    if (this.canvas.width !== Math.round(w * dpr)) {
      this.canvas.width = Math.round(w * dpr);
      this.canvas.height = Math.round(h * dpr);
    }
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(FOG[0], FOG[1], FOG[2], 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT | gl.STENCIL_BUFFER_BIT);

    // Sky first, as a single triangle covering the viewport with depth writes
    // off, so everything else draws over it normally.
    gl.useProgram(this.sky);
    gl.uniform3fv(gl.getUniformLocation(this.sky, "uLow"), SKY_LOW);
    gl.uniform3fv(gl.getUniformLocation(this.sky, "uHigh"), SKY_HIGH);
    gl.depthMask(false);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.sky);
    bindAttribs(gl, this.sky, 2, [["aPos", 2, 0]]);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.depthMask(true);

    var eye = this.eyeFor(target);
    // Depth precision is spent mostly between the near plane and a few times
    // it. Holding near at 0.4 m while the camera retreats to survey a field
    // leaves almost none of it where the geometry actually is.
    var near = Math.max(0.4, this.distance * 0.012);
    var proj = window.GLMath.perspective(window.GLMath.create(), 0.85,
      this.canvas.width / this.canvas.height, near, Math.max(900, this.distance * 6));
    var view = window.GLMath.lookAt(window.GLMath.create(), eye, target, [0, 0, 1]);
    var viewProj = window.GLMath.multiply(window.GLMath.create(), proj, view);
    this.lastViewProj = viewProj;
    this.cssWidth = w;
    this.cssHeight = h;

    // Fog has to follow the camera. Fixed at a 45 m start, a wide shot of a
    // whole field sat entirely inside the fogged band, so every colour in the
    // picture collapsed toward grey and the worked ground stopped being
    // distinguishable from the unworked ground.
    var fogStart = Math.max(45.0, this.distance * 0.85);
    var fogRange = Math.max(190.0, this.distance * 2.2);

    // Ground.
    gl.useProgram(this.ground);
    gl.uniformMatrix4fv(gl.getUniformLocation(this.ground, "uViewProj"), false, viewProj);
    gl.uniform3fv(gl.getUniformLocation(this.ground, "uLight"), LIGHT);
    gl.uniform3fv(gl.getUniformLocation(this.ground, "uFog"), FOG);
    gl.uniform1f(gl.getUniformLocation(this.ground, "uFogStart"), fogStart);
    gl.uniform1f(gl.getUniformLocation(this.ground, "uFogRange"), fogRange);
    gl.uniform3fv(gl.getUniformLocation(this.ground, "uTint"), COL.soil);
    var textured = this.useTexture(parts.texture);
    gl.uniform1f(gl.getUniformLocation(this.ground, "uUseTex"), textured ? 1.0 : 0.0);
    gl.uniform1f(gl.getUniformLocation(this.ground, "uGrid"), this.showGrid === false ? 0.0 : 1.0);
    if (textured) {
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.texture);
      gl.uniform1i(gl.getUniformLocation(this.ground, "uTex"), 0);
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.ground);
    gl.bufferData(gl.ARRAY_BUFFER, parts.ground, gl.DYNAMIC_DRAW);
    bindAttribs(gl, this.ground, 8, [["aPos", 3, 0], ["aNormal", 3, 3], ["aUV", 2, 6]]);
    // The swath and the track ribbons lie a few centimetres above the ground.
    // Across a whole field the camera sits far enough back that the depth
    // buffer cannot resolve that gap, and the two surfaces tear into each
    // other in a speckle of stripes. Pushing the ground back in depth space
    // settles the order by rule instead of by a margin that gets too small.
    gl.enable(gl.POLYGON_OFFSET_FILL);
    gl.polygonOffset(1.6, 4.0);
    gl.drawArrays(gl.TRIANGLES, 0, parts.ground.length / 8);
    gl.disable(gl.POLYGON_OFFSET_FILL);

    // Swath, laid on the ground.
    if (parts.swath.length) {
      gl.useProgram(this.solid);
      gl.uniformMatrix4fv(gl.getUniformLocation(this.solid, "uViewProj"), false, viewProj);
      gl.uniform3fv(gl.getUniformLocation(this.solid, "uLight"), LIGHT);
      gl.uniform3fv(gl.getUniformLocation(this.solid, "uFog"), FOG);
      gl.uniform1f(gl.getUniformLocation(this.solid, "uFogStart"), fogStart);
      gl.uniform1f(gl.getUniformLocation(this.solid, "uFogRange"), fogRange);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.swath);
      gl.bufferData(gl.ARRAY_BUFFER, parts.swath, gl.DYNAMIC_DRAW);
      bindAttribs(gl, this.solid, 9, [["aPos", 3, 0], ["aNormal", 3, 3], ["aColour", 3, 6]]);
      gl.drawArrays(gl.TRIANGLES, 0, parts.swath.length / 9);
    }

    // Shadow, once, through the stencil.
    if (parts.shadow.length) {
      gl.enable(gl.STENCIL_TEST);
      gl.stencilFunc(gl.ALWAYS, 1, 0xFF);
      gl.stencilOp(gl.KEEP, gl.KEEP, gl.REPLACE);
      gl.colorMask(false, false, false, false);
      gl.depthMask(false);
      gl.useProgram(this.flat);
      gl.uniformMatrix4fv(gl.getUniformLocation(this.flat, "uViewProj"), false, viewProj);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.shadow);
      gl.bufferData(gl.ARRAY_BUFFER, parts.shadow, gl.DYNAMIC_DRAW);
      bindAttribs(gl, this.flat, 3, [["aPos", 3, 0]]);
      gl.drawArrays(gl.TRIANGLES, 0, parts.shadow.length / 3);

      gl.colorMask(true, true, true, true);
      gl.stencilFunc(gl.EQUAL, 1, 0xFF);
      gl.stencilOp(gl.KEEP, gl.KEEP, gl.KEEP);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.uniform4f(gl.getUniformLocation(this.flat, "uColour"), 0.16, 0.13, 0.09, 0.38);
      gl.drawArrays(gl.TRIANGLES, 0, parts.shadow.length / 3);
      gl.disable(gl.BLEND);
      gl.disable(gl.STENCIL_TEST);
      gl.depthMask(true);
    }

    // The machine.
    gl.useProgram(this.solid);
    gl.uniformMatrix4fv(gl.getUniformLocation(this.solid, "uViewProj"), false, viewProj);
    gl.uniform3fv(gl.getUniformLocation(this.solid, "uLight"), LIGHT);
    gl.uniform3fv(gl.getUniformLocation(this.solid, "uFog"), FOG);
    gl.uniform1f(gl.getUniformLocation(this.solid, "uFogStart"), fogStart);
    gl.uniform1f(gl.getUniformLocation(this.solid, "uFogRange"), fogRange);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.solid);
    gl.bufferData(gl.ARRAY_BUFFER, parts.machine, gl.DYNAMIC_DRAW);
    bindAttribs(gl, this.solid, 9, [["aPos", 3, 0], ["aNormal", 3, 3], ["aColour", 3, 6]]);
    gl.drawArrays(gl.TRIANGLES, 0, parts.machine.length / 9);
  };

  /* ---------------- public interface ---------------- */

  window.GuidanceScene = {
    create: function (canvas) { return new Scene(canvas); },

    /* A scene that records instead of drawing, for checking the geometry
     * without a browser.
     *
     * Defined here, beside the renderer, rather than hand-written in the
     * checking script. A stub maintained over there drifted out of step with
     * what render() actually calls twice, and each time the check failed for
     * reasons that had nothing to do with the geometry it exists to test.
     */
    headless: function (width, height) {
      var scene = Object.create(Scene.prototype);
      scene.cssWidth = width || 960;
      scene.cssHeight = height || 540;
      scene.autoFit = true;
      scene.applyPreset("chase");
      scene.draw = function (parts, target, tilt) {
        this.parts = parts;
        this.target = target;
        this.tilt = tilt;
      };
      // Projection needs a matrix that only a real draw produces.
      scene.project = function () { return null; };
      return scene;
    },

    render: function (scene, data, frame, terrain) {
      var s = data.series, g = data.scene.machine;
      var tilt = (data.scene.slope_deg || 0) * Math.PI / 180 * (data.scene.slope_sign || 1);
      var im = g.implement;
      var plan = data.scene.plan || null;

      // Real ground, when a field has been read. Everything laid on the ground
      // consults this, so the swath, the tracks, the guidance lines and the
      // ground itself all agree about where the surface is.
      HEIGHT_AT = (terrain && terrain.height) || null;
      HEIGHT_LOCK = null;
      MESH = null;

      var pose = {
        x: s.x[frame], y: s.y[frame], theta: s.theta[frame],
        delta: s.delta_rad[frame] || 0,
        slip: data.scene.slip || 0,
        travel: Math.hypot(s.x[frame] - s.x[0], s.y[frame] - s.y[0]),
        thetaImplement: s.theta_implement ? s.theta_implement[frame] : s.theta[frame]
      };

      // Settled before anything asks how high the ground is, because every
      // such answer is defined relative to this mesh.
      MESH = meshFor(pose.x, plan, 0);
      BODY_PLANE = null;

      // The outfit stands on a plane fitted to the ground under its own
      // wheels, so the front tyres touch down as well as the rear and the
      // implement is carried rather than buried. Fitted before the plane is
      // installed, or every sample would read back the plane itself.
      var machineH = groundHeight(pose.x, pose.y);
      if (HEIGHT_AT) {
        BODY_PLANE = fitGroundPlane(outfitFootprint(pose, g, im));
        machineH = groundHeight(pose.x, pose.y);
      } else {
        HEIGHT_LOCK = machineH;
      }

      var machine = new Builder();
      buildTractor(machine, g, pose, tilt);
      if (im) {
        var a = im.hitch_distance.value, b = im.implement_wheelbase.value;
        var hx = pose.x - a * Math.cos(pose.theta), hy = pose.y - a * Math.sin(pose.theta);
        // Trailed implements sit b behind the hitch. Mounted ones have no b,
        // so they sit on the linkage instead of on top of the tractor.
        var reach = im.type === "trailed" ? b : MOUNTED_LINKAGE_M;
        var ix = hx - reach * Math.cos(pose.thetaImplement);
        var iy = hy - reach * Math.sin(pose.thetaImplement);
        buildImplement(machine, im, hx, hy, ix, iy, pose.theta, pose.thetaImplement, tilt);
      }

      // How much the view has to hold. Worked out before the ground is built,
      // because the ground is sized from it.
      var span = Math.max(g.wheelbase.value * 2.2,
        im ? im.working_width.value : 0,
        im ? (im.hitch_distance.value + im.implement_wheelbase.value +
              g.wheelbase.value * 1.6) : 0);
      // A field is wider than a machine. Widen enough to hold the passes
      // worked so far, so the turn and the neighbouring pass are both in view
      // rather than the camera staying tight on the tractor.
      if (plan) {
        var worked = s.pass_index
          ? s.pass_index[Math.min(frame, s.pass_index.length - 1)] : 0;
        span = Math.max(span, (worked + 1.4) * plan.working_width);
      }
      scene.frame(span);

      HEIGHT_LOCK = null;
      BODY_PLANE = null;

      var groundMb = new Builder();
      buildGround(groundMb, MESH, tilt, terrain);

      var swathMb = new Builder();
      if (im) {
        buildSwath(swathMb, s, frame, tilt, im.hitch_distance.value,
          im.implement_wheelbase.value, im.working_width.value / 2, plan);
        // Only where the manufacturer states a row spacing. Everything else
        // gets worked ground with no rows drawn on it, because a disk harrow
        // does not leave rows and a made-up spacing would look just as real as
        // a sourced one.
        if (im.row_spacing) {
          buildRows(swathMb, s, frame, tilt, im.hitch_distance.value,
            im.implement_wheelbase.value, im.working_width.value / 2,
            im.row_spacing.value, plan);
        }
      }
      buildTracks(swathMb, s, frame, tilt, im, plan);

      // Figures standing at fixed points along the headland, well clear of the
      // widest implement in the catalog, so the machine passes them rather
      // than carrying them along.
      var figures = figurePositions(pose.x);
      var offset = Math.max(FIGURE_OFFSET_M, span * 0.5 + 4);
      figures.forEach(function (f) {
        // Each figure stands upright on the ground where it is, rather than
        // leaning with the slope under it. Sampled at +offset because that is
        // where the figure is drawn: reading the height from -offset put it on
        // ground eighty metres away across the field, and on a hillside that
        // buried it up to the shoulders.
        HEIGHT_LOCK = groundHeight(f[0], offset);
        buildScaleFigure(machine, f[0], offset, tilt);
        HEIGHT_LOCK = null;
      });

      var back = im ? (im.hitch_distance.value + im.implement_wheelbase.value) * 0.5 : 0;
      var target = place([pose.x - back * Math.cos(pose.theta),
                          pose.y - back * Math.sin(pose.theta), 1.4], [0, 0], 0, tilt);

      // Looking down at a field, frame the field. Keeping the camera locked to
      // the machine put the tractor in one corner with the worked ground
      // running off the opposite edge, which is the one view where the whole
      // pattern is the thing worth seeing. Behind and Side still follow the
      // machine, because there the machine is the subject.
      if (plan && scene.mode === "top") {
        var fieldY = -(plan.passes - 1) * plan.working_width / 2;
        scene.frame(Math.max(plan.length, plan.passes * plan.working_width) * 0.92);
        target = place([plan.length / 2, fieldY, 0.0], [0, 0], 0, tilt);
      }

      scene.draw({
        machine: new Float32Array(machine.data),
        ground: new Float32Array(groundMb.data),
        swath: new Float32Array(swathMb.data),
        shadow: new Float32Array(shadowVertices(machine.data, tilt, machineH)),
        texture: terrain && terrain.patch ? terrain.patch.image : null
      }, target, tilt);

      // Anchors for the annotation overlay, in world coordinates, so the
      // labels quote the catalog's own dimensions rather than guesses.
      var anchors = {
        rearAxle: place([0, 0, 0.3], [pose.x, pose.y], pose.theta, tilt),
        frontAxle: place([g.wheelbase.value, 0, 0.3], [pose.x, pose.y], pose.theta, tilt),
        wheelbase: g.wheelbase.value,
        // Label whichever figure the machine is nearest, so the annotation
        // follows the view without the figure itself moving.
        figure: null, figureBase: null,
        target: target,
        pixelsPerMetre: scene.pixelsPerMetre(target)
      };

      var nearest = null, best = 1e9;
      figures.forEach(function (f) {
        var d = Math.abs(f[0] - pose.x);
        if (d < best) { best = d; nearest = f; }
      });
      if (nearest) {
        anchors.figure = place([0, 0, 1.75], [nearest[0], offset], 0, tilt);
        anchors.figureBase = place([0, 0, 0], [nearest[0], offset], 0, tilt);
      }
      if (im) {
        var iw = im.working_width.value / 2;
        var nxx = -Math.sin(pose.thetaImplement), nyy = Math.cos(pose.thetaImplement);
        var ax = pose.x - im.hitch_distance.value * Math.cos(pose.theta);
        var ay = pose.y - im.hitch_distance.value * Math.sin(pose.theta);
        var reach = im.type === "trailed" ? im.implement_wheelbase.value : MOUNTED_LINKAGE_M;
        var cxx = ax - reach * Math.cos(pose.thetaImplement);
        var cyy = ay - reach * Math.sin(pose.thetaImplement);
        anchors.edgeLeft = place([cxx + nxx * iw, cyy + nyy * iw, 1.1], [0, 0], 0, tilt);
        anchors.edgeRight = place([cxx - nxx * iw, cyy - nyy * iw, 1.1], [0, 0], 0, tilt);
        anchors.workingWidth = im.working_width.value;
      }

      pose.anchors = anchors;
      return pose;
    }
  };
})();
