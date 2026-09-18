# Robustness audit: loadtracer 0.5.1

**Status:** Fixes implemented in 0.6.0
**Branch:** `refactor/consistency`
**Author:** Connor Ferster
**Date:** 2026-09-18

---

## 1. Question

A load rundown often breaks when the drawings vary even slightly. This audit
answers:

- Which inputs crash loadtracer, and why?
- Which assumptions about the data are built into the code?
- What has to change to make it robust?

It also looks for the opposite problem: inputs that **don't** crash but give a
wrong answer. Those turned out to be the more serious findings.

## 2. Method

1. **Fixture sweep.** Every PDF in `../papermodels/tests/test_data` was built
   into a `GeometryGraph` with papermodels 0.21 (`JoistArrayModel`, spacing
   1.0), then run through `LoadTracer`. The occupancies were synthetic:
   `{"D": 1.0, "L": 2.5}` for each occupancy found in the drawing.
2. **Shape survey.** The `LoadedElement.model()` output of every fixture was
   checked for:
   - list-valued point load locations
   - `[]` extents
   - loads outside the member
   - zero-length loads
   - beams with fewer than two supports
3. **Probes.** Each suspected failure was reproduced against the 0.5.1 code with
   hand-built papermodel dicts (`tests/builders.py`).
4. **Load conservation.** For each load case, the total occupancy load applied
   to the graph has to arrive at the members at the bottom of the graph (see
   `tests/conservation.py`). "Doesn't crash" is too weak a test for a load
   takedown. This invariant is what found F8 and F13.

Every finding is pinned by a test in `tests/test_sensitivity.py` (unit level)
or `tests/test_integration_papermodels.py` (fixtures).

## 3. Results at a glance

| Fixture | 0.5.1 | 0.6.0 | Load conserved (0.6.0) |
|---|---|---|---|
| collector_extents.pdf | `ReactionNotFoundError` (F4) | runs | yes (no loads drawn) |
| collector_extents_walls.pdf | runs | runs | yes |
| frame_collectors_transfers.pdf | `ReactionNotFoundError` (F4) | runs | yes |
| geometry_testing.pdf | `ReactionNotFoundError` (F4) | runs | yes (no loads drawn) |
| horiz_extents.pdf | runs | runs | yes |
| intersections.pdf | runs | runs | yes |
| many_correspondents.pdf | `ReactionNotFoundError` (F4) | runs | **+7.3%**: walls on overlapping supports (F13, reported) |
| resi_dormers.pdf | runs | runs | yes |
| sketch_to_scale.pdf | `ReactionNotFoundError` (F4) | runs | yes |
| three-pages-on-one.pdf | papermodels `KeyError: None` | same | n/a (upstream, U3) |
| trib-areas-basic.pdf | runs | runs | yes |

5 of the 10 fixtures that papermodels can build crashed in loadtracer 0.5.1.
In 0.6.0 all 10 run. Load is conserved exactly (to 1e-6) on 9 of them. On the
10th, the extra load comes only from walls whose supports overlap, and each
one is reported in `LoadTracer.issues`.

## 4. Findings

"Silent" means that 0.5.1 returned a result without raising an error, and
that result was wrong.

