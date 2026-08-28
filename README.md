# Implement-Aware Agricultural Guidance Simulator

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
python3 -m pytest tests/ -q          # 230 tests, ~85 s
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

**Stage 6, the central experiment.** Across 24 configurations, the two optimal
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

For a public deployment use a real server behind TLS:

```bash
AGGSIM_SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_urlsafe(48))")   gunicorn -w 4 wsgi:app
```

### Security posture

```bash
python3 scripts/security_audit.py     # 17 checks, re-runnable
```

Built in rather than added afterwards: every request field is bounded and
unknown fields are rejected outright; bodies are size limited; simulation cost
is capped by total integration steps, because one long request can cost more
than thousands of page views; every endpoint is rate limited while static
assets are exempt; the contact form carries a CSRF token compared in constant
time; and the Content Security Policy is same origin with no `unsafe-inline`,
which is possible because the page loads no external script, style or font.

No credential appears in this repository. Everything sensitive comes from the
environment, and `.env` is git ignored. The audit reports six accepted
limitations rather than hiding them, the most important being that the rate
limiter is per process and keys on the socket address, so a public deployment
behind a proxy needs `ProxyFix` and an edge limiter.

### Two things this deployment does not invent

**Contact details.** There is no address in the code. Unset, the contact page,
privacy page and footer say so plainly instead of showing a placeholder that
could be mistaken for real.

**A cookie banner with nothing behind it.** Analytics is off by default, and
with it off the site sets no analytics cookie and shows no banner. Switch
analytics on and a real yes or no choice appears, with nothing stored until it
is answered. One strictly necessary session cookie carries the contact form
CSRF token, and the privacy page documents it.

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
  analysis/
    oscillation.py  settling and damping detection (Stage 2)
    coverage.py     skip and overlap between passes (Stage 6)
    tuning.py       dual-objective gain search (Stage 6)
scripts/          one demo script per stage, plus asset and audit tools
web/              browser interface (Flask), separate from the simulation core
tests/            230 tests
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
| 7 · ROS 2 / Gazebo validation | conditional on 0–6 |

Stage 6 is complete and the divergence is real, but two caveats bound it.
**The practical cost is small:** tuning for the tractor costs on average 0.81%
extra RMS edge error, at most 1.51%. The optima are statistically distinct and
agronomically marginal at these settings. **And the scenario is load-bearing:**
below roughly a 2 m acquisition offset both objectives fall monotonically to
the shortest lookahead searched, so neither has an interior optimum and the
comparison is vacuous. `TuningResult.interior` flags that case rather than
letting it read as agreement.

Stage 7 (ROS 2 / Gazebo) remains conditional. Per the brief, it should not
begin until Stages 1–6 are validated, and should be abandoned in favour of
shipping Stages 0–6 if the environment takes more than about two weeks.

---

## Testing

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
