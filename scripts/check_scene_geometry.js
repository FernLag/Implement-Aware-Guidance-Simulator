/* Headless check of the 3D geometry builders.
 *
 *   python3 scripts/dump_scenes.py > /tmp/scenes.json
 *   node scripts/check_scene_geometry.js /tmp/scenes.json
 *
 * The renderer needs a browser, but the geometry does not. This loads the
 * builders, feeds them a real simulation result for every implement in the
 * catalog, and asserts things a screenshot would take a person to notice:
 * that nothing is NaN, that a mounted implement is not buried inside the
 * tractor, and that a machine is roughly the size the catalog says it is.
 *
 * It found the bug it was written for: mounted implements were drawn at zero
 * offset, landing inside the tractor body, so the LaserWeeder simply did not
 * appear.
 */

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const JS_DIR = path.join(ROOT, "web", "static", "js");

global.window = {};
eval(fs.readFileSync(path.join(JS_DIR, "glmath.js"), "utf8"));
eval(fs.readFileSync(path.join(JS_DIR, "scene3d.js"), "utf8"));

const scenes = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));

let failures = 0;
function check(name, ok, detail) {
  if (!ok) {
    failures++;
    console.log(`  FAIL  ${name}: ${detail}`);
  }
}

/* The headless scene comes from the renderer itself, so it cannot drift out of
 * step with what render() calls. A stub maintained here did, twice. */
function capture(data, frame, terrain) {
  const scene = window.GuidanceScene.headless();
  window.GuidanceScene.render(scene, data, frame, terrain);
  return scene.parts;
}

const bare = capture(scenes.__none__, 100).machine;
const bareTris = bare.length / 27;

console.log("Scene geometry check\n");
console.log(
  "implement".padEnd(26) + "tris".padStart(6) + "  width (m)".padStart(12) +
  "  behind axle".padStart(14) + "  status"
);

for (const [id, data] of Object.entries(scenes)) {
  if (id === "__none__" || id === "__field__") { continue; }
  let parts;
  try {
    parts = capture(data, 100);
  } catch (err) {
    check(id, false, `render threw: ${err.message}`);
    continue;
  }

  const m = parts.machine;
  const px = data.series.x[100];
  let lo = 1e9, hi = -1e9, minX = 1e9, bad = 0, behind = 0;
  for (let i = 0; i < m.length; i += 9) {
    for (let k = 0; k < 9; k++) { if (!isFinite(m[i + k])) { bad++; } }
    if (m[i + 1] < lo) { lo = m[i + 1]; }
    if (m[i + 1] > hi) { hi = m[i + 1]; }
    if (m[i] - px < minX) { minX = m[i] - px; }
    if (m[i] - px < -1.6) { behind++; }
  }

  const tris = m.length / 27;
  const declared = data.scene.machine.implement.working_width.value;
  const type = data.scene.machine.implement.type;

  check(`${id} finite`, bad === 0, `${bad} non-finite components`);
  check(`${id} adds geometry`, tris > bareTris,
        `${tris} triangles, tractor alone is ${bareTris}`);
  // The bug this file exists for: an implement drawn inside the tractor.
  check(`${id} clears the tractor`, behind > 0,
        "no vertices behind the rear axle, so it is buried in the machine");
  // A wide implement must actually be wide.
  if (declared > 4.0) {
    check(`${id} spans its width`, hi - lo > declared * 0.75,
          `spans ${(hi - lo).toFixed(1)} m for a declared ${declared} m`);
  }
  check(`${id} triangle budget`, tris < 12000, `${tris} triangles is too many`);

  console.log(
    id.padEnd(26) + String(tris).padStart(6) +
    (hi - lo).toFixed(1).padStart(12) + minX.toFixed(1).padStart(14) +
    "  " + (type === "mounted" ? "mounted" : "trailed")
  );
}

/* Multi-pass field work. The ground geometry here is what makes the turns and
 * the neighbouring pass legible, and none of it exists on a single line. */
const field = scenes.__field__;
if (field) {
  const plan = field.scene.plan;
  check("field carries a plan", !!plan, "scene.plan missing");

  const early = capture(field, 60);
  const late = capture(field, field.series.x.length - 1);

  let bad = 0;
  for (const part of [late.machine, late.swath, late.ground]) {
    for (let i = 0; i < part.length; i++) {
      if (!isFinite(part[i])) { bad++; }
    }
  }
  check("field finite", bad === 0, `${bad} non-finite components`);

  // The worked ground accumulates instead of scrolling out of the window, so
  // by the last frame there is more of it than at the start.
  check("swath keeps its history",
        late.swath.length > early.swath.length,
        `swath went from ${early.swath.length} to ${late.swath.length} floats`);

  // Every pass line must be drawn, spanning the width of the field.
  let lo = 1e9, hi = -1e9;
  for (let i = 0; i < late.swath.length; i += 9) {
    if (late.swath[i + 1] < lo) { lo = late.swath[i + 1]; }
    if (late.swath[i + 1] > hi) { hi = late.swath[i + 1]; }
  }
  const width = (plan.passes - 1) * plan.working_width;
  check("pass lines span the field", hi - lo > width * 0.8,
        `ground spans ${(hi - lo).toFixed(1)} m for a ${width.toFixed(1)} m field`);

  console.log(
    `\nfield: ${plan.passes} passes x ${plan.length} m, ` +
    `ground spans ${(hi - lo).toFixed(1)} m, ` +
    `${(late.swath.length / 27).toFixed(0)} ground triangles`
  );
  check("field ground budget", late.swath.length / 27 < 20000,
        `${(late.swath.length / 27).toFixed(0)} ground triangles is too many`);
}

