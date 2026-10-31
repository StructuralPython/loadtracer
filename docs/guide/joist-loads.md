# Joist loads

## Joists are analysed one at a time

papermodels generates a joist array (e.g. `J1.0`) from one prototype line (see
{doc}`papermodels:guide/markup`). loadtracer analyses each joist in the array
(`J1.0-0`, `J1.0-1`, ...) as its own beam. That is accurate, but each beam under
the array then carries one point load per joist, which is hard to compare with
a hand calculation that uses a line load.

## Distributed by default

With `joist_loads="distributed"` (the default), loadtracer replaces each run of
joist point loads on a member with **one distributed load** over the run, both
in `lt.expanded_pm` and in the analysis model. The total load is unchanged.

For each load case, each joist reaction $P_i$ is divided by the width that
joist carries (half the distance to each neighbour) to give a line load
intensity $w_i$. The profile of the intensities along the run sets the shape
of the distributed load:

| Joist reactions | Distributed load |
|---|---|
| uniform (within `joist_profile_rel_tol`, default 10% of the mean) | uniform |
| increasing or decreasing along the run | trapezoidal, fitted through the intensities |
| anything else (e.g. peaking mid-run) | uniform, with a `JoistLoadVariabilityWarning` when the largest is `joist_variability_ratio` (default 2) or more times the smallest |

In every case, the resultant of the distributed load equals the total of the
joist reactions it replaces. The replaced point loads are kept in
`expanded_pm[tag]["loads"]["converted_point_loads"]`.

A run is broken at a gap of more than 1.5 times the median joist spacing, and
needs at least two joists. Joists at the same location stay as point loads.

## Comparing against hand calculations

{meth}`~loadtracer.load_tracer.LoadTracer.converted_joist_loads` returns one
row per converted load and load case. It gives the load as a line load
(`w_start`, `w_end`) and as an occupancy pressure over a trib width:

```python
import pandas as pd

pd.DataFrame(lt.converted_joist_loads("FB2.0"))
```

| member | array | joists | case | profile | start_loc | end_loc | w_start | w_end | occupancy | pressure | trib_width_start | approximate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| FB2.0 | J2.0 | 13 | D | uniform | 0.0 | 11.114 | 161.48 | 161.48 | roof | 15 | 10.77 | False |

The trib width is the line load divided by the pressure of the joists'
occupancy. It is flagged `approximate` (with a `JoistTribWidthWarning`) when
the joists carry more than one occupancy, or loads transferred from other
members. The occupancy used is then the one with the most area on the joists.

## When to keep point loads

Use `joist_loads="point"` to apply each joist reaction as a point load. The
two give the same total load, but they can give different reactions on a
continuous beam under a joist array whose reactions vary a lot. Example 2
({doc}`../examples/notebooks/example-2`) shows a case where this matters.
