"""
Sensitivity tests: inputs that used to break a load rundown (see
docs/robustness_audit.md). Each test names the audit finding it covers.
"""

import math
import warnings

import pytest

from builders import (
    DictGraph,
    make_beam_pm,
    make_column_pm,
    make_wall_pm,
    occupancy_load,
    point_load,
    support,
    transfer_dist_load,
)
from conservation import applied_occupancy_totals, bottom_reaction_totals
from loadtracer import (
    AnalysisError,
    InvalidPapermodelError,
    LoadTracerWarning,
    ReactionNotFoundError,
    UnstableMemberError,
)
from loadtracer.analysis_models.frame_model import PyniteFrame
from loadtracer.analysis_models.wall_model import LoadbearingWall
from loadtracer.expand_reactions import expand_reaction_loads, is_excluded
from loadtracer.load_tracer import LoadTracer
from loadtracer.validation import conform_loads_to_member, validate_papermodel

OCCUPANCIES = {"res": {"D": 1.0, "L": 2.0}}
GRAVITY = {"gravity": ["FY"]}


def run(graph, **kwargs) -> LoadTracer:
    lt = LoadTracer(geometry_graph=graph, occupancies=OCCUPANCIES, **kwargs)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", LoadTracerWarning)
        lt.execute_analyses()
    return lt


def assert_conserved(lt):
    applied, bottom = applied_occupancy_totals(lt), bottom_reaction_totals(lt)
    assert applied.keys() == bottom.keys()
    for case in applied:
        assert math.isclose(applied[case], bottom[case], rel_tol=1e-9), case


def fy(lt, tag, index, case="D"):
    return lt.reactions[tag][index]["FY"][case]


# F1: beams without enough supports


@pytest.mark.parametrize(
    "supports",
    [[], [5.0], [0.0], [10.0], [support(0.0, fixity="roller"), support(10.0, fixity="roller")]],
    ids=["none", "one-mid", "one-start", "one-end", "two-rollers"],
)
def test_unstable_beam_raises_with_tag(supports):
    graph = DictGraph().add_member(
        make_beam_pm("FB1.0", 10.0, supports, dist_loads=[occupancy_load(0, 10, "res")])
    )
    with pytest.raises(UnstableMemberError, match="FB1.0"):
        run(graph)


def test_cantilever_with_fixed_support_is_stable():
    pm = make_beam_pm(
        "FB1.0", 4.0, [support(0.0, fixity="fixed")], dist_loads=[occupancy_load(0, 4, "res")]
    )
    lt = run(DictGraph().add_member(pm))
    assert fy(lt, "FB1.0", 0) == pytest.approx(-4.0)


def test_supports_away_from_the_ends_give_overhangs():
    pm = make_beam_pm("FB1.0", 10.0, [2.0, 8.0], dist_loads=[occupancy_load(0, 10, "res")])
    lt = run(DictGraph().add_member(pm))
    assert fy(lt, "FB1.0", 0) == pytest.approx(-5.0)
    assert fy(lt, "FB1.0", 1) == pytest.approx(-5.0)


def test_coincident_supports_keep_reaction_indexes():
    pm = make_beam_pm("FB1.0", 10.0, [0.0, 0.0004, 10.0], dist_loads=[occupancy_load(0, 10, "res")])
    lt = run(DictGraph().add_member(pm))
    assert list(lt.reactions["FB1.0"]) == [0, 1, 2]
    assert lt.reactions["FB1.0"][1] == {}
    assert fy(lt, "FB1.0", 0) + fy(lt, "FB1.0", 2) == pytest.approx(-10.0)
    assert any("coincide" in issue for issue in lt.issues["FB1.0"])


def test_support_slightly_off_the_member_is_moved_to_the_end():
    pm = make_beam_pm("FB1.0", 11.065, [0.0, 11.11], dist_loads=[occupancy_load(0, 11.065, "res")])
    lt = run(DictGraph().add_member(pm))
    assert fy(lt, "FB1.0", 0) + fy(lt, "FB1.0", 1) == pytest.approx(-11.065)


# F2: loads off the member or with no length


def test_distributed_load_past_the_member_is_kept_as_end_point_load():
    # The trib area of a joist commonly extends past its ends
    pm = make_beam_pm("J1.0-0", 10.0, [0.0, 10.0], dist_loads=[occupancy_load(-0.5, 10.5, "res")])
    lt = run(DictGraph().add_member(pm))
    assert fy(lt, "J1.0-0", 0) + fy(lt, "J1.0-0", 1) == pytest.approx(-11.0)
    assert fy(lt, "J1.0-0", 0) == pytest.approx(fy(lt, "J1.0-0", 1))


