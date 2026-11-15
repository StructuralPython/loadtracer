"""
A traced member as a beamz9000 beam (https://beamz9000.structuralpython.com):
its supports and its fully resolved loads, one load per load case and
component, ready to draw as a free-body diagram or analyse again.

See LoadTracer.to_beamz.
"""

from __future__ import annotations

import warnings
from typing import Optional

from .analysis_models.frame_model import SUPPORT_CONSTRAINTS, get_node_locations
from .errors import LoadTracerWarning

# Pynite constraint lists back to fixity names.
_FIXITIES = {tuple(c): name for name, c in SUPPORT_CONSTRAINTS.items()}


def member_to_beamz(
    pm: dict,
    precision: int = 3,
    length_unit: Optional[str] = None,
    force_unit: Optional[str] = None,
    **beam_options,
) -> dict:
    """
    Returns the expanded papermodel 'pm' of a horizontal member (from
    LoadTracer.expanded_pm) as a beam in the beamz9000 scheme format.

    The beam is the member's analysis model: the same length, nodes and
    supports (pin, roller or fixed) as loadtracer's frame model, so analysing
    it in beamz9000 gives the reactions loadtracer found. Each expanded load
    component becomes one beamz9000 load with its load case:

    - gravity ("FY"/"Fy") distributed and point loads, downward positive;
    - in-plane ("FX"/"Fx") point loads, as horizontal point loads;
    - moments ("MZ"/"Mz"), counter-clockwise positive.

    Other components (out-of-plane loads, in-plane distributed loads) can't be
    drawn on a beam; they are left out with a LoadTracerWarning.

    'precision': Decimal places for locations. Magnitudes keep 6 significant
        figures, or 4 when written with units (beamz9000 shows those as
        written).
    'length_unit', 'force_unit': Units to write the values with (e.g. "ft"
        and "kip", or "m" and "kN"), for a scheme with a forallpeople
        `_environment`. Give both or neither. Without them, the values are
        plain numbers in loadtracer's units.
    'beam_options': Any other keys of the beamz9000 beam, added as given,
        e.g. e=..., i=..., results=["forces", "reactions"], load_combos=[...].
    """
    attrs = pm["element_attributes"]
    tag = attrs["tag"]
    if attrs["orientation"] != "horizontal":
        raise ValueError(f"{tag} is a vertical member: only horizontal members are beams")
    if (length_unit is None) != (force_unit is None):
        raise ValueError("give both 'length_unit' and 'force_unit', or neither")

    def at(x: float):
        x = round(x, precision) + 0.0  # + 0.0 turns -0.0 into 0.0
        return f"{x:g} {length_unit}" if length_unit else x

    def mag(value: float, unit: Optional[str]):
        # beamz9000 shows a value with units as written, so it is kept short;
        # a plain number is labelled to 3 decimals by beamz9000 itself.
        if unit:
            return f"{float(f'{value:.4g}') + 0.0:g} {unit}"
        return float(f"{value:.6g}") + 0.0

    point_unit = force_unit
    line_unit = f"{force_unit}/{length_unit}" if force_unit else None
    moment_unit = f"{force_unit}*{length_unit}" if force_unit else None

    nodes = get_node_locations(pm)
    supports = [
        "free" if constraints is None else _FIXITIES[tuple(constraints)]
        for _, constraints in nodes
    ]
    locations = [location for location, _ in nodes]

    loads, skipped = [], []
    # loadtracer gives load components positive in their papermodels direction
    # (gravity positive in "FY"), so its frame model is the real beam mirrored
    # top to bottom: a component's vertical force and moment are reversed,
    # its horizontal force is not.
    for dist_load in pm["loads"]["distributed_loads"]:
        for c in dist_load.get("expanded", []):
            w1, w2 = c["start_magnitude"], c["end_magnitude"]
            if w1 == 0 and w2 == 0:
                continue
            if c["dir"].upper() != "FY":
                skipped.append(f"{c['dir']} distributed ({c['case']})")
                continue
            load = {"x1": at(c["start_loc"]), "x2": at(c["end_loc"]), "case": c["case"]}
            if w1 == w2:
                load["w"] = mag(w1, line_unit)
            else:
                load["mag1"], load["mag2"] = mag(w1, line_unit), mag(w2, line_unit)
            loads.append({"dist": load})
    for point_load in pm["loads"]["point_loads"]:
        for c in point_load.get("expanded", []):
            p, direction = c["magnitude"], c["dir"].upper()
            if p == 0:
                continue
            x = at(c["location"])
            if direction == "FY":
                loads.append({"point": {"p": mag(p, point_unit), "x": x, "case": c["case"]}})
            elif direction == "FX":
                # Rightward (+X) when p > 0.
                angle = 90 if p > 0 else -90
                loads.append({"point": {"p": mag(abs(p), point_unit), "x": x, "angle": angle,
                                        "case": c["case"]}})
            elif direction == "MZ":
                loads.append({"moment": {"m": mag(-p, moment_unit), "x": x, "case": c["case"]}})
            else:
                skipped.append(f"{c['dir']} point ({c['case']})")
    if skipped:
        warnings.warn(
            f"{tag}: {len(skipped)} load component(s) can't be drawn on a beam and were "
            f"left out: {', '.join(sorted(set(skipped)))}",
            LoadTracerWarning,
            stacklevel=3,
        )

    beam = {
        "spans": [at(b - a) for a, b in zip(locations, locations[1:])],
        "supports": supports,
        "loads": loads,
    }
    return beam | beam_options
