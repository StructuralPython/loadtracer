from typing import Optional, Union, Any
from copy import deepcopy, copy
import jsonchain
from rich import print

class ReactionNotFoundError(Exception):
    pass


def expand_reaction_loads(
    member_model: dict,
    member_reactions: dict,
    distributed_direction_mapping: dict,
    point_direction_mapping: dict,
    missing_reactions: str = "raise",
) -> tuple[dict, dict]:
    """
    Returns a copy of 'member_model' with all reaction load transfers
    replaced by their load components as described in the 'reactions'
    dict.

    'member_model': A member dictionary as output from papermodels
        The member dictionary may have point or distributed loads with
        occupancy values assigned. If no occupancy values are assigned
        then no changes occur to the member model.
    'member_reactions': a dictionary of nodal reactions from a member analysis
        The order of node reactions is assumed to be in geometric order
        (i.e. order of appearance in local x-ordinates). Therefore the names
        of each node should be irrelevant to the mapping since they will
        be assigned by numerical index.
        e.g.
        {
            'member_name': {
                'node_id0': {
                    'load_dir1': {
                        'component1': 12.3,
                        'component2': 14.5,
                        'component3': 9.4,
                    },
                    'load_dir2': {
                        'component1': 43.2,
                        'component2': 34.2,
                        'component3': 13.4,
                    },
                    ...
                },
                'node_id1': {
                    'load_dir1': {
                        'component1': 12.3,
                        'component2': 14.5,
                        'component3': 9.4,
                    },
                    'load_dir2': {
                        'component1': 43.2,
                        'component2': 34.2,
                        'component3': 13.4,
                    },
                    ...
                }, ...
            },
        }

    'distributed_direction_mapping' / 'point_direction_mapping':
        A dictionary mapping of the names of the load directions
        from papermodels (i.e. 'gravity', 'inplane', 'out_of_plane')
        and the reaction directions they should map from the node reactions.

        The mapping value can be either a single string or a list of values, e.g.

        {'gravity': ["FY"]} - This will only apply the FY reaction load components
            from the node_reactions. If this dictionary is passed as a distributed
            direction mapping, then the FY value will be applied as both the
            'start_magnitude' and 'end_magnitude' value of a distributed load.
            If it is for a point load mapping, then it will apply to the magnitude

        {'gravity': ["FY", "MZ"]} - This will apply both the FY and MZ reaction
        components as node reactions. If this is passed as a distributed direction
        mapping, a distributed moment load would be created in addition to a distributed
        'FY' load.
    'missing_reactions': one of either 'raise' or 'ignore'
    """
    # POINT LOADS
    ignored_reactions = {}
    new_model = deepcopy(member_model)
    new_model["loads"]["point_loads"] = []
    new_point_loads = new_model["loads"]["point_loads"]
    for point_load in member_model["loads"]["point_loads"]:
        transfer_source = point_load["transfer_source"]
        if not transfer_source:
            new_point_loads.append(point_load)
            continue
        transfer_index = point_load["transfer_reaction_index"]
        model_direction = point_load["direction"]
        try:
            indexed_reactions = expand_point_reactions(
                point_load,
                member_reactions,
                transfer_source,
                model_direction,
                point_direction_mapping,
            )
        except ReactionNotFoundError:
            tag = member_model["element_attributes"]["tag"]
            if missing_reactions != "ignore":
                raise ReactionNotFoundError(
                    f"Member {tag}: No reactions were found for {transfer_source}"
                )
            else:
                ignored_reactions.setdefault(tag, [])
                ignored_reactions[tag].append(transfer_source)
                continue
        transfer_reactions = indexed_reactions[transfer_index]
        new_point_load = copy(point_load)
        new_point_load.setdefault("expanded", [])
        new_point_load["expanded"] += transfer_reactions
        new_point_loads.append(new_point_load)
    tag = member_model["element_attributes"]["tag"]
    # DISTRIBUTED LOADS
    new_model["loads"]["distributed_loads"] = []
    new_dist_loads = new_model["loads"]["distributed_loads"]
    for dist_load in member_model["loads"]["distributed_loads"]:
        transfer_source = dist_load["transfer_source"]
        if not transfer_source:
            new_dist_loads.append(dist_load)
            continue
        transfer_index = dist_load["transfer_reaction_index"]
        model_direction = dist_load["direction"]
        try:
            tag = member_model["element_attributes"]["tag"]
            # print(f'{tag=}')
            indexed_reactions = expand_distributed_reactions(
                dist_load,
                member_reactions,
                transfer_source,
                model_direction,
                distributed_direction_mapping,
            )
        except ReactionNotFoundError:
            if missing_reactions != "ignore":
                tag = member_model["element_attributes"]["tag"]
                raise ReactionNotFoundError(
                    f"Member {tag}: No reactions were found for {transfer_source}"
                )
            else:
                ignored_reactions.setdefault(tag, [])
                ignored_reactions[tag].append(transfer_source)
                continue
        try:
            transfer_reactions = indexed_reactions[transfer_index]
        except:
            raise ValueError(
                f"Problem with {tag}. {indexed_reactions=} {member_reactions[tag]=}"
            )
        new_dist_load = copy(dist_load)
        new_dist_load.setdefault("expanded", [])
        new_dist_load["expanded"] += transfer_reactions
        new_dist_loads.append(new_dist_load)
    return new_model, ignored_reactions