def test_distributed_load_entirely_past_the_member_is_not_lost():
    pm = make_beam_pm("J1.0-0", 10.0, [0.0, 10.0], dist_loads=[occupancy_load(10.0, 10.2, "res")])
    lt = run(DictGraph().add_member(pm))
    assert fy(lt, "J1.0-0", 1) == pytest.approx(-0.2)


def test_zero_length_distributed_load_is_dropped():
    pm = make_beam_pm(
        "FB1.0",
        10.0,
        [0.0, 10.0],
        dist_loads=[occupancy_load(4.0, 4.0, "res"), occupancy_load(0, 10, "res")],
    )
    lt = run(DictGraph().add_member(pm))
    assert fy(lt, "FB1.0", 0) == pytest.approx(-5.0)


def test_clipping_preserves_trapezoid_resultant():
    pm = make_beam_pm("B", 10.0, [0.0, 10.0])
    pm["loads"]["distributed_loads"] = [
        {
            "expanded": [
                {"start_magnitude": 0.0, "end_magnitude": 12.0, "start_loc": -2.0,
                 "end_loc": 10.0, "case": "D", "dir": "FY"}
            ]
        }
    ]
    issues = conform_loads_to_member(pm)
    kept = pm["loads"]["distributed_loads"][0]["expanded"][0]
    assert kept["start_loc"] == 0.0 and kept["start_magnitude"] == pytest.approx(2.0)
    end_load = pm["loads"]["point_loads"][0]["expanded"][0]
    assert end_load["location"] == 0.0 and end_load["magnitude"] == pytest.approx(2.0)
    assert issues


# F3: errors lost their cause


def test_unexpected_errors_keep_the_member_tag_and_cause(monkeypatch):
    def boom(self):
        raise RuntimeError("solver exploded")

    monkeypatch.setattr(PyniteFrame, "get_reactions", boom)
    graph = DictGraph().add_member(
        make_beam_pm("FB1.0", 10.0, [0.0, 10.0], dist_loads=[occupancy_load(0, 10, "res")])
    )
    with pytest.raises(AnalysisError, match="FB1.0.*solver exploded") as info:
        run(graph)
    assert isinstance(info.value.__cause__, RuntimeError)


def test_collect_mode_records_errors_and_continues():
    graph = (
        DictGraph()
        .add_member(make_beam_pm("FB2.0", 10.0, [5.0], dist_loads=[occupancy_load(0, 10, "res")]),
                    supported_by=("CT1.0",))
        .add_member(make_beam_pm("FB2.1", 10.0, [0.0, 10.0], dist_loads=[occupancy_load(0, 10, "res")]))
        .add_member(make_column_pm("CT1.0", point_loads=[point_load([], "FB2.0")]))
    )
    lt = run(graph, on_error="collect")
    assert isinstance(lt.errors["FB2.0"], UnstableMemberError)
    assert isinstance(lt.errors["CT1.0"], ReactionNotFoundError)
    assert fy(lt, "FB2.1", 0) == pytest.approx(-5.0)


# F4: unloaded members had no reactions, which broke every member below them


def test_unloaded_member_passes_zero_load_down():
    graph = (
        DictGraph()
        .add_member(make_beam_pm("FB1.0", 10.0, [0.0, 10.0]), supported_by=("CT0.0", "CT0.1"))
        .add_member(make_column_pm("CT0.0", point_loads=[point_load([0.0], "FB1.0", 0)]))
        .add_member(make_column_pm("CT0.1", point_loads=[point_load([0.0], "FB1.0", 1)]))
    )
    lt = run(graph)
    assert lt.reactions["FB1.0"] == {0: {}, 1: {}}
    assert lt.reactions["CT0.0"] == {0: {}}


# F5: reaction indexes shifted when a support had no reaction


