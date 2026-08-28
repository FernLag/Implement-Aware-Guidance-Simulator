# Implement-Aware Agricultural Guidance Simulator

A Python simulation of how an agricultural tractor tracks a planned path under
autosteer, built to compare two competing error objectives:

1. **Tractor cross-track error** — how far the tractor's reference point is from the line
2. **Implement edge error** — how far the implement's working edge is from where it should be

**Central hypothesis:** the controller tuning that minimises tractor error is
*not* the tuning that minimises implement-edge error, and the gap between them
grows with implement width, hitch length, and side slope.

This matters because coverage quality — skip and overlap between adjacent
passes — depends on where the *implement* is, not where the tractor is. Nearly
all published path-tracking work optimises tractor error.

---

## Quick start

```bash
git clone https://github.com/FernLag/Implement-Aware-Guidance-Simulator.git
cd Implement-Aware-Guidance-Simulator
python3 -m pip install -r requirements.txt
python3 -m pytest tests/ -q          # 143 tests, ~75 s
```

Requires Python 3.11+. Dependencies are NumPy, Matplotlib, PyYAML and pytest —
no simulation frameworks. The integrator and vehicle model are written by hand
so their behaviour is fully understood and defensible.

---

## Demo

Each stage has one script. They write PNGs to `results/` and print their
numeric results, **including every assumed parameter used**, to stdout.

### 1. The equipment catalog

```bash
python3 -m aggsim.catalog
```

Lists 7 tractors (2.05–3.05 m wheelbase, 75–410 hp) and 9 implements
(1.52–21.2 m working width), the feasible pairings, and all 41 assumed
parameters with the reasoning behind each.

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

The slowest script — it runs 300-second simulations to distinguish a decaying
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

### 5. The implement and the second metric  *(~40 s)*  ← start here

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
every gain tested** — a controller-independent constant set by the crab angle
acting on the implement's longitudinal offset.

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
  wants large `k`; Stage 3's `e_ss ∝ L_d` wants small. That tension is what
  Stage 6 has to resolve.

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
widths (manufacturer product pages), wheel slip by soil surface (PM 2089g).
Assumed and swept: steering geometry, actuator time constant and slew rate,
side-slope drift coefficient, implement drift ratio, hitch geometry.

Assumptions are **printed by every script**, never silently applied.

### Controllers are pure functions

A controller takes state and returns a steering command. No plotting, no I/O,
no coupling to the simulation loop — the loop accepts any `State -> delta`
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
  analysis/       oscillation detection
scripts/          one demo script per stage
tests/            143 tests
```

### Conventions

- **SI throughout.** Metres, radians, seconds, watts.
- **Cross-track error is positive to the LEFT** of the AB line. Fixed in
  Stage 1 so implement edge error shares the frame; the Stanley law is
  written with a minus accordingly.
- **State is at the rear axle**, which makes the bicycle equations exact
  rather than approximate. Stanley's front-axle reference is computed from it.
- **Edge error is measured against ±w/2**, not against the line — otherwise a
  perfectly placed wide implement would report an error equal to its half
  width.

---

## Status

| Stage | State |
|---|---|
| 0 · Equipment catalog | done — 7 tractors, 9 implements |
| 1 · Vehicle model, pure pursuit | done |
| 2 · Steering actuator dynamics | done |
| 3 · Terrain effects | done |
| 4 · Implement model, second metric | done |
| 5 · Stanley comparison | done |
| 6 · Dual-objective tuning | not started |
| 7 · ROS 2 / Gazebo validation | conditional on 0–6 |

Preliminary signal for Stage 6, on flat ground with actuator lag and a 3 m
acquisition transient: the two optimal lookahead gains do separate
(`k_tractor` = 0.50 vs `k_implement` = 0.40–0.45), but by only one to two
steps of a 0.05 grid. Stage 6 needs to resolve that properly before it counts
as a finding. If the optima turn out to coincide across the configuration
space, that is a negative result and gets reported as one.

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
- a known damping ratio ζ = 0.10 is recovered from a synthetic decay within 5%

Three tests are called for by name in the project brief:

- **Geometry** — a vehicle on the line with zero heading error commands
  exactly zero steering. Enforced for *both* controllers.
- **Catalog integrity** — every entry has a source or an explicit assumed flag.
- **Degenerate case** — with zero implement width and zero hitch geometry,
  implement edge error reduces *exactly* to tractor cross-track error
  (`np.array_equal`, not `approx`). Three further tests confirm each degenerate
  condition is individually necessary, so it cannot pass for the wrong reason.

---

## Prior work

Path tracking for agricultural vehicles is well established; pure pursuit,
Stanley, slip compensation and terrain effects all have substantial
literature. This project claims no novelty in the controllers.

The intended contribution is the **dual-objective comparison** — tractor error
versus implement edge error as competing optimisation targets — combined with
a real equipment catalog so results are grounded in actual machines. Any
novelty claim in documentation should first be checked against the literature
on *implement-referenced control* and *implement steering systems*, the
adjacent area most likely to contain prior work on this framing.
