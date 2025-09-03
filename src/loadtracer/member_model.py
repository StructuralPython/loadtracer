from copy import deepcopy
import re
from typing import Optional
from .utils import str_to_float, parse_unit_system, convert_unit_string


DEFAULT_ATTRS = {
    "L": 1.0,
    "E": 1.0,
    "Iz": 1.0,
    "Iy": 1.0,
    "A": 1.0,
    "J": 1.0,
    "nu": 1.0,
    "rho": 1.0,
}


def get_structured_toml_data(
    toml_data: dict,
    elevations: dict,
    occupancies: dict,
    reactions: dict,
) -> dict:
    """
    Returns the 'toml_data' ready to build the FE model
    """
    structured_toml_data = expand_toml_loads(toml_data, occupancies, reactions)
    structured_toml_data = expand_vertical_elements(structured_toml_data, elevations)
    support_locs = [support['location'] for support in structured_toml_data['element_geometry']['supports']]
    support_codes = {support['location']: support['fixity'][0].upper() for support in structured_toml_data['element_geometry']['supports']}

    length = structured_toml_data['element_attributes']['length']
    structured_toml_data['element_attributes'] = structured_toml_data['element_attributes'] | parse_beam_attributes([f"{length}"])
    structured_toml_data['element_geometry']['support_codes'] = support_codes
    structured_toml_data['element_geometry']["nodes"] = get_node_locations(
        support_locs, length
    )
    structured_toml_data['element_geometry']["spans"] = get_all_spans(
        support_locs, length
    )
    return structured_toml_data


def expand_vertical_elements(
        structured_toml_data: dict, 
        elevations: Optional[dict] = None,
    ) -> dict:
    """
    Returns a copy of 'structured_toml_data' but mutated so that all
    elements have an ['element_attributes']['elevation'] field and 
    all vertical elements have an additional ['element_attributes']['height']
    field.

    'elevations': a dict structured as [int, float] as follows:
        {
            0: 3500,
            1: 6000,
            2: 8500,
            3: 11000,
            # ...etc
        }
    Where the keys represent page indexes of parsed elements
    and the values represent the elevation of the floor in the
    plans represented on that page.
    """
    new_toml_data = deepcopy(structured_toml_data)
    if elevations is None:
        return new_toml_data

    element_tag = new_toml_data['element_attributes']['tag']
    match = re.search(pattern=r"[A-Za-z]+([0-9]+).[0-9]+", string=element_tag)
    page_idx = match.groups()[0]
    element_elevation = elevations.get(page_idx, [])
    if new_toml_data['element_attributes']['orientation'] == "vertical":
        previous_page_idx = int(page_idx) - 1
        elevation_below = elevations.get(f"{previous_page_idx}")
        if elevation_below is None:
            raise ValueError(
                f"Element {element_tag=} is a vertical element on {page_idx=} "
                f"but since there is no {page_idx-1=}, it cannot exist there.\n"
                "Did you mean to draw it as a transferring element?"
            )
        else:
            height = element_elevation - elevation_below
        new_toml_data['element_attributes']['elevation'] = element_elevation
        new_toml_data['element_attributes']['height'] = height
    return new_toml_data





def expand_toml_loads(
    toml_data: dict,
    occupancies: dict,
    reactions: dict,
) -> dict:
    """
    Returns a structured beam dict ready for analysis.
    """
    new_data = deepcopy(toml_data)
    new_data['loads']['point_loads'] = {} # Start new point loads
    for point_load in toml_data['loads']['point_loads']:
        point_transfer_source = point_load['transfer_source']
        point_occupancy = point_load['occupancy']
        if point_transfer_source:
            reaction_directions = (
                reactions
                .get(point_load['transfer_source'], {})
                .get(f"{point_load['transfer_reaction_index']}", {})
            )
            new_data['loads']['point_loads'].setdefault("transfer", [])
            for load_direction, reaction_magnitude_components in reaction_directions.items():
                for load_case, mag_comp in reaction_magnitude_components.items():
                    new_point_load = point_load | {'magnitude': mag_comp, 'case': load_case, "direction": load_direction}
                    new_data['loads']['point_loads'].setdefault("expanded", [])
                    new_data['loads']['point_loads']['expanded']['transfer'].append(new_point_load)
        elif point_occupancy:
            occupancy = point_load['occupancy']
            occupancy_components = occupancies.get(occupancy, {})
            new_data['loads']['point_loads']['expanded'].setdefault("occupancy", [])
            for load_case, mag_comp in occupancy_components.items():
                # TODO: Probably need to parse unit system
                magnitude = mag_comp * point_load['applied_area']
                new_point_load = point_load | {'magnitude': magnitude, 'case': load_case}
                new_data['loads']['point_loads']['exanded']['occupancy'].append(new_point_load)

    new_data['loads']['distributed_loads'] = {}
    for dist_load in toml_data['loads']['distributed_loads']:
        dist_transfer_source = dist_load['transfer_source']
        dist_occupancy = dist_load['occupancy']
        if dist_transfer_source:
            reaction_dir_magnitude_components = (
                reactions
                .get(dist_load['transfer_source'], {})
            )
            new_data['loads']['distributed_loads']['expanded'].setdefault("transfer", [])
            for load_direction, reaction_magnitude_component in reaction_dir_magnitude_components.items():
                for load_case, linear_reaction in reaction_magnitude_component.items():
                    new_dist_load = dist_load | {
                        "start_magnitude": linear_reaction['w0'], 
                        "end_magnitude": linear_reaction['w1'], 
                        "direction": load_direction, 
                        "case": load_case
                    }
                    new_data['loads']['distributed_loads']['expanded']['transfer'].append(new_dist_load)

        elif dist_occupancy:
            occupancy = dist_load['occupancy']
            occupancies_lower = {k.lower(): v for k, v in occupancies.items()}
            occupancy_components = occupancies_lower.get(occupancy, {})
            new_data['loads']['distributed_loads']['expanded'].setdefault("occupancy", [])
            for load_case, mag_comp in occupancy_components.items():
                # unit_system = parse_unit_system("psf")
                # mag_comp = convert_unit_string(mag_comp, unit_system)
                total_load = mag_comp * dist_load['applied_area']
                start_mag = total_load * dist_load['start_magnitude']
                end_mag = total_load * dist_load['end_magnitude']
                new_dist_load = dist_load | {'start_magnitude': start_mag, 'end_magnitude': end_mag, 'case': load_case, "direction": load_direction}
                new_data['loads']['distributed_loads']['expanded']['occupancy'].append(new_dist_load)
    return new_data


