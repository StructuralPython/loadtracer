from typing import Optional
from copy import deepcopy

from .errors import ReactionNotFoundError, InvalidPapermodelError

MISSING_REACTIONS_OPTIONS = ("raise", "ignore")


def expand_reaction_loads(
    member_model: dict,
    member_reactions: dict,
    distributed_direction_mapping: dict,
    point_direction_mapping: dict,
    missing_reactions: str = "raise",
    exclude_members: Optional[list[str]] = None,
) -> tuple[dict, dict]:
    """
    Returns a tuple of a copy of 'member_model' with the "expanded" load components
    of every transfer load populated from the reactions of its source member, and
    a dict of the reactions that were ignored (keyed by the tag of 'member_model',
    only populated when 'missing_reactions' is "ignore").

    Loads without a 'transfer_source' (e.g. occupancy loads) are copied unchanged.

    'member_model': A member dictionary as output from papermodels
    'member_reactions': a dictionary of the reactions of the members analysed
        so far, keyed by member tag and then by support index. The support
        indexes match the 'transfer_reaction_index' of the transfer loads.
        Reactions are the forces on the supports so the load components have
        the opposite sign.
        e.g.
        {
            'member_name': {
                0: {'FY': {'D': -12.3, 'L': -14.5}, 'FX': {...}, ...},
                1: {'FY': {'D': -43.2, 'L': -34.2}, 'FX': {...}, ...},
            },
            'wall_name': {
                0: {'FY': {'D': [dist_load, ...], 'L': [dist_load, ...]}},
            },
        }
        A support with no reaction in a direction or load case (e.g. a member
        with no loads) contributes no load components.
    'distributed_direction_mapping' / 'point_direction_mapping':
        A dictionary mapping the names of the load directions from papermodels
        (i.e. 'gravity', 'inplane', 'out_of_plane') to the list of reaction
        directions to apply from the source reactions.
        e.g. {'gravity': ["FY"]} or {'gravity': ["FY", "MZ"]}
    'missing_reactions': one of either 'raise' or 'ignore'. The reactions of a
        source member are missing when the source was not analysed (or failed)
        or does not have the 'transfer_reaction_index'.
    'exclude_members': Transfer loads from these members (or from the
        sub-elements of these members, e.g. "J1.0-3" for "J1.0") are removed.
    """
    if missing_reactions not in MISSING_REACTIONS_OPTIONS:
        raise ValueError(
            f"missing_reactions must be one of {MISSING_REACTIONS_OPTIONS}, "
            f"not {missing_reactions!r}"
        )
    tag = member_model["element_attributes"]["tag"]
    exclude_members = set(exclude_members or [])
    ignored_reactions = {}
    new_model = deepcopy(member_model)

    for load_type, direction_mapping, expand in (
        ("point_loads", point_direction_mapping, expand_point_reactions),
        ("distributed_loads", distributed_direction_mapping, expand_distributed_reactions),
    ):
        new_loads = []
        for load in new_model["loads"][load_type]:
            transfer_source = load.get("transfer_source") or None
            if transfer_source is None:
                new_loads.append(load)
                continue
            if is_excluded(transfer_source, exclude_members):
                continue
            reaction = get_indexed_reaction(
                member_reactions, transfer_source, load.get("transfer_reaction_index")
            )
            if reaction is None:
                if missing_reactions == "raise":
                    raise ReactionNotFoundError(
                        f"No reactions were found for {transfer_source} (reaction index "
                        f"{load.get('transfer_reaction_index')!r}).",
                        tag,
                    )
                ignored_reactions.setdefault(tag, []).append(transfer_source)
                new_loads.append(load)
                continue
            model_direction = load.get("direction", "gravity")
            load.setdefault("expanded", [])
            for analysis_dir in direction_mapping[model_direction]:
                load_cases = reaction.get(analysis_dir, {})
                load["expanded"].extend(expand(load, load_cases, analysis_dir, tag))
            new_loads.append(load)
        new_model["loads"][load_type] = new_loads
    return new_model, ignored_reactions


def is_excluded(transfer_source: str, exclude_members: set[str]) -> bool:
    """
    Returns True if 'transfer_source' or its parent element (the part of a
    sub-element tag before the last "-", e.g. "J1.0" of "J1.0-3") is in
    'exclude_members'.
    """
    parent, sep, index = transfer_source.rpartition("-")
    return transfer_source in exclude_members or (
        bool(sep) and index.isdigit() and parent in exclude_members
    )


