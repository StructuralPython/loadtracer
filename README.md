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
