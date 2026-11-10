"""
The "pynite" and "pycba" frame backends must be interchangeable: the same
rundown gives the same reactions (format, indexes, signs and values) with
either backend.
"""

import math
import sys
import warnings

import pytest
from pydantic import ValidationError

from builders import (
    DictGraph,
    make_beam_pm,
    make_column_pm,
    occupancy_load,
    point_load,
    support,
)
from conservation import applied_occupancy_totals, bottom_reaction_totals
from loadtracer import AnalysisError, LoadTracerWarning
from loadtracer.analysis_models.frame_model import (
    PycbaFrame,
    PyniteFrame,
    build_pycba_frame_model,
    frame_model_class,
)
from loadtracer.load_tracer import LoadTracer

pycba_tools = pytest.importorskip("pycba_tools")

OCCUPANCIES = {"res": {"D": 1.0, "L": 2.0}}


def run(graph, frame_backend: str, occupancies=OCCUPANCIES, **kwargs) -> LoadTracer:
    lt = LoadTracer(
        geometry_graph=graph,
        occupancies=occupancies,
        frame_backend=frame_backend,
        show_progress=False,
        **kwargs,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", LoadTracerWarning)
        lt.execute_analyses()
    return lt


def assert_same_reactions(
    a: dict, b: dict, rel_tol: float = 1e-6, abs_tol: float = 1e-9
):
    """Recursively compares two reaction trees: same keys, close values."""
    if isinstance(a, dict):
        assert isinstance(b, dict) and a.keys() == b.keys()
        for key in a:
            assert_same_reactions(a[key], b[key], rel_tol, abs_tol)
    elif isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b)
        for x, y in zip(a, b):
            assert_same_reactions(x, y, rel_tol, abs_tol)
    elif isinstance(a, float):
        assert math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol), (a, b)
    else:
        assert a == b


def joists(n: int, length: float, trib: float = 1.0) -> list[dict]:
    return [
        make_beam_pm(
            f"J1.0-{i}",
            length,
            [0.0, length],
            dist_loads=[occupancy_load(0, length, "res", trib)],
        )
        for i in range(n)
    ]


GRAPHS = {
    "simple_beam": lambda: DictGraph().add_member(
        make_beam_pm(
            "FB1.0", 6.0, [0.0, 6.0], dist_loads=[occupancy_load(0, 6.0, "res", 2.0)]
        )
    ),
    "overhangs": lambda: DictGraph().add_member(
        make_beam_pm(
            "FB1.0", 10.0, [2.0, 8.0], dist_loads=[occupancy_load(0, 10.0, "res", 1.5)]
        )
    ),
    "trapezoid_within_two_sub_members": lambda: DictGraph().add_member(
        make_beam_pm(
            "FB1.0",
            10.0,
            [0.0, 4.0, 10.0],
            dist_loads=[occupancy_load(1.0, 9.0, "res", 1.0, 3.0)],
        )
    ),
    "fixed_cantilever": lambda: DictGraph().add_member(
        make_beam_pm(
            "FB1.0",
            4.0,
            [support(0.0, fixity="fixed")],
            dist_loads=[occupancy_load(1.0, 4.0, "res")],
        )
    ),
    "continuous_with_coincident_support": lambda: DictGraph().add_member(
        make_beam_pm(
            "FB1.0",
            12.0,
            [0.0, 0.0004, 5.0, 12.0],
            dist_loads=[occupancy_load(0, 12.0, "res")],
        )
    ),
    # Joist reactions -> beam (as distributed or point loads) -> column
    "joists_on_beam_on_columns": lambda: (
        DictGraph()
        .add_array("J1.0", joists(5, 4.0), supported_by=("FB1.0",))
        .add_member(
            make_beam_pm(
                "FB1.0",
                9.0,
                [0.0, 4.5, 9.0],
                point_loads=[
                    point_load(1.0 + 1.5 * i, f"J1.0-{i}", 1) for i in range(5)
                ],
            ),
            supported_by=("C1", "C2", "C3"),
        )
        .add_member(make_column_pm("C1", point_loads=[point_load(0.0, "FB1.0", 0)]))
        .add_member(make_column_pm("C2", point_loads=[point_load(0.0, "FB1.0", 1)]))
        .add_member(make_column_pm("C3", point_loads=[point_load(0.0, "FB1.0", 2)]))
    ),
}


@pytest.mark.parametrize("joist_loads", ["distributed", "point"])
@pytest.mark.parametrize("name", GRAPHS)
def test_backends_give_the_same_reactions(name, joist_loads):
    pynite = run(GRAPHS[name](), "pynite", joist_loads=joist_loads)
    pycba = run(GRAPHS[name](), "pycba", joist_loads=joist_loads)
    assert pynite.errors == pycba.errors == {}
    assert_same_reactions(pynite.reactions, pycba.reactions)


