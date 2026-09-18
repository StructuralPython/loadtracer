# loadtracer

loadtracer takes a [papermodels](https://github.com/StructuralPython/papermodels)
`GeometryGraph` and traces the loads through it. Each element is analysed in turn,
from the top of the graph down, and its reactions are applied to the elements that
support it. Beams are analysed with [PyniteFEA](https://github.com/JWock82/Pynite),
walls with `loadbearing_wall.LinearWallModel`, and columns as concentric columns.

loadtracer is an analysis step only. It needs the graph and the occupancy loads,
not design data such as element heights or floor elevations.

## Usage

```python
from decimal import Decimal
from papermodels.datatypes.geometry_graph import GeometryGraph
from papermodels.datatypes.joist_models import JoistArrayModel
from loadtracer.load_tracer import LoadTracer

graph = GeometryGraph.from_pdf_file("plan.pdf", scale=Decimal(1 / 72 * 4))
graph.assign_collector_behaviour(JoistArrayModel, spacing=1.0)

lt = LoadTracer(
    geometry_graph=graph,
    occupancies={"residential": {"D": 0.5, "L": 1.9}, "roof": {"D": 0.4, "S": 1.2}},
)
lt.execute_analyses(artifacts_dir="artifacts")  # writes models.json, reaction_forces.json
```

After a rundown:

| Attribute | Contents |
|---|---|
| `lt.expanded_pm[tag]` | The papermodel of each member with every load expanded into load-case components (`"expanded"`) |
| `lt.models[tag]` | The serialized analysis model of each member |
| `lt.reactions[tag]` | `{support_index: {dir: {case: value}}}`: the forces on each support. Walls give lists of distributed loads |
| `lt.issues[tag]` | Input that was corrected so the rundown could continue (e.g. loads past a member end). Review these |
| `lt.errors[tag]` | Members that could not be analysed (with `on_error="collect"`) |
| `lt.ignored_reactions[tag]` | Transfer loads whose source reactions were missing (with `missing_reactions="ignore"`) |

### Joist loads as distributed loads

A joist array from papermodels (e.g. `J1.0`) is analysed one joist at a time
(`J1.0-0`, `J1.0-1`, ...), so the members under it receive one point load per
joist. By default (`joist_loads="distributed"`), loadtracer replaces each run of
joist point loads on a member with one distributed load over the run, in both
`expanded_pm` and the analysis model. The total load is unchanged. The shape of
the load depends on the joist reactions, divided by the width each joist carries:

| Joist reactions | Distributed load |
|---|---|
| uniform (within `joist_profile_rel_tol`, default 10% of the mean) | uniform |
| increasing or decreasing along the run | trapezoidal, fitted through the reactions |
| anything else (e.g. peaking mid-run) | uniform, with a `JoistLoadVariabilityWarning` when the largest is `joist_variability_ratio` (default 2) or more times the smallest |

`lt.converted_joist_loads()` returns a list of rows (one per converted load and load case) that describe each converted load as a line load and as an
occupancy pressure over a trib width, for comparing against hand calculations:

```python
import pandas as pd
pd.DataFrame(lt.converted_joist_loads("FB2.0"))
#   member array  joists case  profile  start_loc  end_loc  w_start  w_end  ...  occupancy  pressure  trib_width_start  trib_width_end  approximate
```

The trib width is the line load divided by the pressure of the joists'
occupancy. It is flagged `approximate` (with a `JoistTribWidthWarning`) when the
joists carry more than one occupancy or other transferred loads. Use
`joist_loads="point"` to apply each joist reaction as a point load.

### Options

- `on_error="raise" | "collect"`: stop at the first member that fails, or record
  it in `lt.errors` and continue.
- `missing_reactions="raise" | "ignore"`: what to do when a member receives load
  from a member without reactions (e.g. one that failed or was excluded).
- `execute_analyses(exclude_members=[...])`: skip members. Excluding a joist
  array (e.g. `"J1.0"`) excludes all of its joists.
- `execute_analyses(linear_wall_spread_angle=...)`: spread loads down walls at
  this angle (degrees). A non-zero angle needs a `height` on each wall's annotation.

Errors are subclasses of `loadtracer.LoadTracerError` and name the member they
concern. See [docs/robustness_audit.md](docs/robustness_audit.md) for the input
that loadtracer corrects, reports or rejects, and why.

## Development

loadtracer is developed against a papermodels checkout next to this repository
(`../papermodels`, see `[tool.uv.sources]` in `pyproject.toml`):

```
uv sync
uv run pytest
```

The integration tests run the papermodels test fixtures end to end and are
skipped when `../papermodels` is not present.
