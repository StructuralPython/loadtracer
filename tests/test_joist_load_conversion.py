import math
import warnings

import pytest

from builders import DictGraph, make_beam_pm, make_wall_pm, occupancy_load, point_load
from conservation import applied_occupancy_totals, bottom_reaction_totals
from loadtracer.errors import LoadTracerWarning
from loadtracer.joist_load_conversion import (
    DECREASING,
    INCREASING,
    UNIFORM,
    VARIABLE,
    JoistLoadVariabilityWarning,
    JoistTribWidthWarning,
    classify_profile,
    convert_joist_point_loads,
    fit_trapezoid,
    group_joist_point_loads,
    split_joist_tag,
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


@pytest.mark.parametrize(
    "intensities, profile",
    [
        ([2.0] * 6, UNIFORM),
        ([1.0, 1.5, 2.0, 2.5, 3.0], INCREASING),
        ([3.0, 2.5, 2.0, 1.5, 1.0], DECREASING),
        ([1.0, 2.0, 3.0, 2.0, 1.0], VARIABLE),
        ([1.0, 1.04, 0.97, 1.03, 0.98], UNIFORM),
        ([1.0, 1.08, 0.95, 1.05, 1.02], VARIABLE),
        ([1.0, -1.0, 1.0], VARIABLE),
        ([0.0, 0.0, 0.0], UNIFORM),
    ],
    ids=["uniform", "increasing", "decreasing", "triangular", "noisy", "noisy-over-tol", "uplift", "zero"],
)
def test_classify_profile(intensities, profile):
    assert classify_profile(intensities) == profile


@pytest.mark.parametrize("scale", [1e-3, 1.0, 1e6, -1.0, -1e6])
@pytest.mark.parametrize(
    "intensities",
    [[2.0] * 5, [1.0, 1.5, 2.0, 2.5], [2.5, 2.0, 1.5, 1.0], [1.0, 3.0, 1.0], [1.0, 1.05, 0.97]],
)
def test_classify_profile_is_scale_free(intensities, scale):
    assert classify_profile([w * scale for w in intensities]) == classify_profile(intensities)


def test_classify_profile_tolerance_is_relative():
    # max - min relative to the mean: 0.09 and 0.11 around a mean of 1.0
    assert classify_profile([0.955, 1.045], rel_tol=0.10) == UNIFORM
    assert classify_profile([100.955, 101.045], rel_tol=0.10) == UNIFORM
    assert classify_profile([0.945, 1.055, 1.0], rel_tol=0.10) != UNIFORM


# Conversion scenarios


def test_uniform_joists_become_a_udl():
    locations, reactions = uniform_reactions(9, 1.0, w=3.0)
    pm = convert_joist_point_loads(beam_with_points(joist_array("J1.0", locations, reactions)))
    (dist_load,) = converted(pm)
    (component,) = dist_load["expanded"]
    assert component["profile"] == UNIFORM
    assert component["start_magnitude"] == pytest.approx(3.0)
    assert component["end_magnitude"] == pytest.approx(3.0)
    assert (component["start_loc"], component["end_loc"]) == (0.0, 8.0)
    assert pm["loads"]["point_loads"] == []
    assert len(pm["loads"]["converted_point_loads"]) == 9
    assert dist_load["converted_from"] == [f"J1.0-{i}" for i in range(9)]


@pytest.mark.parametrize("direction", [1, -1])
def test_linearly_varying_joists_become_a_trapezoid(direction):
    locations = [float(i) for i in range(11)]
    widths = trib_widths(locations)
    line_load = [2.0 + 0.4 * x for x in locations][::direction]
    reactions = [w * b for w, b in zip(line_load, widths)]
    pm = convert_joist_point_loads(beam_with_points(joist_array("J1.0", locations, reactions)))
    (component,) = converted(pm)[0]["expanded"]
    assert component["profile"] == (INCREASING if direction == 1 else DECREASING)
    assert resultant(component) == pytest.approx(sum(reactions))
    assert component["start_magnitude"] == pytest.approx(line_load[0], rel=0.05)
    assert component["end_magnitude"] == pytest.approx(line_load[-1], rel=0.05)


def test_triangular_joists_become_a_udl_with_warning_at_two_to_one():
    locations = [float(i) for i in range(9)]
    widths = trib_widths(locations)
    line_load = [1.0, 1.5, 2.0, 2.5, 3.0, 2.5, 2.0, 1.5, 1.0]
    reactions = [w * b for w, b in zip(line_load, widths)]
    with pytest.warns(JoistLoadVariabilityWarning, match="FB1.0.*J1.0.*3.0:1"):
        pm = convert_joist_point_loads(beam_with_points(joist_array("J1.0", locations, reactions)))
    (component,) = converted(pm)[0]["expanded"]
    assert component["profile"] == VARIABLE
    assert component["start_magnitude"] == component["end_magnitude"]
    assert resultant(component) == pytest.approx(sum(reactions))


def test_variable_joists_under_two_to_one_do_not_warn():
    locations = [float(i) for i in range(5)]
    widths = trib_widths(locations)
    line_load = [1.0, 1.6, 1.0, 1.6, 1.0]
    reactions = [w * b for w, b in zip(line_load, widths)]
    with warnings.catch_warnings():
        warnings.simplefilter("error", JoistLoadVariabilityWarning)
        pm = convert_joist_point_loads(beam_with_points(joist_array("J1.0", locations, reactions)))
    assert converted(pm)[0]["expanded"][0]["profile"] == VARIABLE


def test_each_load_case_is_classified_separately():
    locations = [0.0, 1.0, 2.0, 3.0]
    widths = trib_widths(locations)
    loads = [
        joist_point_load(f"J1.0-{i}", x, {"D": 2.0 * b, "L": (1.0 + x) * b})
        for i, (x, b) in enumerate(zip(locations, widths))
    ]
    pm = convert_joist_point_loads(beam_with_points(loads))
    profiles = {c["case"]: c["profile"] for c in converted(pm)[0]["expanded"]}
    assert profiles == {"D": UNIFORM, "L": INCREASING}


@pytest.mark.parametrize(
    "line_load",
    [
        [3.0] * 7,
        [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
        [7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
        [1.0, 5.0, 1.0, 5.0, 1.0, 5.0, 1.0],
        [0.1, 0.1, 0.1, 10.0, 10.0, 10.0, 10.0],
    ],
)
def test_converted_load_equals_the_joist_total(line_load):
    locations = [0.0, 0.7, 1.9, 3.0, 4.2, 5.0, 6.1]
    reactions = [w * b for w, b in zip(line_load, trib_widths(locations))]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", JoistLoadVariabilityWarning)
        pm = convert_joist_point_loads(beam_with_points(joist_array("J1.0", locations, reactions)))
    (component,) = converted(pm)[0]["expanded"]
    assert math.isclose(resultant(component), sum(reactions), rel_tol=1e-12)
    assert component["point_load_total"] == pytest.approx(sum(reactions))


def test_fit_trapezoid_never_changes_sign():
    locations = [0.0, 1.0, 2.0, 3.0]
    w_start, w_end = fit_trapezoid(locations, [0.1, 0.1, 0.1, 10.0], total=6.0)
    assert w_start >= 0 and w_end >= 0
    assert (w_start + w_end) / 2 * 3.0 == pytest.approx(6.0)


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
    view = converted(pm)[0]["trib_view"]["D"]
    assert view == {
        "occupancy": "res",
        "pressure": 1.5,
        "trib_width_start": pytest.approx(4.0),
        "trib_width_end": pytest.approx(4.0),
        "approximate": False,
    }


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
    assert row["profile"] == UNIFORM
    assert row["array"] == "J1.0" and row["joists"] == 9
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
    "kwargs", [{"joist_profile_rel_tol": -0.1}, {"joist_profile_rel_tol": 1.0}, {"joist_variability_ratio": 1.0}]
)
def test_conversion_settings_are_validated(kwargs):
    with pytest.raises(ValueError):
        LoadTracer(geometry_graph=DictGraph(), occupancies={"res": {"D": 1.0}}, **kwargs)