| # | Input | 0.5.1 symptom | Root cause (0.5.1) | Fix (0.6.0) |
|---|---|---|---|---|
| F1 | Beam with 0 supports, or 1 support | 0 supports: `UnboundLocalError: node_name`. 1 support mid-span: **silent**, a single reaction of −5.5 for a load of 10 (the member was cut off at the support). 1 support at the end: **silent**, −9 | `frame_model.py:158-170`: the end nodes are only added when `idx == 0` or `idx == len - 1`, so a single support takes only the first branch. Nothing checks stability. | `get_node_locations` adds free end nodes independently of the supports. It raises `UnstableMemberError` unless there are ≥ 2 supports including a pin, or a `fixed` support. |
| F2 | Loads outside [0, L], or with zero length. Common: joist trib areas project 0.06–0.32 past the joist ends, and one fixture (`resi_dormers.pdf`) has a load lying entirely past its member's end | Distributed load 0.5 past each end: **silent**, 1.0 of 11.0 lost. Point load 0.2 past the end: **silent**, reactions `{}`, so the load disappears | Pynite ignores the part of a load outside the member. `wall_model.py:96,121` clamps only `end_loc`, and mutates the point load it is given. | `validation.conform_loads_to_member` clips every expanded load to the member. The part outside becomes a point load at the nearest end, so the total load is exact. Each correction is recorded in `LoadTracer.issues`. |
| F3 | Any exception while analysing a member | `ReactionNotFoundError: Error calculating reaction for: X` for *every* error. The cause is lost, and `KeyboardInterrupt` is caught too | Bare `except:` in `load_tracer.py:212` and `expand_reactions.py:181`. The error message at `expand_reactions.py:183` indexes `member_reactions[tag]`, which raises a `KeyError` of its own. | Error hierarchy in `errors.py` (`LoadTracerError` → `ReactionNotFoundError`, `UnstableMemberError`, `InvalidPapermodelError`, `AnalysisError`). Every error carries the member tag, and unexpected errors are wrapped with `raise … from e`. New `on_error="collect"` records failures in `.errors` and continues. |
| F4 | A member with no load. The load area doesn't reach it, or it's a drawn member that isn't loaded yet | `ReactionNotFoundError` on every member below it. **This is the main reason 0.5.1 "breaks when there is any variance in the input"**: it caused all 5 fixture crashes | The member has no load cases, so Pynite has no combinations, so `extract_node_reactions` returns `{}`. Then `expand_reactions.py:107` treats `{}` / `{0: {}}` as "missing". | Reactions are keyed by support index and always list every support (`{0: {}, 1: {}}` for an unloaded member). A support that was analysed and has no load contributes no load components. "Missing" now means only that the source wasn't analysed or has no such index. |
| F5 | A support with zero reaction (for example, a point load directly over the middle of three supports) | **Silent**: the reaction indexes shift. The middle support's reaction was reported as index 0 and applied to the member under the *first* support | `pynite_tools.extract_node_reactions` drops any node whose reactions are all ≈ 0, and `expand_reactions.py:243` maps node → index by `enumerate`. | `frame_model.get_support_reactions` reads the reactions of the support nodes directly, in support order, zeros included. |
| F6 | Reaction missing for `transfer_reaction_index` 0, or index out of range | `AssertionError` (not caught by `missing_reactions="ignore"`). An out-of-range index: **silent**, zero load | `if transfer_index and (...)` at `expand_reactions.py:152` is falsy for index 0, and the code then reaches `assert` at `:333`. Out of range falls back to `[null_point_load]` at `:135`. | `get_indexed_reaction` looks up the index explicitly. Anything unavailable raises `ReactionNotFoundError`, which names the source and the index, or is recorded under `"ignore"`. |
| F7 | Any transfer load | **Silent**: each transfer load appears twice in `expanded_pm`, once with its expansion and once without. Loads without an occupancy were also duplicated once per analysis direction | `expand_reactions.py:113,138` and `expand_occupancies.py:103` append to lists that the `deepcopy` already filled. The shallow `copy()` shared `expanded` lists with the input. | The load lists are rebuilt from the deep copy, and each load appears exactly once. |
| F8 | A wall with both point loads and distributed loads | **Silent**: the distributed part of the wall's reaction never reaches the member below | `wall_model.py:116` hard-codes `dir="Fy"` for distributed loads, while point loads use `"FY"`, so the reactions are split over two keys. `expand_reactions.py:344` falls back to `"Fy"` only when `"FY"` is absent. | Each load keeps its own `dir`. The `.title()` workaround is removed. |
| F9 | Walls stacked on walls | **Silent**: the load changes sign at every wall. A +5 load into `WT1.0` arrived at `WT0.0` as −5 (in total) | Walls report reactions with the sign of the load, but frames and columns report the force on the support. loadbearing-wall 0.3.0 (the version in the 0.5.1 lock) accepts `reverse_reaction_force_direction` but never uses it. | loadbearing-wall 0.5.0 applies the flag. loadtracer now requires `loadbearing-wall>=0.5.0` and passes `reverse_reaction_force_direction=True` explicitly, so every model reports support forces. |
| F10 | A wall over more than one member, or over a shorter member | **Silent**: the *whole* wall reaction was applied to each member under it (+22.7% on `many_correspondents`) | `expand_distributed_reactions` ignored `transfer_source_start_extent` / `transfer_source_end_extent`. | `map_wall_reaction` takes only the part of the wall over each receiver, and scales it so the force is conserved when drawn lengths differ. `assign_wall_transfer_cells` shares out the parts of a wall that aren't over any member (overhangs, gaps, and reactions that the minimum point spread pushes past the wall ends), so the whole reaction is transferred exactly once. |
| F11 | No `elevations` / `vertical_element_heights`; a lowercase or non-standard tag; a floor index beyond the elevations | `ValueError`, `AttributeError: 'NoneType' has no attribute 'groups'`, `IndexError` | `pm_processing.py:17,43,21`. Heights are design data, but loadtracer required them for every vertical element. | **Removed.** Heights and elevations are no longer inputs; passing them gives a `DeprecationWarning`. `LinearWallModel` uses height only for a non-zero spread angle (verified in its source and pinned by a test). That case reads `height` from the wall's annotation, or raises. |
| F12 | Structural problems in the papermodel: unknown orientation, missing length, list-valued locations, `[]` extents, unknown direction or occupancy, empty occupancies | `UnboundLocalError: member_model`, `KeyError`, `TypeError: [] + float`, `IndexError` at `load_tracer.py:67` | No validation of the input. Model selection at `load_tracer.py:170` had no else branch. | `validation.validate_papermodel` checks the structure with pattern matching, and raises `InvalidPapermodelError` with the tag. List locations on columns (from papermodels, see U1) become 0.0, and `[]` extents become the full length. Occupancies are validated at construction. |
| F13 | A wall linked to members that overlap under it | Double counting (the remaining +7.3% on `many_correspondents`). For example, `WB1.0` bears on `WT1.3` along its whole length *and* on `FB1.2`/`FB1.3` under parts of it | How the load divides between two supports under the same stretch of wall depends on their stiffness, which the graph doesn't carry. | **Detected and reported, not resolved.** The overlap is applied to both members and recorded in `LoadTracer.issues[wall]`, with a warning. See U2. |
| F14 | Excluding a joist array by its parent tag (`exclude_members=["J1.0"]`) | **Silent**: the joists (`J1.0-0`…) were still analysed and their loads still applied | `expand_reactions.py:105,147` matched exact tags only. | `is_excluded` also matches the parent of `PARENT-idx` tags. |
| F15 | A column under a wall (a distributed load on a point column) | **Silent**: the load was dropped | `column_model.build_column_model` read only point loads. | Distributed loads are added to the column as their resultants. |

