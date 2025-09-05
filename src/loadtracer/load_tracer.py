from __future__ import annotations
import concurrent.futures
from typing import Optional, Union
from dataclasses import dataclass

import networkx as nx
import pathlib
from papermodels.datatypes.geometry_graph import GeometryGraph
from rich.progress import Progress
from . import beams
from . import member_model as mm
from .analysis_models.column_model import PointColumn
from .analysis_models.frame_model import PyniteFrame
from .analysis_models.wall_model import LoadbearingWall


@dataclass
class LoadTracer:
    geometry_graph: "GeometryGraph"
    occupancies: Optional[dict] = None
    elevations: Optional[dict] = None
    occupancies_path: Optional[str | pathlib.Path] = None
    elevations_path: Optional[str | pathlib.Path] = None
    debug_mode: bool = False
    rundown_upon_init: bool = True
    show_progress=True
    loaded_elements: Optional[list] = None
    reactions: Optional[dict] = None
    forces: Optional[dict] = None
    deflections: Optional[dict] = None
    member_load_models: Optional[dict] = None
    member_graph_models: Optional[dict] = None

    def __post_init__(self):
        self.loaded_elements = self.geometry_graph.create_loaded_elements()
        if self.rundown_upon_init:
            self.generate_reactions()
            # self.generate_loads()
            # self.generate_deflections()

    def generate_reactions(self):
        self.execute_analyses(
            calculate_reactions=True, 
            use_existing_reactions=False
        )


    def execute_analyses(
        self,
        calculate_reactions: bool = False,
        use_existing_reactions: bool = False,
        force_arrays: bool = False,
        deflection_arrays: bool = False,
        n_points=200,
        progress: bool = False,
        debug: bool = False,
    ) -> None:
        """

        """
        if calculate_reactions:
            if not use_existing_reactions or self.reactions is None:
                self.reactions = {}

        if force_arrays:
            self.forces = {}
        if deflection_arrays:
            self.deflections = {}

        sorted_nodes = nx.topological_sort(self.geometry_graph)
        self.member_graph_models = {}
        self.member_load_models = {}
        for member_name in sorted_nodes:
            papermodel = self.loaded_elements[member_name].model()
            if papermodel['orientation'] == 'vertical' and papermodel['reaction_type']:
                member_model = LoadbearingWall(papermodel)
            elif papermodel['orientation'] == 'vertical':
                member_model = PointColumn(papermodel)
            elif papermodel['orientation'] == 'horizontal':
                member_model = PyniteFrame(papermodel)

            reactions = member_model.get_reactions()
            self.reactions.update({member_name: member_model.get_reactions()})