def expand_point_reactions(
    point_load,
    member_reactions,
    transfer_source,
    model_direction,
    point_direction_mapping,
) -> dict:
    """
    Returns a dictionary of load point reactions structured the following way:

    1. Keyed by reaction index (reaction indexes are assumed to be solve in x-positive
        bias direction
    )
    Values are a list of

    Example output:

    {
        0: [
            {
                "magnitude": magnitude_value,
                "location": location_value,
                "case": case_value,
                "dir": analysis_dir_value
            },
            {
                "magnitude": magnitude_value,
                "location": location_value,
                "case": case_value,
                "dir": analysis_dir_value
            },
        ],
        1: [
            {
                "magnitude": magnitude_value,
                "location": location_value,
                "case": case_value,
                "dir": analysis_dir_value
            },
            {
                "magnitude": magnitude_value,
                "location": location_value,
                "case": case_value,
                "dir": analysis_dir_value
            },
        ]
    }
    """
    transfer_reactions = member_reactions.get(transfer_source, None)
    if transfer_reactions is None:
        raise ReactionNotFoundError(f"{transfer_reactions=}")
    acc = {}
    for index, node_id in enumerate(transfer_reactions):
        acc[index] = []
        loads_by_dir = transfer_reactions[node_id]
        analysis_dirs = point_direction_mapping[model_direction]
        for analysis_dir in analysis_dirs:
            load_cases = loads_by_dir.get(analysis_dir, None)
            if load_cases is None:
                raise ReactionNotFoundError(f"{transfer_reactions=}")
            # Typical condition from a frame member
            for case_name, magnitude in load_cases.items():
                mag = -magnitude if magnitude > 0 else magnitude
                new_point_load = {
                    "magnitude": mag,
                    "location": point_load["location"],
                    "case": case_name,
                    "dir": analysis_dir,
                }
                acc[index].append(new_point_load)
    if not acc:
        raise ReactionNotFoundError(f"{transfer_reactions=}")
    return acc