## 5. Assumptions that remain (documented, not changed)

- **Reaction order.** `transfer_reaction_index` refers to the source member's
  supports sorted by location, which is how papermodels orders them. Supports
  that coincide are kept, so the indexes still line up, but only the first is
  modelled.
- **Support fixity.** The first support is a pin and the others are rollers,
  unless a support dict has a `fixity` (`"pin"`, `"roller"`, `"fixed"`).
- **Stiffness and continuity.** Beams use a unit, uniform EI, and a beam over
  more than two supports is continuous. Loads are distributed as a prismatic
  continuous member would distribute them, which can differ from simple-span
  hand calculations. A heavily loaded long span can lift the end of a short
  adjacent span: `FB3.1` in `sketch_to_scale.pdf` (spans 13.4 + 4.9) puts 59.6
  of uplift into `CT3.2` in the L case.
- **Walls.** A wall's reaction maps onto the member below in the same
  direction, from source extents to target extents. Both are measured from
  each member's positive-x end, which is the papermodels convention. Walls use
  `minimum_point_spread` to spread point loads.
- **Columns** are concentric: point load locations are ignored.
- **Gravity only.** The `inplane` and `out_of_plane` mappings are wired through
  but no fixture or test uses them.
- **Pressures.** Occupancy loads are the pressure × the magnitudes from
  papermodels (trib widths). The `applied_area_ratio` scaling for
  linear-reaction collectors was not audited.

