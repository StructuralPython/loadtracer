# loadtracer

**The load rundown for papermodels.**

[papermodels](https://papermodels.structuralpython.com/) reads a marked-up
drawing and works out *what supports what*: a load path graph, the joist arrays,
the trib areas and the area loads on every member. loadtracer finishes the job.
It analyses every member in that graph, from the roof down, and applies each
member's reactions to the members that support it, until every load has reached
the foundation.

- Beams and joists are analysed with [PyniteFEA](https://github.com/JWock82/Pynite).
- Walls are analysed with `loadbearing_wall.LinearWallModel`.
- Columns are analysed as concentric columns.

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
lt.execute_analyses(artifacts_dir="artifacts")

lt.reactions["CB0.1"]   # the forces on the support of a column at the foundation
```

loadtracer is an analysis step only. It needs the graph and the occupancy
pressures. It does not need design data such as member sizes, element heights
or floor elevations.

::::{grid} 1 1 2 2
:gutter: 2

:::{grid-item-card} Getting started
:link: getting-started
:link-type: doc
Install loadtracer and run your first load rundown.
:::

:::{grid-item-card} How a rundown works
:link: guide/rundown
:link-type: doc
The order of analysis, the steps for each member, and the analysis models.
:::

:::{grid-item-card} Examples
:link: examples/index
:link-type: doc
The papermodels examples, taken through to the foundation.
:::

:::{grid-item-card} API reference
:link: api/index
:link-type: doc
Every module, class and function.
:::
::::

```{toctree}
:hidden:
:caption: Guide

getting-started
guide/rundown
guide/results
guide/joist-loads
guide/options
guide/assumptions
```

```{toctree}
:hidden:
:caption: Examples

examples/index
```

```{toctree}
:hidden:
:caption: Reference

api/index
design/index
```
