from copy import deepcopy

from .errors import InvalidPapermodelError


def expand_occupancy_loads(
    member_model: dict,
    occupancies: dict,
    distributed_direction_mapping: dict,
    reaction_type: str,
) -> dict:
    """
    Returns a copy of 'member_model' with the "expanded" load components of
    every occupancy load populated from the 'occupancies' dict.

    'member_model': A member dictionary as output from papermodels
        The member dictionary may have distributed loads with occupancy
        values assigned. Loads without an occupancy are copied unchanged.
    'occupancies': a dictionary of load components keyed by occupancy.
        e.g.
        {
            'occupancy1': {
                'component1': 1.0,
                'component2': 0.3,
                'component3': 1.9,
            },
            'occupancy2': {
                'component1': 0.4,
                'component2': 1.0,
                'component3': 0.8,
            }
        }
        Each value (the numbers shown in the above example), should represent
        a pressure. These values will be multiplied by the 'applied_area' key
        of each load and also multiplied by the start and end magnitude values
        (in the case of distributed loads).
    'distributed_direction_mapping': A dictionary mapping the load directions
        from papermodels (e.g. 'gravity') to a list of analysis directions.
    'reaction_type': One of 'linear' or 'point'; used in determining how to treat
        supplied trib areas which represent different things based on the
        reaction_type.
    """
    new_model = deepcopy(member_model)
    tag = new_model["element_attributes"]["tag"]
    length = new_model["element_attributes"]["length"]
    for dist_load in new_model["loads"]["distributed_loads"]:
        occupancy = dist_load.get("occupancy")
        if not occupancy:
            continue
        if occupancy not in occupancies:
            raise InvalidPapermodelError(
                f"Occupancy {occupancy!r} was not found in the occupancies provided. "
                f"Occupancies available: {list(occupancies)}",
                tag,
            )
        model_dir = dist_load.get("direction", "gravity")
        for analysis_dir in distributed_direction_mapping[model_dir]:
            expand_distributed_load(
                dist_load, occupancies[occupancy], analysis_dir, length, reaction_type
            )
    return new_model


def expand_distributed_load(
    dist_load: dict,
    occupancy: dict,
    analysis_dir: str,
    length: float,
    reaction_type: str,
) -> dict:
    """
    Returns 'dist_load' with a load component added to its "expanded" list for
    each load case in 'occupancy'. 'dist_load' is mutated.
    """
    dist_load.setdefault("expanded", [])
    if dist_load["end_loc"] - dist_load["start_loc"] <= 0.0:
        return dist_load
    applied_area = dist_load["applied_area"]
    if reaction_type == "linear":
        # A collector with a linear reaction has a trib area that reflects the
        # total area covered by the joist region. It is reduced to a unit width,
        # which is what the applied_area represents on array collector elements.
        applied_area = 1 * length * dist_load["applied_area_ratio"]

    for load_case, load_value in occupancy.items():
        load_factor = load_value * applied_area
        dist_load["expanded"].append(
            {
                "start_magnitude": dist_load["start_magnitude"] * load_factor,
                "end_magnitude": dist_load["end_magnitude"] * load_factor,
                "start_loc": dist_load["start_loc"],
                "end_loc": dist_load["end_loc"],
                "case": load_case,
                "dir": analysis_dir.upper(),
            }
        )
    return dist_load
