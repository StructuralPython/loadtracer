from typing import Optional
from copy import deepcopy
import math
import json
import pathlib
import re
from Pynite import FEModel3D
import numpy as np
from .utils import (
    str_to_int,
    str_to_float,
    read_csv_file,
    convert_unit_string,
    parse_unit_system,
    read_json_file,
    write_json_file,
    read_toml_file
)


def build_toml_beam(toml_data: dict) -> FEModel3D:
    """
    Returns a FEModel3D of a beam that has the attributes described in 'beam_data' and 'A', 'J', 'nu', and 'rho'.
    """
    beam_model = FEModel3D()
    elem_attrs = toml_data['element_attributes']
    elem_geom = toml_data['element_geometry']
    for node_name, x_coord in elem_geom["nodes"].items():
        beam_model.add_node(node_name, x_coord, 0, 0)
        support_type = elem_geom["support_codes"].get(x_coord, None)
        if support_type == "P":
            beam_model.def_support(node_name, True, True, True, True, True, False)
        elif support_type == "R":
            beam_model.def_support(node_name, False, True, False, False, False, False)
        elif support_type == "F":
            beam_model.def_support(node_name, True, True, True, True, True, True)

    shear_modulus = calc_shear_modulus(elem_attrs["E"], elem_attrs["nu"])
    beam_model.add_material(
        "Beam Material",
        elem_attrs["E"],
        shear_modulus,
        elem_attrs["nu"],
        elem_attrs["rho"],
    )
    beam_model.add_section(
        "Section",
        Iy=elem_attrs['Iy'],
        Iz=elem_attrs['Iz'],
        J=elem_attrs['J'],
        A=elem_attrs['A'],
    )

    # The variable 'node_name' retains the last value from the for loop
    # Which gives us the j-node
    beam_model.add_member(
        elem_attrs["tag"],
        "N0",
        node_name,
        material_name="Beam Material",
        section_name="Section"
    )
    load_cases = []
    for point_load in toml_data["loads"]['point_loads']:
        beam_model.add_member_pt_load(
                elem_attrs["tag"],
                "Fy",
                point_load["magnitude"],
                point_load["location"],
                case=point_load["case"],
            )
        
        if point_load["case"] not in load_cases:
            load_cases.append(point_load["case"])
        
    for dist_load in toml_data['loads']['distributed_loads']:
        beam_model.add_member_dist_load(
                elem_attrs["tag"],
                "Fy",
                dist_load["start_magnitude"],
                dist_load["end_magnitude"],
                dist_load["start_loc"],
                dist_load["end_loc"],
                case=dist_load["case"],
            )
        if dist_load["case"] not in load_cases:
            load_cases.append(dist_load["case"])

    for load_case in load_cases:
        beam_model.add_load_combo(load_case, {load_case: 1.0})
    return beam_model


def load_toml_beam_model(
    toml_path: str,
    load_combos: Optional[dict] = None,
    occupancies_json: Optional[pathlib.Path | str] = None,
    reactions_json: Optional[pathlib.Path | str] = None,
    elevations_json: Optional[pathlib.Path | str] = None
):
    """
    Returns an FEModel3D beam model representing the beam described in 'filename'
    """
    beam_data_raw = read_toml_file(toml_path)
    occupancies = {}

    if occupancies_json is not None:
        occupancies = read_json_file(occupancies_json)
        with open(occupancies_json) as json_file:
            occupancies = json.load(json_file)

    reactions = None
    if reactions_json is not None:
        reactions = read_json_file(reactions_json)

    if elevations_json is not None:
        elevations = read_json_file(elevations_json)

    beam_data_structured = get_structured_toml_data(
        beam_data_raw, occupancies, reactions, elevations
    )
    beam_model = build_toml_beam(beam_data_structured)
    if load_combos is not None:
        for combo_name, combo_factors in load_combos.items():
            combo_factors = {k.replace("_fact", ''): v for k, v in combo_factors.items()}
            beam_model.add_load_combo(combo_name, combo_factors)
    return beam_model


