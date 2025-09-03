from typing import Optional, Union, Any
from copy import deepcopy
import jsonchain

def expand_reaction_loads(
    member_model: dict,
    node_reactions: dict,
    distributed_direction_mapping: dict,
    point_direction_mapping: dict,
) -> dict:
    """
    Returns a copy of 'member_model' with all reaction load transfers
    replaced by their load components as described in the 'reactions'
    dict.

    'member_model': A member dictionary as output from papermodels
        The member dictionary may have point or distributed loads with
        occupancy values assigned. If no occupancy values are assigned
        then no changes occur to the member model.
    'node_reactions': a dictionary of nodal reactions from a member analysis
        The order of node reactions is assumed to be in geometric order
        (i.e. order of appearance in local x-ordinates). Therefore the names
        of each node should be irrelevant to the mapping since they will
        be assigned by numerical index.
        e.g. 
        {
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
        }

    'distributed_direction_mapping' / 'point_direction_mapping': 
        A dictionary mapping of the names of the load directions
        from papermodels (i.e. 'gravity', 'inplane', 'out_of_plane')
        and the reaction directions they should map from the node reactions.

        The mapping value can be either a single string or a list of values, e.g.

        {'gravity': "FY"} - This will only apply the FY reaction load components 
            from the node_reactions. If this dictionary is passed as a distributed
            direction mapping, then the FY value will be applied as both the 
            'start_magnitude' and 'end_magnitude' value of a distributed load.
            If it is for a point load mapping, then it will apply to the magnitude

        {'gravity': ["FY", "MZ"]} - This will apply both the FY and MZ reaction
        components as node reactions. If this is passed as a distributed direction
        mapping, a distributed moment load would be created in addition to a distributed
        'FY' load.
    """
    new_model = deepcopy(member_model)
    new_model['loads']['point_loads'] = []
    new_point_loads = new_model['loads']['point_loads']
    for point_load in member_model['loads']['point_loads']:
    ...