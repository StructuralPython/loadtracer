"""
End to end load rundowns of the papermodels test fixtures.

Requires a papermodels (>= 0.21) checkout next to this repository
(../papermodels); the tests are skipped otherwise.
"""

import contextlib
from collections import defaultdict
import io
import math
import pathlib
import warnings
from decimal import Decimal

import pytest

import papermodels
from conservation import applied_occupancy_totals, bottom_reaction_totals, resultant
from loadtracer import LoadTracerWarning
from loadtracer.load_tracer import LoadTracer

TEST_DATA = pathlib.Path(__file__).parents[2] / "papermodels" / "tests" / "test_data"
QUARTER_INCH_SCALE = Decimal(1) / Decimal(72) * Decimal(4)
PAPERMODELS_VERSION = tuple(int(p) for p in papermodels.__version__.split(".")[:2])

pytestmark = pytest.mark.skipif(
    not TEST_DATA.exists() or PAPERMODELS_VERSION < (0, 21),
    reason="needs a papermodels >= 0.21 checkout at ../papermodels",
)

FIXTURES = sorted(p.name for p in TEST_DATA.glob("*.pdf")) if TEST_DATA.exists() else []
# Walls in these fixtures are linked to members that overlap under them, so the
# load on the overlap is applied to both (reported in LoadTracer.issues)
OVERLAPPING_SUPPORTS = {"many_correspondents.pdf"}
PAPERMODELS_FAILURES = {"three-pages-on-one.pdf": "papermodels raises KeyError: None"}


def load_graph(name: str):
    from papermodels.datatypes.geometry_graph import GeometryGraph
    from papermodels.datatypes.joist_models import JoistArrayModel

    with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        graph = GeometryGraph.from_pdf_file(TEST_DATA / name, scale=QUARTER_INCH_SCALE)
        graph.assign_collector_behaviour(JoistArrayModel, spacing=1.0)
    return graph


@pytest.fixture(scope="module", params=FIXTURES)
def rundown(request) -> tuple[str, LoadTracer]:
    name = request.param
    if name in PAPERMODELS_FAILURES:
        pytest.xfail(PAPERMODELS_FAILURES[name])
    return name, run(load_graph(name))


def run(graph, **kwargs) -> LoadTracer:
    occupancies = {
        lg.occupancy: {"D": 1.0, "L": 2.5}
        for lg in graph.loading_geometries
        if getattr(lg, "occupancy", None)
    } or {"none": {"D": 1.0}}
    lt = LoadTracer(geometry_graph=graph, occupancies=occupancies, **kwargs)
    with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
        warnings.simplefilter("ignore", LoadTracerWarning)
        lt.execute_analyses()
    return lt


def test_every_member_is_analysed(rundown):
    _, lt = rundown
    assert lt.errors == {}
    assert lt.ignored_reactions == {}
    assert set(lt.reactions) == set(lt.expanded_pm)


def test_load_is_conserved(rundown):
    name, lt = rundown
    applied = applied_occupancy_totals(lt)
    bottom = bottom_reaction_totals(lt)
    if name in OVERLAPPING_SUPPORTS:
        assert any("both support" in issue for issues in lt.issues.values() for issue in issues)
        for case in applied:
            assert bottom[case] >= applied[case]
        return
    assert applied.keys() == bottom.keys()
    for case in applied:
        assert math.isclose(applied[case], bottom[case], rel_tol=1e-6), case


def test_converted_joist_loads_replace_the_joist_point_loads_exactly(rundown):
    _, lt = rundown
    for pm in lt.expanded_pm.values():
        replaced, replacing = defaultdict(float), defaultdict(float)
        for load in pm["loads"].get("converted_point_loads", []):
            parent = load["transfer_source"].rpartition("-")[0]
            for component in load["expanded"]:
                replaced[(parent, component["case"])] += component["magnitude"]
        arrays = {parent for parent, _ in replaced}
        for load in pm["loads"]["distributed_loads"] + pm["loads"]["point_loads"]:
            if load.get("transfer_source") in arrays:
                for component in load.get("expanded", []):
                    replacing[(load["transfer_source"], component["case"])] += resultant(component)
        assert replacing.keys() == replaced.keys()
        for key, total in replaced.items():
            assert math.isclose(replacing[key], total, rel_tol=1e-9, abs_tol=1e-12), key


def test_point_and_distributed_joist_loads_carry_the_same_total_load(rundown):
    name, distributed = rundown
    point = run(distributed.geometry_graph, joist_loads="point")
    for case, total in bottom_reaction_totals(point).items():
        assert math.isclose(bottom_reaction_totals(distributed)[case], total, rel_tol=1e-6)
