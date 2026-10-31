# Getting started

## Installation

loadtracer is not on PyPI yet. Install it from GitHub:

```bash
pip install git+https://github.com/structuralpython/loadtracer.git
```

This also installs [papermodels](https://papermodels.structuralpython.com/)
and the analysis packages (PyniteFEA, loadbearing-wall). loadtracer needs
Python 3.12 or later.

## Your first rundown

A rundown has three steps. The first is the papermodels workflow, described in
the papermodels guide ({doc}`papermodels:getting-started`).

### 1. Build the graph with papermodels

```python
from decimal import Decimal
from papermodels.datatypes.geometry_graph import GeometryGraph
from papermodels.datatypes.joist_models import JoistArrayModel

graph = GeometryGraph.from_pdf_file("sketch_to_scale.pdf", scale=Decimal(1 / 72 * 4))
graph.assign_collector_behaviour(JoistArrayModel, spacing=1.0)
```

Pass the graph itself to loadtracer. Do not call `create_loaded_elements()`
first: loadtracer calls it, then works through the members in graph order.

### 2. Give the occupancy pressures

Each loading area in the drawing names an **occupancy** (see
{doc}`papermodels:guide/markup`). loadtracer needs the pressure of every load
case for each occupancy, in the units of the drawing:

```python
occupancies = {
    "residential": {"D": 15, "L": 40},   # psf, since this drawing is in feet
    "roof": {"D": 20, "S": 30},
}
```

The load case names (`"D"`, `"L"`, `"S"`, ...) are yours to choose. Every
reaction is reported per load case, and loadtracer does not combine or factor
them.

### 3. Run the rundown

```python
from loadtracer.load_tracer import LoadTracer

lt = LoadTracer(geometry_graph=graph, occupancies=occupancies)
lt.execute_analyses(artifacts_dir="artifacts")
```

`execute_analyses` analyses every member and stores the results on `lt`. With
`artifacts_dir`, it also writes `models.json` (every analysis model) and
`reaction_forces.json` (every reaction).

## Reading the results

```python
lt.reactions["FB2.0"]
# {0: {'FX': {'D': 0.0, 'L': 0.0}, 'FY': {'D': -897.35, 'L': -2392.93}, ...},
#  1: {'FX': {'D': 0.0, 'L': 0.0}, 'FY': {'D': -897.35, 'L': -2392.93}, ...}}

lt.reactions["CB0.0"]   # a column at the foundation
# {0: {'FY': {'D': -1812.87, 'L': -4834.32}}}
```

Reactions are keyed by support index (in order along the member), then by
direction and load case. They are the forces **on the support**, so a gravity
rundown gives negative `FY` reactions. See {doc}`guide/results` for everything
a rundown produces.

Before using the results, check two things:

```python
lt.issues   # input that loadtracer corrected so that the rundown could continue
lt.errors   # members that could not be analysed (with on_error="collect")
```

loadtracer warns once (a `LoadTracerWarning`) when there are issues. Read them:
they usually point to markups that do not quite meet, such as a load area that
extends past the end of a joist.

## Next steps

- {doc}`guide/rundown`: what happens to each member.
- {doc}`guide/joist-loads`: why beams under joist arrays get line loads.
- {doc}`examples/index`: worked examples, with the drawings.
