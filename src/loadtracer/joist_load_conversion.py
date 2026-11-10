"""
Conversion of joist point loads into distributed loads.

A joist array from papermodels (e.g. "J1.0") is analysed as one member per joist
("J1.0-0", "J1.0-1", ...), so the members that support the array receive one
point load per joist. That is the most accurate representation, but it is hard
to compare against hand calculations, which use line loads. This module
replaces the point loads of each joist array on a member with an equivalent
distributed load: a uniform load where that is accurate enough, otherwise a
piecewise-linear load (a "polyline": a chain of trapezoidal loads).

For each run of joists and each load case:

1. Each joist carries a strip of the member that runs halfway to each of its
   neighbours (to the end joist at the ends). Its intensity is its reaction
   divided by the strip width: w_i = P_i / t_i.
2. The "load shift" of a candidate distributed load is the largest difference,
   at any boundary between two strips, between the load it has applied so far
   (from the start of the run) and the joist reactions so far, as a fraction of
   the total joist reaction. It measures how far the distributed load moves load
   along the member, which is what changes moments and reactions.
3. If a uniform load over the run has a load shift of no more than
   'load_shift_limit' (default 1%), it is used.
4. Otherwise a polyline is fitted (see fit_polyline): its corners ("knots") are
   at joist locations, and are added until the average intensity on every strip
   is within 'polyline_tol' (default 2%) of the joist's intensity.
5. If the polyline's load shift is still more than 'load_shift_limit', a
   JoistLoadVariabilityWarning is raised.

In every case the total of the distributed load equals the total of the joist
reactions it replaces. A polyline's resultant is also at the same location as
theirs; a uniform load's is within the load shift limit.
"""

from __future__ import annotations

import math
import statistics
import warnings
from collections import defaultdict
from typing import Optional

import numpy as np

from .errors import LoadTracerWarning

UNIFORM = "uniform"
POLYLINE = "polyline"


