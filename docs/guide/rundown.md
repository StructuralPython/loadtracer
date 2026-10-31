# How a rundown works

## The order of analysis

papermodels builds a {class}`~papermodels.datatypes.geometry_graph.GeometryGraph`:
a directed graph in which an edge `A → B` means *B supports A* (see
{doc}`papermodels:guide/load-paths`). loadtracer visits the members in
**topological order**, so a member is always analysed after every member that
bears on it. When it reaches a member, the reactions of everything above it
are already known.

A joist array (e.g. `J1.0`) is one node in the graph, but loadtracer analyses
each of its joists (`J1.0-0`, `J1.0-1`, ...) as its own member.

## The steps for each member

For each member, {meth}`~loadtracer.load_tracer.LoadTracer.execute_analyses`:

1. **Takes the papermodel.** This is the dict that
   {meth}`LoadedElement.model() <papermodels.datatypes.element.LoadedElement.model>`
   returns (see {doc}`papermodels:guide/exporting`): the member's attributes,
   its supports, and its loads.
2. **Validates it** ({func}`~loadtracer.validation.validate_papermodel`). The
   structure is checked, and the values that papermodels produces loosely are
   normalized: supports are sorted along the member, a support just off the
   member is moved onto its end, and a distributed load with no extents is
   applied over the full length. Each correction is recorded as an issue.
3. **Expands the occupancy loads**
   ({func}`~loadtracer.expand_occupancies.expand_occupancy_loads`). Each area
   load from papermodels names an occupancy. Its magnitudes are multiplied by the
   pressure of each load case of that occupancy, to give one load component per
   load case.
4. **Expands the transfer loads**
   ({func}`~loadtracer.expand_reactions.expand_reaction_loads`). Each load from
   a member above names its source (`transfer_source`) and the support of the
   source it comes from (`transfer_reaction_index`). The reactions of that
   support become load components on this member, with the opposite sign.
5. **Converts joist point loads into distributed loads**, by default
   ({doc}`joist-loads`).
6. **Keeps every load on the member**
   ({func}`~loadtracer.validation.conform_loads_to_member`). Load that falls
   past an end of the member is moved to that end as a point load, so the total
   load is unchanged. Each correction is recorded as an issue.
7. **Builds and solves the analysis model**, then stores the model and its
   reactions.

The expanded papermodel from steps 3–6 is kept in `lt.expanded_pm[tag]`. Each
load in it has an `"expanded"` list of its components:

```python
{"start_magnitude": 161.5, "end_magnitude": 161.5, "start_loc": 0.0,
 "end_loc": 11.114, "case": "D", "dir": "FY"}
```

## Analysis models

The analysis model depends on the member's orientation and reaction type,
which papermodels reads from the legend.

| Member | Orientation / reaction | Analysis model |
|---|---|---|
| Beams and joists | horizontal / point or linear | {class}`~loadtracer.analysis_models.frame_model.PyniteFrame`: a PyniteFEA `FEModel3D` with one member |
| Walls | vertical / linear | {class}`~loadtracer.analysis_models.wall_model.LoadbearingWall`: a `loadbearing_wall.LinearWallModel` |
| Columns | vertical / point | {class}`~loadtracer.analysis_models.column_model.PointColumn`: a concentric column |

**Frames.** The first support is a pin and the others are rollers, unless a
support has a `fixity` of its own (`"pin"`, `"roller"` or `"fixed"`). A beam
over three or more supports is continuous. A beam needs at least two supports
(one of them a pin), or a fixed support; otherwise loadtracer raises
{class}`~loadtracer.errors.UnstableMemberError`. Each load case is solved on
its own as a load combination with a factor of 1.0.

**Walls** carry their loads down to one continuous support. Their reaction is a
list of distributed loads along the wall, which is mapped onto the members
below: each member takes the part of the wall that sits over it. Point loads
on a wall spread over at least `linear_wall_minimum_point_spread`, and can
spread down the wall at an angle (see {doc}`options`).

**Columns** add up their loads. Point load locations are ignored, and a
distributed load on a column (e.g. from a wall above) is added as its resultant.

## Sign convention

Load components are positive in the direction that papermodels gives them
(gravity loads are positive). Reactions are the **forces on the supports**, so
they have the opposite sign: a gravity rundown gives negative `FY` reactions.
Every analysis model reports reactions with this convention, so a load passes
from member to member, frame to wall to column, with its sign intact.
