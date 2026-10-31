# Modelling assumptions

loadtracer is a load rundown, not a design. These are the assumptions it makes,
and where they can differ from a hand calculation.

Stiffness
: Beams have a unit, uniform EI. A member's size does not affect how it
  distributes load.

Continuity
: A beam over more than two supports is continuous, and distributes load as a
  prismatic continuous beam would. This can differ from simple-span hand
  calculations. A heavily loaded long span can lift the end of a short adjacent
  span: the reaction at that support is then an uplift, and is carried down as
  one.

Support fixity
: The first support of a beam is a pin and the others are rollers, unless the
  support has a `fixity` (`"pin"`, `"roller"` or `"fixed"`).

Reaction order
: A `transfer_reaction_index` refers to the source member's supports sorted
  along the member, which is how papermodels orders them. Coincident supports
  are kept (so the indexes still line up), but only the first is modelled, and
  it reports the reaction.

Walls
: A wall's reaction maps onto the member below in the same direction, from the
  part of the wall over that member (the source extents) to the part of the
  member under the wall (the target extents). Both are measured from each
  member's start, which is the papermodels convention. When the two lengths
  differ (e.g. from rounding in the drawing), the load is scaled so that the
  force is unchanged.

Walls on overlapping supports
: When two members support the same part of a wall, how the load divides
  between them depends on their stiffness, which the graph does not carry.
  loadtracer applies the overlap to **both** and records an issue. Fix the
  markup so each part of a wall bears on one member.

Columns
: Columns are concentric. Point load locations on a column are ignored.

Loads off a member
: Load that falls past the end of a member (common where a trib area is drawn
  wider than its joist) is moved to that end as a point load. The total load is
  kept, and an issue is recorded.

Load directions
: The `inplane` and `out_of_plane` directions are carried through, but only
  gravity loads are covered by the tests.

The {doc}`robustness audit <../design/robustness-audit>` covers how each of
these was tested, and the input that loadtracer corrects, reports or rejects.
