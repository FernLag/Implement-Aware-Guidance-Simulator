# Implement-Aware Agricultural Guidance Simulator

[![tests](https://github.com/FernLag/Implement-Aware-Guidance-Simulator/actions/workflows/tests.yml/badge.svg)](https://github.com/FernLag/Implement-Aware-Guidance-Simulator/actions/workflows/tests.yml)
[![licence: MIT](https://img.shields.io/badge/licence-MIT-2E6B33)](LICENSE)

A Python simulation of how an agricultural tractor tracks a planned path under
autosteer, built to compare two competing error objectives:

1. **Tractor cross-track error**: how far the tractor's reference point is from the line
2. **Implement edge error**: how far the implement's working edge is from where it should be

**Central hypothesis:** the controller tuning that minimises tractor error is
*not* the tuning that minimises implement-edge error, and the gap between them
grows with implement width, hitch length, and side slope.

This matters because coverage quality, meaning skip and overlap between
adjacent passes, depends on where the *implement* is, not where the tractor
is. Nearly all published path-tracking work optimises tractor error.

---

## Quick start

```bash
git clone https://github.com/FernLag/Implement-Aware-Guidance-Simulator.git
cd Implement-Aware-Guidance-Simulator
python3 -m pip install -r requirements.txt
python3 -m pytest tests/ -q          # 355 tests, ~95 s
```

Requires Python 3.11+. Dependencies are NumPy, Matplotlib, PyYAML and pytest.
There are no simulation frameworks. The integrator and vehicle model are written by hand
so their behaviour is fully understood and defensible.

---

## Demo

Each stage has one script. They write PNGs to `results/` and print their
numeric results, **including every assumed parameter used**, to stdout.

### 1. The equipment catalog

```bash
python3 -m aggsim.catalog
```

Lists **18 tractors** (2.05–3.91 m wheelbase, 70–532 hp) and **21 implements**
(1.52–21.2 m working width), the feasible pairings, and all 101 assumed
parameters with the reasoning behind each.

| | manufacturers |
|---|---|
| Tractors | John Deere, Case IH, New Holland, Kubota, Fendt, Massey Ferguson, Valtra, CLAAS, Deutz-Fahr, Mahindra, Monarch |
| Implements | John Deere, Case IH, KUHN Krause, Väderstad, HORSCH, AMAZONE, Great Plains, Land Pride, Carbon Robotics, Verdant Robotics |

Includes newer autonomous and robotic machines: the **Monarch MK-V**
driver-optional electric tractor, and the **Carbon Robotics LaserWeeder G2**
and **Verdant Robotics Sharpshooter** as three-point mounted implements.

Two entries carry a modelling caveat rather than a number. The **Case IH
Steiger 500 Quadtrac** and **John Deere 9R 540** steer by frame articulation,
which the Stage 1 bicycle model does not represent, so `from_tractor()`
**refuses** them, an error beats plausible numbers from the wrong model.

### 2. Straight-line tracking  *(~5 s)*

```bash
python3 scripts/stage1_straight_line.py
```

A 3 m offset decays to ~1e-18 m. Look for: 0.136 m overshoot, settling under
2 cm at 7.2 s.

### 3. Actuator dynamics and oscillation onset  *(~3 min)*

```bash
python3 scripts/stage2_actuator_dynamics.py
```

The slowest script, it runs 300-second simulations to distinguish a decaying
transient from a sustained oscillation. Look for: onset at 9.75 m/s for
k = 0.10, and panel (d), where the conclusion swings entirely on an assumed
time constant.

### 4. Terrain effects  *(~30 s)*

```bash
python3 scripts/stage3_terrain.py
```

**The key demonstration:** pure pursuit holds a steady offset on a side slope
and never returns to the line. Panel (b) plots the simulation against a closed
form; they agree to 2.7e-13 m.

### 5. The implement and the second metric  *(~40 s)*  <- start here

```bash
python3 scripts/stage4_implement.py
```

The core of the project. Panel (c) is the hypothesis in one picture: tractor
error is a flat line across every implement in the catalog, while worst-case
edge error is not.

### 6. Stanley vs pure pursuit  *(~90 s)*

```bash
python3 scripts/stage5_stanley_comparison.py
```

Both controllers scored against both objectives. Look for panel (d): every
point sits below parity, meaning tuning that improves the tractor metric
delivers proportionally less to the implement.

### 7. The dual-objective tuning comparison  *(~8 min)*

```bash
python3 scripts/stage6_dual_objective.py
```

The central experiment: 24 configurations, each scanned over 32 lookahead
gains against three objectives. Writes `results/stage6_results.json` alongside
the figure. Look for panel (b), the divergence is negative everywhere, which
is the opposite sign to the hypothesis the project started from.

**Shortest meaningful demo:** run step 1, then step 5.

---

## What the simulation shows so far

On a 10° side slope with a 12.19 m trailed planter, at 3 m/s:

| | tractor error | worst edge error | ratio |
|---|---|---|---|
| pure pursuit, k = 0.5 | 0.2550 m | 0.6275 m | 2.46 |
| Stanley, k_e = 20 | 0.1681 m | 0.5406 m | 3.22 |

Stanley improves the tractor metric by 34% but the edge metric by only 14%.
The difference between the two metrics is **0.3725 m for every controller and
every gain tested**, a controller-independent constant set by the crab angle
acting on the implement's longitudinal offset.

**Stage 6, the central experiment.** Across 51 configurations, the two optimal
lookahead gains diverge in every one, by more than one grid step in every one:

| | k_tractor | k_implement | gap |
|---|---|---|---|
| mean over 24 configurations |, |, | **−0.087 s** |
| range | 0.27–0.46 | 0.30–0.40 | −0.140 to −0.051 |

So the hypothesis holds, but **the sign is the opposite of the one the
project assumed**. The implement wants a *shorter* lookahead than the tractor,
not a longer one. The brief expected aggressive tuning to whip a trailed
implement; instead, over most of the configuration space, the implement
benefits from the tighter tuning and it is *relaxing* toward the tractor
optimum that costs it. The whipping regime does exist, but only at the
extreme: a 21.2 m cultivator recovering from a 5 m offset flips the gap
positive (+0.035).

Three results that were not expected going in, each documented where it lives:

- **Stanley does not eliminate the steady-state offset.** Raising `k_e` drives
  the *front* axle to zero, but the rear axle floors at `L·v_d/√(v²+v_d²)`
  ≈ 0.157 m, from crabbing alone. At moderate gain Stanley is no better than
  pure pursuit.
- **Implement side-draft is inert under the obvious modelling choice.** With
  one drift coefficient for both bodies, zero hitch angle is an *exact*
  equilibrium, so side slope drives the metrics apart through the crab angle
  rather than through hitch articulation.
- **A longer lookahead helps stability but hurts slope tracking.** Stage 2
  wants large `k`; Stage 3's `e_ss ∝ L_d` wants small.
- **The hitch had no mechanical stop.** A sweep over the parameter space found
  the implement winding past 1800 degrees of hitch angle, which a drawbar
  cannot do. There is now a stop, and a run that reaches it is reported as
  invalid rather than presented as a result.
- **Skip and overlap do not follow either control objective.** A uniform
  lateral offset creates no skip at all, it shifts the whole field pattern
  without opening a gap. Skip is driven by implement *yaw*, so it falls
  monotonically with lookahead and wants the longest one searched, pulling
  against both control optima. Tuning for implement edge error actually makes
  skip *worse* (8.6 cm vs 7.2 cm on a 3 m drill).

---

## Web interface

A browser interface for running single passes without the command line.

```bash
python3 -m pip install -r requirements-web.txt
cp .env.example .env          # then set AGGSIM_SECRET_KEY
python3 wsgi.py               # http://127.0.0.1:5000
```

Pick a tractor and implement from the catalog, set speed, side slope, slip and
controller, and the page charts tractor cross-track error against implement
edge error on the same axes. Results include skip between adjacent passes as a
percentage of working width, so the output carries an agronomic unit and not
only a control one.

The picker warns when a tractor cannot pull the implement you chose. The
guidance model has no notion of draft, so it will happily produce numbers for
an outfit that could not move, and the catalog's feasibility check is now
surfaced rather than sitting unused. Every run can be downloaded as CSV, and
the settings can be shared as a link that reopens the same run.

A **3D view** plays the pass back with the machine on tilted ground, the hitch
articulating, and the worked swath painted behind it, which makes the implement
lag visible in a way a line chart does not. It is drawn by a hand written WebGL
renderer, no library: a depth buffer rather than sorting by centroid, per-pixel
lighting, hardware anti-aliasing, and perspective-correct ground texturing. The
whole client comes to 68 kB.

A frame is four draw calls rather than roughly 1,900 canvas path fills, which
is where the lag came from.

The view draws a curved bonnet, a cab with posts and glass, an exhaust stack,
fenders, front weights, tread lugs and rims on every wheel, and tools along the
implement bar chosen by its draft class: discs for a harrow, row units for a
planter, tines for a cultivator, modules for a laser weeder. On the ground it
lays down three tracks along the ground, the guidance line, where the tractor
actually went and where the implement centre actually went, in the same olive
and clay the charts use. It also draws the worked swath and the boundary lines
where the two neighbouring passes should meet, so skip and overlap are visible directly rather than only
as a number. Wheels turn with distance travelled, and turn faster than the
ground goes by in proportion to slip, which is the one place the model's travel
reduction can be seen rather than read. **Scale is stated, not implied.** The ground carries a five metre grid computed
from world position, dimension lines quote the catalog's own wheelbase and
working width, a 1.75 m figure stands beside the machine, and a map-style
scale bar rounds to a usable figure. The labels are real SVG text over the
canvas rather than glyphs baked into a texture, so they stay crisp at any zoom
and a screen reader can read them.

**Real fields, driving the model.** Pick one of five verified cropland presets,
spanning nearly flat Iowa corn to rolling Palouse wheat with 13.6 m of relief,
or enter any latitude and longitude in the United States and the simulator reads the ground there from USGS 3DEP
elevation at 1 m resolution, lays the USGS aerial photograph under the machine,
and **runs the simulation on that ground**. Not a single slope number: the side
slope is sampled every few metres along the guidance line, so the disturbance
changes under the machine as it drives.

The difference is visible in the result. On a uniform hillside the tractor is
pushed one way and holds there. On a real Palouse field, where the side slope
runs from -12.6 to +3.4 degrees over 180 m, the error wanders across the line
instead, because the ground changes sign beneath it.

The gradient is resolved along the guidance line and across it, because only
the across component is the side slope the model uses: the same field driven
north and driven east gives quite different numbers.

Those requests are made by the server, not by your browser, so the content
security policy stays same-origin and no request goes from a visitor to a third
party. Both services are free, need no key and no account, and are United
States only. Outside coverage the tool says so rather than returning a slope of
zero.

Wheel diameters in that view are **derived from the catalogued tyre codes**,
so a `480/80R50` rolls at its real 2.04 m. Track width, body size and hitch
geometry are not published by any manufacturer in the catalog, are drawn to
plausible proportions, and are labelled as drawing only beneath the view. None
of them touch the simulation. The model underneath stays planar: there is no
roll, pitch or suspension, so the view shows a planar result in three
dimensions rather than adding physics to it.

### Hosting it for free

`render.yaml` deploys it to Render's free tier, which requires no payment
method and suspends rather than billing when a limit is reached. The blueprint
declares no database and no persistent disk, so nothing in it can become a
paid resource. See [DEPLOYMENT.md](DEPLOYMENT.md) for the verified figures,
the trade-offs, and configs for Docker platforms and Vercel.

For a public deployment use a real server behind TLS:

```bash
AGGSIM_SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_urlsafe(48))")   gunicorn -w 4 wsgi:app
```

### Security posture

```bash
python3 scripts/security_audit.py     # 21 checks, re-runnable
```

Built in rather than added afterwards: every request field is bounded and
unknown fields are rejected outright; bodies are size limited; simulation cost
is capped by total integration steps, because one long request can cost more
than thousands of page views; every endpoint is rate limited while static
assets are exempt; the contact form carries a CSRF token compared in constant
time; and the Content Security Policy is same origin with no `unsafe-inline`,
which is possible because the page loads no external script, style or font.

The site **sets no cookies at all**. With no form and no account there is no
session to keep, so there is nothing to consent to and nothing stored in the
browser. It also collects no personal data.

No credential appears in this repository. Everything sensitive comes from the
environment, and `.env` is git ignored. The audit reports four accepted
limitations rather than hiding them, the most important being that the rate
limiter is per process and keys on the socket address, so a public deployment
behind a proxy needs `ProxyFix` and an edge limiter.

### Two things this deployment does not invent

**Contact details.** There is no address in the code. Unset, the footer says so
plainly instead of showing a placeholder that could be mistaken for real.

**A cookie banner with nothing behind it.** Analytics is off by default, and
with it off the site sets no cookie of any kind and shows no banner, because a
consent prompt on a site that stores nothing teaches people to dismiss the
question. Switch analytics on and a real yes or no choice appears, with nothing
stored until it is answered.

---

## Project rules

Two rules shape most of the design.

### Every parameter is sourced or explicitly flagged

A bare `float` cannot record where it came from, so every physical value is a
`Param` carrying either a source URL or `assumed=True` with a rationale.
Construction **fails** if it has neither, and a bare number in the YAML fails
at load. Provenance is structural, not a discipline someone has to remember.

```python
>>> from aggsim.catalog import load_catalog
>>> load_catalog().tractor("jd_6145r").wheelbase.describe()
'2.766 m  [source: https://www.tractordata.com/...-6145r-dimensions.html]'
```

Sourced: tractor dimensions and power (TractorData, Nebraska tests), implement
widths and masses (manufacturer product pages), wheel slip by soil surface
(PM 2089g).

The rule bites in practice. Three examples of figures that were **rejected**
rather than used: a widely-quoted 9.4 t mass for the HORSCH Joker 8 RT traces
back to a farming *simulation game* wiki, not the manufacturer; "weights" of
148–193 lb for a 28-ft disk harrow turned out to be per-blade figures; and a
22,100 lb Great Plains mass appeared only in a search summary that could not
be checked against primary text. Each is recorded as an assumption with the
reason, not quietly adopted.

Not in the catalog, deliberately: **Yamaha** builds agricultural UAVs and
invests in ag robotics but does not make tractors, so there is no entry to
source.
Assumed and swept: steering geometry, actuator time constant and slew rate,
side-slope drift coefficient, implement drift ratio, hitch geometry.

Assumptions are **printed by every script**, never silently applied.

### Controllers are pure functions

A controller takes state and returns a steering command. No plotting, no I/O,
no coupling to the simulation loop, the loop accepts any `State -> delta`
callable and does not know which controller it is driving. Stage 7 wraps these
same functions as ROS 2 nodes, so anything reaching outside the arguments
would need a rewrite.

---

## Layout

```
aggsim/
  catalog/      equipment specifications with tracked provenance (Stage 0)
    param.py      Param: value + source | assumed + rationale
    validate.py   rejects physically impossible pairings
  model/
    vehicle.py    kinematic bicycle model, RK4, steering actuator
    implement.py  one-trailer kinematics and the edge error metric (Stage 4)
  geometry/
    abline.py     AB line, cross-track error, lookahead intersection
  control/
    pure_pursuit.py, stanley.py    pure functions
  config/
    steering.py   actuator lag and slew limit (Stage 2)
    terrain.py    side slope and slip (Stage 3)
  sim/run.py      fixed-step loop
  ros2/           URDF generation and node wrappers (Stage 7 groundwork)
  analysis/
    oscillation.py  settling and damping detection (Stage 2)
    coverage.py     skip and overlap between passes (Stage 6)
    tuning.py       dual-objective gain search (Stage 6)
scripts/          one demo script per stage, plus asset and audit tools
web/              browser interface (Flask), separate from the simulation core
tests/            355 tests
```

### Conventions

- **SI throughout.** Metres, radians, seconds, watts.
- **Cross-track error is positive to the LEFT** of the AB line. Fixed in
  Stage 1 so implement edge error shares the frame; the Stanley law is
  written with a minus accordingly.
- **State is at the rear axle**, which makes the bicycle equations exact
  rather than approximate. Stanley's front-axle reference is computed from it.
- **Edge error is measured against ±w/2**, not against the line, otherwise a
  perfectly placed wide implement would report an error equal to its half
  width.

---

## Status

| Stage | State |
|---|---|
| 0 · Equipment catalog | done, 18 tractors, 21 implements |
| 1 · Vehicle model, pure pursuit | done |
| 2 · Steering actuator dynamics | done |
| 3 · Terrain effects | done |
| 4 · Implement model, second metric | done |
| 5 · Stanley comparison | done |
| 6 · Dual-objective tuning | done, 24 configurations |
| 7 · ROS 2 / Gazebo validation | groundwork done, environment not attempted |

Stage 6 is complete and the divergence is real, but three caveats bound it.
**144 gain settings were excluded** because the hitch reached its stop there;
those runs describe a machine folded into itself and are not candidate optima,
so they are masked out of the search rather than averaged in.
**The practical cost is small:** tuning for the tractor costs on average 0.81%
extra RMS edge error, at most 1.51%. The optima are statistically distinct and
agronomically marginal at these settings. **And the scenario is load-bearing:**
below roughly a 2 m acquisition offset both objectives fall monotonically to
the shortest lookahead searched, so neither has an interior optimum and the
comparison is vacuous. `TuningResult.interior` flags that case rather than
letting it read as agreement.

**Stage 7** is split deliberately. The half that needs no ROS 2 and no Gazebo
is done and tested: a URDF generated from the catalog, and node wrappers around
the controllers.

```bash
python3 scripts/stage7_description.py     # writes results/urdf/
```

The description uses the real wheelbase and the wheel diameters derived from
the catalogued tyre codes, puts `base_link` at the rear axle so both
simulations agree where the machine is, and gives the hitch a revolute joint
whose limit is **the same 85 degree stop the kinematic model enforces**, so the
two agree about what is impossible. The provenance travels with the file: a
URDF pulled out of this repository still says which of its numbers are sourced
and which are assumed.

`ControllerBridge` turns a pose and a speed into a steering command using the
identical `pure_pursuit` and `stanley` functions Stages 1 to 6 call, and a test
asserts the outputs are equal, not merely similar. `rclpy` is imported lazily,
so the module works on a machine with no ROS and explains why it cannot run.

The Gazebo half is **not** attempted. Per the brief it should be abandoned
rather than allowed to consume weeks, and a finished kinematic study is worth
more than a half-configured Gazebo world. Nothing above depends on it.

---

## Testing

A headless geometry check runs the 3D builders under Node for every implement
in the catalog and asserts things a screenshot would otherwise be the only way
to notice: nothing non-finite, a mounted implement not buried inside the
tractor, a wide implement actually spanning its width. It found the bug it was
written for.

```bash
python3 scripts/dump_scenes.py > /tmp/scenes.json
node scripts/check_scene_geometry.js /tmp/scenes.json
```

The suite is offline by design. `tests/conftest.py` closes the socket layer for
the whole run, so a test that tried to reach USGS fails loudly instead of
depending on a public service being up. CI runs it on Python 3.11 and 3.12
along with the security audit.

```bash
python3 -m pytest tests/ -q                    # everything
python3 -m pytest tests/test_stage4.py -q      # one stage
```

The suite checks behaviour against theory wherever a closed form exists, not
just against previous output:

- constant steering traces a circle of radius `L/tan δ` (1e-6 m over 2000 steps)
- RK4's radius error is >100× smaller than Euler's at the same step
- the steady-state slope offset matches its closed form to 2.7e-13 m
- Stanley's front-axle offset matches its closed form, and its rear-axle
  floor `L·v_d/√(v²+v_d²)` is approached but never crossed
- parabolic sub-grid refinement recovers a known parabola vertex exactly
- a known damping ratio ζ = 0.10 is recovered from a synthetic decay within 5%

Three tests are called for by name in the project brief:

- **Geometry**, a vehicle on the line with zero heading error commands
  exactly zero steering. Enforced for *both* controllers.
- **Catalog integrity**, every entry has a source or an explicit assumed flag.
- **Degenerate case**, with zero implement width and zero hitch geometry,
  implement edge error reduces *exactly* to tractor cross-track error
  (`np.array_equal`, not `approx`). Three further tests confirm each degenerate
  condition is individually necessary, so it cannot pass for the wrong reason.

---

## Licence

MIT, see [LICENSE](LICENSE). Manufacturer names, model numbers and brand
liveries are the trademarks of their owners and are used only to identify the
machines whose published specifications the catalog cites. Aerial imagery and
elevation are courtesy of the U.S. Geological Survey and are in the public
domain.

---

## Prior work

Path tracking for agricultural vehicles is well established; pure pursuit,
Stanley, slip compensation and terrain effects all have substantial
literature. This project claims no novelty in the controllers.

The intended contribution is the **dual-objective comparison**, tractor error
versus implement edge error as competing optimisation targets, combined with
a real equipment catalog so results are grounded in actual machines. Any
novelty claim in documentation should first be checked against the literature
on *implement-referenced control* and *implement steering systems*, the
adjacent area most likely to contain prior work on this framing.