def get_indexed_reaction(
    member_reactions: dict, transfer_source: str, transfer_index
) -> Optional[dict]:
    """
    Returns the reactions of 'transfer_source' at 'transfer_index' or None if
    they are not available. A missing 'transfer_index' ("" or None) means the
    first reaction.
    """
    source_reactions = member_reactions.get(transfer_source)
    if source_reactions is None:
        return None
    match transfer_index:
        case None | "":
            transfer_index = 0
        case int():
            pass
        case str() if transfer_index.isdigit():
            transfer_index = int(transfer_index)
        case _:
            return None
    return source_reactions.get(transfer_index)


def expand_point_reactions(
    point_load: dict, load_cases: dict, analysis_dir: str, tag: str
) -> list[dict]:
    """
    Returns a list of point load components (one per load case) at the location
    of 'point_load' for the reactions in 'load_cases' ({case: reaction}).

    Example output:

    [
        {"magnitude": 12.3, "location": 2.5, "case": "D", "dir": "FY"},
        {"magnitude": 14.5, "location": 2.5, "case": "L", "dir": "FY"},
    ]
    """
    acc = []
    for case_name, reaction in load_cases.items():
        match reaction:
            case int() | float():
                # From a frame member or a column
                magnitude = -reaction
            case list():
                # From a wall: the resultant of its distributed reactions
                magnitude = -sum(
                    (r["start_magnitude"] + r["end_magnitude"])
                    / 2
                    * (r["end_loc"] - r["start_loc"])
                    for r in reaction
                )
            case _:
                raise InvalidPapermodelError(
                    f"Unrecognized reaction from {point_load['transfer_source']}: "
                    f"{reaction!r}",
                    tag,
                )
        acc.append(
            {
                "magnitude": magnitude,
                "location": point_load["location"],
                "case": case_name,
                "dir": analysis_dir,
            }
        )
    return acc


def expand_distributed_reactions(
    dist_load: dict, load_cases: dict, analysis_dir: str, tag: str
) -> list[dict]:
    """
    Returns a list of distributed load components for the reactions in
    'load_cases' ({case: reaction}) applied over the extents of 'dist_load'.

    A reaction from a frame member with a linear reaction (a force per unit
    length) is applied over the extents of 'dist_load', scaled by its
    magnitudes. A reaction from a wall (a list of distributed loads along the
    wall) is mapped onto the member with map_wall_reaction.

    Example output:

    [
        {
            "start_magnitude": 1.2,
            "end_magnitude": 1.2,
            "start_loc": 0.0,
            "end_loc": 4.5,
            "case": "D",
            "dir": "FY",
        },
        ...
    ]
    """
    acc = []
    for case_name, reaction in load_cases.items():
        match reaction:
            case int() | float():
                acc.append(
                    {
                        "start_magnitude": -reaction * dist_load["start_magnitude"],
                        "end_magnitude": -reaction * dist_load["end_magnitude"],
                        "start_loc": dist_load["start_loc"],
                        "end_loc": dist_load["end_loc"],
                        "case": case_name,
                        "dir": analysis_dir,
                    }
                )
            case list():
                acc.extend(
                    map_wall_reaction(dist_load, reaction, case_name, analysis_dir)
                )
            case _:
                raise InvalidPapermodelError(
                    f"Unrecognized reaction from {dist_load['transfer_source']}: "
                    f"{reaction!r}",
                    tag,
                )
    return acc