def get_node_reactions(
    solved_beam_model: FEModel3D,
    load_combos: Optional[list[str]] = None,
) -> dict:
    """
    Returns the node reactions for the given 'load_combos'. If reaction
    directions have a value near 0.0 then they are filtered out of the final.

    members are stored by an integer index corresponding to their order of appearance,
    left-to-right, in the beam. This allows node look-up to be performed according
    to their position rather than requiring to know their node name.
    """
    acc = []
    if load_combos is None:
        load_combos = list(solved_beam_model.load_combos.keys())
    all_node_reactions = get_all_node_reactions(solved_beam_model)
    for direction_dict in all_node_reactions.values():
        for direction, combo_reactions in direction_dict.items():
            if direction == "loc":
                loc = combo_reactions
                continue
            reaction_data = {}
            if not math.isclose(sum(combo_reactions.values()), 0.0, abs_tol=1e-6):
                reaction_data["loc"] = loc
                reaction_data[direction] = {}
                for combo_name, reaction in combo_reactions.items():
                    if combo_name in load_combos:
                        if combo_name.endswith("_fact"):
                            combo_name = combo_name.replace("_fact","")
                        reaction_data[direction][combo_name] = reaction
                acc.append(reaction_data)
    return {idx: reaction for idx, reaction in enumerate(acc)}


def extract_moment_arrays(
    solved_beam_model: FEModel3D,
    combo_names: Optional[list[str]] = None,
    n_points: int = 200,
) -> dict:
    """
    Returns a dictionary of moment arrays for the combo names in 'combo_names'
    if combo_name is None then all combos are returned.

    Moment arrays have empty directions filtered out.
    """
    acc = {}
    if combo_names is None:
        combo_names = list(solved_beam_model.load_combos.keys())
    for direction in ["Mz", "My"]:
        acc[direction] = {}
        all_moment_arrays = extract_arrays_all_combos(
            solved_beam_model, "moment", direction, n_points
        )
        for combo_name, xy_arrays in all_moment_arrays.items():
            if combo_name in combo_names:
                xy_arrays[1] = -1 * xy_arrays[1] # Reverse moment direction as per PyNite conventions
                if not np.isclose(xy_arrays[1], 0.0).all():
                    acc[direction][combo_name] = xy_arrays.tolist()
    return acc


def extract_shear_arrays(
    solved_beam_model: FEModel3D,
    combo_names: Optional[list[str]] = None,
    n_points: int = 200,
) -> dict:
    """
    Returns a dictionary of shear arrays for the combo names in 'combo_names'
    if combo_name is None then all combos are returned.

    Moment arrays have empty directions filtered out.
    """
    acc = {}
    if combo_names is None:
        combo_names = list(solved_beam_model.load_combos.keys())
    for direction in ["Fy", "Fz"]:
        acc[direction] = {}
        all_shear_arrays = extract_arrays_all_combos(
            solved_beam_model, "shear", direction, n_points
        )
        for combo_name, xy_arrays in all_shear_arrays.items():
            if combo_name in combo_names:
                if not np.isclose(xy_arrays[1], 0.0).all():
                    acc[direction][combo_name] = xy_arrays.tolist()
    return acc


def extract_axial_arrays(
    solved_beam_model: FEModel3D,
    combo_names: Optional[list[str]] = None,
    n_points: int = 200,
) -> dict:
    """
    Returns a dictionary of axial arrays for the combo names in 'combo_names'
    if combo_name is None then all combos are returned.

    Moment arrays have empty directions filtered out.
    """
    acc = {}
    if combo_names is None:
        combo_names = list(solved_beam_model.load_combos.keys())
    for direction in ["axial"]:
        acc[direction] = {}
        all_axial_arrays = extract_arrays_all_combos(
            solved_beam_model, "axial", direction, n_points
        )
        for combo_name, xy_arrays in all_axial_arrays.items():
            if combo_name in combo_names:
                if not np.isclose(xy_arrays[1], 0.0).all():
                    acc[direction][combo_name] = xy_arrays.tolist()
    return acc


