from dataclasses import dataclass
import pathlib
from typing import Optional, Any, Union
import io

from .analysis_model import AbstractAnalysisModel
from loadbearing_wall import LinearWallModel
import math


@dataclass
class LoadbearingWall(AbstractAnalysisModel):
    pm: dict
    model: Optional[LinearWallModel]
    vertical_spread_angle: float = 0.0

    def __post_init__(self):
        self.model = build_linear_wall_model(self.pm, self.vertical_spread_angle)

    def get_reactions(self):
        reactions = self.model.get_reactions()
        return {0: reactions}

    def dump_model(
        self, filepath: Optional[str | pathlib.Path] = None, indent: int = 2
    ) -> Optional[dict]:
        """
        Dumps the model to 'filepath'. If 'filepath' is None, then a Python
        dict is returned.
        """
        if filepath is not None:
            return self.model.to_json(self.model, filepath, indent=indent)
        else:
            return self.model.dump_dict()

    def load_model(
        self,
        filepath: Optional[str | pathlib.Path] = None,
        model_data: Optional[dict] = None,
    ) -> dict:
        """
        Loads the model from either 'filepath' or 'model_data' and returns a dict
        """
        if filepath is not None:
            return self.model.from_json(filepath)
        else:
            return self.model.from_dict(model_data)

    @classmethod
    def from_papermodel(
        self,
        model_data: Optional[dict] = None,
        filepath: Optional[str | pathlib.Path] = None,
    ) -> dict:
        """
        Loads the model from either 'fp' or 'model_data' and returns a dict
        """
        if filepath is not None:
            return LinearWallModel.from_json(filepath)
        else:
            return LinearWallModel.from_dict(model_data)


def build_linear_wall_model(pm: dict, spread_angle: float) -> LinearWallModel:
    """
    Returns a LinearWallModel based on the data within 'pm'
    """
    wall_model = LinearWallModel(
        height=pm["element_attributes"]["height"],
        length=pm["element_attributes"]["length"],
        vertical_spread_angle=spread_angle,
        gravity_dir="Fy",
        inplane_dir="Fx",
        out_of_plane_dir="Fz",
        magnitude_start_key="start_magnitude",
        magnitude_end_key="end_magnitude",
        location_start_key="start_loc",
        location_end_key="end_loc",
    )

    length = pm["element_attributes"]["length"]
    for dist_load in pm["loads"]["distributed_loads"]:
        for dt in dist_load["expanded"]:
            end_loc = dt["end_loc"]
            if length < end_loc:
                if math.isclose(length, end_loc, rel_tol=1e-3):
                    end_loc = length
                else:
                    raise ValueError(
                        f"The end location of the load is beyond the length of the wall:\n"
                        f"Wall length: {length}\n"
                        f"Distributed load: {dt}"
                    )
            else:
                end_loc = dt["end_loc"]
            wall_model.add_dist_load(
                magnitude_start=dt["start_magnitude"],
                magnitude_end=dt["end_magnitude"],
                location_start=dt["start_loc"],
                location_end=end_loc,
                case=dt["case"],
                dir="Fy",
            )
    return wall_model


