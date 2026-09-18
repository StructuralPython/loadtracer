"""
Load conservation checks for a completed LoadTracer rundown: the total load
applied from occupancies must reach the bottom of the graph.
"""

from collections import defaultdict


def resultant(component: dict) -> float:
    """Returns the resultant force of a point or distributed load component."""
    if "magnitude" in component:
        return component["magnitude"]
    return (
        (component["start_magnitude"] + component["end_magnitude"])
        / 2
        * (component["end_loc"] - component["start_loc"])
    )


def applied_occupancy_totals(lt) -> dict[str, float]:
    """
    Returns the total occupancy load (per load case) applied to all members,
    including load moved to a member end because it was off the member.
    """
    acc = defaultdict(float)
    for pm in lt.expanded_pm.values():
        for load in pm["loads"]["distributed_loads"] + pm["loads"]["point_loads"]:
            is_occupancy_load = not load.get("transfer_source")
            if is_occupancy_load:
                for component in load.get("expanded", []):
                    acc[component["case"]] += resultant(component)
    return dict(acc)


def bottom_members(lt) -> list[str]:
    """Returns the tags of analysed members that do not transfer load to any member."""
    graph = lt.geometry_graph
    return [tag for tag in lt.reactions if tag in graph and graph.out_degree(tag) == 0]


def bottom_reaction_totals(lt) -> dict[str, float]:
    """
    Returns the total reaction (per load case) at the bottom of the graph, as
    loads (i.e. with the opposite sign of the support forces).
    """
    acc = defaultdict(float)
    for tag in bottom_members(lt):
        for reactions_by_dir in lt.reactions[tag].values():
            for case, reaction in reactions_by_dir.get("FY", {}).items():
                if isinstance(reaction, list):
                    acc[case] -= sum(resultant(r) for r in reaction)
                else:
                    acc[case] -= reaction
    return dict(acc)
