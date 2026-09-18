"""
Validation and normalization of papermodel dicts.

Two passes are applied to every member during a load rundown:

1. validate_papermodel: checks the shape of the papermodel as output by
    papermodels.LoadedElement.model() (before any loads are expanded) and
    normalizes the values that papermodels is known to produce loosely
    (unsorted supports, list-valued point load locations on columns,
    distributed loads without extents).

2. conform_loads_to_member: after the loads have been expanded into their
    load case components, keeps every load component on the member so that
    the analysis model can be built. Load that falls outside of the member
    is moved to the nearest member end as a point load so that the total
    load on the member is unchanged.

Both return the list of issues they found so that the designer can review them.
"""

from copy import deepcopy
from typing import Optional

from .errors import InvalidPapermodelError

ORIENTATIONS = ("horizontal", "vertical")
REACTION_TYPES = ("point", "linear")
DEFAULT_DIRECTIONS = frozenset({"gravity", "inplane", "out_of_plane"})


def validate_papermodel(
    pm: dict,
    tol: float = 1e-3,
    directions: frozenset[str] = DEFAULT_DIRECTIONS,
) -> tuple[dict, list[str]]:
    """
    Returns a normalized copy of 'pm' and a list of issues found.
    Raises InvalidPapermodelError if 'pm' cannot be used.

    'pm': A papermodel dict for a single member
    'tol': Supports off the member are moved onto the nearest member end (and
        reported as an issue when they are more than 'tol' off). Supports within
        'tol' of each other are flagged as coincident.
    'directions': The load directions that are recognized (the keys of the
        direction mappings on the LoadTracer).
    """
    match pm:
        case {
            "element_attributes": {"tag": str(tag)} as attrs,
            "element_geometry": dict(geometry),
            "loads": {"point_loads": list(), "distributed_loads": list()},
        }:
            pass
        case {"element_attributes": {"tag": tag}}:
            raise InvalidPapermodelError(
                "The papermodel must have 'element_attributes', 'element_geometry' and "
                "'loads' (with 'point_loads' and 'distributed_loads' lists).",
                tag,
            )
        case _:
            raise InvalidPapermodelError(
                "The papermodel has no 'element_attributes' with a 'tag'."
            )

    match attrs:
        case {
            "orientation": "horizontal" | "vertical" as orientation,
            "reaction_type": "point" | "linear" as reaction_type,
        }:
            pass
        case _:
            raise InvalidPapermodelError(
                f"Unsupported orientation/reaction type: "
                f"{attrs.get('orientation')!r}/{attrs.get('reaction_type')!r}. "
                f"Expected one of {ORIENTATIONS} and one of {REACTION_TYPES}.",
                tag,
            )

    pm = deepcopy(pm)
    issues = []
    is_column = orientation == "vertical" and reaction_type == "point"
    length = None
    if not is_column:
        match attrs.get("length"):
            case int() | float() as length if length > 0:
                length = float(length)
            case other:
                raise InvalidPapermodelError(
                    f"A {orientation} member with a {reaction_type} reaction needs a "
                    f"positive 'length', not {other!r}.",
                    tag,
                )

    if orientation == "horizontal":
        pm["element_geometry"]["supports"] = _normalize_supports(
            geometry.get("supports", []), length, tol, tag, issues
        )

    for point_load in pm["loads"]["point_loads"]:
        _check_direction(point_load, directions, tag)
        match point_load:
            case {"location": int() | float()}:
                pass
            case {"location": list()} if is_column:
                # papermodels gives columns a list of the transfer locations of
                # the elements above. A concentric column does not use them.
                point_load["location"] = 0.0
            case {"location": [int() | float() as location]}:
                point_load["location"] = location
            case {"location": list() as locations}:
                raise InvalidPapermodelError(
                    f"The point load from {point_load.get('transfer_source')!r} has "
                    f"{len(locations)} locations; expected one.",
                    tag,
                )
            case _:
                raise InvalidPapermodelError(
                    f"A point load has no numeric 'location': {point_load!r}", tag
                )

    for dist_load in pm["loads"]["distributed_loads"]:
        _check_direction(dist_load, directions, tag)
        match dist_load:
            case {"start_loc": int() | float(), "end_loc": int() | float()}:
                pass
            case {"start_loc": [], "end_loc": []} if length is not None:
                # papermodels could not calculate the extents of a linear
                # correspondent (e.g. a wall on a wall); apply it over the full length
                dist_load["start_loc"] = 0.0
                dist_load["end_loc"] = length
                issues.append(
                    f"The distributed load from {dist_load.get('transfer_source')!r} "
                    "has no extents; it was applied over the full length."
                )
            case _:
                raise InvalidPapermodelError(
                    "A distributed load has no numeric 'start_loc'/'end_loc': "
                    f"{dist_load!r}",
                    tag,
                )
    return pm, issues