class JoistLoadVariabilityWarning(LoadTracerWarning):
    """
    The distributed load that replaces the joist reactions of an array moves
    more of the load along the member than the load shift limit allows.
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


def strip_bounds(locations) -> np.ndarray:
    """
    Returns the boundaries of the strips carried by the joists at 'locations'
    (sorted): the first location, the midpoints between neighbours and the last
    location (len(locations) + 1 values).
    """
    x = np.asarray(locations, dtype=float)
    return np.concatenate([x[:1], (x[:-1] + x[1:]) / 2, x[-1:]])


def trib_widths(locations: list[float]) -> list[float]:
    """
    Returns the width carried by each joist at 'locations' (sorted): half of
    the distance to each neighbour. The widths add up to the length of the run.
    """
    return np.diff(strip_bounds(locations)).tolist()


def load_shift(strip_loads, point_loads) -> float:
    """
    Returns the load shift of a distributed load that puts 'strip_loads' on
    the joist strips, against the joist reactions 'point_loads': the largest
    difference between the two running totals at a boundary between strips,
    as a fraction of the total magnitude of the joist reactions.
    """
    point_loads = np.asarray(point_loads, dtype=float)
    scale = np.abs(point_loads).sum()
    if len(point_loads) < 2 or scale == 0.0:
        return 0.0
    running = np.cumsum(np.asarray(strip_loads, dtype=float) - point_loads)[:-1]
    return float(np.abs(running).max() / scale)


def strip_load_matrix(locations, knots: list[int]) -> np.ndarray:
    """
    Returns the matrix A (one row per joist strip, one column per knot) with
    A[i, k] = the integral over strip i of the hat function of knot k (1 at
    knot k, 0 at the other knots, linear in between). A polyline with knot
    values u puts the load A @ u on the strips.

    'knots' are indexes into 'locations' and must include the first and last.
    The integrals are exact: each one is the difference of the running
    integral of the (piecewise-linear) hat function at the strip boundaries.
    """
    x = np.asarray(locations, dtype=float)
    xk = x[knots]
    h = np.diff(xk)
    n_knots = len(knots)
    values = np.eye(n_knots)  # row j: the value of every hat function at knot j
    # Running integral of every hat function at each knot (trapezoids are exact)
    at_knots = np.vstack(
        [np.zeros(n_knots), np.cumsum((values[:-1] + values[1:]) / 2 * h[:, None], axis=0)]
    )
    bounds = strip_bounds(x)
    j = np.clip(np.searchsorted(xk, bounds, side="right") - 1, 0, n_knots - 2)
    d = (bounds - xk[j])[:, None]
    running = (
        at_knots[j]
        + values[j] * d
        + (values[j + 1] - values[j]) * d**2 / (2 * h[j][:, None])
    )
    return np.diff(running, axis=0)


def knot_load_moments(locations, knots: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """
    Returns (F, M): F[k] and M[k] are the integrals of the hat function of
    knot k and of x times it over the run. A polyline with knot values u has
    a total load F @ u and a first moment (about x = 0) M @ u.
    """
    xk = np.asarray(locations, dtype=float)[knots]
    a, b = xk[:-1], xk[1:]
    h = b - a
    F = np.zeros(len(knots))
    M = np.zeros(len(knots))
    # On [a, b] the hat of the left knot falls from 1 to 0, the right one rises
    F[:-1] += h / 2
    F[1:] += h / 2
    M[:-1] += h * (2 * a + b) / 6
    M[1:] += h * (a + 2 * b) / 6
    return F, M


def fit_knot_values(locations, point_loads, knots: list[int]) -> np.ndarray:
    """
    Returns the values at 'knots' of the polyline that best matches the joist
    reactions 'point_loads': the u that minimises

        sum_i ((A u)_i - P_i)**2 / t_i

    where (A u)_i is the load the polyline puts on strip i (see
    strip_load_matrix) and t_i is the strip width, subject to

        F @ u = sum_i P_i            (the same total)
        M @ u = sum_i x_i * P_i      (the same resultant location)

    (see knot_load_moments). The constrained least squares problem is solved
    through its KKT equations.
    """
    x = np.asarray(locations, dtype=float)
    P = np.asarray(point_loads, dtype=float)
    weight = 1 / np.diff(strip_bounds(x))
    A = strip_load_matrix(x, knots)
    F, M = knot_load_moments(x, knots)
    C = np.vstack([F, M])
    d = np.array([P.sum(), (x * P).sum()])
    n = len(knots)
    kkt = np.zeros((n + 2, n + 2))
    kkt[:n, :n] = A.T @ (A * weight[:, None])
    kkt[:n, n:] = C.T
    kkt[n:, :n] = C
    rhs = np.concatenate([A.T @ (P * weight), d])
    solution, *_ = np.linalg.lstsq(kkt, rhs, rcond=None)
    return solution[:n]


def fit_polyline(
    locations, point_loads, tol: float = 0.02
) -> tuple[list[int], np.ndarray, float]:
    """
    Returns (knots, knot_values, fit_error) of a polyline that replaces the
    joist reactions 'point_loads' at 'locations' (sorted). 'knots' are indexes
    into 'locations'.

    The fit error is the largest difference between the average intensity of
    the polyline on a joist's strip and the joist's intensity, as a fraction of
    the mean intensity magnitude. Knots are added at the worst joist, starting
    from the two end knots, until it is no more than 'tol'; then any interior
    knot that is not needed to stay within 'tol' is removed. At worst every
    joist is a knot, which matches every strip load exactly.
    """
    x = np.asarray(locations, dtype=float)
    P = np.asarray(point_loads, dtype=float)
    widths = np.diff(strip_bounds(x))
    w = P / widths
    scale = np.abs(w).mean()

    def fit(knots):
        u = fit_knot_values(x, P, knots)
        if scale == 0.0:
            return u, np.zeros(len(x))
        strip_w = (strip_load_matrix(x, knots) @ u) / widths
        return u, np.abs(strip_w - w) / scale

    knots = [0, len(x) - 1]
    u, errors = fit(knots)
    while errors.max() > tol and len(knots) < len(x):
        worst = next(int(i) for i in np.argsort(-errors) if i not in knots)
        knots = sorted(knots + [worst])
        u, errors = fit(knots)

    removed = True
    while removed and len(knots) > 2:
        removed = False
        trials = []
        for k in knots[1:-1]:
            trial = [j for j in knots if j != k]
            trials.append((fit(trial)[1].max(), trial))
        error, trial = min(trials, key=lambda item: item[0])
        if error <= tol:
            knots, removed = trial, True
    u, errors = fit(knots)
    return knots, u, float(errors.max())


def convert_joist_point_loads(
    pm: dict,
    joist_pms: Optional[dict] = None,
    occupancies: Optional[dict] = None,
    polyline_tol: float = 0.02,
    load_shift_limit: float = 0.01,
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
        "trib_view": {case: {...}} the occupancy and pressure that the trib
            widths of the components are based on (see trib_view)
    Its "expanded" components are the trapezoids of each load case, in order
    along the run. Each one also has:
        "profile": "uniform" or "polyline" (the shape used for its load case)
        "segment": the index of the trapezoid in its load case's polyline
        "point_load_total": the total of the joist reactions that the load
            case's components replace
        "load_shift": the load shift of the load case's components
        "fit_error": the fit error of the load case's components (see
            fit_polyline)
        "trib_width_start", "trib_width_end": the line load as a trib width of
            the occupancy in "trib_view" (None if there is no trib view)

    'joist_pms': The expanded papermodels of the joists, keyed by tag. Used for
        the trib width view.
    'occupancies': The occupancies of the load rundown. Used for the trib width view.
    'polyline_tol': The fit tolerance of the polyline (see fit_polyline)
    'load_shift_limit': A uniform load is used when its load shift is no more
        than this; a polyline whose load shift is more than this raises a
        JoistLoadVariabilityWarning
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
            run, tag, joist_pms or {}, occupancies or {}, polyline_tol, load_shift_limit
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


def _convert_case(
    locations: list[float], loads: list[float], polyline_tol: float, load_shift_limit: float
) -> tuple[str, list[tuple[float, float, float, float]], float, float]:
    """
    Returns (profile, segments, load_shift, fit_error) for the joist reactions
    'loads' of one load case. Each segment is (x1, x2, w1, w2).
    """
    x = np.asarray(locations, dtype=float)
    P = np.asarray(loads, dtype=float)
    widths = np.diff(strip_bounds(x))
    length = x[-1] - x[0]
    udl = P.sum() / length
    udl_shift = load_shift(udl * widths, P)
    if udl_shift <= load_shift_limit:
        scale = np.abs(P / widths).mean()
        error = float(np.abs(udl - P / widths).max() / scale) if scale else 0.0
        return UNIFORM, [(x[0], x[-1], udl, udl)], udl_shift, error

    knots, u, error = fit_polyline(x, P, polyline_tol)
    shift = load_shift(strip_load_matrix(x, knots) @ u, P)
    xk = x[knots]
    segments = [
        (float(xk[j]), float(xk[j + 1]), float(u[j]), float(u[j + 1]))
        for j in range(len(knots) - 1)
    ]
    return POLYLINE, segments, shift, error


def _convert_run(
    run: list[dict],
    tag: str,
    joist_pms: dict,
    occupancies: dict,
    polyline_tol: float,
    load_shift_limit: float,
) -> dict:
    locations = [load["location"] for load in run]
    joist_tags = [load["transfer_source"] for load in run]
    parent = split_joist_tag(joist_tags[0])[0]

    magnitudes = defaultdict(lambda: [0.0] * len(run))
    for idx, load in enumerate(run):
        for component in load["expanded"]:
            magnitudes[(component["case"], component["dir"])][idx] += component["magnitude"]

    components = []
    for (case, direction), loads in magnitudes.items():
        profile, segments, shift, error = _convert_case(
            locations, loads, polyline_tol, load_shift_limit
        )
        if shift > load_shift_limit:
            warnings.warn(
                f"Member {tag}: the distributed load that replaces joist array "
                f"{parent} ({case}) moves {shift:.1%} of its load along "
                f"{locations[0]} to {locations[-1]} (limit {load_shift_limit:.1%}). "
                "Review the joist loads, or use joist_loads='point'.",
                JoistLoadVariabilityWarning,
                stacklevel=3,
            )
        for idx, (x1, x2, w1, w2) in enumerate(segments):
            components.append(
                {
                    "start_magnitude": w1,
                    "end_magnitude": w2,
                    "start_loc": x1,
                    "end_loc": x2,
                    "case": case,
                    "dir": direction,
                    "profile": profile,
                    "segment": idx,
                    "point_load_total": math.fsum(loads),
                    "load_shift": shift,
                    "fit_error": error,
                }
            )

    view = trib_view(components, joist_tags, joist_pms, occupancies, tag, parent)
    for component in components:
        case_view = view.get(component["case"])
        pressure = case_view["pressure"] if case_view else None
        component["trib_width_start"] = (
            abs(component["start_magnitude"]) / pressure if pressure else None
        )
        component["trib_width_end"] = (
            abs(component["end_magnitude"]) / pressure if pressure else None
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
        "trib_view": view,
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
    Returns the occupancy and pressure used to express the converted load
    'components' as trib widths, keyed by load case:

        {case: {"occupancy", "pressure", "approximate"}}

    The occupancy is the one with the most applied area on the joists. A trib
    width is a line load divided by the pressure of that occupancy. The trib
    widths are exact when the joists carry only that occupancy; otherwise
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
    for case in dict.fromkeys(component["case"] for component in components):
        pressure = occupancies.get(occupancy, {}).get(case)
        if not pressure:
            continue
        view[case] = {"occupancy": occupancy, "pressure": pressure, "approximate": approximate}
    return view