def test_zero_reaction_support_keeps_its_index():
    # A point load directly over the middle support: the end supports have no
    # reaction and pynite_tools would drop them, shifting the middle one to index 0
    graph = (
        DictGraph()
        .add_member(make_beam_pm("J1.0-0", 4.0, [0.0, 4.0], dist_loads=[occupancy_load(0, 4, "res")]),
                    supported_by=("CT0.9", "FB1.0"))
        .add_member(make_column_pm("CT0.9", point_loads=[point_load([0.0], "J1.0-0", 0)]))
        .add_member(make_beam_pm("FB1.0", 10.0, [0.0, 5.0, 10.0], point_loads=[point_load(5.0, "J1.0-0", 1)]),
                    supported_by=("CT0.0", "CT0.1", "CT0.2"))
        .add_member(make_column_pm("CT0.0", point_loads=[point_load([0.0], "FB1.0", 0)]))
        .add_member(make_column_pm("CT0.1", point_loads=[point_load([0.0], "FB1.0", 1)]))
        .add_member(make_column_pm("CT0.2", point_loads=[point_load([0.0], "FB1.0", 2)]))
    )
    lt = run(graph)
    assert fy(lt, "FB1.0", 0) == pytest.approx(0.0, abs=1e-9)
    assert fy(lt, "FB1.0", 1) == pytest.approx(-2.0)
    assert fy(lt, "CT0.1", 0) == pytest.approx(-2.0)
    assert fy(lt, "CT0.0", 0) == pytest.approx(0.0, abs=1e-9)
    assert_conserved(lt)


# F6: missing reactions


def test_missing_index_zero_reaction_is_ignored_when_asked():
    pm = make_wall_pm("WT0.0", 10.0, dist_loads=[transfer_dist_load(0, 10, "WT1.0", 0)])
    new_pm, ignored = expand_reaction_loads(pm, {}, GRAVITY, GRAVITY, missing_reactions="ignore")
    assert ignored == {"WT0.0": ["WT1.0"]}
    with pytest.raises(ReactionNotFoundError, match="WT0.0.*WT1.0"):
        expand_reaction_loads(pm, {}, GRAVITY, GRAVITY, missing_reactions="raise")


def test_missing_reaction_index_is_reported():
    pm = make_column_pm("CT0.0", point_loads=[point_load(0.0, "FB1.0", 3)])
    with pytest.raises(ReactionNotFoundError, match="index 3"):
        expand_reaction_loads(pm, {"FB1.0": {0: {}, 1: {}}}, GRAVITY, GRAVITY)


# F7: transfer loads were duplicated in the expanded papermodel


def test_transfer_loads_are_not_duplicated():
    pm = make_beam_pm(
        "FB1.0",
        10.0,
        [0.0, 10.0],
        point_loads=[point_load(5.0, "J1.0-0", 0)],
        dist_loads=[transfer_dist_load(0, 10, "B2", 0), occupancy_load(0, 10, "res")],
    )
    reactions = {"J1.0-0": {0: {"FY": {"D": -1.0}}}, "B2": {0: {"FY": {"D": -2.0}}}}
    new_pm, _ = expand_reaction_loads(pm, reactions, GRAVITY, GRAVITY)
    assert len(new_pm["loads"]["point_loads"]) == 1
    assert len(new_pm["loads"]["distributed_loads"]) == 2
    assert "expanded" not in pm["loads"]["point_loads"][0]


# F8: walls: split reaction directions, flipped signs, whole-wall transfers


def test_wall_point_and_distributed_loads_both_reach_the_member_below():
    graph = (
        DictGraph()
        .add_member(make_beam_pm("J1.0-0", 4.0, [0.0, 4.0], dist_loads=[occupancy_load(0, 4, "res")]),
                    supported_by=("WT1.0",))
        .add_member(
            make_wall_pm("WT1.0", 10.0,
                         point_loads=[point_load(3.0, "J1.0-0", 0), point_load(7.0, "J1.0-0", 1)],
                         dist_loads=[occupancy_load(0, 10, "res")]),
            supported_by=("WT0.0",),
        )
        .add_member(make_wall_pm("WT0.0", 10.0, dist_loads=[transfer_dist_load(0, 10, "WT1.0")]))
    )
    lt = run(graph)
    assert set(lt.reactions["WT1.0"][0]) == {"FY"}
    assert_conserved(lt)


def test_load_sign_is_preserved_through_stacked_walls():
    graph = (
        DictGraph()
        .add_member(make_wall_pm("WT2.0", 10.0, dist_loads=[occupancy_load(0, 10, "res")]),
                    supported_by=("WT1.0",))
        .add_member(make_wall_pm("WT1.0", 10.0, dist_loads=[transfer_dist_load(0, 10, "WT2.0")]),
                    supported_by=("WT0.0",))
        .add_member(make_wall_pm("WT0.0", 10.0, dist_loads=[transfer_dist_load(0, 10, "WT1.0")]))
    )
    lt = run(graph)
    for tag in ("WT1.0", "WT0.0"):
        components = lt.expanded_pm[tag]["loads"]["distributed_loads"][0]["expanded"]
        assert all(c["start_magnitude"] > 0 for c in components if c["case"] == "D")
    assert_conserved(lt)


