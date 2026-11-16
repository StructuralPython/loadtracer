"""LoadTracer.to_beamz and member_to_beamz: traced members as beamz9000 beams."""

import pytest

from builders import make_beam_pm
from loadtracer import LoadTracerWarning
from loadtracer.beamz import member_to_beamz
from loadtracer.errors import LoadTracerError, UnstableMemberError


def expanded(pm: dict, dist=(), point=()) -> dict:
    """'pm' with already-expanded load components, as in LoadTracer.expanded_pm."""
    pm["loads"]["distributed_loads"] = [{"expanded": list(dist)}]
    pm["loads"]["point_loads"] = [{"expanded": list(point)}]
    return pm


def dist(case, w1, w2, x1, x2, dir="FY"):
    return {"case": case, "dir": dir, "start_magnitude": w1, "end_magnitude": w2,
            "start_loc": x1, "end_loc": x2}


def point(case, p, x, dir="FY"):
    return {"case": case, "dir": dir, "magnitude": p, "location": x}


def test_supports_and_free_ends_follow_the_analysis_model():
    pm = expanded(make_beam_pm("B1", 10.0, [1.0, 6.0, {"location": 9.0, "fixity": "fixed"}]))
    beam = member_to_beamz(pm)
    assert beam["spans"] == [1.0, 5.0, 3.0, 1.0]
    assert beam["supports"] == ["free", "pin", "roller", "fixed", "free"]


def test_loads_are_resolved_per_case_with_gravity_down():
    pm = expanded(
        make_beam_pm("B1", 6.0, [0.0, 6.0]),
        dist=[dist("D", 2.0, 2.0, 0.0, 6.0), dist("L", 1.0, 3.123456789, 1.0, 4.0)],
        point=[point("L", 10.0, 3.0), point("D", -4.0, 2.0)],
    )
    assert member_to_beamz(pm)["loads"] == [
        {"dist": {"x1": 0.0, "x2": 6.0, "case": "D", "w": 2.0}},
        {"dist": {"x1": 1.0, "x2": 4.0, "case": "L", "mag1": 1.0, "mag2": 3.12346}},
        {"point": {"p": 10.0, "x": 3.0, "case": "L"}},
        {"point": {"p": -4.0, "x": 2.0, "case": "D"}},  # An uplift stays upward.
    ]


def test_horizontal_loads_moments_and_undrawable_components():
    pm = expanded(
        make_beam_pm("B1", 6.0, [0.0, 6.0]),
        dist=[dist("W", 1.0, 1.0, 0.0, 6.0, dir="FX")],
        point=[point("W", -5.0, 2.0, dir="FX"), point("D", 3.0, 4.0, dir="MZ"),
               point("W", 1.0, 1.0, dir="FZ"), point("D", 0.0, 1.0)],
    )
    with pytest.warns(LoadTracerWarning, match="2 load component"):
        loads = member_to_beamz(pm)["loads"]
    assert loads == [
        {"point": {"p": 5.0, "x": 2.0, "angle": -90, "case": "W"}},  # Leftward.
        {"moment": {"m": -3.0, "x": 4.0, "case": "D"}},
    ]


def test_units_and_beam_options():
    pm = expanded(
        make_beam_pm("B1", 12.0, [0.0, 12.0]),
        dist=[dist("D", 0.512345, 0.512345, 0.0, 12.0)],
        point=[point("L", 2.0, 6.0), point("D", 1.0, 3.0, dir="MZ")],
    )
    beam = member_to_beamz(pm, length_unit="ft", force_unit="kip", e="29000 ksi")
    assert beam["spans"] == ["12 ft"]
    assert beam["loads"] == [
        {"dist": {"x1": "0 ft", "x2": "12 ft", "case": "D", "w": "0.5123 kip/ft"}},
        {"point": {"p": "2 kip", "x": "6 ft", "case": "L"}},
        {"moment": {"m": "-1 kip*ft", "x": "3 ft", "case": "D"}},
    ]
    assert beam["e"] == "29000 ksi"
    with pytest.raises(ValueError, match="both"):
        member_to_beamz(pm, length_unit="ft")


