"""
Conversion of joist point loads into distributed loads.

A joist array from papermodels (e.g. "J1.0") is analysed as one member per joist
("J1.0-0", "J1.0-1", ...), so the members that support the array receive one
point load per joist. That is the most accurate representation, but it is hard
to compare against hand calculations, which use a line load (or an occupancy
over a trib width). This module replaces the point loads of each joist array on
a member with an equivalent distributed load.

For each run of joists and each load case, the joist reactions P_i are divided
by the width that each joist carries (half the distance to its neighbours) to
get line load intensities w_i. The profile of the intensities along the run
decides the shape of the distributed load:

- "uniform": a uniform load (UDL)
- "increasing" / "decreasing": a trapezoidal load fitted through the intensities
- "variable": a UDL, with a JoistLoadVariabilityWarning when the largest
    intensity is 'variability_ratio' (default 2) or more times the smallest

In every case the total of the distributed load equals the total of the joist
reactions it replaces.
"""

from __future__ import annotations

import math
import statistics
import warnings
from collections import defaultdict
from typing import Optional

from .errors import LoadTracerWarning

UNIFORM = "uniform"
INCREASING = "increasing"
DECREASING = "decreasing"
VARIABLE = "variable"


class JoistLoadVariabilityWarning(LoadTracerWarning):
    """
    The joist reactions of an array vary so much that the uniform load that
    replaces them may not be representative.
    """


class JoistTribWidthWarning(LoadTracerWarning):
    """
    The trib width view of a converted joist load is approximate (the joists
    carry more than one occupancy or loads other than occupancy loads).
    """


def split_joist_tag(tag: str) -> Optional[tuple[str, int]]:
    """
    Returns (parent, index) for the tag of a joist in a joist array
    (e.g. "J1.0-3" -> ("J1.0", 3)) or None if 'tag' is not a joist tag.
    """
    parent, sep, index = tag.rpartition("-")
    if sep and parent and index.isdigit():
        return parent, int(index)
    return None


def group_joist_point_loads(
    point_loads: list[dict], gap_factor: float = 1.5, min_joists: int = 2
) -> list[list[dict]]:
    """
    Returns runs of point loads from joist arrays. Each run is a list of point
    loads from the same joist array (and in the same direction), sorted by
    location, with no gap between neighbours of more than 'gap_factor' times
    the median joist spacing of the array. Runs with fewer than 'min_joists'
    point loads are not returned.

    Joists at the same location are left as point loads by
    convert_joist_point_loads. Only point loads that have been expanded (their source reactions were found)
    are included. Point loads from members that are not joists are ignored.
    """
    by_array = defaultdict(list)
    for point_load in point_loads:
        joist = split_joist_tag(point_load.get("transfer_source") or "")
        if joist is None or "expanded" not in point_load:
            continue
        by_array[(joist[0], point_load.get("direction", "gravity"))].append(point_load)

    runs = []
    for loads in by_array.values():
        loads.sort(key=lambda load: load["location"])
        spacings = [b["location"] - a["location"] for a, b in zip(loads, loads[1:])]
        max_gap = gap_factor * statistics.median(spacings) if spacings else 0.0
        run = loads[:1]
        for spacing, load in zip(spacings, loads[1:]):
            if max_gap > 0 and spacing > max_gap:
                runs.append(run)
                run = []
            run.append(load)
        runs.append(run)
    return [run for run in runs if len(run) >= min_joists]


def trib_widths(locations: list[float]) -> list[float]:
    """
    Returns the width carried by each joist at 'locations' (sorted): half of
    the distance to each neighbour. The widths add up to the length of the run.
    """
    midpoints = [(a + b) / 2 for a, b in zip(locations, locations[1:])]
    bounds = [locations[0]] + midpoints + [locations[-1]]
    return [b - a for a, b in zip(bounds, bounds[1:])]


def classify_profile(intensities: list[float], rel_tol: float = 0.10) -> str:
    """
    Returns one of "uniform", "increasing", "decreasing" or "variable" for the
    line load 'intensities' along a joist run (in order of location).

    'rel_tol' is relative to the load: the intensities are divided by their
    mean magnitude before they are compared, so the result does not depend on
    the units or the size of the load.

    - "uniform": the normalized intensities vary by no more than 'rel_tol'
    - "increasing": no step down of more than 'rel_tol' and a rise of more than
        'rel_tol' from the first to the last
    - "decreasing": the mirror of "increasing"
    - "variable": anything else, including loads that change sign
    """
    scale = statistics.fmean(abs(w) for w in intensities)
    if math.isclose(scale, 0.0, abs_tol=1e-12):
        return UNIFORM
    if any(w > 0 for w in intensities) and any(w < 0 for w in intensities):
        return VARIABLE
    normalized = [abs(w) / scale for w in intensities]
    if max(normalized) - min(normalized) <= rel_tol:
        return UNIFORM
    steps = [b - a for a, b in zip(normalized, normalized[1:])]
    rise = normalized[-1] - normalized[0]
    if all(step >= -rel_tol for step in steps) and rise > rel_tol:
        return INCREASING
    if all(step <= rel_tol for step in steps) and -rise > rel_tol:
        return DECREASING
    return VARIABLE


