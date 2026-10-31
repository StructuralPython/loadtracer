# Examples

These examples follow the
[papermodels examples](https://papermodels.structuralpython.com/examples/index.html)
and take each one to completion. Each builds the papermodels `GeometryGraph`
from the same drawing, then runs the load rundown with loadtracer, down to the
reactions at the foundation.

| Example | Shows |
|---|---|
| {doc}`Example 1 <notebooks/example-1>` | Joist arrays to foundation; joist loads as line loads and as occupancy × trib width |
| {doc}`Example 2 <notebooks/example-2>` | Manually tagged elements; when point joist loads matter (a variable joist array on a continuous beam) |
| {doc}`Example 3 <notebooks/example-3>` | Load transfer through walls; roof joists on a wall; a wall line load onto a beam |
| {doc}`Example 4 <notebooks/example-4>` | Columns and walls; a continuous beam with an uplift reaction |
| {doc}`Example 5 <notebooks/example-5>` | A multi-page plan on one sheet; a column that transfers to one beam rather than every element it touches |
| {doc}`Example 6 <notebooks/example-6>` | User-drawn trib areas and irregular loading areas (no joists) |

Each notebook:

1. builds the graph with papermodels,
2. sets the occupancy pressures (psf, since the drawings are in feet),
3. runs loadtracer and checks that all of the applied load reaches the bottom,
4. follows one member through: converted joist loads, expanded loads, analysis
   model and reactions,
5. compares joist loads as point loads and as distributed loads,
6. lists the reactions at the bottom of the building.

The papermodels
{doc}`legend entries notebook <papermodels:examples/notebooks/legend-entries>`
explains the annotation legend used in the drawings.

## Running the examples

Clone the repository and run the notebooks from their folders in
[`Examples/`](https://github.com/structuralpython/loadtracer/tree/main/Examples).
They use the development dependencies. Example 5 reads its PDF (37 MB) from
the papermodels repository: set `PAPERMODELS_EXAMPLES` to the papermodels
`Examples` directory, or keep papermodels next to loadtracer.

```bash
uv sync
uv run python Examples/run_all.py            # executes every notebook in place
uv run python Examples/run_all.py Example_3
```

```{toctree}
:maxdepth: 1
:hidden:

notebooks/example-1
notebooks/example-2
notebooks/example-3
notebooks/example-4
notebooks/example-5
notebooks/example-6
```
