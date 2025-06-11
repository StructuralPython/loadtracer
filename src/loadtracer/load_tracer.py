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
from . analysis_models import LinearWallModel, ColumnModel, BeamModel


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
            member_graph_model = self.loaded_elements[member_name].model()
            self.member_graph_models.update({member_name: member_graph_model})
            member_load_model = mm.get_structured_toml_data(
                member_graph_model, self.occupancies, self.reactions, self.elevations
            )

            beam_models = []
            if member_load_model['orientation'] == 'vertical' and member_load_model['reaction_type']:
                member_model = LinearWallModel(member_load_model)
            elif member_load_model['orientation'] == 'vertical':
                member_model = ColumnModel(member_load_model)
            elif member_load_model['orientation'] == 'horizontal':
                member_model = BeamModel(member_load_model)
                beam_models.append(member_model)

            # Have a wrapper for the member model so there is a consistent
            reactions = member_model.get_reactions(reactions_options)
            forces = member_model.get_forces(forces_options)
            deflections = member_model.get_deflections(deflections_options)

            # Need to populate the member toml data with reactions and store it




            #     # determine_out_of_plane_reactions(member_)
            # if member_graph_model['orientation'] == "horizontal":

                # self.member_load_models.update({member_name: member_load_model})
                # # Refactor this out to an "in-plane" analysis model for generating member reactions
                # # In other words, this should be the step to create the "loaded model" with all
                # # force magnitudes populated
                # member_analysis_model = beams.build_toml_beam(member_load_model)
                # try:
                #     member_analysis_model.analyze()
                # except TypeError as e:  # If a str is entered as a load magnitude
                #     if debug:
                #         print(f"{member_name=}")
                #         print(f"{member_graph_model=}")
                #         print(f"{member_load_model=}")
                #         print(e)
                #     else:
                #         pass # Analysis error is expected if the reaction loads have not been processed

                # member_reactions = beams.get_node_reactions(member_analysis_model)
                # self.reactions[member_name] = member_reactions

                # if force_arrays:
                #     self.forces[member_name] = {}
                #     self.forces[member_name]["shear"] = beams.extract_shear_arrays(
                #         member_analysis_model, n_points=n_points
                #     )
                #     self.forces[member_name]["moment"] = beams.extract_moment_arrays(
                #         member_analysis_model, n_points=n_points
                #     )
                #     self.forces[member_name]["axial"] = beams.extract_axial_arrays(
                #         member_analysis_model, n_points=n_points
                #     )
                #     self.forces[member_name]["torque"] = beams.extract_torque_arrays(
                #         member_analysis_model, n_points=n_points
                #     )
                # if deflection_arrays:
                #     self.deflections[member_name] = {}
                #     self.deflections[member_name] = beams.extract_deflection_arrays(
                #         member_analysis_model, n_points=n_points
                #     )


# def determine_inplane_reactions(member_model: dict, reactions: dict, occupancies: dict) -> :

# # e.g. Walls
# def determine_linear_oop_reactions(member_model: dict) -> 