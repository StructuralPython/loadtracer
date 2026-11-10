# Options and errors

## LoadTracer options

```python
lt = LoadTracer(
    geometry_graph=graph,
    occupancies=occupancies,
    on_error="collect",
    missing_reactions="ignore",
    joist_loads="distributed",
)
```

`on_error`
: `"raise"` (default) stops at the first member that cannot be analysed.
  `"collect"` records the error in `lt.errors` and continues. The members that
  the failed member bears on then have missing reactions (see below).

`missing_reactions`
: What to do when a member receives load from a member that has no reactions,
  because it failed, was excluded, or has no support at that
  `transfer_reaction_index`. `"raise"` (default) raises a
  {class}`~loadtracer.errors.ReactionNotFoundError`. `"ignore"` records the
  source in `lt.ignored_reactions` and continues without that load.

`joist_loads`
: `"distributed"` (default) or `"point"`. See {doc}`joist-loads`.

`joist_profile_rel_tol`, `joist_variability_ratio`
: How joist reactions are classified when they are converted. See
  {doc}`joist-loads`.

`frame_backend`
: The library that analyses beams and joists: `"pynite"` (default,
  [PyniteFEA](https://github.com/JWock82/Pynite)) or `"pycba"`
  ([pycba](https://github.com/ccaprani/pycba), through
  [pycba-tools](https://github.com/StructuralPython/pycba-tools)). See
  [Frame backends](#frame-backends).

`show_progress`
: Not used yet; to show a progress bar, pass `progress=True` to
  `execute_analyses`.

## Rundown options

```python
lt.execute_analyses(
    artifacts_dir="artifacts",
    exclude_members=["J1.0", "FB2.3"],
    linear_wall_spread_angle=45,
    linear_wall_minimum_point_spread=1,
    progress=True,
)
```

`artifacts_dir`
: Write `models.json` and `reaction_forces.json` here (see {doc}`results`).

`exclude_members`
: Skip these members. Loads that they would transfer to the members below are
  dropped. Excluding a joist array (e.g. `"J1.0"`) excludes all of its joists.

`linear_wall_spread_angle`
: Spread loads down walls at this angle, in degrees (default 0). A non-zero
  angle needs the wall height: add a numeric `height` to each wall's annotation
  in the drawing (papermodels reads it into `user_defined`).

`linear_wall_minimum_point_spread`
: The minimum length that a point load on a wall spreads over (default 1, in
  drawing units).

`progress`
: Show a progress bar while the members are analysed.

(frame-backends)=
## Frame backends

Both backends build the same beam from a papermodel (the same nodes, supports
and loads) and return reactions in the same format, with the same support
indexes and sign convention, so they are interchangeable:

```python
lt = LoadTracer(geometry_graph=graph, occupancies=occupancies, frame_backend="pycba")
```

The `"pycba"` backend needs the `pycba` extra:

```bash
pip install "loadtracer[pycba] @ git+https://github.com/structuralpython/loadtracer.git"
```

| | `"pynite"` | `"pycba"` |
|---|---|---|
| Analysis | 3D frame finite elements | 2D continuous beam (in-plane bending) |
| Load directions | All | Gravity (`Fy`/`FY` loads) and `Mz` moments. A member with a non-zero load in another direction fails with an `AnalysisError` |
| Reactions | `FX` ... `MZ` | `FY` and `MZ`; the others are zero |
| `models.json` | [pynite-tools](https://pypi.org/project/pynite-tools/) JSON | [pycba-tools](https://pypi.org/project/pycba-tools/) JSON (tagged `"backend": "pycba"`) |

The tests run every papermodels test drawing with both backends and check that
the reactions agree.

```{note}
PyniteFEA (up to at least 3.2.1) applies a trapezoidal load incorrectly when
the load spans three or more segments of a member (between supports or other
nodes), and its reactions then do not balance the load. Converted joist loads
can be trapezoidal. pycba does not have this problem.
```

## Load directions

papermodels gives each load a direction: `gravity`, `inplane` or
`out_of_plane`. Three mappings on `LoadTracer` set which analysis directions
each of them becomes:

```python
occupancy_distributed_load_direction_mapping = {"gravity": ["Fy"], "inplane": ["Fx"], "out_of_plane": ["Fz"]}
reaction_distributed_load_direction_mapping = {"gravity": ["FY"], "inplane": ["FX"], "out_of_plane": ["FZ"]}
reaction_point_load_direction_mapping = {"gravity": ["FY"], "inplane": ["FX"], "out_of_plane": ["FZ"]}
```

The reaction mappings list the reaction directions carried down to the member
below. For example, `{"gravity": ["FY", "MZ"]}` would also carry moments.
Only gravity loads are covered by the tests.

## Errors

Every error is a subclass of {class}`~loadtracer.errors.LoadTracerError`,
and names the member it concerns (`Member FB2.0: ...`, also in `error.tag`).

| Error | Raised when |
|---|---|
| {class}`~loadtracer.errors.InvalidPapermodelError` | A papermodel does not have the shape or values loadtracer needs, e.g. an occupancy with no pressures, or a member with no length |
| {class}`~loadtracer.errors.UnstableMemberError` | A beam's supports cannot make it stable, e.g. a beam with one support |
| {class}`~loadtracer.errors.ReactionNotFoundError` | A member receives load from a member whose reactions are not available |
| {class}`~loadtracer.errors.AnalysisError` | Any other failure while building or solving a model. The original exception is its `__cause__` |

With `on_error="collect"`, these are gathered in `lt.errors` instead of raised:

```python
lt = LoadTracer(geometry_graph=graph, occupancies=occupancies, on_error="collect")
lt.execute_analyses()
for tag, error in lt.errors.items():
    print(error)
```

## Warnings

All warnings are subclasses of {class}`~loadtracer.errors.LoadTracerWarning`:

- `LoadTracerWarning`: once per rundown, when `lt.issues` is not empty
- {class}`~loadtracer.joist_load_conversion.JoistLoadVariabilityWarning`:
  joist reactions that vary a lot were converted to a uniform load
- {class}`~loadtracer.joist_load_conversion.JoistTribWidthWarning`: a trib
  width in `converted_joist_loads()` is approximate

```{note}
`LoadTracer(elevations=..., vertical_element_heights=...)` is deprecated.
Heights and elevations are design data, and are ignored with a
`DeprecationWarning`. Wall heights, when a spread angle needs them, come from
the wall's annotation.
```
