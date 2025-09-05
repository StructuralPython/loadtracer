import re


def get_element_height(pm: dict, elevations: dict):
    """
    Determines the floor to floor height from 'floor_heights' and populates
    the 'height' attribute in 'pm' (a model for a single element).
    'pm' -a papermodel dict
    'elevations' - a dictionary of floor elevations where the keys are the floor
        name and the values are the floor elevation
    """
    elevations_from_bottom = sorted(elevations.values())
    floor_index = extract_floor_index(pm['element_attributes']['tag'])
    target_elevation = elevations_from_bottom[floor_index]
    if floor_index == 0 and len(elevations_from_bottom) == 1:
        floor_height = target_elevation
    elif floor_index == 0:
        floor_height = 0.0
    else:
        floor_height = target_elevation - elevations_from_bottom[floor_index - 1]
    return floor_height


def extract_floor_index(tag: str) -> int:
    """
    Returns the floor index for a given tag.

    e.g.
        "WT3.4" -> 3
        "FB0.2" -> 0
        "SJF1.0-7" -> 1
    """
    pattern = re.compile(r'[A-Z]+([0-9]+).[0-9]+[\-0-9]*')
    result = pattern.match(tag)
    floor_index = int(result.groups()[0])
    return floor_index