def test_pycba_conserves_trapezoidal_load_across_three_sub_members():
    """
    PyniteFEA (3.2.1) applies a trapezoidal load that spans three or more
    sub-members incorrectly to the middle ones, so its reactions do not
    balance the load. pycba does not have this problem.
    """
    pm = make_beam_pm(
        "FB1.0", 10.0, [2.0, 8.0], dist_loads=[occupancy_load(0, 10.0, "res", 1.5, 3.0)]
    )
    lt = run(DictGraph().add_member(pm), "pycba")
    applied, bottom = applied_occupancy_totals(lt), bottom_reaction_totals(lt)
    for case in applied:
        assert math.isclose(applied[case], bottom[case], rel_tol=1e-9), case


def test_pycba_models_are_serialized():
    lt = run(GRAPHS["simple_beam"](), "pycba")
    model_data = lt.models["FB1.0"]
    assert model_data["backend"] == "pycba"
    assert model_data["name"] == "FB1.0"
    model = PycbaFrame.from_papermodel(model_data=model_data)
    assert isinstance(model, pycba_tools.CBAModel)
    assert set(model.load_combos) == {"D", "L"}


def test_default_backend_is_pynite():
    lt = run(GRAPHS["simple_beam"](), "pynite")
    assert LoadTracer.model_fields["frame_backend"].default == "pynite"
    assert "backend" not in lt.models["FB1.0"]


def test_frame_model_class():
    assert frame_model_class("pynite") is PyniteFrame
    assert frame_model_class("pycba") is PycbaFrame
    with pytest.raises(ValueError):
        frame_model_class("sap2000")


def test_unknown_backend_is_rejected():
    with pytest.raises(ValidationError):
        LoadTracer(
            geometry_graph=DictGraph(), occupancies=OCCUPANCIES, frame_backend="sap2000"
        )


def test_missing_pycba_tools_fails_on_construction(monkeypatch):
    monkeypatch.setitem(sys.modules, "pycba_tools", None)  # import raises ImportError
    with pytest.raises(ImportError, match=r"loadtracer\[pycba\]"):
        LoadTracer(
            geometry_graph=DictGraph(), occupancies=OCCUPANCIES, frame_backend="pycba"
        )


def expanded_beam_pm(
    dist_dir: str = "Fy", point_dir: str = "Fy", magnitude: float = -1.0
) -> dict:
    pm = make_beam_pm("FB1.0", 4.0, [0.0, 4.0])
    pm["loads"]["distributed_loads"] = [
        {
            "expanded": [
                {
                    "dir": dist_dir,
                    "case": "D",
                    "start_magnitude": magnitude,
                    "end_magnitude": magnitude,
                    "start_loc": 0.0,
                    "end_loc": 4.0,
                }
            ]
        }
    ]
    pm["loads"]["point_loads"] = [
        {
            "expanded": [
                {"dir": point_dir, "case": "L", "magnitude": magnitude, "location": 1.0}
            ]
        }
    ]
    return pm


def test_pycba_loads_use_pynite_signs():
    frame = PycbaFrame(expanded_beam_pm())
    reactions = frame.get_reactions()
    assert reactions[0]["FY"]["D"] + reactions[1]["FY"]["D"] == pytest.approx(4.0)
    assert reactions[0]["FY"]["L"] == pytest.approx(0.75)
    assert reactions[1]["FY"]["L"] == pytest.approx(0.25)


def test_pycba_moment_loads_match_pynite():
    pm = expanded_beam_pm(point_dir="Mz", magnitude=2.0)
    assert_same_reactions(
        PyniteFrame(pm).get_reactions(), PycbaFrame(pm).get_reactions()
    )


@pytest.mark.parametrize(
    "dist_dir, point_dir", [("Fx", "Fy"), ("Fy", "Fz"), ("Fz", "Fy")]
)
def test_pycba_rejects_loads_it_cannot_analyse(dist_dir, point_dir):
    with pytest.raises(AnalysisError, match="FB1.0.*pycba"):
        build_pycba_frame_model(expanded_beam_pm(dist_dir, point_dir))


def test_pycba_skips_zero_loads_in_other_directions():
    pm = expanded_beam_pm(dist_dir="Fx", magnitude=0.0)
    model = build_pycba_frame_model(pm)
    assert model.load_cases.get("D", []) == []
    assert "D" in model.load_combos


def test_member_with_no_loads():
    pm = make_beam_pm("FB1.0", 4.0, [0.0, 4.0])
    assert (
        PycbaFrame(pm).get_reactions()
        == PyniteFrame(pm).get_reactions()
        == {0: {}, 1: {}}
    )
