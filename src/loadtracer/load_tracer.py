from __future__ import annotations
import concurrent.futures
from typing import Optional, Union
from dataclasses import dataclass, field

import networkx as nx
import pathlib
from papermodels.datatypes.geometry_graph import GeometryGraph
from rich.progress import Progress, track
from rich import print
import jsonchain
from .analysis_models.column_model import PointColumn
from .analysis_models.frame_model import PyniteFrame
from .analysis_models.wall_model import (
    LoadbearingWall,
    convert_point_arrays_into_dist_loads,
    filter_non_point_arrays,
)
from .expand_occupancies import expand_occupancy_loads
from .expand_reactions import expand_reaction_loads
from .pm_processing import get_element_height

from pydantic import BaseModel, Field

class ReactionNotFoundError(Exception):
    pass

class LoadTracer(BaseModel, arbitrary_types_allowed=True):
    geometry_graph: "GeometryGraph"
    occupancies: dict
    elevations: dict
    occupancy_distributed_load_direction_mapping: dict = Field(
        default={"gravity": ["Fy"], "inplane": ["Fx"], "out_of_plane": ["Fz"]}
    )
    reaction_distributed_load_direction_mapping: dict = Field(
        default={"gravity": ["FY"], "inplane": ["FX"], "out_of_plane": ["FZ"]}
    )
    reaction_point_load_direction_mapping: dict = Field(
        default={"gravity": ["FY"], "inplane": ["FX"], "out_of_plane": ["FZ"]}
    )
    missing_reactions: str = "raise"
    show_progress: bool = True
    models: Optional[dict] = None
    reactions: Optional[dict] = None
    ignored_reactions: Optional[dict] = None
    expanded_pm: Optional[dict] = None
    load_cases_used: Optional[list[str]] = None

    def model_post_init(self, cls):
        loads_found = []
        for loads in self.occupancies.values():
            for load in loads.keys():
                loads_found.append(load)
        self.load_cases_used = sorted(set(loads_found))

    def null_point_load(self) -> dict:
        """
        Returns a null point load using one of the load cases in
        self.load_cases_used.
        """
        return {
            "magnitude": 0.0,
            "location": 0.0,
            "case": self.load_cases_used[0],
            "dir": self.reaction_point_load_direction_mapping['gravity'][0],
        }
    
    def null_dist_load(self, member_length: float) -> dict:
        """
        Returns a null dist load using one of the load cases in self.load_cases_used
        """
        return {
                "start_magnitude": 0.0,
                "end_magnitude": 0.0,
                "start_loc": 0.0,
                "end_loc": member_length,
                "case": self.load_cases_used[0],
                "dir": self.reaction_distributed_load_direction_mapping['gravity'][0],
        }

    def generate_rundown(self, 
            artifacts_dir: Optional[str | pathlib.Path] = None, 
            progress: bool = False,
            linear_wall_spread_angle: float = 0,
            linear_wall_minimum_point_spread: float = 1
        ):
        self.execute_analyses(
            artifacts_dir=artifacts_dir, 
            progress=progress,
            linear_wall_spread_angle=linear_wall_spread_angle,
            linear_wall_minimum_point_spread=linear_wall_minimum_point_spread
        )


    def execute_analyses(
        self,
        artifacts_dir: Optional[str | pathlib.Path] = None,
        progress: bool = False,
        debug: bool = False,
        linear_wall_spread_angle: float = 0,
        linear_wall_minimum_point_spread: float = 1
    ) -> None:
        """
        Executes the analyses to calculate reactions so that the
        entire geometry graph can be expressed as completely resolved
        analysis models.
        """
        self.models = {}
        self.reactions = {}
        self.expanded_pm = {}
        sorted_nodes = nx.topological_sort(self.geometry_graph)
        loaded_elements = self.geometry_graph.create_loaded_elements()
        # Include subelements in the sorted nodes
        expanded_sorted_nodes = []
        if self.missing_reactions == "ignore":
            self.ignored_reactions = {}
        for node_name in sorted_nodes:
            element = self.geometry_graph.nodes[node_name]["element"]
            if element.subelements is not None:
                inner_acc = [subelem.tag for subelem in element.subelements]
                expanded_sorted_nodes.extend(inner_acc)
            else:
                expanded_sorted_nodes.append(element.tag)
        node_iterator = expanded_sorted_nodes
        if progress:
            node_iterator = track(list(expanded_sorted_nodes))
        for member_name in node_iterator:
            papermodel = loaded_elements[member_name].model()
            element_attributes = papermodel["element_attributes"]
            tag = element_attributes["tag"]
            length = element_attributes['length']
            expanded_papermodel = expand_occupancy_loads(
                papermodel,
                self.occupancies,
                self.occupancy_distributed_load_direction_mapping,
                reaction_type=element_attributes["reaction_type"],
                null_point_load=self.null_point_load(),
                null_dist_load=self.null_dist_load(member_length=length)
            )
            expanded_papermodel, ignored_reactions = expand_reaction_loads(
                expanded_papermodel,
                self.reactions,
                self.reaction_distributed_load_direction_mapping,
                self.reaction_point_load_direction_mapping,
                null_point_load=self.null_point_load(),
                null_dist_load=self.null_dist_load(member_length=length),
                missing_reactions=self.missing_reactions,
            )
            if self.ignored_reactions is not None:
                self.ignored_reactions.update(ignored_reactions)
            self.expanded_pm[member_name] = expanded_papermodel
            orientation = expanded_papermodel["element_attributes"]["orientation"]
            # reaction_type = papermodel['element_attributes']['reaction_type']
            tag = expanded_papermodel["element_attributes"]["tag"]
            if orientation == "vertical":
                element_height = get_element_height(
                    expanded_papermodel, self.elevations
                )
                expanded_papermodel["element_attributes"]["height"] = element_height
                expanded_papermodel["element_geometry"]["height"] = element_height

            if (
                orientation == "vertical"
                and element_attributes["reaction_type"] == "linear"
            ):
                # TODO: Why did I do this? Why is this necessary?
                # distributed_loads = convert_point_arrays_into_dist_loads(
                #     expanded_papermodel["loads"]["point_loads"]
                # )
                # non_arrays = filter_non_point_arrays(
                #     expanded_papermodel["loads"]["point_loads"]
                # )

                # expanded_papermodel["loads"]["point_loads"] = non_arrays
                # expanded_papermodel["loads"]["distributed_loads"].extend(
                #     distributed_loads
                # )
                

                member_model = LoadbearingWall(
                    expanded_papermodel,
                    vertical_spread_angle=linear_wall_spread_angle,
                    minimum_point_spread=linear_wall_minimum_point_spread
                )
                member_model.model.spread_loads()
            elif (
                orientation == "vertical"
                and element_attributes["reaction_type"] == "point"
            ):
                member_model = PointColumn(expanded_papermodel)
            elif orientation == "horizontal":
                member_model = PyniteFrame(expanded_papermodel)

            model_dict = member_model.dump_model()
            self.models.update({member_name: model_dict})
            try:
                reactions = member_model.get_reactions()
            except:
                if self.missing_reactions == 'raise':
                    raise ReactionNotFoundError(f'Error calculating reaction for: {member_name}')
                else:
                    reactions = {}
            self.reactions.update({member_name: reactions})

        if artifacts_dir:
            artifacts_path = pathlib.Path(artifacts_dir)
            jsonchain.dump_json(self.models, artifacts_path / "models.json")
            jsonchain.dump_json(self.reactions, artifacts_path / "reaction_forces.json")
