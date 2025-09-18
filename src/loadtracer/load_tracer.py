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
from .analysis_models.wall_model import LoadbearingWall
from .expand_occupancies import expand_occupancy_loads
from .expand_reactions import expand_reaction_loads
from .pm_processing import get_element_height

from pydantic import BaseModel, Field


class LoadTracer(BaseModel, arbitrary_types_allowed=True):
    geometry_graph: "GeometryGraph"
    occupancies: Optional[dict] = None
    elevations: Optional[dict] = None
    occupancy_distributed_load_direction_mapping: dict = Field(
        default={"gravity": ["Fy"], "inplane": ["Fx"], "out_of_plane": ["Fz"]}
    )
    reaction_distributed_load_direction_mapping: dict = Field(
        default={"gravity": ["FY"], "inplane": ["FX"], "out_of_plane": ["FZ"]}
    )
    reaction_point_load_direction_mapping: dict = Field(
        default={"gravity": ["FY"], "inplane": ["FX"], "out_of_plane": ["FZ"]}
    )
    show_progress: bool = True
    _models: Optional[dict] = None
    _reactions: Optional[dict] = None
    _expanded_pm: Optional[dict] = None

    def generate_rundown(self, artifacts_dir: Optional[str | pathlib.Path] = None):
        self.execute_analyses(artifacts_dir=artifacts_dir)

    def execute_analyses(
        self,
        artifacts_dir: Optional[str | pathlib.Path] = None,
        progress: bool = False,
        debug: bool = False,
    ) -> None:
        """
        Executes the analyses to calculate reactions so that the
        entire geometry graph can be expressed as completely resolved
        analysis models.
        """
        self._models = {}
        self._reactions = {}
        self._expanded_pm = {}
        sorted_nodes = nx.topological_sort(self.geometry_graph)
        loaded_elements = self.geometry_graph.create_loaded_elements()
        # Include subelements in the sorted nodes
        expanded_sorted_nodes = []
        for node_name in sorted_nodes:
            element = self.geometry_graph.nodes[node_name]['element']
            if element.subelements is not None:
                inner_acc = [subelem.tag for subelem in element.subelements]
                expanded_sorted_nodes.extend(inner_acc)
            else:
                expanded_sorted_nodes.append(element.tag)
        node_iterator = expanded_sorted_nodes
        if progress:
            node_iterator = track(list(sorted_nodes))
        for member_name in node_iterator:
            papermodel = loaded_elements[member_name].model()
            tag = papermodel["element_attributes"]["tag"]
            if tag == "WT3.0":
                print(papermodel)
            papermodel = expand_occupancy_loads(
                papermodel,
                self.occupancies,
                self.occupancy_distributed_load_direction_mapping,
            )
            papermodel = expand_reaction_loads(
                papermodel,
                self._reactions,
                self.reaction_distributed_load_direction_mapping,
                self.reaction_point_load_direction_mapping,
            )
            self._expanded_pm[member_name] = papermodel
            orientation = papermodel["element_attributes"]["orientation"]
            # reaction_type = papermodel['element_attributes']['reaction_type']
            tag = papermodel["element_attributes"]["tag"]
            if orientation == "vertical":
                element_height = get_element_height(papermodel, self.elevations)
                papermodel["element_attributes"]["height"] = element_height
                papermodel["element_geometry"]["height"] = element_height

            if orientation == "vertical" and tag[0] == "W":
                # print(f"{tag=}")
                # if orientation == 'vertical' and reaction_type == "linear":
                member_model = LoadbearingWall(papermodel)
                # if tag == "WT3.0":
                #     print(f"{member_model=}")
            elif orientation == "vertical":
                # elif orientation == 'vertical' and reaction_type == "point":
                member_model = PointColumn(papermodel)
            elif orientation == "horizontal":
                member_model = PyniteFrame(papermodel)
            reactions = member_model.get_reactions()

            model_dict = member_model.dump_model()
            self._models.update({member_name: model_dict})
            self._reactions.update({member_name: reactions})

        if artifacts_dir:
            artifacts_path = pathlib.Path(artifacts_dir)
            jsonchain.dump_json(self._models, artifacts_path / "models.json")
            jsonchain.dump_json(
                self._reactions, artifacts_path / "reaction_forces.json"
            )