def max_min_ratio(intensities: list[float]) -> float:
    """
    Returns the ratio of the largest to the smallest intensity magnitude
    (infinity when the smallest is zero, 1.0 when all are zero).
    """
    magnitudes = [abs(w) for w in intensities]
    if max(magnitudes) == 0.0:
        return 1.0
    if min(magnitudes) == 0.0:
        return math.inf
    return max(magnitudes) / min(magnitudes)


def fit_trapezoid(
    locations: list[float], intensities: list[float], total: float
) -> tuple[float, float]:
    """
    Returns the (start, end) intensities of a trapezoidal load over
    locations[0] to locations[-1] whose resultant is 'total'. The slope comes
    from a least squares line through the intensities; both ends are then
    scaled so that the resultant is exactly 'total'. An end that would have
    the opposite sign of 'total' is set to zero.
    """
    length = locations[-1] - locations[0]
    x_mean = statistics.fmean(locations)
    w_mean = statistics.fmean(intensities)
    sxx = sum((x - x_mean) ** 2 for x in locations)
    slope = (
        sum((x - x_mean) * (w - w_mean) for x, w in zip(locations, intensities)) / sxx
    )
    w_start = w_mean + slope * (locations[0] - x_mean)
    w_end = w_mean + slope * (locations[-1] - x_mean)
    resultant = (w_start + w_end) / 2 * length
    if math.isclose(resultant, 0.0, abs_tol=1e-12):
        return total / length, total / length
    factor = total / resultant
    w_start, w_end = w_start * factor, w_end * factor
    if w_start * total < 0:
        w_start, w_end = 0.0, 2 * total / length
    elif w_end * total < 0:
        w_start, w_end = 2 * total / length, 0.0
    return w_start, w_end


def convert_joist_point_loads(
    pm: dict,
    joist_pms: Optional[dict] = None,
    occupancies: Optional[dict] = None,
    rel_tol: float = 0.10,
    variability_ratio: float = 2.0,
    min_joists: int = 2,
) -> dict:
    """
    Returns 'pm' (an expanded papermodel) with the point loads from each run of
    joists (see group_joist_point_loads) replaced by one distributed load.
    'pm' is mutated. The replaced point loads are kept in
    pm["loads"]["converted_point_loads"].

    The distributed load has the usual keys of a transfer load (its
    'transfer_source' is the joist array) and:
        "converted_from": the tags of the joists
        "trib_view": {case: {...}} the load as an occupancy over a trib width
            (see trib_view)
    Each of its "expanded" components also has:
        "profile": the profile of the joist reactions (see classify_profile)
        "point_load_total": the total of the joist reactions it replaces
        "max_min_ratio": the ratio of the largest to the smallest intensity

    'joist_pms': The expanded papermodels of the joists, keyed by tag. Used for
        the trib width view.
    'occupancies': The occupancies of the load rundown. Used for the trib width view.
    'rel_tol': The relative tolerance for classify_profile
    'variability_ratio': A "variable" profile whose max/min intensity ratio is
        this or more raises a JoistLoadVariabilityWarning
    """
    tag = pm["element_attributes"]["tag"]
    runs = group_joist_point_loads(pm["loads"]["point_loads"], min_joists=min_joists)
    converted_ids = set()
    new_dist_loads = []
    for run in runs:
        if min(trib_widths([load["location"] for load in run])) <= 0:
            # Joists at the same location: there is no width to spread them over
            continue
        dist_load = _convert_run(
            run, tag, joist_pms or {}, occupancies or {}, rel_tol, variability_ratio
        )
        new_dist_loads.append(dist_load)
        converted_ids.update(id(load) for load in run)

    if converted_ids:
        point_loads = pm["loads"]["point_loads"]
        pm["loads"]["converted_point_loads"] = [
            load for load in point_loads if id(load) in converted_ids
        ]
        pm["loads"]["point_loads"] = [
            load for load in point_loads if id(load) not in converted_ids
        ]
        pm["loads"]["distributed_loads"].extend(new_dist_loads)
    return pm


