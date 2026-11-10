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
in `lt.expanded_pm` and in the analysis model. For each load case, the
distributed load is either uniform or a chain of trapezoids that follows the
joist reactions (a *polyline*). Its total always equals the joist reactions it
replaces. The replaced point loads are kept in
`expanded_pm[tag]["loads"]["converted_point_loads"]`.

A run is broken at a gap of more than 1.5 times the median joist spacing, and
needs at least two joists. Joists at the same location stay as point loads.

### Joist strips

Each joist at $x_i$ carries a strip of the member that runs halfway to each of
its neighbours (to $x_0$ and $x_n$ at the ends of the run). With strip
boundaries $b_i$, the strip widths $t_i$ and the joist line loads $w_i$ are

$$
b_0 = x_0,\quad b_i = \frac{x_{i-1} + x_i}{2},\quad b_{n+1} = x_n,\qquad
t_i = b_{i+1} - b_i,\qquad w_i = \frac{P_i}{t_i}
$$

### Load shift

The *load shift* of a distributed load measures how much of the joist load it
moves along the member, which is what changes moments and reactions. With
$Q_i$ the load the distributed load puts on strip $i$, it is the largest
difference between the running totals at a strip boundary:

$$
\text{load shift} = \max_j \left| \sum_{i<j} (Q_i - P_i) \right| \Big/ \sum_i |P_i|
$$

### Uniform or polyline

1. If a uniform load over the run has a load shift of no more than
   `joist_load_shift_limit` (default 1%), it is used. Joists that carry the
   same load always become a uniform load.
2. Otherwise loadtracer fits a polyline whose corners (knots) are at joist
   locations. Starting from the two ends, it adds a knot at the joist whose
   strip is worst fitted until the average line load of the polyline on every
   strip is within `joist_polyline_tol` (default 2% of the mean line load) of
   the joist's $w_i$. It then removes any knot that is not needed to stay
   within that tolerance.
3. If the polyline's load shift is more than `joist_load_shift_limit`, a
   {class}`~loadtracer.joist_load_conversion.JoistLoadVariabilityWarning` is
   raised. Check those members with `joist_loads="point"`.

The knot values $u$ of a polyline are the weighted least squares fit of its
strip loads $(A u)_i$ to the joist reactions, constrained to the same total
and the same resultant location as the joist reactions:

$$
\min_u \sum_i \frac{\left((A u)_i - P_i\right)^2}{t_i}
\quad\text{subject to}\quad
\int w\,dx = \sum_i P_i,\qquad \int x\,w\,dx = \sum_i x_i P_i
$$

$A_{ik}$ is the integral over strip $i$ of the hat function of knot $k$ (1 at
that knot, 0 at the others, linear in between). It is computed exactly, and
the constrained problem is solved through its KKT equations
(`fit_knot_values` in {mod}`loadtracer.joist_load_conversion`).

A run whose reactions rise or fall linearly becomes a single trapezoid. You can
still draw a separate joist prototype over a ramp; the polyline makes that
unnecessary to keep the shape of the load.

## Comparing against hand calculations

{meth}`~loadtracer.load_tracer.LoadTracer.converted_joist_loads` returns one
row per trapezoid of each converted load and load case (`segment` numbers the
trapezoids of a polyline). It gives the load as a line load (`w_start`,
`w_end`) and as an occupancy pressure over a trib width, with the load shift
and fit error of its load case:

```python
import pandas as pd

pd.DataFrame(lt.converted_joist_loads("FB2.0"))
```

| member | array | joists | case | profile | segment | start_loc | end_loc | w_start | w_end | load_shift | occupancy | pressure | trib_width_start | approximate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| FB2.0 | J2.0 | 13 | D | uniform | 0 | 0.0 | 11.114 | 161.48 | 161.48 | 0.0 | roof | 15 | 10.77 | False |

The trib width is the line load divided by the pressure of the joists'
occupancy. It is flagged `approximate` (with a `JoistTribWidthWarning`) when
the joists carry more than one occupancy, or loads transferred from other
members. The occupancy used is then the one with the most area on the joists.

## When to keep point loads

Use `joist_loads="point"` to apply each joist reaction as a point load. The
two give the same total load, and with the polyline their reactions are close:
in Example 2 ({doc}`../examples/notebooks/example-2`), a joist array whose
reactions vary by 3:1 on a continuous beam gives reactions within 1% of the
point loads. Point loads remain the reference when a
`JoistLoadVariabilityWarning` is raised.
