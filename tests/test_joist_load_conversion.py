import math
import warnings

import pytest

from builders import DictGraph, make_beam_pm, make_wall_pm, occupancy_load, point_load
from conservation import applied_occupancy_totals, bottom_reaction_totals
from loadtracer.errors import LoadTracerWarning
import numpy as np

from loadtracer.joist_load_conversion import (
    POLYLINE,
    UNIFORM,
    JoistLoadVariabilityWarning,
    JoistTribWidthWarning,
    convert_joist_point_loads,
    fit_knot_values,
    fit_polyline,
    group_joist_point_loads,
    knot_load_moments,
    load_shift,
    split_joist_tag,
    strip_bounds,
    strip_load_matrix,
    trib_widths,
)
from loadtracer.load_tracer import LoadTracer


def joist_point_load(tag: str, location: float, magnitudes: dict, index: int = 0) -> dict:
    load = point_load(location, tag, index)
    load["expanded"] = [
        {"magnitude": m, "location": location, "case": case, "dir": "FY"}
        for case, m in magnitudes.items()
    ]
    return load


def joist_array(parent: str, locations: list[float], magnitudes: list[float], case="D"):
    return [
        joist_point_load(f"{parent}-{idx}", x, {case: m})
        for idx, (x, m) in enumerate(zip(locations, magnitudes))
    ]


def beam_with_points(point_loads, length=12.0) -> dict:
    pm = make_beam_pm("FB1.0", length, [0.0, length])
    pm["loads"]["point_loads"] = point_loads
    return pm


def resultant(component):
    return (
        (component["start_magnitude"] + component["end_magnitude"])
        / 2
        * (component["end_loc"] - component["start_loc"])
    )


def converted(pm) -> list[dict]:
    return [d for d in pm["loads"]["distributed_loads"] if "converted_from" in d]


def uniform_reactions(n: int, spacing: float, w: float) -> tuple[list[float], list[float]]:
    """Locations and reactions of joists at 'spacing' carrying a line load 'w'."""
    locations = [i * spacing for i in range(n)]
    widths = trib_widths(locations)
    return locations, [w * width for width in widths]


# Grouping


def test_split_joist_tag():
    assert split_joist_tag("J1.0-3") == ("J1.0", 3)
    assert split_joist_tag("SJF1.0-12") == ("SJF1.0", 12)
    assert split_joist_tag("A-B-2") == ("A-B", 2)
    assert split_joist_tag("FB1.0") is None
    assert split_joist_tag("FB-A") is None


def test_two_arrays_on_one_beam_are_separate_runs():
    loads = joist_array("J1.0", [0, 1, 2, 3], [1] * 4) + joist_array("J2.0", [6, 7, 8], [2] * 3)
    runs = group_joist_point_loads(loads)
    assert sorted(len(run) for run in runs) == [3, 4]


def test_gap_in_an_array_splits_the_run():
    loads = joist_array("J1.0", [0, 1, 2, 3, 7, 8, 9], [1] * 7)
    runs = group_joist_point_loads(loads)
    assert [[load["location"] for load in run] for run in runs] == [[0, 1, 2, 3], [7, 8, 9]]


def test_posts_single_joists_and_unexpanded_loads_are_not_grouped():
    loads = (
        [joist_point_load("CT2.0", 5.0, {"D": 10})]
        + joist_array("J1.0", [2.0], [1])
        + [point_load(3.0, "J3.0-0"), point_load(4.0, "J3.0-1")]
    )
    assert group_joist_point_loads(loads) == []


def test_unsorted_joists_are_sorted():
    loads = joist_array("J1.0", [3, 0, 2, 1], [1] * 4)
    (run,) = group_joist_point_loads(loads)
    assert [load["location"] for load in run] == [0, 1, 2, 3]


def test_trib_widths_add_up_to_the_run():
    widths = trib_widths([0.0, 1.0, 2.5, 3.0])
    assert widths == pytest.approx([0.5, 1.25, 1.0, 0.25])
    assert sum(widths) == pytest.approx(3.0)


# Profiles


# The polyline arithmetic


