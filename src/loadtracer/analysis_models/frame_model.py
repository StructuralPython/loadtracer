from dataclasses import dataclass
import pathlib
from typing import Optional, Any, Union
import io

from .analysis_model import AbstractAnalysisModel
from Pynite import FEModel3D
import pynite_tools as pt
import jsonchain


@dataclass
class PyniteFrame(AbstractAnalysisModel):
    pm: dict
    model: Optional[FEModel3D]

    def __post_init__(self):
        self.model = build_pynite_frame_model(self.pm)

    def get_reactions(self):
        self.model.analyze_linear()
        reactions = pt.extract_node_reactions(self.model, results_key=None)
        return reactions

    def dump_model(
        self, fp: Optional[io.StringIO] = None, indent: int = 2
    ) -> Optional[dict]:
        """
        Dumps the model to 'fp'. If 'fp' is None, then a Python
        dict is returned.
        """
        if fp is not None:
            return pt.dump(self.model, fp, indent=indent)
        else:
            return pt.dump_dict(self.model)

    def load_model(
        self, fp: Optional[io.StringIO] = None, model_data: Optional[dict] = None
    ) -> dict:
        """
        Loads the model from either 'fp' or 'model_data' and returns a dict
        """
        if fp is not None:
            return pt.load(fp)
        else:
            return pt.load_dict(model_data)

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
            return pt.from_json(filepath)
        else:
            return pt.load_dict(model_data)


def build_pynite_frame_model(
    pm: dict,
    material: Optional[dict] = None,
    section: Optional[dict] = None,
    load_combinations: Optional[dict] = None,
):
    """
    Returns a FEModel3D populated with teh data from 'pm'.
    """
    if load_combinations is None:
        load_combinations = {}
    model = FEModel3D()

    if material is None:
        material = pynite_default_material()
    if section is None:
        section = pynite_default_section()

    model.add_material(**material)
    model.add_section(**section)

    node_locations = get_node_locations(pm)
    # Node locations, just the x-coord of each node is needed
    ords = [node_loc[0] for node_loc in node_locations]

    # Add the nodes to the model and name them sequentially
    for idx, ord in enumerate(ords):
        node_name = f"N{idx}"
        support = node_locations[idx][1]
        model.add_node(node_name, X=ord, Y=0, Z=0)
        if support:
            model.def_support(node_name, *support)

    # Define the member
    model.add_member(
        name=pm["element_attributes"]["tag"],
        i_node="N0",
        j_node=node_name,
        material_name=material["name"],
        section_name=section["name"],
        rotation=0.0,
    )

    # Add loads
    load_cases = set()
    for dist_load in pm["loads"]["distributed_loads"]:
        for expansion in dist_load["expanded"]:
            load_cases.add(expansion["case"])
            model.add_member_dist_load(
                pm["element_attributes"]["tag"],
                direction=expansion["dir"],
                w1=expansion["start_magnitude"],
                w2=expansion["end_magnitude"],
                x1=expansion["start_loc"],
                x2=expansion["end_loc"],
                case=expansion["case"],
            )

    for point_load in pm["loads"]["point_loads"]:
        for expansion in point_load["expanded"]:
            load_cases.add(expansion["case"])
            model.add_member_pt_load(
                pm["element_attributes"]["tag"],
                direction=expansion["dir"],
                P=expansion["magnitude"],
                x=expansion["location"],
                case=expansion["case"],
            )

    # Add load combinations
    for load_combination in load_combinations:
        model.add_load_combo(**load_combination)

    # Add load cases as combinations
    for load_case in sorted(load_cases):
        case_combo = {"name": load_case, "factors": {load_case: 1.0}}
        model.add_load_combo(**case_combo)

    return model


def pynite_default_material():
    return {"name": "default", "E": 1, "G": 1, "nu": 0.5, "rho": 1.0, "fy": 1.0}


def pynite_default_section():
    return {
        "name": "default",
        "A": 1,
        "Iz": 1,
        "Iy": 1,
        "J": 1,
    }


def get_node_locations(pm: dict) -> list[tuple]:
    """
    Returns the node locations
    """
    supports = pm["element_geometry"]["supports"]
    length = pm['element_attributes']['length']

    augmented_supports = []
    for idx, support in enumerate(supports):
        if idx == 0 and support['location'] != 0.0:
            augmented_supports.append({'location': 0.0, 'fixity': 'free'})
            augmented_supports.append(support)
        elif idx == len(supports) - 1 and support['location'] != length:
            augmented_supports.append(support)
            augmented_supports.append({'location': length, 'fixity': 'free'})
        else:
            augmented_supports.append(support)
    acc = []
    for support in augmented_supports:
        location = support["location"]
        fixity = support["fixity"]
        constraints = None
        if fixity == "pin":
            constraints = [1, 1, 1, 1, 1, 0]
        elif fixity == "roller":
            constraints = [0, 1, 0, 0, 0, 0]
        elif fixity == "free":
            constraints = [0, 0, 0, 0, 0, 0]
        assert constraints is not None
        acc.append((location, constraints))
    return sorted(acc, key=lambda x: x[0])
