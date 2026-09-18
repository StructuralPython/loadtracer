from dataclasses import dataclass
import pathlib
from typing import Optional, Any, Union
import io

from .analysis_model import AbstractAnalysisModel
from ..errors import UnstableMemberError
from Pynite import FEModel3D
import pynite_tools as pt
import jsonchain


@dataclass
class PyniteFrame(AbstractAnalysisModel):
    pm: dict
    model: Optional[FEModel3D]

    def __post_init__(self):
        self.model = build_pynite_frame_model(self.pm)

    def get_reactions(self) -> dict[int, dict]:
        """
        Returns the reactions keyed by support index (see get_support_reactions).
        A member with no loads has empty reactions at each support.
        """
        if not self.model.load_combos:
            return {idx: {} for idx, _ in enumerate(self.pm["element_geometry"]["supports"])}
        self.model.analyze_linear()
        return get_support_reactions(self.model, self.pm)

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
    Returns a FEModel3D populated with the data from 'pm'.
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

    # Add the nodes to the model and name them sequentially
    for idx, (location, constraints) in enumerate(get_node_locations(pm)):
        node_name = f"N{idx}"
        model.add_node(node_name, X=location, Y=0, Z=0)
        if constraints is not None:
            model.def_support(node_name, *constraints)

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
        for expansion in dist_load.get("expanded", []):
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
        for expansion in point_load.get("expanded", []):
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


SUPPORT_CONSTRAINTS = {
    "fixed": [1, 1, 1, 1, 1, 1],
    "pin": [1, 1, 1, 1, 1, 0],
    "roller": [0, 1, 0, 0, 0, 0],
}
REACTION_DIRECTIONS = ("FX", "FY", "FZ", "MX", "MY", "MZ")


def get_node_locations(pm: dict) -> list[tuple[float, Optional[list[int]]]]:
    """
    Returns a list of (location, constraints) for the nodes of the member,
    sorted by location. The member ends are included as free nodes
    (constraints = None) when there is no support at the end.

    The first support is a pin and the others are rollers unless a support
    has a "fixity" of its own. Coincident supports (see validate_papermodel)
    are not modelled.

    Raises UnstableMemberError if the supports cannot make the member stable.
    """
    tag = pm["element_attributes"]["tag"]
    length = pm["element_attributes"]["length"]
    supports = [
        s for s in pm["element_geometry"]["supports"] if not s.get("coincident")
    ]
    fixities = [
        s.get("fixity", "pin" if idx == 0 else "roller")
        for idx, s in enumerate(supports)
    ]
    unknown = set(fixities) - set(SUPPORT_CONSTRAINTS)
    if unknown:
        raise UnstableMemberError(f"Unknown support fixity: {sorted(unknown)}", tag)
    if not ("fixed" in fixities or (len(supports) >= 2 and "pin" in fixities)):
        raise UnstableMemberError(
            f"The member has {len(supports)} support(s) ({fixities}); it needs at "
            "least two supports, one of them a pin, or a fixed support.",
            tag,
        )

    nodes = [(s["location"], SUPPORT_CONSTRAINTS[f]) for s, f in zip(supports, fixities)]
    if supports[0]["location"] > 0.0:
        nodes.insert(0, (0.0, None))
    if supports[-1]["location"] < length:
        nodes.append((length, None))
    return nodes


def get_support_reactions(model: FEModel3D, pm: dict) -> dict[int, dict]:
    """
    Returns the reactions of the solved 'model' keyed by support index, in the
    same order as the supports in 'pm' (which is the order that papermodels
    uses for 'transfer_reaction_index'). Every support is included, even when
    its reactions are zero, so that the indexes always line up.

    e.g. {0: {"FY": {"D": -5.0, "L": -10.0}, ...}, 1: {...}}
    """
    load_combos = list(model.load_combos)
    nodes_by_location = {node.X: node for node in model.nodes.values()}
    acc = {}
    for idx, support in enumerate(pm["element_geometry"]["supports"]):
        if support.get("coincident"):
            acc[idx] = {}
            continue
        node = nodes_by_location[support["location"]]
        acc[idx] = {
            direction: {
                combo: _clean(getattr(node, f"Rxn{direction}")[combo])
                for combo in load_combos
            }
            for direction in REACTION_DIRECTIONS
        }
    return acc


def _clean(value: float, abs_tol: float = 1e-9) -> float:
    """Returns 'value' as a float, with numerical noise near zero removed."""
    value = float(value)
    return 0.0 if abs(value) < abs_tol else value