def test_wall_on_several_members_is_divided_between_them():
    # A 12-long wall bears on a beam from 0 to 4 and on a wall from 4 to 12
    graph = (
        DictGraph()
        .add_member(make_wall_pm("WT1.0", 12.0, dist_loads=[occupancy_load(0, 12, "res")]),
                    supported_by=("FB0.0", "WT0.0"))
        .add_member(make_beam_pm("FB0.0", 4.0, [0.0, 4.0],
                                 dist_loads=[transfer_dist_load(0, 4, "WT1.0", source_extents=(0.0, 4.0))]))
        .add_member(make_wall_pm("WT0.0", 8.0,
                                 dist_loads=[transfer_dist_load(0, 8, "WT1.0", source_extents=(4.0, 12.0))]))
    )
    lt = run(graph)
    assert fy(lt, "FB0.0", 0) + fy(lt, "FB0.0", 1) == pytest.approx(-4.0)
    assert_conserved(lt)


def test_wall_longer_than_its_support_is_not_lost():
    graph = (
        DictGraph()
        .add_member(make_wall_pm("WT1.0", 12.0, dist_loads=[occupancy_load(0, 12, "res")]),
                    supported_by=("WT0.0",))
        .add_member(make_wall_pm("WT0.0", 10.0,
                                 dist_loads=[transfer_dist_load(0, 10, "WT1.0", source_extents=(1.0, 11.0))]))
    )
    assert_conserved(run(graph))


def test_wall_on_overlapping_supports_is_reported():
    graph = (
        DictGraph()
        .add_member(make_wall_pm("WT1.0", 12.0, dist_loads=[occupancy_load(0, 12, "res")]),
                    supported_by=("FB0.0", "WT0.0"))
        .add_member(make_beam_pm("FB0.0", 4.0, [0.0, 4.0],
                                 dist_loads=[transfer_dist_load(0, 4, "WT1.0", source_extents=(2.0, 6.0))]))
        .add_member(make_wall_pm("WT0.0", 12.0,
                                 dist_loads=[transfer_dist_load(0, 12, "WT1.0", source_extents=(0.0, 12.0))]))
    )
    lt = LoadTracer(geometry_graph=graph, occupancies=OCCUPANCIES)
    with pytest.warns(LoadTracerWarning):
        lt.execute_analyses()
    assert any("both support" in issue for issue in lt.issues["WT1.0"])


def test_wall_builder_does_not_mutate_its_input():
    pm = make_wall_pm("WT0.0", 10.0)
    pm["loads"]["point_loads"] = [
        {"location": 10.5, "expanded": [{"magnitude": 1.0, "location": 10.5, "case": "D", "dir": "FY"}]}
    ]
    conformed = validate_papermodel(pm)[0]
    conform_loads_to_member(conformed)
    LoadbearingWall(conformed, vertical_spread_angle=0, minimum_point_spread=1)
    assert pm["loads"]["point_loads"][0]["expanded"][0]["location"] == 10.5


# F9: invalid input


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda pm: pm["element_attributes"].update(orientation="unknown"), "orientation"),
        (lambda pm: pm["element_attributes"].update(length={}), "length"),
        (lambda pm: pm.pop("loads"), "loads"),
        (lambda pm: pm["loads"]["point_loads"].append(point_load([1.0, 2.0], "X")), "2 locations"),
        (lambda pm: pm["loads"]["point_loads"].append(point_load(None, "X")), "location"),
        (lambda pm: pm["loads"]["distributed_loads"].append(
            transfer_dist_load(0, 1, "X", direction="sideways")), "sideways"),
    ],
    ids=["orientation", "length", "no-loads", "multi-location", "no-location", "direction"],
)
def test_invalid_papermodel_raises_with_tag(change, message):
    pm = make_beam_pm("FB1.0", 10.0, [0.0, 10.0])
    change(pm)
    with pytest.raises(InvalidPapermodelError, match=f"FB1.0.*{message}"):
        validate_papermodel(pm)


def test_column_list_locations_are_accepted():
    pm = make_column_pm("CT0.0", point_loads=[point_load([], "A"), point_load([0.0, 0.0], "B")])
    pm, _ = validate_papermodel(pm)
    assert [p["location"] for p in pm["loads"]["point_loads"]] == [0.0, 0.0]