def random_run(seed: int):
    """Joists at uneven spacing with random reactions, and a random set of knots."""
    rng = np.random.default_rng(seed)
    x = np.unique(rng.uniform(0.0, 12.0, rng.integers(2, 30)))
    while len(x) < 2:
        x = np.unique(rng.uniform(0.0, 12.0, 5))
    P = rng.uniform(-1.0, 5.0, len(x))
    interior = rng.choice(np.arange(1, len(x) - 1), rng.integers(0, max(len(x) - 2, 0) + 1), replace=False) if len(x) > 2 else []
    return x, P, sorted({0, len(x) - 1, *map(int, interior)})


def strip_centroids(x):
    b = strip_bounds(x)
    return (b[:-1] + b[1:]) / 2


@pytest.mark.parametrize("seed", range(25))
def test_strip_load_matrix_reproduces_constant_and_linear_loads(seed):
    x, _, knots = random_run(seed)
    A = strip_load_matrix(x, knots)
    widths = np.diff(strip_bounds(x))
    assert A @ np.ones(len(knots)) == pytest.approx(widths)
    assert A @ x[knots] == pytest.approx(widths * strip_centroids(x))


def test_strip_load_matrix_by_hand():
    # Two knots (0 and 2.4) over strips [0, 0.3], [0.3, 0.9], ...: the hat of
    # the first knot is 1 - x / 2.4, so its integral over [0, 0.3] is 0.28125
    A = strip_load_matrix([0.0, 0.6, 1.2, 1.8, 2.4], [0, 4])
    assert A[:, 0] == pytest.approx([0.28125, 0.45, 0.3, 0.15, 0.01875])
    assert A[:, 1] == pytest.approx(A[::-1, 0])


@pytest.mark.parametrize("seed", range(25))
def test_knot_load_moments_by_numerical_integration(seed):
    x, _, knots = random_run(seed)
    F, M = knot_load_moments(x, knots)
    fine = np.linspace(x[0], x[-1], 200_001)
    for k in range(len(knots)):
        hat = np.interp(fine, x[knots], np.eye(len(knots))[k])
        assert F[k] == pytest.approx(np.trapezoid(hat, fine), abs=1e-6)
        assert M[k] == pytest.approx(np.trapezoid(fine * hat, fine), abs=1e-5)


@pytest.mark.parametrize("seed", range(25))
def test_fitted_load_keeps_the_total_and_the_resultant_location(seed):
    x, P, knots = random_run(seed)
    u = fit_knot_values(x, P, knots)
    F, M = knot_load_moments(x, knots)
    assert F @ u == pytest.approx(P.sum(), abs=1e-9)
    assert M @ u == pytest.approx((x * P).sum(), abs=1e-8)
    assert (strip_load_matrix(x, knots) @ u).sum() == pytest.approx(P.sum(), abs=1e-9)


def test_worked_example():
    # A step from 3.45 to 6.0 kN/m (the docs' worked example)
    x = [0.0, 0.6, 1.2, 1.8, 2.4]
    P = [1.035, 2.07, 2.07, 3.0, 1.8]
    # One trapezoid: fixed by the total (9.975) and the resultant location alone
    assert fit_knot_values(x, P, [0, 4]) == pytest.approx([2.61875, 5.69375])
    knots, u, error = fit_polyline(x, P, tol=0.02)
    assert knots == [0, 2, 3, 4]
    assert error <= 0.02


@pytest.mark.parametrize("tol", [0.10, 0.05, 0.02, 0.005])
def test_fit_polyline_meets_the_tolerance(tol):
    x = np.arange(31) * 0.6
    w = np.where((x > 13.0) & (x < 15.5), 9.05, 4.2)  # an RTU on a roof beam
    P = w * np.diff(strip_bounds(x))
    knots, u, error = fit_polyline(x, P, tol)
    assert error <= tol
    assert knots[0] == 0 and knots[-1] == len(x) - 1
    assert len(knots) < len(x)


def test_load_shift():
    # The joist loads [1, 1, 2] as a uniform 4/2.0 over strips 0.5, 1.0, 0.5:
    # the strip loads are [1, 2, 1]; the running differences are 0 and 1 (of 4)
    assert load_shift([1.0, 2.0, 1.0], [1.0, 1.0, 2.0]) == pytest.approx(0.25)
    assert load_shift([1.0, 1.0, 2.0], [1.0, 1.0, 2.0]) == 0.0
    assert load_shift([0.0], [0.0]) == 0.0