def test_vertical_and_unstable_members_are_refused():
    pm = expanded(make_beam_pm("W1", 6.0, [0.0, 6.0]))
    pm["element_attributes"]["orientation"] = "vertical"
    with pytest.raises(ValueError, match="vertical"):
        member_to_beamz(pm)
    with pytest.raises(UnstableMemberError):
        member_to_beamz(expanded(make_beam_pm("B1", 6.0, [3.0])))


def test_to_beamz_needs_a_rundown():
    from loadtracer.load_tracer import LoadTracer

    from types import SimpleNamespace

    not_run = SimpleNamespace(expanded_pm=None, errors=None)
    with pytest.raises(LoadTracerError, match="execute_analyses"):
        LoadTracer.to_beamz(not_run, "B1")
    failed = SimpleNamespace(expanded_pm={}, errors={"B1": "unstable"})
    with pytest.raises(LoadTracerError, match="not analysed: unstable"):
        LoadTracer.to_beamz(failed, "B1")


# --- End to end, against loadtracer's own reactions --------------------------------

def _sketch_rundown():
    from test_integration_papermodels import TEST_DATA, load_graph, run

    if TEST_DATA is None:
        pytest.skip("needs the papermodels test drawings")
    return run(load_graph("sketch_to_scale.pdf"))


@pytest.mark.parametrize("units", [None, ("ft", "kip")])
def test_beamz9000_reproduces_loadtracer_reactions(units):
    bz = pytest.importorskip("beamz9000")
    analysis = pytest.importorskip("beamz9000.analysis")
    pytest.importorskip("pycba_tools")
    from loadtracer.analysis_models.frame_model import get_node_locations

    lt = _sketch_rundown()
    to_kip = 1 / 4448.2216 if units else 1.0
    compared = 0
    for tag, pm in lt.expanded_pm.items():
        if pm["element_attributes"]["orientation"] != "horizontal":
            continue
        kwargs = dict(length_unit=units[0], force_unit=units[1]) if units else {}
        scheme = {tag: lt.to_beamz(tag, **kwargs)}
        if units:
            scheme["_environment"] = "structural"
        beam = bz.parse_scheme(scheme)[tag]
        if not beam.loads:
            continue
        result = analysis.analyze(beam, [])
        nodes = [location for location, _ in get_node_locations(pm)]
        for idx, s in enumerate(pm["element_geometry"]["supports"]):
            if s.get("coincident"):
                continue
            node = min(range(len(nodes)), key=lambda i: abs(nodes[i] - s["location"]))
            fy = lt.reactions[tag][idx]["FY"]
            scale = max(1.0, *(abs(v) for v in fy.values()))
            for case, value in fy.items():
                got = next((r.fy for r in result.reactions if r.node == node and r.case == case), 0.0)
                # loadtracer's reactions are negative for an upward reaction.
                assert got * to_kip == pytest.approx(-value, abs=1e-3 * scale)
                compared += 1
    assert compared > 100


def test_horizontal_reactions_match_the_frame_model():
    """An in-plane point load gives beamz9000 the horizontal reaction loadtracer finds."""
    bz = pytest.importorskip("beamz9000")
    analysis = pytest.importorskip("beamz9000.analysis")
    pytest.importorskip("pycba_tools")
    from loadtracer.analysis_models.frame_model import PyniteFrame

    pm = expanded(
        make_beam_pm("B1", 6.0, [0.0, 6.0]),
        point=[point("W", 5.0, 2.0, dir="FX"), point("W", 3.0, 4.0)],
    )
    reactions = PyniteFrame(pm, None).get_reactions()
    result = analysis.analyze(bz.parse_scheme({"B1": member_to_beamz(pm)})["B1"], [])
    pin = next(r for r in result.reactions if r.node == 0 and r.case == "W")
    # Under the top-to-bottom mirror, FX is unchanged and FY is reversed.
    assert pin.fx == pytest.approx(reactions[0]["FX"]["W"])
    assert pin.fy == pytest.approx(-reactions[0]["FY"]["W"])
