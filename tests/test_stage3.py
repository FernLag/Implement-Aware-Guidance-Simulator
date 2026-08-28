"""Stage 3 tests: side slope and wheel slip.

The centrepiece is that pure pursuit's steady-state offset on a side slope
has a closed form, so the simulation is checked against theory rather than
against its own previous output:

    e_ss = L_d * v_d / sqrt(v_eff^2 + v_d^2)

Derivation: at steady state the tractor crabs so its total velocity is
parallel to the line, giving tan(theta) = -v_d / v_eff. Pure pursuit commands
zero steering only when it points exactly at the lookahead point, which at
offset e means sin(theta) = -e / L_d. Eliminating theta gives the result.
Note it contains no wheelbase term.
"""

import numpy as np
import pytest

from aggsim.catalog import load_catalog
from aggsim.config import load_steering
from aggsim.config.terrain import FLAT, G, Terrain, load_soils
from aggsim.control import PurePursuitGains, make_pure_pursuit
from aggsim.geometry import ABLine
from aggsim.model import State, from_tractor
from aggsim.sim import SimConfig, simulate

LINE = ABLine((0.0, 0.0), (1.0, 0.0))
GAINS = PurePursuitGains(k=0.5, l_min=3.0)


@pytest.fixture(scope="module")
def params():
    return from_tractor(load_catalog().tractor("jd_6145r"))


def _run(params, terrain, v=3.0, e0=0.0, duration=200.0, steering=None):
    cfg = SimConfig(speed=v, dt=0.01, duration=duration)
    ctrl = make_pure_pursuit(LINE, cfg.speed, GAINS, params)
    return simulate(State(0.0, e0, 0.0), LINE, ctrl, params, cfg,
                    steering=steering, terrain=terrain)


def predicted_offset(terrain, v, gains=GAINS):
    v_eff = v * terrain.speed_factor
    v_d = terrain.lateral_drift
    return gains.lookahead(v) * v_d / np.hypot(v_eff, v_d)


# --- terrain model ---------------------------------------------------------

def test_flat_terrain_is_a_no_op(params):
    """Terrain must be off by default, or Stage 1 results change silently."""
    assert FLAT.lateral_drift == 0.0
    assert FLAT.speed_factor == 1.0
    with_flat = _run(params, FLAT, e0=2.0, duration=60.0)
    without = _run(params, None, e0=2.0, duration=60.0)
    assert np.allclose(with_flat.cross_track, without.cross_track)


def test_drift_is_proportional_to_g_sin_phi():
    c = 0.10
    for deg in (0.0, 5.0, 10.0, 20.0):
        t = Terrain(slope_angle=np.radians(deg))
        assert t.lateral_drift == pytest.approx(c * G * np.sin(np.radians(deg)))


def test_slope_sign_flips_the_drift_direction():
    left = Terrain(slope_angle=np.radians(10.0), slope_sign=1.0)
    right = Terrain(slope_angle=np.radians(10.0), slope_sign=-1.0)
    assert left.lateral_drift == pytest.approx(-right.lateral_drift)


def test_slip_scales_forward_velocity():
    assert Terrain(slip=0.12).speed_factor == pytest.approx(0.88)


def test_terrain_rejects_impossible_values():
    with pytest.raises(ValueError, match="slip"):
        Terrain(slip=1.0)
    with pytest.raises(ValueError, match="slope_angle"):
        Terrain(slope_angle=np.pi)
    with pytest.raises(ValueError, match="slope_sign"):
        Terrain(slope_sign=0.0)


def test_effects_are_independently_toggleable():
    slope_only = Terrain(slope_angle=np.radians(10.0))
    slip_only = Terrain(slip=0.12)
    assert slope_only.slope_enabled and not slope_only.slip_enabled
    assert slip_only.slip_enabled and not slip_only.slope_enabled


# --- the Stage 3 demonstration --------------------------------------------

def test_side_slope_produces_a_steady_state_offset(params):
    """The Stage 3 demonstration, and the setup for Stage 5."""
    log = _run(params, Terrain(slope_angle=np.radians(10.0)))
    e = log.final_cross_track()
    assert abs(e) > 0.1  # a real, agronomically visible offset
    # Steady: unchanged over the last 20 s.
    tail = log.cross_track[log.t > log.t[-1] - 20.0]
    assert np.ptp(tail) < 1e-6