# Conversion scenarios


def test_uniform_joists_become_a_udl():
    locations, reactions = uniform_reactions(9, 1.0, w=3.0)
    pm = convert_joist_point_loads(beam_with_points(joist_array("J1.0", locations, reactions)))
    (dist_load,) = converted(pm)
    (component,) = dist_load["expanded"]
    assert component["profile"] == UNIFORM
    assert component["load_shift"] == pytest.approx(0.0, abs=1e-12)
    assert component["start_magnitude"] == pytest.approx(3.0)
    assert component["end_magnitude"] == pytest.approx(3.0)
    assert (component["start_loc"], component["end_loc"]) == (0.0, 8.0)
    assert pm["loads"]["point_loads"] == []
    assert len(pm["loads"]["converted_point_loads"]) == 9
    assert dist_load["converted_from"] == [f"J1.0-{i}" for i in range(9)]


def test_nearly_uniform_joists_become_a_udl():
    # A 3% bump over part of the run (RB0.4 in the ymprint-chaining demo):
    # a uniform load moves less than 1% of the load along the beam
    locations = [0.6 * i for i in range(21)]
    line_load = [3.56 if 1.5 < x < 9.0 else 3.45 for x in locations]
    reactions = [w * b for w, b in zip(line_load, trib_widths(locations))]
    pm = convert_joist_point_loads(beam_with_points(joist_array("J1.0", locations, reactions)))
    (component,) = converted(pm)[0]["expanded"]
    assert component["profile"] == UNIFORM
    assert 0.0 < component["load_shift"] <= 0.01
    assert resultant(component) == pytest.approx(sum(reactions))


@pytest.mark.parametrize("direction", [1, -1])
def test_linearly_varying_joists_become_one_trapezoid(direction):
    locations = [float(i) for i in range(11)]
    widths = trib_widths(locations)
    line_load = [2.0 + 0.4 * x for x in locations][::direction]
    reactions = [w * b for w, b in zip(line_load, widths)]
    pm = convert_joist_point_loads(beam_with_points(joist_array("J1.0", locations, reactions)))
    (component,) = converted(pm)[0]["expanded"]
    assert component["profile"] == POLYLINE
    # Close, not exact: the end joists' reactions act at the ends of the run,
    # but a line load puts them over half a joist spacing
    assert component["start_magnitude"] == pytest.approx(line_load[0], rel=0.03)
    assert component["end_magnitude"] == pytest.approx(line_load[-1], rel=0.03)
    assert component["fit_error"] <= 0.02


def test_peaked_joist_loads_become_a_polyline():
    locations = [float(i) for i in range(9)]
    widths = trib_widths(locations)
    line_load = [1.0, 1.5, 2.0, 2.5, 3.0, 2.5, 2.0, 1.5, 1.0]
    reactions = [w * b for w, b in zip(line_load, widths)]
    with warnings.catch_warnings():
        warnings.simplefilter("error", JoistLoadVariabilityWarning)
        pm = convert_joist_point_loads(beam_with_points(joist_array("J1.0", locations, reactions)))
    components = converted(pm)[0]["expanded"]
    assert len(components) >= 2
    assert {c["profile"] for c in components} == {POLYLINE}
    assert [c["segment"] for c in components] == list(range(len(components)))
    assert components[0]["start_loc"] == 0.0 and components[-1]["end_loc"] == 8.0
    for a, b in zip(components, components[1:]):  # continuous
        assert a["end_loc"] == b["start_loc"]
        assert a["end_magnitude"] == pytest.approx(b["start_magnitude"])
    assert components[0]["fit_error"] <= 0.02
    assert sum(map(resultant, components)) == pytest.approx(sum(reactions))


def test_load_shift_above_the_limit_warns():
    locations = [float(i) for i in range(9)]
    line_load = [1.0, 1.5, 2.0, 2.5, 3.0, 2.5, 2.0, 1.5, 1.0]
    reactions = [w * b for w, b in zip(line_load, trib_widths(locations))]
    loads = joist_array("J1.0", locations, reactions)
    # A very loose fit (one trapezoid) cannot follow the peak
    with pytest.warns(JoistLoadVariabilityWarning, match=r"FB1.0.*J1.0 \(D\) moves .*% of its load"):
        pm = convert_joist_point_loads(beam_with_points(loads), polyline_tol=0.9, load_shift_limit=0.001)
    (component,) = converted(pm)[0]["expanded"]
    assert component["load_shift"] > 0.001