def map_wall_reaction(
    dist_load: dict, wall_reaction: list[dict], case_name: str, analysis_dir: str
) -> list[dict]:
    """
    Returns the load components on the receiving member from the distributed
    reactions of a wall ('wall_reaction', in the wall's local coordinates).

    The 'transfer_source_start_extent' to 'transfer_source_end_extent' of
    'dist_load' (the part of the wall that is over the receiving member) is
    mapped onto its 'start_loc' to 'end_loc'. When the two lengths differ (e.g.
    from rounding in the drawing) the magnitudes are scaled so that the force
    is unchanged.

    The reaction taken from the wall is the part within the
    'transfer_source_cell' of 'dist_load' (see assign_wall_transfer_cells) so
    that the parts of the wall that are not over any member (e.g. a wall that
    is longer than the wall below it) are not lost. Those parts map to just
    beyond 'start_loc'/'end_loc'. When 'dist_load' has no source extents, the
    whole wall bears on the member starting at 'start_loc'.
    """
    t0, t1 = dist_load["start_loc"], dist_load["end_loc"]
    match (
        dist_load.get("transfer_source_start_extent"),
        dist_load.get("transfer_source_end_extent"),
    ):
        case (int() | float() as s0, int() | float() as s1) if s1 > s0:
            scale = (t1 - t0) / (s1 - s0)
            c0, c1 = dist_load.get("transfer_source_cell", (s0, s1))
        case _:
            s0, scale = 0.0, 1.0
            c0, c1 = float("-inf"), float("inf")

    acc = []
    for subload in wall_reaction:
        x1, x2 = subload["start_loc"], subload["end_loc"]
        a, b = max(x1, c0), min(x2, c1)
        if b <= a:
            continue
        w1, w2 = subload["start_magnitude"], subload["end_magnitude"]
        wa = w1 + (w2 - w1) * (a - x1) / (x2 - x1)
        wb = w1 + (w2 - w1) * (b - x1) / (x2 - x1)
        acc.append(
            {
                "start_magnitude": -wa * dist_load["start_magnitude"] / scale,
                "end_magnitude": -wb * dist_load["end_magnitude"] / scale,
                "start_loc": t0 + (a - s0) * scale,
                "end_loc": t0 + (b - s0) * scale,
                "case": case_name,
                "dir": analysis_dir,
            }
        )
    return acc


def assign_wall_transfer_cells(papermodels: dict[str, dict]) -> dict[str, list[str]]:
    """
    Returns a dict of issues keyed by the tag of the wall they concern.
    Mutates the distributed loads in 'papermodels' ({tag: papermodel}) whose
    transfer source is a wall by adding a "transfer_source_cell": [start, end].

    The length of each wall is divided into one cell per load that it transfers
    (in the order of the loads' source extents): the first cell has no start,
    the last cell has no end and the gap between two adjacent source extents
    is divided at its midpoint. The whole
    reaction of the wall is then transferred exactly once.

    Source extents that overlap mean that more than one member supports the
    same part of the wall. How the load divides between them depends on their
    stiffness, which is not known, so the overlapping part is transferred to
    each of them and an issue is reported.
    """
    walls = {
        tag
        for tag, pm in papermodels.items()
        if pm["element_attributes"].get("orientation") == "vertical"
        and pm["element_attributes"].get("reaction_type") == "linear"
    }
    loads_by_wall = {}
    for receiver, pm in papermodels.items():
        for dist_load in pm["loads"]["distributed_loads"]:
            source = dist_load.get("transfer_source")
            match (
                dist_load.get("transfer_source_start_extent"),
                dist_load.get("transfer_source_end_extent"),
            ):
                case (int() | float() as s0, int() | float() as s1) if (
                    source in walls and s1 > s0
                ):
                    loads_by_wall.setdefault(source, []).append((s0, s1, receiver, dist_load))

    issues = {}
    for wall, loads in loads_by_wall.items():
        loads.sort(key=lambda load: (load[0], load[1]))
        cells = [[s0, s1] for s0, s1, _, _ in loads]
        # Open-ended so that reactions beyond the ends of the wall (e.g. from the
        # minimum spread of a point load near an end) are also transferred
        cells[0][0] = float("-inf")
        cells[-1][1] = float("inf")
        for (prev, cell), (prev_load, load) in zip(
            zip(cells, cells[1:]), zip(loads, loads[1:])
        ):
            if prev_load[1] <= load[0]:
                prev[1] = cell[0] = (prev_load[1] + load[0]) / 2
            else:
                issues.setdefault(wall, []).append(
                    f"{prev_load[2]} and {load[2]} both support {wall} from "
                    f"{load[0]} to {min(prev_load[1], load[1])}; the load on that "
                    "part of the wall was applied to both."
                )
        for cell, (_, _, _, dist_load) in zip(cells, loads):
            dist_load["transfer_source_cell"] = cell
    return issues
