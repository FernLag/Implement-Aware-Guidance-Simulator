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

/* A stand-in for the real Scene. It must offer the same surface the renderer
 * calls, or this file starts failing for reasons that have nothing to do with
 * the geometry it is meant to be checking. */
function stubScene() {
  return {
    autoFit: true, baseDistance: 20, distance: 20, mode: "chase",
    frame(span) { this.lastSpan = span; },
    draw(parts) { this.parts = parts; }
  };
}

function capture(data, frame) {
  const scene = stubScene();
  window.GuidanceScene.render(scene, data, frame);
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
  if (id === "__none__") { continue; }
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

console.log();
if (failures) {
  console.log(`${failures} check(s) failed`);
  process.exit(1);
}
console.log(`all checks passed across ${Object.keys(scenes).length - 1} implements`);