def test_each_load_case_is_converted_separately():
    locations = [float(i) for i in range(11)]
    widths = trib_widths(locations)
    loads = [
        joist_point_load(f"J1.0-{i}", x, {"D": 2.0 * b, "L": (1.0 + x) * b})
        for i, (x, b) in enumerate(zip(locations, widths))
    ]
    pm = convert_joist_point_loads(beam_with_points(loads))
    profiles = {c["case"]: c["profile"] for c in converted(pm)[0]["expanded"]}
    assert profiles == {"D": UNIFORM, "L": POLYLINE}


@pytest.mark.parametrize(
    "line_load",
    [
        [3.0] * 7,
        [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
        [7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
        [1.0, 5.0, 1.0, 5.0, 1.0, 5.0, 1.0],
        [0.1, 0.1, 0.1, 10.0, 10.0, 10.0, 10.0],
        [2.0, 1.0, -1.0, -2.0, -1.0, 1.0, 2.0],
    ],
)
def test_converted_load_keeps_the_joist_total_and_resultant(line_load):
    locations = [0.0, 0.7, 1.9, 3.0, 4.2, 5.0, 6.1]
    reactions = [w * b for w, b in zip(line_load, trib_widths(locations))]
    pm = convert_joist_point_loads(beam_with_points(joist_array("J1.0", locations, reactions)))
    components = converted(pm)[0]["expanded"]
    assert math.isclose(sum(map(resultant, components)), sum(reactions), rel_tol=1e-9, abs_tol=1e-9)
    assert components[0]["point_load_total"] == pytest.approx(sum(reactions))
    if components[0]["profile"] == POLYLINE:
        moment = sum(
            (c["end_loc"] - c["start_loc"])
            * (c["start_magnitude"] * (2 * c["start_loc"] + c["end_loc"])
               + c["end_magnitude"] * (c["start_loc"] + 2 * c["end_loc"]))
            / 6
            for c in components
        )
        assert moment == pytest.approx(sum(x * p for x, p in zip(locations, reactions)), abs=1e-9)
    else:
        assert components[0]["load_shift"] <= 0.01


def test_other_point_loads_are_kept():
    post = joist_point_load("CT2.0", 5.0, {"D": 10.0})
    locations, reactions = uniform_reactions(5, 1.0, w=1.0)
    pm = convert_joist_point_loads(beam_with_points([post] + joist_array("J1.0", locations, reactions)))
    assert pm["loads"]["point_loads"] == [post]


def test_coincident_joists_are_left_as_point_loads():
    loads = joist_array("J1.0", [1.0, 1.0], [1.0, 1.0])
    pm = convert_joist_point_loads(beam_with_points(loads))
    assert converted(pm) == []
    assert len(pm["loads"]["point_loads"]) == 2


# Trib width view


def joist_pm(tag: str, occupancy_areas: dict[str, float], transfer: bool = False) -> dict:
    pm = make_beam_pm(tag, 10.0, [0.0, 10.0])
    for occupancy, area in occupancy_areas.items():
        load = occupancy_load(0, 10, occupancy)
        load["applied_area"] = area
        pm["loads"]["distributed_loads"].append(load)
    if transfer:
        load = point_load(5.0, "CT3.0")
        load["expanded"] = [{"magnitude": 1.0, "location": 5.0, "case": "D", "dir": "FY"}]
        pm["loads"]["point_loads"].append(load)
    return pm


def test_trib_view_for_a_single_occupancy_is_exact():
    locations, reactions = uniform_reactions(5, 1.0, w=6.0)
    joist_pms = {f"J1.0-{i}": joist_pm(f"J1.0-{i}", {"res": 10.0}) for i in range(5)}
    pm = convert_joist_point_loads(
        beam_with_points(joist_array("J1.0", locations, reactions)),
        joist_pms=joist_pms,
        occupancies={"res": {"D": 1.5, "L": 2.0}},
    )
    dist_load = converted(pm)[0]
    assert dist_load["trib_view"]["D"] == {"occupancy": "res", "pressure": 1.5, "approximate": False}
    component = next(c for c in dist_load["expanded"] if c["case"] == "D")
    assert component["trib_width_start"] == pytest.approx(4.0)
    assert component["trib_width_end"] == pytest.approx(4.0)


@pytest.mark.parametrize(
    "areas, transfer",
    [({"res": 10.0, "office": 2.0}, False), ({"res": 10.0}, True)],
    ids=["mixed-occupancies", "transfer-loads"],
)
def test_trib_view_is_approximate_for_mixed_loads(areas, transfer):
    locations, reactions = uniform_reactions(5, 1.0, w=6.0)
    joist_pms = {f"J1.0-{i}": joist_pm(f"J1.0-{i}", areas, transfer) for i in range(5)}
    with pytest.warns(JoistTribWidthWarning, match="J1.0"):
        pm = convert_joist_point_loads(
            beam_with_points(joist_array("J1.0", locations, reactions)),
            joist_pms=joist_pms,
            occupancies={"res": {"D": 1.5}, "office": {"D": 1.0}},
        )
    view = converted(pm)[0]["trib_view"]["D"]
    assert view["occupancy"] == "res"
    assert view["approximate"] is True


# End to end


def array_graph(n: int = 9, length: float = 8.0, span: float = 6.0, beam_supports=(0.0, 8.0)):
    """A joist array spanning between a beam and a wall; the beam sits on walls."""
    spacing = length / (n - 1)
    joists = [
        make_beam_pm(
            f"J1.0-{i}", span, [0.0, span], dist_loads=[occupancy_load(-0.1, span + 0.1, "res", spacing)]
        )
        for i in range(n)
    ]
    for pm in joists[:: n - 1]:  # the end joists carry half a spacing
        pm["loads"]["distributed_loads"][0]["start_magnitude"] = spacing / 2
        pm["loads"]["distributed_loads"][0]["end_magnitude"] = spacing / 2
    beam = make_beam_pm(
        "FB1.0",
        length,
        list(beam_supports),
        point_loads=[point_load(i * spacing, f"J1.0-{i}", 0) for i in range(n)],
    )
    wall = make_wall_pm("WT1.0", length, point_loads=[point_load(i * spacing, f"J1.0-{i}", 1) for i in range(n)])
    graph = DictGraph().add_array("J1.0", joists, supported_by=("FB1.0", "WT1.0")).add_member(beam).add_member(wall)
    return graph


def rundown(graph, **kwargs) -> LoadTracer:
    lt = LoadTracer(geometry_graph=graph, occupancies={"res": {"D": 1.0, "L": 2.0}}, **kwargs)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", LoadTracerWarning)
        lt.execute_analyses()
    return lt


def test_joist_loads_are_distributed_by_default():
    lt = rundown(array_graph())
    for member in ("FB1.0", "WT1.0"):
        pm = lt.expanded_pm[member]
        assert pm["loads"]["point_loads"] == []
        assert [d["transfer_source"] for d in pm["loads"]["distributed_loads"]] == ["J1.0"]
    member = lt.models["FB1.0"]["members"]["FB1.0"]
    assert len(member["DistLoads"]) == 2  # one per load case in the Pynite model
    assert member["PtLoads"] == []


def test_point_mode_keeps_joist_point_loads():
    lt = rundown(array_graph(), joist_loads="point")
    assert len(lt.expanded_pm["FB1.0"]["loads"]["point_loads"]) == 9
    assert lt.converted_joist_loads() == []


def test_converted_joist_loads_table():
    rows = rundown(array_graph()).converted_joist_loads("FB1.0")
    assert {row["case"] for row in rows} == {"D", "L"}
    row = next(row for row in rows if row["case"] == "D")
    assert row["profile"] == UNIFORM and row["segment"] == 0
    assert row["array"] == "J1.0" and row["joists"] == 9
    assert row["total"] == pytest.approx(row["joist_total"])
    # A 6.2 long joist trib strip (6.0 span + 0.1 each side) gives 3.1 to each support
    assert row["w_start"] == pytest.approx(3.1)
    assert row["occupancy"] == "res" and row["trib_width_start"] == pytest.approx(3.1)


@pytest.mark.parametrize("beam_supports", [(0.0, 8.0), (0.0, 3.0, 8.0), (1.0, 7.0)])
def test_distributed_and_point_modes_carry_the_same_load(beam_supports):
    graph = array_graph(beam_supports=beam_supports)
    point, distributed = rundown(graph, joist_loads="point"), rundown(graph)
    for lt in (point, distributed):
        applied, bottom = applied_occupancy_totals(lt), bottom_reaction_totals(lt)
        for case in applied:
            assert math.isclose(applied[case], bottom[case], rel_tol=1e-9)
    for member in ("FB1.0", "WT1.0"):
        for case in ("D", "L"):
            totals = [
                sum(r["FY"][case] if not isinstance(r["FY"][case], list) else sum(map(resultant, r["FY"][case]))
                    for r in lt.reactions[member].values())
                for lt in (point, distributed)
            ]
            assert totals[0] == pytest.approx(totals[1])


def test_uniform_joists_give_the_same_reactions_as_point_loads():
    graph = array_graph(n=17)
    point, distributed = rundown(graph, joist_loads="point"), rundown(graph)
    for idx in (0, 1):
        assert distributed.reactions["FB1.0"][idx]["FY"]["D"] == pytest.approx(
            point.reactions["FB1.0"][idx]["FY"]["D"], rel=1e-9
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"joist_polyline_tol": 0.0},
        {"joist_polyline_tol": 1.0},
        {"joist_load_shift_limit": -0.01},
        {"joist_load_shift_limit": 1.0},
    ],
)
def test_conversion_settings_are_validated(kwargs):
    with pytest.raises(ValueError):
        LoadTracer(geometry_graph=DictGraph(), occupancies={"res": {"D": 1.0}}, **kwargs)