def extract_torque_arrays(
    solved_beam_model: FEModel3D,
    combo_names: Optional[list[str]] = None,
    n_points: int = 200,
) -> dict:
    """
    Returns a dictionary of torque arrays for the combo names in 'combo_names'
    if combo_name is None then all combos are returned.

    Arrays have empty directions filtered out but the empty direction key
    still exists in the dictionary. It has a value of an empty dict: {}.
    """
    acc = {}
    if combo_names is None:
        combo_names = list(solved_beam_model.load_combos.keys())
    for direction in ["torque"]:
        acc[direction] = {}
        all_torque_arrays = extract_arrays_all_combos(
            solved_beam_model, "torque", direction, n_points
        )
        for combo_name, xy_arrays in all_torque_arrays.items():
            if combo_name in combo_names:
                if not np.isclose(xy_arrays[1], 0.0).all():
                    acc[direction][combo_name] = xy_arrays.tolist()
    return acc


def extract_deflection_arrays(
    solved_beam_model: FEModel3D,
    combo_names: Optional[list[str]] = None,
    n_points: int = 200,
) -> dict:
    """
    Returns a dictionary of deflection arrays for the combo names in 'combo_names'
    if combo_name is None then all combos are returned.

    Arrays have empty directions filtered out but the empty direction key
    still exists in the dictionary. It has a value of an empty dict: {}.
    """
    acc = {}
    if combo_names is None:
        combo_names = list(solved_beam_model.load_combos.keys())
    for direction in ["dy", "dz"]:
        acc[direction] = {}
        all_deflection_arrays = extract_arrays_all_combos(
            solved_beam_model, "deflection", direction, n_points
        )
        for combo_name, xy_arrays in all_deflection_arrays.items():
            if combo_name in combo_names:
                if not np.isclose(xy_arrays[1], 0.0).all():
                    acc[direction][combo_name] = xy_arrays.tolist()
    return acc


def extract_arrays_all_combos(
    solved_beam_model: FEModel3D,
    result_type: str,
    direction: Optional[str] = None,
    n_points: int = 200,
) -> dict:
    """
    Returns a dictionary keyed by load combo name that contains the resulting arrays of the 'solved_beam_model',
    for the given 'result_type' and 'direction' with 'n_points' as the number of values in the array.

    'solved_beam_model': A PyNite.FEModel3D object that contains one member and has been successfully analyzed
    'result_type': str, one of {'shear', 'moment', 'deflection', 'axial', 'torque'}
    'direction': str that corresponds to the 'result_type':
        'shear': {'Fy', 'Fz'}
        'moment': {'Mz', 'My'}
        'deflection': {'dx', 'dy', 'dz'}
    'n_points': the number of values in the resulting arrays

    The keys in the resulting dictionary represent the names of all of the load combos in the model. The
    values are (n_points, 2)-shaped arrays that contain an x-array (of beam locations) and a y-array (of results).
    """
    all_combos = {}
    beam_name = list(solved_beam_model.members.keys())[0]
    member = solved_beam_model.members[beam_name]
    if result_type == "shear":
        method = member.shear_array
    elif result_type == "moment":
        method = member.moment_array
    elif result_type == "deflection":
        method = member.deflection_array
    elif result_type == "axial":
        method = member.axial_array
    elif result_type == "torque":
        method = member.torque_array

    for combo_name in solved_beam_model.load_combos:
        if result_type in ("shear", "moment", "deflection"):
            all_combos[combo_name] = method(direction, n_points, combo_name)
        else:
            all_combos[combo_name] = method(n_points, combo_name)
    return all_combos


def get_all_node_reactions(
    beam_model: FEModel3D,
) -> dict[str, dict[str, dict[str, float]]]:
    """
    Returns a nested dictionary of node reactions for all load combos keyed
    by node name, direction, and then load combo name.
    """
    acc = {}
    for node_name, node_data in beam_model.nodes.items():
        acc[node_name] = {}
        acc[node_name]["loc"] = node_data.X
        for attr in ("RxnFX", "RxnFY", "RxnFZ", "RxnMX", "RxnMY", "RxnMZ"):
            acc[node_name][attr.replace("Rxn", "")] = getattr(node_data, attr)

    return acc