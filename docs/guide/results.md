# Results

After {meth}`~loadtracer.load_tracer.LoadTracer.execute_analyses`, the
results are stored on the `LoadTracer`, keyed by member tag.

| Attribute | Contents |
|---|---|
| `lt.reactions[tag]` | The forces on each support (see below) |
| `lt.models[tag]` | The serialized analysis model of each member |
| `lt.expanded_pm[tag]` | The papermodel of each member with every load expanded into load case components (`"expanded"`) |
| `lt.issues[tag]` | Input that was corrected so that the rundown could continue |
| `lt.errors[tag]` | Members that could not be analysed (with `on_error="collect"`) |
| `lt.ignored_reactions[tag]` | Transfer loads whose source reactions were missing (with `missing_reactions="ignore"`) |
| `lt.load_cases_used` | Every load case in the occupancies, sorted |

## Reactions

Reactions are keyed by **support index**, then by direction, then by load case:

```python
{support_index: {direction: {load_case: value}}}
```

The support index is the position of the support along the member, which is
the order that papermodels uses for `transfer_reaction_index`. Every support is
listed, even when its reactions are zero, so the indexes always line up.

| Member | Directions | Values |
|---|---|---|
| Frame | `FX`, `FY`, `FZ`, `MX`, `MY`, `MZ` | floats |
| Column | the directions it is loaded in (e.g. `FY`) | floats |
| Wall | the directions it is loaded in | lists of distributed loads along the wall (one support, index `0`) |

A wall's reaction is a list of loads like:

```python
{"start_magnitude": -120.0, "end_magnitude": -120.0, "start_loc": 0.0,
 "end_loc": 8.5, "case": "D", "dir": "FY"}
```

A member that carries no load has empty reactions (`{0: {}, 1: {}}`), and
contributes no load to the members below it.

## Files

With `execute_analyses(artifacts_dir=...)`, loadtracer writes:

- `models.json`: `lt.models`, every analysis model
- `reaction_forces.json`: `lt.reactions`

The frame models are written with
[pynite-tools](https://pypi.org/project/pynite-tools/), so they can be loaded
back into PyniteFEA models.

## Issues

`lt.issues` lists, for each member, the input that loadtracer changed in order
to keep going. For example:

- a support off the end of the member, moved onto the end
- a distributed load that extends past the member end, applied there as a point load
- a distributed load with no extents, applied over the full length
- two members that support the same part of a wall (the overlap is applied to both)

None of these stop the rundown, and the total load is kept in each case
(except the last, which counts the overlap twice). But each usually points to a
markup that should be fixed. loadtracer issues one `LoadTracerWarning` at the
end of a rundown that has issues.

## Load conservation

A useful check on any rundown: for each load case, the total occupancy load
applied to the building should equal the total of the reactions at the bottom
of the graph. The {doc}`examples <../examples/index>` all make this check.