## 6. Upstream recommendations

| # | Project | Recommendation |
|---|---|---|
| U1 | papermodels | `LoadedElement._get_transfer_loads` gives point correspondents on a polygon the **whole list** of transfer locations as `location` (`[]`, `[0.0]`, `[0.0, 0.0, 0.0]` on the fixtures). It should give a single value. |
| U2 | papermodels | A wall can be linked to members that overlap under it (F13). The graph should link each part of a wall to one support, or carry enough information to divide the load between them. |
| U3 | papermodels | `three-pages-on-one.pdf` fails in `GeometryGraph.from_pdf_file` with `KeyError: None`. |
| U4 | papermodels | Occupancy loads on joists commonly extend 0.06–0.32 past the joist ends (the trib band is wider than the joist line). loadtracer moves this load to the ends; confirm whether it's intended. |
| U5 | papermodels | Point transfer loads from joists carry no trib extents. `JoistArrayModel` already calculates them for each crossing (`_trib_extent_on_support`). Exposing them would make the joist point-to-distributed load conversion (Task 2) exact at array ends. |
| U6 | loadbearing_wall | Fixed in 0.5.0: `reverse_reaction_force_direction` was ignored in 0.3.0 (F9). Still open: `print()` calls in `spread_loads` / `apply_spread_angle` write to stdout on every analysis, and reactions from `minimum_point_spread` can extend past the wall ends. |
| U7 | pynite_tools | `extract_node_reactions` drops nodes whose reactions are all zero, which breaks index-based consumers (F5), and it rounds values to nearby integers. |
| U8 | PyniteFEA | Fixed in 3.x: 1.6.2 (the version in the 0.5.1 lock) imported `pip._vendor.pkg_resources` in `__init__` and failed in environments without pip. The lock is now on 3.2.0. |
| U9 | papermodels | `paper/pdf.py` calls `pikepdf.Stream.read_bytes`, which later pikepdf 10.x releases no longer have (it fails on 10.13, works on 10.0.2). papermodels doesn't bound its pikepdf version, so a fresh install can't read PDFs. loadtracer's lock holds pikepdf at 10.0.2. |
| U10 | papermodels | papermodels' `Examples/Example 5/multi-page-plan.pdf` fails in `GeometryGraph.from_elements` → `collector_elements` (`geometry_graph.py:106`) with `KeyError: 'element'`: a graph node has no element (an edge refers to a tag that isn't a node). |
| U11 | papermodels | papermodels' `Examples/Example 2`: the PDF tags a beam on page 2 `FB2.5`, but the graph names it `FB2.0`. The manual tags `FB1.14` and `CB0.10` are kept. |

## 7. Behaviour changes in 0.6.0

- Dependencies: `loadbearing-wall>=0.5.0`. The lock is on PyniteFEA 3.2.0 and
  pynite-tools 0.7.0 (it was 1.6.2 / 0.6.7). The 0.5.1 symptoms in §4 were
  observed on the old lock; the 0.6.0 results in §3 are on the new one.

- `LoadTracer(elevations=…, vertical_element_heights=…)` is deprecated: the
  values are ignored, with a warning. `pm_processing.py` is removed.
- Reactions are stored as `{support_index: {dir: {case: value}}}` rather than
  `{node_name: …}`. Every support is included, and all six directions are
  listed for frames. Values are floats, where before they were rounded to
  nearby integers.
- `LoadTracer.issues` records every input that was corrected; the rundown warns
  once (`LoadTracerWarning`) when there are any. `LoadTracer.errors` records
  members that failed under `on_error="collect"`.
- `expand_occupancy_loads` / `expand_reaction_loads` no longer take null-load
  arguments, and `LoadTracer.null_point_load` / `null_dist_load` are removed.
- Only transfer loads from excluded members are dropped. Loads whose source
  reactions are ignored stay in `expanded_pm` without an expansion.
