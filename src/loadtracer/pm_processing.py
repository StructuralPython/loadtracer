from typing import Optional
import re


def get_element_height(
    pm: dict, elevations: Optional[dict] = None, element_heights: Optional[dict] = None
):
    """
    Determines the floor to floor height from 'floor_heights' and populates
    the 'height' attribute in 'pm' (a model for a single element).
    'pm' -a papermodel dict
    'elevations' - a dictionary of floor elevations where the keys are the floor
        name and the values are the floor elevation
    'element_heights' - a dictionary of actual element heights
    """
    if elevations is None and element_heights is None:
        raise ValueError("Pass one of either elevations or element_heights")
    floor_index = extract_floor_index(pm["element_attributes"]["tag"])
    if elevations is not None:
        elevations_from_bottom = sorted(elevations.values())
        target_elevation = elevations_from_bottom[floor_index]
        if floor_index == 0 and len(elevations_from_bottom) == 1:
            floor_height = target_elevation
        elif floor_index == 0:
            floor_height = 0.0
        else:
            floor_height = target_elevation - elevations_from_bottom[floor_index - 1]
        return floor_height
    elif element_heights is not None:
        floor_height = element_heights[floor_index]
        return floor_height


def extract_floor_index(tag: str) -> int:
    """
    Returns the floor index for a given tag.

    e.g.
        "WT3.4" -> 3
        "FB0.2" -> 0
        "SJF1.0-7" -> 1
    """
    pattern = re.compile(r"[A-Z]+([0-9]+).[0-9]+[\-0-9]*")
    result = pattern.match(tag)
    floor_index = int(result.groups()[0])
    return floor_index
