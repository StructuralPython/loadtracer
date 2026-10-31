# loadtracer examples

These examples follow the [papermodels examples](https://github.com/StructuralPython/papermodels/tree/main/Examples)
and take each one to completion. Each builds the papermodels `GeometryGraph` from the same
drawing, then runs the load rundown with loadtracer, down to the reactions at the foundation.

| Example | Drawing | Shows |
|---|---|---|
| [Example 1](Example%201/Example_1.ipynb) | `sketch_to_scale.pdf` | Joist arrays to foundation; joist loads as line loads and as occupancy × trib width |
| [Example 2](Example%202/Example_2.ipynb) | `sketch_to_scale-w_manual_tag.pdf` | Manually tagged elements; when point joist loads matter (a variable joist array on a continuous beam) |
| [Example 3](Example%203/Example_3.ipynb) | `sketch_to_scale-vertical-loads.pdf` | Load transfer through walls; roof joists on a wall; a wall line load onto a beam |
| [Example 4](Example%204/Example_4.ipynb) | `sketch_to_scale-vertical-loads.pdf` | Columns and walls; a continuous beam with an uplift reaction |
| [Example 5](Example%205/Example_5.ipynb) | `multi-page-plan.pdf` (not included, 37 MB) | Multi-page plan on one sheet; a column that transfers to one beam rather than every element it touches |
| [Example 6](Example%206/Example_6.ipynb) | `user-applied-trib-area-arbitrary-loads.pdf` | User-drawn trib areas and irregular loading areas (no joists) |

papermodels' `Annotation Legend Entries.ipynb` (in its Example 4) explains the annotation
legend used in the drawings.

Each notebook:

1. builds the graph with papermodels
2. sets the occupancy pressures (psf, since the drawings are in feet)
3. runs loadtracer and checks that all of the applied load reaches the bottom
4. follows one member through: converted joist loads, expanded loads, analysis model and reactions
5. compares joist loads as point loads and as distributed loads
6. lists the reactions at the bottom of the building

## Running

The examples need papermodels 0.22 or later and the development dependencies:

```
uv sync
uv run python Examples/run_all.py          # executes every notebook in place
uv run python Examples/run_all.py Example_3
```

Example 5 reads its PDF from the papermodels repository: set `PAPERMODELS_EXAMPLES` to the
papermodels `Examples` directory, or keep papermodels next to loadtracer. Each run writes the
analysis models and reactions to `artifacts/` in the example's directory (not committed).