def expand_distributed_reactions(
    dist_load,
    member_reactions,
    transfer_source,
    model_direction,
    distributed_direction_mapping,
) -> dict:
    """
    Returns a dictionary of load distributed reactions structured the following way:

    1. Keyed by reaction index (reaction indexes are assumed to be solve in x-positive
        bias direction
    )
    Value for the key is a list of dicts representing complete
    distributed load descriptions.

    Example output:

    {
        0: [ # reaction index
            {
                "start_magnitude": magnitude_value,
                "end_magnitude": magnitude_value,
                "start_loc": start_loc_value,
                "end_loc": end_loc_value,
                "case": case_value,
                "dir": analysis_direction_value,
            },
            {
                "start_magnitude": magnitude_value,
                "end_magnitude": magnitude_value,
                "start_loc": start_loc_value,
                "end_loc": end_loc_value,
                "case": case_value,
                "dir": analysis_direction_value,
            },
            ...
        ],
        ...
        1: [ # reaction index
            {
                "start_magnitude": magnitude_value,
                "end_magnitude": magnitude_value,
                "start_loc": start_loc_value,
                "end_loc": end_loc_value,
                "case": case_value,
                "dir": analysis_direction_value,
            },
            {
                "start_magnitude": magnitude_value,
                "end_magnitude": magnitude_value,
                "start_loc": start_loc_value,
                "end_loc": end_loc_value,
                "case": case_value,
                "dir": analysis_direction_value,
            },
            ...
        ],
        ...
    }
    """
    transfer_reactions = member_reactions.get(transfer_source, None)
    assert transfer_reactions is not None
    acc = {}
    for index, node_id in enumerate(transfer_reactions):
        acc[index] = []
        # TODO: Deal with this hard-coded key from pynite_tools
        loads_by_dir = transfer_reactions[node_id]
        analysis_dirs = distributed_direction_mapping[model_direction]
        for analysis_dir in analysis_dirs:
            # HACK: To Fix
            load_cases = loads_by_dir.get(analysis_dir, None)
            if load_cases is None:
                load_cases = loads_by_dir.get(analysis_dir.title(), None)
            if load_cases is None:
                raise ReactionNotFoundError(f"{transfer_reactions=}")
            # print(f'{load_cases=}')
            if isinstance(load_cases, dict):
                for case_name, load in load_cases.items():
                    if isinstance(load, list):
                        # print(f'load from wall {case_name=} {load=}')
                        # print(f'{dist_load=}')
                        # Load from a wall
                        for subload in load:
                            sm = subload["start_magnitude"]
                            em = subload["end_magnitude"]
                            # only invert when positive to avoid double-negation
                            start_mag_neg = -sm if sm > 0 else sm
                            end_mag_neg = -em if em > 0 else em
                            # determine start_loc and end_loc
                            if subload["start_loc"] <= dist_load["start_loc"]:
                                start_loc = dist_load["start_loc"]
                            else:
                                start_loc = subload["start_loc"]
                            if subload["end_loc"] >= dist_load["end_loc"]:
                                end_loc = dist_load["end_loc"]
                            else:
                                end_loc = subload["end_loc"]
                            new_dist_load = {
                                "start_magnitude": start_mag_neg,
                                "end_magnitude": end_mag_neg,
                                "start_loc": start_loc,
                                "end_loc": end_loc,
                                "case": case_name,
                                "dir": analysis_dir,
                            }
                            acc[index].append(new_dist_load)
                    else:
                        print(f'load from frame member {case_name=} {load=}')
                        # Load from a frame member (single scalar)
                        load_val = load
                        load_adj = -load_val if load_val > 0 else load_val
                        new_dist_load = {
                            "start_magnitude": load_adj * dist_load["start_magnitude"],
                            "end_magnitude": load_adj * dist_load["end_magnitude"],
                            "start_loc": dist_load["start_loc"],
                            "end_loc": dist_load["end_loc"],
                            "case": case_name,
                            "dir": analysis_dir,
                        }
                        acc[index].append(new_dist_load)
            elif isinstance(load_cases, list):
                # print(f'load from loadbearing wall {load_cases=}')
                # When the member is a loadbearing_wall and has a list of reactions
                for case_dist_load in load_cases:
                    new_dist_load = copy(case_dist_load)
                    # Should have all other required keys
                    # Need to update direction with analysis dir
                    new_dist_load.update({"dir": analysis_dir})
                    acc[index].append(new_dist_load)
    return acc