@pytest.mark.parametrize("key", ["joist_profile_rel_tol", "joist_variability_ratio"])
def test_replaced_conversion_settings_warn(key):
    with pytest.warns(DeprecationWarning, match=key):
        lt = LoadTracer(geometry_graph=DictGraph(), occupancies={"res": {"D": 1.0}}, **{key: 2.0})
    assert lt.joist_polyline_tol == 0.02


def rtu_graph(n: int = 21, length: float = 12.0, span: float = 3.0):
    """
    A joist array on a beam continuous over three supports, with an RTU load on
    three joists near the middle support.
    """
    spacing = length / (n - 1)
    joists = []
    for i in range(n):
        trib = spacing / 2 if i in (0, n - 1) else spacing
        loads = [occupancy_load(0.0, span, "res", trib)]
        if i in (11, 12, 13):
            loads.append(occupancy_load(0.0, span, "rtu", trib))
        joists.append(make_beam_pm(f"J1.0-{i}", span, [0.0, span], dist_loads=loads))
    beam = make_beam_pm(
        "FB1.0", length, [0.0, length / 2, length],
        point_loads=[point_load(i * spacing, f"J1.0-{i}", 0) for i in range(n)],
    )
    wall = make_wall_pm("WT1.0", length, point_loads=[point_load(i * spacing, f"J1.0-{i}", 1) for i in range(n)])
    return DictGraph().add_array("J1.0", joists, supported_by=("FB1.0", "WT1.0")).add_member(beam).add_member(wall)


def test_polyline_gives_reactions_close_to_point_loads():
    graph = rtu_graph()
    occupancies = {"res": {"D": 1.0, "L": 2.0}, "rtu": {"D": 4.0}}
    results = {}
    for mode in ("point", "distributed"):
        lt = LoadTracer(geometry_graph=graph, occupancies=occupancies, joist_loads=mode, show_progress=False)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", JoistTribWidthWarning)
            warnings.simplefilter("error", JoistLoadVariabilityWarning)
            lt.execute_analyses()
        results[mode] = lt
    dead = [c for c in results["distributed"].expanded_pm["FB1.0"]["loads"]["distributed_loads"][0]["expanded"] if c["case"] == "D"]
    assert {c["profile"] for c in dead} == {POLYLINE}
    for idx in (0, 1, 2):
        assert results["distributed"].reactions["FB1.0"][idx]["FY"]["D"] == pytest.approx(
            results["point"].reactions["FB1.0"][idx]["FY"]["D"], rel=0.01
        )