def get_node_locations(
    support_locations: list[float], beam_length: float
) -> dict[str, float]:
    """
    Returns a dict representing the node names and node coordinates required for
    a beam with support locations at 'support_locations' and a beam of length of
    'beam_length'.

    Each node name and node location is unique. nodes are numbered sequentially from
    left to right starting at "N0".
    """
    nodes_to_create = support_locations[:]  # make a copy
    if 0.0 not in support_locations:
        nodes_to_create.append(0.0)
    if beam_length not in support_locations:
        nodes_to_create.append(beam_length)

    node_locations = {}
    for idx, sup_loc in enumerate(sorted(nodes_to_create)):
        node_locations.update({f"N{idx}": sup_loc})
    return node_locations


def get_all_spans(
    support_locations: list[float], beam_length: float
) -> dict[str, float]:
    """
    Returns a dictionary of spans in the following format

    spans = {
        "left_cant": [x],
        "interior_spans": [r, s, t, ...],
        "right_cant": [y]
    }

    Where the interior spans are enumerated spatially from left-to-right so the order
    of all spans combined together could be 
    spans['left_cant'] + spans['interior_spans'] + spans['right_cant']
    """
    sorted_supports = sorted(support_locations)
    spans = {}
    if 0.0 not in sorted_supports:
        spans['left_cant'] = [sorted_supports[0] - 0.0]
    else:
        spans['left_cant'] = []

    if beam_length not in support_locations:
        spans['right_cant'] = [beam_length - sorted_supports[-1]]
    else:
        spans['right_cant'] = []

    interior_spans = []
    prev_support = 0.0
    for idx, support_loc in enumerate(sorted_supports):
        if idx >= 1:
            interior_spans.append(support_loc - prev_support)
        prev_support = support_loc
    spans['interior_spans'] = interior_spans
    return spans

def parse_beam_attributes(
    beam_attributes: list[str], unit_designation: Optional[str] = None
) -> dict[str, float]:
    """
    Returns a dictionary of beam attributes according to which attributes are present
    in 'beam_attributes' in the order according to the beam file format BEAM_FORMAT.md,
    Workbook_04 edition. The order of attributes are as follows: Length,E,Iz,[Iy,A,J,nu,rho]
    """
    beam_attrs = map_beam_attributes(parse_kwargs(beam_attributes, unit_designation))
    return DEFAULT_ATTRS | beam_attrs


def parse_kwargs(
    attr_items: list[str], unit_designation: Optional[str] = None
) -> dict[str, str | float]:
    """
    Returns a dictionary of any of the elements in 'attr_items' that
    contain an "=" character as key, value pairs.
    """

    """
    Returns a dictionary representing the parsed beam attributes contained
    in 'attr_items'. Each beam attribute may be either a float or a str.
    A float is interpreted as being a positional attribute in the order
    of: L, E, Iz, Iy, A, J, nu, rho

    If it is a str and the str has a "=" in it, then it is interpreted
    as a kwarg. 

    Positional and kwargs are treated consistently with positional and
    kwargs in Python.
    """
    positional_items = []
    remaining_items = []
    kwargs_flag = False
    for attr_item in attr_items:
        if "=" in attr_item and kwargs_flag == False:
            kwargs_flag = True
            remaining_items.append(attr_item)
            continue
        if kwargs_flag and "=" not in attr_item:
            raise ValueError(
                "Beam file cannot have positional beam attributes following keyword attributes"
            )
        elif not kwargs_flag and "=" not in attr_item:
            positional_items.append(attr_item)
        else:
            remaining_items.append(attr_item)

    kwargs = {}
    for attr_item in remaining_items:
        attr, item = attr_item.split("=", 1)
        attr = attr.rstrip(" ")
        item = item.strip(" ")
        as_float = str_to_float(item)
        if unit_designation is not None:
            unit_system = parse_unit_system(unit_designation)
            as_float = convert_unit_string(as_float, unit_system)
        kwargs.update({attr: as_float})

    positional_args = []
    for attr_item in positional_items:
        attr_item = attr_item.strip(" ")
        as_float = str_to_float(attr_item)
        if unit_designation is not None:
            unit_system = parse_unit_system(unit_designation)
            as_float = convert_unit_string(as_float, unit_system)
        positional_args.append(as_float)

    return dict(zip(DEFAULT_ATTRS.keys(), positional_args)) | kwargs



def map_beam_attributes(parsed_attrs: dict[str]) -> dict[str]:
    """
    Converts the dict keys in 'parsed_attrs' to the official
    dict keys in DEFAULT_ATTRS used in the structured beam data
    """
    attr_map = {
        "l": "L",
        "e": "E",
        "Ix": "Iz",
        "ix": "Iz",
        "iz": "Iz",
        "iy": "Iy",
        "a": "A",
        "j": "J",
    }
    acc = {}
    for attr, value in parsed_attrs.items():
        new_attr = attr_map.get(attr, attr)
        acc.update({new_attr: value})
    return acc