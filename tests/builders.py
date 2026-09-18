"""
Builders for papermodel dicts shaped like papermodels.LoadedElement.model()
output (papermodels 0.21) and a GeometryGraph that serves them, so that
LoadTracer can be run end to end on hand-written models.
"""

from copy import deepcopy
from types import SimpleNamespace
from typing import Optional

from papermodels.datatypes.geometry_graph import GeometryGraph


def _pm(tag, length, orientation, reaction_type, supports, point_loads, dist_loads):
    return {
        "element_attributes": {
            "tag": tag,
            "length": length,
            "orientation": orientation,
            "reaction_type": reaction_type,
            "user_defined": {},
        },
        "element_geometry": {"geometry": "", "supports": supports},
        "loads": {
            "point_loads": list(point_loads),
            "distributed_loads": list(dist_loads),
        },
    }


def support(location: float, **kwargs) -> dict:
    return {"location": location, "overlap_length": 0.0, "terminus": None, **kwargs}


def make_beam_pm(
    tag: str,
    length: float,
    supports: list[float | dict],
    point_loads=(),
    dist_loads=(),
    reaction_type: str = "point",
) -> dict:
    supports = [s if isinstance(s, dict) else support(s) for s in supports]
    return _pm(tag, length, "horizontal", reaction_type, supports, point_loads, dist_loads)


def make_wall_pm(tag: str, length: float, point_loads=(), dist_loads=()) -> dict:
    pm = _pm(tag, length, "vertical", "linear", [], point_loads, dist_loads)
    for dist_load in pm["loads"]["distributed_loads"]:
        if dist_load.get("occupancy"):
            # A member with a linear reaction scales occupancy loads by
            # length * applied_area_ratio (see expand_distributed_load)
            dist_load["applied_area_ratio"] = 1 / length
    return pm


def make_column_pm(tag: str, point_loads=(), dist_loads=()) -> dict:
    return _pm(tag, {}, "vertical", "point", [], point_loads, dist_loads)


def point_load(
    location, transfer_source: str, transfer_reaction_index: int = 0, **kwargs
) -> dict:
    return {
        "location": location,
        "magnitude": 0.0,
        "transfer_source": transfer_source,
        "transfer_reaction_index": transfer_reaction_index,
        "direction": "gravity",
        **kwargs,
    }


def transfer_dist_load(
    start_loc,
    end_loc,
    transfer_source: str,
    transfer_reaction_index: int = 0,
    source_extents: tuple = ([], []),
    **kwargs,
) -> dict:
    return {
        "transfer_source": transfer_source,
        "transfer_reaction_index": transfer_reaction_index,
        "transfer_source_start_extent": source_extents[0],
        "transfer_source_end_extent": source_extents[1],
        "occupancy": "",
        "load_components": {},
        "applied_area": 0.0,
        "start_loc": start_loc,
        "start_magnitude": 1.0,
        "end_loc": end_loc,
        "end_magnitude": 1.0,
        "direction": "gravity",
        **kwargs,
    }


def occupancy_load(
    start_loc: float,
    end_loc: float,
    occupancy: str,
    trib_width: float = 1.0,
    end_trib_width: Optional[float] = None,
) -> dict:
    """
    An occupancy load as papermodels gives it on a member with a point reaction
    (a joist or beam with its own trib area): the magnitudes are trib widths
    and the applied area ratio is the share of the load in the trib area.
    With an 'applied_area' of 1 and a ratio of 1 the expanded line load is
    pressure * trib width.
    """
    end_trib_width = trib_width if end_trib_width is None else end_trib_width
    return {
        "transfer_source": "",
        "transfer_reaction_index": "",
        "occupancy": occupancy,
        "load_components": [],
        "applied_area": 1.0,
        "applied_area_ratio": 1.0,
        "start_loc": start_loc,
        "start_magnitude": trib_width,
        "end_loc": end_loc,
        "end_magnitude": end_trib_width,
    }


class DictGraph(GeometryGraph):
    """
    A GeometryGraph whose loaded elements return the given papermodel dicts.

    Add members from the top of the graph down with .add_member(). Joists of
    a joist array can be added with .add_array() so that they are sub-elements
    of their parent, as JoistArrayModel creates them.
    """

    def __init__(self):
        super().__init__()
        self._papermodels = {}

    def add_member(self, pm: dict, supported_by: tuple[str, ...] = ()) -> "DictGraph":
        tag = pm["element_attributes"]["tag"]
        self._papermodels[tag] = pm
        self.add_node(tag, element=SimpleNamespace(tag=tag, subelements=None))
        for other in supported_by:
            self.add_edge(tag, other)
        return self

    def add_array(
        self, parent: str, joists: list[dict], supported_by: tuple[str, ...] = ()
    ) -> "DictGraph":
        subelements = []
        for pm in joists:
            tag = pm["element_attributes"]["tag"]
            self._papermodels[tag] = pm
            subelements.append(SimpleNamespace(tag=tag))
        self.add_node(parent, element=SimpleNamespace(tag=parent, subelements=subelements))
        for other in supported_by:
            self.add_edge(parent, other)
        return self

    def create_loaded_elements(self) -> dict:
        return {
            tag: SimpleNamespace(model=lambda pm=pm: deepcopy(pm))
            for tag, pm in self._papermodels.items()
        }