@pytest.mark.parametrize("deg,slip,v", [(10, 0.0, 3.0), (5, 0.0, 3.0),
                                        (10, 0.12, 3.0), (15, 0.0, 5.0)])
def test_steady_state_offset_matches_closed_form(params, deg, slip, v):
    terrain = Terrain(slope_angle=np.radians(deg), slip=slip)
    log = _run(params, terrain, v=v)
    assert log.final_cross_track() == pytest.approx(predicted_offset(terrain, v), abs=1e-6)


@pytest.mark.parametrize("tractor_id", ["jd_5075e", "jd_6145r", "jd_8r_410"])
def test_offset_is_independent_of_wheelbase(tractor_id):
    """The closed form contains no wheelbase term; the simulation must agree."""
    p = from_tractor(load_catalog().tractor(tractor_id))
    log = _run(p, Terrain(slope_angle=np.radians(10.0)))
    assert log.final_cross_track() == pytest.approx(0.25503, abs=1e-4)


def test_offset_grows_with_slope_angle(params):
    offsets = [abs(_run(params, Terrain(slope_angle=np.radians(d))).final_cross_track())
               for d in (2.0, 5.0, 10.0, 15.0)]
    assert all(a < b for a, b in zip(offsets, offsets[1:]))


def test_offset_scales_with_lookahead_distance(params):
    """e_ss is proportional to L_d, so a longer lookahead tracks worse."""
    terrain = Terrain(slope_angle=np.radians(10.0))
    cfg = SimConfig(speed=3.0, dt=0.01, duration=200.0)
    offsets = []
    for l_min in (2.0, 4.0, 8.0):
        gains = PurePursuitGains(k=0.0, l_min=l_min)
        ctrl = make_pure_pursuit(LINE, cfg.speed, gains, params)
        log = simulate(State(0.0, 0.0, 0.0), LINE, ctrl, params, cfg, terrain=terrain)
        offsets.append(log.final_cross_track())
    ratios = [b / a for a, b in zip(offsets, offsets[1:])]
    assert ratios == pytest.approx([2.0, 2.0], rel=1e-3)


def test_offset_sign_follows_the_downhill_direction(params):
    left = _run(params, Terrain(slope_angle=np.radians(10.0), slope_sign=1.0))
    right = _run(params, Terrain(slope_angle=np.radians(10.0), slope_sign=-1.0))
    assert left.final_cross_track() == pytest.approx(-right.final_cross_track())


def test_slip_alone_causes_no_steady_state_offset(params):
    """Slip slows the vehicle; it applies no lateral disturbance."""
    log = _run(params, Terrain(slip=0.16), e0=2.0)
    assert abs(log.final_cross_track()) < 1e-6


def test_slip_worsens_the_offset_on_a_slope(params):
    """Lower effective speed means less authority against the same drift."""
    dry = _run(params, Terrain(slope_angle=np.radians(10.0), slip=0.0))
    slippery = _run(params, Terrain(slope_angle=np.radians(10.0), slip=0.16))
    assert abs(slippery.final_cross_track()) > abs(dry.final_cross_track())


def test_slip_reduces_distance_travelled(params):
    fast = _run(params, Terrain(slip=0.0), duration=60.0)
    slow = _run(params, Terrain(slip=0.20), duration=60.0)
    assert slow.x[-1] == pytest.approx(0.8 * fast.x[-1], rel=1e-9)


def test_offset_persists_with_actuator_dynamics(params):
    """The offset is a controller property, not an artefact of ideal steering."""
    terrain = Terrain(slope_angle=np.radians(10.0))
    log = _run(params, terrain, duration=300.0, steering=load_steering())
    assert log.final_cross_track() == pytest.approx(predicted_offset(terrain, 3.0), abs=1e-3)


# --- soil catalog ----------------------------------------------------------

def test_soil_slip_values_carry_provenance():
    soils = load_soils()
    assert set(soils) == {"concrete", "firm_untilled", "tilled", "sandy"}
    for name, param in soils.items():
        assert param.source or (param.assumed and param.rationale), name


def test_sandy_slip_is_flagged_assumed():
    """PM 2089g gives no number for sandy soil, unlike the other surfaces."""
    soils = load_soils()
    assert soils["sandy"].assumed
    for name in ("concrete", "firm_untilled", "tilled"):
        assert not soils[name].assumed


def test_soil_slip_values_are_ordered_by_surface_softness():
    s = load_soils()
    assert s["concrete"].value < s["firm_untilled"].value < s["tilled"].value < s["sandy"].value