def _check_direction(load: dict, directions: frozenset[str], tag: str) -> None:
    match load.get("direction", "gravity"):
        case str(direction) if direction in directions:
            pass
        case direction:
            raise InvalidPapermodelError(
                f"Unknown load direction {direction!r}. Known directions: "
                f"{sorted(directions)}",
                tag,
            )


def _normalize_supports(
    supports: list, length: float, tol: float, tag: str, issues: list[str]
) -> list[dict]:
    """
    Returns 'supports' sorted by location with locations near the member ends
    moved onto the ends and coincident supports flagged with "coincident".
    """
    acc = []
    for support in supports:
        match support:
            case {"location": int() | float() as location}:
                pass
            case _:
                raise InvalidPapermodelError(
                    f"A support has no numeric 'location': {support!r}", tag
                )
        clamped = min(max(float(location), 0.0), length)
        if abs(clamped - location) > tol:
            issues.append(
                f"The support at {location} is off the member (length {length}); "
                f"it was moved to {clamped}."
            )
        acc.append(dict(support, location=clamped))
    acc.sort(key=lambda s: s["location"])

    # A coincident support is kept (so that reaction indexes still line up with
    # papermodels' transfer_reaction_index) but flagged: it is not modelled and
    # the reaction at that location is reported on the first support.
    for prev, support in zip(acc, acc[1:]):
        if support["location"] - prev["location"] <= tol:
            support["coincident"] = True
            issues.append(
                f"Supports at {prev['location']} and {support['location']} coincide; "
                "the reaction is reported on the first of them."
            )
    return acc


def conform_loads_to_member(pm: dict, tol: float = 1e-3) -> list[str]:
    """
    Returns a list of issues. Mutates the expanded load components of 'pm'
    (a papermodel with expanded loads) so that every component is on the member:

    - Distributed load components with no length are removed.
    - Distributed load components are clipped to the member. The load on the
        clipped-off portion is added as a point load at the nearest member end.
    - Point load components off the member are moved onto the nearest end.

    Members with no length (point columns) are not changed.
    """
    attrs = pm["element_attributes"]
    tag = attrs["tag"]
    length = attrs.get("length")
    if attrs["orientation"] == "vertical" and attrs["reaction_type"] == "point":
        return []
    issues = []

    end_point_loads = []
    for dist_load in pm["loads"]["distributed_loads"]:
        kept = []
        for component in dist_load.get("expanded", []):
            inside, outside = _clip_dist_component(component, length)
            if inside is not None:
                kept.append(inside)
            for point_component, overhang in outside:
                end_point_loads.append(
                    {
                        "transfer_source": dist_load.get("transfer_source", ""),
                        "location": point_component["location"],
                        "direction": dist_load.get("direction", "gravity"),
                        "from_clipped_distributed_load": True,
                        "expanded": [point_component],
                    }
                )
                if overhang > tol:
                    issues.append(
                        f"{overhang:.3f} of the distributed load from "
                        f"{dist_load.get('transfer_source') or 'an occupancy'} "
                        f"({component['case']}) extends past the member end at "
                        f"{point_component['location']}; its load was applied as a "
                        "point load at the end."
                    )
        if "expanded" in dist_load:
            dist_load["expanded"] = kept
    pm["loads"]["point_loads"].extend(end_point_loads)

    for point_load in pm["loads"]["point_loads"]:
        for component in point_load.get("expanded", []):
            location = component["location"]
            clamped = min(max(location, 0.0), length)
            if clamped != location:
                component["location"] = clamped
                if abs(clamped - location) > tol:
                    issues.append(
                        f"The point load from {point_load.get('transfer_source')!r} at "
                        f"{location} is off the member; it was moved to {clamped}."
                    )
    return issues


def _clip_dist_component(
    component: dict, length: float
) -> tuple[Optional[dict], list[tuple[dict, float]]]:
    """
    Returns the part of the distributed load 'component' that lies on
    [0, length] (or None) and a list of (point_component, overhang_length)
    for the parts that lie off of it, as resultants at the nearest member end.
    """
    x1, x2 = component["start_loc"], component["end_loc"]
    w1, w2 = component["start_magnitude"], component["end_magnitude"]
    if x2 - x1 <= 0.0:
        return None, []

    def w(x: float) -> float:
        return w1 + (w2 - w1) * (x - x1) / (x2 - x1)

    def resultant(a: float, b: float) -> float:
        return (w(a) + w(b)) / 2 * (b - a)

    outside = []
    for a, b, end in ((x1, min(x2, 0.0), 0.0), (max(x1, length), x2, length)):
        if b > a:
            point_component = {
                "magnitude": resultant(a, b),
                "location": end,
                "case": component["case"],
                "dir": component["dir"],
            }
            outside.append((point_component, b - a))

    a, b = max(x1, 0.0), min(x2, length)
    inside = None
    if b > a:
        inside = dict(
            component,
            start_loc=a,
            end_loc=b,
            start_magnitude=w(a),
            end_magnitude=w(b),
        )
    return inside, outside
