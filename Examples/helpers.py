"""
Helpers for the loadtracer examples: tables of loads and reactions from a
completed LoadTracer rundown.
"""

import contextlib
import io
from collections import defaultdict

import pandas as pd


def quietly(func, *args, **kwargs):
    """
    Returns func(*args, **kwargs) with anything printed to stdout discarded
    (loadbearing_wall prints while it analyses walls).
    """
    with contextlib.redirect_stdout(io.StringIO()):
        return func(*args, **kwargs)


def occupancies_in(graph) -> list[str]:
    """Returns the occupancies used by the loading areas in 'graph'."""
    return sorted({lg.occupancy for lg in graph.loading_geometries if lg.occupancy})


def resultant(component: dict) -> float:
    """Returns the resultant of a point or distributed load component."""
    if "magnitude" in component:
        return component["magnitude"]
    return (
        (component["start_magnitude"] + component["end_magnitude"])
        / 2
        * (component["end_loc"] - component["start_loc"])
    )


def load_table(lt, tag: str) -> pd.DataFrame:
    """Returns the expanded loads on member 'tag' (one row per load case component)."""
    rows = []
    loads = lt.expanded_pm[tag]["loads"]
    for kind, key in (("point", "point_loads"), ("distributed", "distributed_loads")):
        for load in loads[key]:
            source = load.get("transfer_source") or f"occupancy: {load.get('occupancy')}"
            for c in load.get("expanded", []):
                rows.append(
                    {
                        "kind": kind,
                        "source": source,
                        "case": c["case"],
                        "start": c.get("start_loc", c.get("location")),
                        "end": c.get("end_loc", c.get("location")),
                        "w_start / P": c.get("start_magnitude", c.get("magnitude")),
                        "w_end": c.get("end_magnitude"),
                        "total": resultant(c),
                        "profile": c.get("profile", ""),
                    }
                )
    return pd.DataFrame(rows)


def reaction_table(lt, tags=None) -> pd.DataFrame:
    """
    Returns the gravity reactions (as loads on the support, i.e. positive
    downwards) of the members 'tags' (all members when None), one row per
    member and support, one column per load case. Wall reactions are totals.
    """
    rows = []
    for tag in tags if tags is not None else lt.reactions:
        for support, by_dir in lt.reactions[tag].items():
            row = {"member": tag, "support": support}
            for case, reaction in by_dir.get("FY", {}).items():
                total = sum(map(resultant, reaction)) if isinstance(reaction, list) else reaction
                row[case] = -total
            rows.append(row)
    return pd.DataFrame(rows).fillna(0.0).set_index(["member", "support"])


def bottom_members(lt) -> list[str]:
    """Returns the members that do not transfer load to another member."""
    graph = lt.geometry_graph
    return [tag for tag in lt.reactions if tag in graph and graph.out_degree(tag) == 0]


def load_check(lt) -> pd.DataFrame:
    """
    Returns the total occupancy load applied to the building and the total
    reaction at the bottom members, per load case. They are equal when all of
    the load reaches the bottom.
    """
    applied = defaultdict(float)
    for pm in lt.expanded_pm.values():
        for load in pm["loads"]["distributed_loads"] + pm["loads"]["point_loads"]:
            if not load.get("transfer_source"):
                for c in load.get("expanded", []):
                    applied[c["case"]] += resultant(c)
    bottom = reaction_table(lt, bottom_members(lt)).sum()
    return pd.DataFrame({"applied": pd.Series(applied), "at the bottom": bottom})


def compare_modes(lt_point, lt_distributed, tags) -> pd.DataFrame:
    """
    Returns the reactions of 'tags' with joist loads as point loads and as
    distributed loads, side by side.
    """
    point = reaction_table(lt_point, tags)
    distributed = reaction_table(lt_distributed, tags)
    table = pd.concat({"point": point, "distributed": distributed}, axis=1)
    for case in point.columns:
        table[("difference", case)] = distributed[case] - point[case]
    return table