def test_linear_correspondent_without_extents_is_applied_over_the_wall():
    pm = make_wall_pm("WT0.0", 10.0, dist_loads=[transfer_dist_load([], [], "WT1.0")])
    pm, issues = validate_papermodel(pm)
    load = pm["loads"]["distributed_loads"][0]
    assert (load["start_loc"], load["end_loc"]) == (0.0, 10.0)
    assert issues


@pytest.mark.parametrize("occupancies", [{}, {"res": {}}, {"res": 1.0}])
def test_invalid_occupancies_are_rejected(occupancies):
    with pytest.raises(ValueError):
        LoadTracer(geometry_graph=DictGraph(), occupancies=occupancies)


def test_unknown_occupancy_raises_with_tag():
    graph = DictGraph().add_member(
        make_beam_pm("FB1.0", 10.0, [0.0, 10.0], dist_loads=[occupancy_load(0, 10, "office")])
    )
    with pytest.raises(InvalidPapermodelError, match="FB1.0.*office"):
        run(graph)


# F10: heights and elevations are no longer inputs


def test_rundown_needs_no_heights():
    graph = (
        DictGraph()
        .add_member(make_wall_pm("WT1.0", 10.0, dist_loads=[occupancy_load(0, 10, "res")]),
                    supported_by=("CT0.0",))
        .add_member(make_column_pm("CT0.0", dist_loads=[transfer_dist_load(0, 10, "WT1.0")]))
    )
    lt = run(graph)
    assert fy(lt, "CT0.0", 0) == pytest.approx(-10.0)


@pytest.mark.parametrize("removed", ["elevations", "vertical_element_heights"])
def test_removed_height_inputs_warn(removed):
    with pytest.warns(DeprecationWarning, match=removed):
        LoadTracer(geometry_graph=DictGraph(), occupancies=OCCUPANCIES, **{removed: {}})


def test_wall_height_does_not_change_reactions_without_spread_angle():
    pm = make_wall_pm("WT0.0", 10.0)
    pm["loads"]["point_loads"] = [
        {"location": 5.0, "expanded": [{"magnitude": 1.0, "location": 5.0, "case": "D", "dir": "FY"}]}
    ]
    reactions = []
    for height in (None, 3.0, 30.0):
        pm["element_attributes"]["user_defined"] = {} if height is None else {"height": height}
        reactions.append(
            LoadbearingWall(pm, vertical_spread_angle=0, minimum_point_spread=1).get_reactions()
        )
    assert reactions[0] == reactions[1] == reactions[2]


def test_spread_angle_needs_an_annotated_wall_height():
    pm = make_wall_pm("WT0.0", 10.0)
    with pytest.raises(InvalidPapermodelError, match="WT0.0.*height"):
        LoadbearingWall(pm, vertical_spread_angle=30, minimum_point_spread=1)
    pm["element_attributes"]["user_defined"] = {"height": "9"}
    LoadbearingWall(pm, vertical_spread_angle=30, minimum_point_spread=1)


# F11: excluding a joist array


def test_excluding_a_joist_array_excludes_its_joists():
    assert is_excluded("J1.0-3", {"J1.0"})
    assert not is_excluded("J1.0-3", {"J1"})
    assert not is_excluded("FB-A", {"FB"})
    graph = (
        DictGraph()
        .add_array("J1.0", [make_beam_pm("J1.0-0", 4.0, [0.0, 4.0], dist_loads=[occupancy_load(0, 4, "res")])],
                   supported_by=("FB1.0",))
        .add_member(make_beam_pm("FB1.0", 10.0, [0.0, 10.0], point_loads=[point_load(5.0, "J1.0-0", 1)]))
    )
    lt = LoadTracer(geometry_graph=graph, occupancies=OCCUPANCIES)
    lt.execute_analyses(exclude_members=["J1.0"])
    assert "J1.0-0" not in lt.reactions
    assert lt.reactions["FB1.0"] == {0: {}, 1: {}}


# F12: columns ignored distributed loads


def test_column_carries_distributed_loads():
    graph = (
        DictGraph()
        .add_member(make_wall_pm("WT1.0", 6.0, dist_loads=[occupancy_load(0, 6, "res")]),
                    supported_by=("CT0.0",))
        .add_member(make_column_pm("CT0.0", dist_loads=[transfer_dist_load(0, 6, "WT1.0")]))
    )
    lt = run(graph)
    assert fy(lt, "CT0.0", 0, "L") == pytest.approx(-12.0)