def _convert_run(
    run: list[dict],
    tag: str,
    joist_pms: dict,
    occupancies: dict,
    rel_tol: float,
    variability_ratio: float,
) -> dict:
    locations = [load["location"] for load in run]
    widths = trib_widths(locations)
    joist_tags = [load["transfer_source"] for load in run]
    parent = split_joist_tag(joist_tags[0])[0]

    magnitudes = defaultdict(lambda: [0.0] * len(run))
    for idx, load in enumerate(run):
        for component in load["expanded"]:
            magnitudes[(component["case"], component["dir"])][idx] += component["magnitude"]

    components = []
    for (case, direction), loads in magnitudes.items():
        intensities = [p / w for p, w in zip(loads, widths)]
        total = sum(loads)
        profile = classify_profile(intensities, rel_tol)
        ratio = max_min_ratio(intensities)
        if profile in (INCREASING, DECREASING):
            w_start, w_end = fit_trapezoid(locations, intensities, total)
        else:
            w_start = w_end = total / (locations[-1] - locations[0])
        if profile == VARIABLE and ratio >= variability_ratio:
            warnings.warn(
                f"Member {tag}: the reactions of joist array {parent} ({case}) vary by "
                f"{ratio:.1f}:1 along {locations[0]} to {locations[-1]}; they were "
                "converted to a uniform load. Review the joist loads.",
                JoistLoadVariabilityWarning,
                stacklevel=3,
            )
        components.append(
            {
                "start_magnitude": w_start,
                "end_magnitude": w_end,
                "start_loc": locations[0],
                "end_loc": locations[-1],
                "case": case,
                "dir": direction,
                "profile": profile,
                "point_load_total": total,
                "max_min_ratio": ratio,
            }
        )

    indexes = {load.get("transfer_reaction_index") for load in run}
    return {
        "transfer_source": parent,
        "transfer_reaction_index": indexes.pop() if len(indexes) == 1 else None,
        "transfer_source_start_extent": [],
        "transfer_source_end_extent": [],
        "occupancy": "",
        "load_components": {},
        "applied_area": 0.0,
        "start_loc": locations[0],
        "start_magnitude": 1.0,
        "end_loc": locations[-1],
        "end_magnitude": 1.0,
        "direction": run[0].get("direction", "gravity"),
        "converted_from": joist_tags,
        "trib_view": trib_view(components, joist_tags, joist_pms, occupancies, tag, parent),
        "expanded": components,
    }


def trib_view(
    components: list[dict],
    joist_tags: list[str],
    joist_pms: dict,
    occupancies: dict,
    tag: str,
    parent: str,
) -> dict:
    """
    Returns the converted load 'components' as an occupancy pressure over a
    trib width, keyed by load case:

        {case: {"occupancy", "pressure", "trib_width_start", "trib_width_end",
                "approximate"}}

    The occupancy is the one with the most applied area on the joists. The
    trib widths are the line load divided by the pressure of that occupancy.
    They are exact when the joists carry only that occupancy; otherwise
    "approximate" is True (and a JoistTribWidthWarning is raised).
    """
    area_by_occupancy = defaultdict(float)
    has_other_loads = False
    for joist_tag in joist_tags:
        joist_pm = joist_pms.get(joist_tag)
        if joist_pm is None:
            continue
        for load in joist_pm["loads"]["distributed_loads"] + joist_pm["loads"]["point_loads"]:
            if load.get("occupancy"):
                area_by_occupancy[load["occupancy"]] += load.get("applied_area", 0.0)
            elif load.get("transfer_source") and load.get("expanded"):
                # A load transferred onto the joists (e.g. from a post)
                has_other_loads = True
    if not area_by_occupancy:
        return {}
    occupancy = max(area_by_occupancy, key=area_by_occupancy.get)
    approximate = len(area_by_occupancy) > 1 or has_other_loads
    if approximate:
        carried = sorted(area_by_occupancy) + (["transfer loads"] if has_other_loads else [])
        warnings.warn(
            f"Member {tag}: joist array {parent} carries {', '.join(carried)}; its "
            f"trib widths are expressed with {occupancy!r} and are approximate.",
            JoistTribWidthWarning,
            stacklevel=4,
        )

    view = {}
    for component in components:
        pressure = occupancies.get(occupancy, {}).get(component["case"])
        if not pressure:
            continue
        view[component["case"]] = {
            "occupancy": occupancy,
            "pressure": pressure,
            "trib_width_start": abs(component["start_magnitude"]) / pressure,
            "trib_width_end": abs(component["end_magnitude"]) / pressure,
            "approximate": approximate,
        }
    return view
