from copy import deepcopy


def expand_occupancy_loads(
    member_model: dict,
    occupancies: dict,
    distributed_direction_mapping: dict,
    reaction_type: str,
    null_point_load: dict,
    null_dist_load: dict,
) -> dict:
    """
    Returns a copy of 'member_model' with all occupancy loads
    replaced by their load components as described in the 'occupancies'
    dict.

    'member_model': A member dictionary as output from papermodels
        The member dictionary may have point or distributed loads with
        occupancy values assigned. If no occupancy values are assigned
        then no changes occur to the member model.
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
    'reaction_type': One of 'linear' or 'point'; used in determining how to treat
        supplied trib areas which represent different things based on the
        reaction_type.
    'null_point_load': A dictionary representing a null load (0 magnitude)
        for each load case in the occupancies.
    'null_dist_load': A dictionary representing a null dist load (0)
    """
    new_model = deepcopy(member_model)
    # new_model['loads']['point_loads'] = []

    # Below is a place-holder implementation for point loads for if/when
    # papermodels implements point supports that can interact with loads
    # e.g. using diaphragm or other collector elements or user-assigned
    # trib areas on point supports.
    # Need to still implement expand_point_load but it is probably similar
    # to expand_distributed_load

    # new_point_loads = new_model['loads']['point_loads']
    # for point_load in member_model['loads']['point_loads']:
    # occupancy = point_load['occupancy']
    # if occupancy and occupancy in occupancies:
    #     expanded_load = expand_point_load(point_load, occupancies[occupancy])
    #     new_point_loads.append(expanded_load)

    # elif occupancy and occupancy not in occupancies:
    #     raise ValueError(
    #         f"Occupancy: {occupancy} not found in the occupancies data provided.\n"
    #         f"Occupancies available: {[occ for occ in occupancies.keys()]}"
    #     )
    # else:
    #     new_point_loads.append(point_load)

    # This loop mutates the new_model to have a new key with the expanded loads
    new_model["loads"]["distributed_loads"] = []
    new_dist_loads = new_model["loads"]["distributed_loads"]
    for dist_load in member_model["loads"]["distributed_loads"]:
        occupancy = dist_load["occupancy"]
        model_dir = dist_load.get("direction", "gravity")
        analysis_dirs = distributed_direction_mapping[model_dir]
        tag = new_model["element_attributes"]["tag"]
        for analysis_dir in analysis_dirs:
            if occupancy and occupancy in occupancies:
                debug = False
                try:
                    expanded_load = expand_distributed_load(
                        dist_load,
                        occupancies[occupancy],
                        analysis_dir,
                        member_model["element_attributes"]["length"],
                        reaction_type,
                        null_dist_load,
                        debug=debug,
                    )
                except Exception as e:
                    print(new_model["element_attributes"]["tag"])
                    raise e
                new_dist_loads.append(expanded_load)

            elif occupancy and occupancy not in occupancies:
                raise ValueError(
                    f"Occupancy: {occupancy} not found in the occupancies data provided.\n"
                    f"Occupancies available: {[occ for occ in occupancies.keys()]}"
                )
            else:
                new_dist_loads.append(dist_load)

    return new_model


def expand_distributed_load(
    dist_load: dict,
    occupancy: dict,
    analysis_dir: str,
    length: float,
    reaction_type: str,
    null_dist_load: dict,
    debug: bool = False,
) -> dict:
    """
    Returns a dict representing the expanded load of 'dist_load' according
    to 'occupancy'.
    """
    new_dist_load = deepcopy(dist_load)
    new_dist_load.setdefault("expanded", [])
    applied_area = new_dist_load["applied_area"]
    area_ratio = dist_load["applied_area_ratio"]
    # The total area ratio is required because the dist_load start/end magnitudes
    # already take this ratio into account and we need to undo its affect when
    # we scale up the dist load magnitude to the applied area load.
    # It is kept because it is convenient to review the actual "applied area" of
    # the load on a member for personal validation.
    if reaction_type == "linear":
        # divide by length to get width of equivalent rectangle * unit_width
        # THis only needs to be done with collector elements with linear reactions
        # because their trib area reflects the total area covered by the joist region.
        # It needs to be reduced to a unit width which is what the applied_area
        # represents on array collector elements.
        applied_area = 1 * length * area_ratio
    load_constant = applied_area

    for load_case, load_value in occupancy.items():
        # load_constant = load_value * applied_area / total_area_ratio
        load_factor = (
            load_value * load_constant
        )  # This gives the correct value for CollectorTribModel with a single extent with partial loads when the total_area_ratio reflects te
        if debug:
            print(
                f"{load_case=} | {load_value=} | {applied_area=}| {area_ratio=} | {load_constant=} | {dist_load["start_magnitude"]=} | {dist_load["start_magnitude"] * load_constant=}"
            )
        expanded = {
            "start_magnitude": dist_load["start_magnitude"] * load_factor,
            "end_magnitude": dist_load["end_magnitude"] * load_factor,
            "start_loc": dist_load["start_loc"],
            "end_loc": dist_load["end_loc"],
            "case": load_case,
            "dir": analysis_dir,
        }
        if dist_load["end_loc"] - dist_load["start_loc"] <= 0.0:
            continue
        new_dist_load["expanded"].append(expanded)
    if new_dist_load["expanded"] == []:
        new_dist_load["expanded"].append(null_dist_load)

    return new_dist_load