/* THE TRACKS MUST SIT ON THE GROUND, NOT INSIDE IT.
 *
 * The ground is drawn as flat triangles between height samples, while the
 * tracks and the worked swath are laid on the surface those samples describe.
 * If the two use different interpolations, the flat triangle can stand a long
 * way above the smooth surface -- measured at up to 81 cm on real Palouse
 * terrain -- and the trace vanishes into the hillside wherever it does.
 *
 * A picture will not show this reliably: it depends on the camera angle and it
 * looks like an ordinary depth artifact. The geometry shows it exactly. */
if (field) {
  // A smooth analytic surface with real curvature, so the check does not
  // depend on the network. Scaled to farmland: the steepest gradient here is
  // about 0.26, or 15 degrees, which is at the top end of what is worked. An
  // earlier version used wavelengths of 20 to 40 m at the same amplitudes,
  // giving 45 degree slopes -- ground no tractor would be on, and it made the
  // check fail on terrain rather than on a defect.
  const bumpy = (x, y) =>
    6 * Math.sin(x / 60) + 4 * Math.cos(y / 45) + 2 * Math.sin((x + y) / 30);

  const flat = JSON.parse(JSON.stringify(field));
  flat.scene.slope_deg = 0;  // so a vertex's z is its height, nothing else
  const p = capture(flat, flat.series.x.length - 1,
                    { height: bumpy, map: null, patch: null });

  // Ground triangles, as (x, y) -> plane.
  const tris = [];
  for (let i = 0; i < p.ground.length; i += 24) {
    const v = [];
    for (let k = 0; k < 3; k++) {
      v.push([p.ground[i + k * 8], p.ground[i + k * 8 + 1], p.ground[i + k * 8 + 2]]);
    }
    tris.push(v);
  }

  function groundZAt(x, y) {
    for (const t of tris) {
      const [a, b, c] = t;
      const d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1]);
      if (Math.abs(d) < 1e-12) { continue; }
      const w0 = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / d;
      const w1 = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / d;
      const w2 = 1 - w0 - w1;
      if (w0 >= -1e-9 && w1 >= -1e-9 && w2 >= -1e-9) {
        return w0 * a[2] + w1 * b[2] + w2 * c[2];
      }
    }
    return null;
  }

  /* Vertices AND triangle interiors. The tear that prompted this was in the
   * middle of a quad, not at its corners: the swath is as wide as the
   * implement and was emitted as one flat quad, so its corners sat correctly
   * on the surface while its middle passed underneath a ridge. Checking only
   * vertices would have called that clean. */
  let buried = 0, worst = Infinity, tested = 0;
  function probe(x, y, z) {
    const gz = groundZAt(x, y);
    if (gz === null) { return; }
    tested++;
    const clearance = z - gz;
    if (clearance < worst) { worst = clearance; }
    if (clearance < -0.001) { buried++; }
  }
  for (let i = 0; i + 26 < p.swath.length; i += 27 * 7) {
    const v = [];
    for (let k = 0; k < 3; k++) {
      v.push([p.swath[i + k * 9], p.swath[i + k * 9 + 1], p.swath[i + k * 9 + 2]]);
    }
    v.forEach(q => probe(q[0], q[1], q[2]));
    probe((v[0][0] + v[1][0] + v[2][0]) / 3,
          (v[0][1] + v[1][1] + v[2][1]) / 3,
          (v[0][2] + v[1][2] + v[2][2]) / 3);
    // Edge midpoints too: a long thin triangle can dip between its corners.
    for (let k = 0; k < 3; k++) {
      const a = v[k], b = v[(k + 1) % 3];
      probe((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2);
    }
  }

  check("tracks were actually sampled", tested > 100,
        `only ${tested} overlay points landed on a ground triangle`);
  check("tracks sit on the ground", buried === 0,
        `${buried} of ${tested} overlay points are below the ground surface, ` +
        `worst ${(worst * 100).toFixed(1)} cm under`);

  /* THE MACHINE MUST STAND ON THE GROUND TOO. Pinned to a single height, the
   * front tyres of a tractor on a slope bury themselves to the hub. */
  let lowest = Infinity, highest = -Infinity, machineTested = 0;
  for (let i = 0; i < p.machine.length; i += 9 * 11) {
    const x = p.machine[i], y = p.machine[i + 1], z = p.machine[i + 2];
    const gz = groundZAt(x, y);
    if (gz === null) { continue; }
    machineTested++;
    lowest = Math.min(lowest, z - gz);
    highest = Math.max(highest, z - gz);
  }
  if (machineTested > 20) {
    // A wheel rim may sit a little proud or a fraction below by the mesh's
    // own facet error, but nothing should be a wheel-radius deep.
    check("the machine stands on the ground", lowest > -0.35,
          `a machine vertex is ${(-lowest).toFixed(2)} m below the surface, ` +
          "which is a tyre buried in the hillside");
    console.log(
      `terrain: machine sits between ${lowest.toFixed(2)} m and ` +
      `${highest.toFixed(2)} m of the ground over ${machineTested} points`);
  }

  console.log(
    `terrain: ${tested} overlay points (corners, edges and interiors) checked, ` +
    `least clearance ${(worst * 100).toFixed(2)} cm`
  );
}

console.log();
if (failures) {
  console.log(`${failures} check(s) failed`);
  process.exit(1);
}
console.log(`all checks passed across ${Object.keys(scenes).length - 1} implements`);