def convert_point_arrays_into_dist_loads(
    point_loads: list[dict],
) -> list[dict]:
    """
    Converts a list of point loads from the papermodel, turning them
    into a series of distributed loads spaced according to the joist
    interval.

    This function only looks at point loads as part of point arrays
    assigned to the papermodel. Any isolated point loads applied to
    the wall are unconverted.
    """
    point_loads_by_parent = filter_point_arrays(point_loads)
    intervals = get_point_intervals_by_parent(point_loads_by_parent)
    dist_loads = []
    for parent, intervals in intervals.items():
        num_loads = len(point_loads_by_parent[parent])
        for idx, point_load in enumerate(point_loads_by_parent[parent]):
            if idx == num_loads - 1:
                interval = 0
            else:
                interval = intervals[idx]
            if idx == 0:
                start_loc = point_load["location"]
                end_loc = start_loc + interval / 2
            # elif idx == 1:
            #     start_loc = prev_end_loc
            #     end_loc = prev_interval / 2 + interval / 2
            elif idx == num_loads - 1:
                start_loc = prev_end_loc
                end_loc = prev_end_loc + prev_interval / 2 + interval / 2
            else:
                start_loc = prev_end_loc
                end_loc = prev_end_loc + prev_interval / 2 + interval / 2

            prev_end_loc = end_loc
            start_loc = round(start_loc, 3)
            end_loc = round(end_loc, 3)
            distance = end_loc - start_loc
            prev_interval = interval

            magnitude_factor = 1 / distance

            expanded_dists = []
            point_load.setdefault("expanded", [])
            for expanded_point in point_load["expanded"]:
                expanded_dist = {
                    "start_magnitude": magnitude_factor * expanded_point["magnitude"],
                    "end_magnitude": magnitude_factor * expanded_point["magnitude"],
                    "start_loc": start_loc,
                    "end_loc": end_loc,
                    "case": expanded_point["case"],
                    "dir": expanded_point["dir"],
                }
                expanded_dists.append(expanded_dist)

            dist_load = {
                "transfer_source": point_load["transfer_source"],
                "transfer_source_start_extent": [],
                "transfer_source_end_extent": [],
                "occupancy": "",
                "load_components": {},
                "applied_area": 0.0,
                "start_loc": start_loc,
                "start_magnitude": magnitude_factor,
                "end_loc": end_loc,
                "end_magnitude": magnitude_factor,
                "direction": point_load["direction"],
                "expanded": expanded_dists,
            }

            dist_loads.append(dist_load)
    return dist_loads


def filter_point_arrays(point_loads: list[dict]) -> dict[str, list[dict]]:
    """
    Returns a dictionary of point loads keyed by transfer source parent
    with the values sorted by location.
    """
    point_loads_by_parent = {}
    for point_load in point_loads:
        transfer_source = point_load["transfer_source"]
        if not "-" in transfer_source:
            continue
        parent = point_load["transfer_source"].split("-")[0]
        point_loads_by_parent.setdefault(parent, [])
        point_loads_by_parent[parent].append(point_load)

    for parent, point_loads in point_loads_by_parent.items():
        point_loads_by_parent[parent] = sorted(point_loads, key=lambda x: x["location"])
    return point_loads_by_parent


def get_point_intervals_by_parent(
    point_loads_by_parent: dict[str, list[dict]],
) -> dict[str, list[float]]:
    """
    Returns a dictionary with keys representing the
    transfer source parent and the values representing
    the interval size between each point load in the
    array.
    """
    intervals = {}
    for parent, point_loads in point_loads_by_parent.items():
        intervals.setdefault(parent, [])
        for idx, point_load in enumerate(point_loads):
            loc = point_load["location"]
            if idx == 0:
                prev_loc = loc
                continue
            interval = abs(loc - prev_loc)
            intervals[parent].append(interval)
            prev_loc = loc
    return intervals


def filter_non_point_arrays(point_loads: list[dict]) -> dict[str, list[dict]]:
    """
    REturns a dict of non-array point laods
    """
    nons = []
    for point_load in point_loads:
        transfer_source = point_load["transfer_source"]
        if not "-" in transfer_source:
            nons.append(point_load)
    return nons

    # intervals = {}
    # prev_loc = None
    # prev_parent = None
    # for point_load in point_loads:
    #     transfer_source = point_load['transfer_source']
    #     if not "-" in transfer_source:
    #         continue
    #     if parent == prev_parent:
    #     parent = point_load['transfer_source'].split("-")[0]

    #     loc = point_load['location']
    #     intervals.setdefault(parent, [])
    #     interval = abs(loc - prev_loc)
    #     intervals[parent].append(point_load)

    #     prev_parent = parent
