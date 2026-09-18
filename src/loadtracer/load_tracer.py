from __future__ import annotations
from typing import Literal, Optional
import pathlib
import warnings

import networkx as nx
from papermodels.datatypes.geometry_graph import GeometryGraph
from rich.progress import track
import jsonchain
from pydantic import BaseModel, Field, model_validator

from .analysis_models.column_model import PointColumn
from .analysis_models.frame_model import PyniteFrame
from .analysis_models.wall_model import LoadbearingWall
from .errors import (
    AnalysisError,
    InvalidPapermodelError,
    LoadTracerError,
    LoadTracerWarning,
    ReactionNotFoundError,  # noqa: F401 (re-exported for backwards compatibility)
)
from .expand_occupancies import expand_occupancy_loads
from .expand_reactions import (
    assign_wall_transfer_cells,
    expand_reaction_loads,
    is_excluded,
)
from .validation import conform_loads_to_member, validate_papermodel

REMOVED_INPUTS = ("elevations", "vertical_element_heights")


class LoadTracer(BaseModel, arbitrary_types_allowed=True):
    """
    Traces the loads through the elements of a papermodels GeometryGraph by
    analysing each element in turn (from the top of the graph down) and applying
    its reactions to the elements that support it.

    'geometry_graph': The papermodels GeometryGraph
    'occupancies': The load components (pressures) of each occupancy, keyed by
        occupancy, e.g. {'residential': {'D': 0.5, 'L': 1.9}}
    'missing_reactions': "raise" or "ignore". What to do when a member receives
        a load from a member whose reactions are not available.
    'on_error': "raise" or "collect". With "collect", a member that cannot be
        analysed is recorded in .errors and the rundown continues. Members that
        it supports then have missing reactions.
    """

    geometry_graph: "GeometryGraph"
    occupancies: dict
    occupancy_distributed_load_direction_mapping: dict = Field(
        default={"gravity": ["Fy"], "inplane": ["Fx"], "out_of_plane": ["Fz"]}
    )
    reaction_distributed_load_direction_mapping: dict = Field(
        default={"gravity": ["FY"], "inplane": ["FX"], "out_of_plane": ["FZ"]}
    )
    reaction_point_load_direction_mapping: dict = Field(
        default={"gravity": ["FY"], "inplane": ["FX"], "out_of_plane": ["FZ"]}
    )
    missing_reactions: Literal["raise", "ignore"] = "raise"
    on_error: Literal["raise", "collect"] = "raise"
    show_progress: bool = True
    models: Optional[dict] = None
    reactions: Optional[dict] = None
    ignored_reactions: Optional[dict] = None
    expanded_pm: Optional[dict] = None
    load_cases_used: Optional[list[str]] = None
    issues: Optional[dict] = None
    errors: Optional[dict] = None

    @model_validator(mode="before")
    @classmethod
    def _drop_removed_inputs(cls, data):
        """
        Element heights and floor elevations are design data and are no longer
        used. Warn instead of silently ignoring them.
        """
        if isinstance(data, dict):
            for key in REMOVED_INPUTS:
                if key in data:
                    warnings.warn(
                        f"LoadTracer no longer uses '{key}'; it is ignored and will "
                        "be an error in a future version. Wall heights, when needed "
                        "for a vertical spread angle, are read from the wall's "
                        "annotation ('height').",
                        DeprecationWarning,
                        stacklevel=4,
                    )
                    data = {k: v for k, v in data.items() if k != key}
        return data

    def model_post_init(self, __context):
        if not self.occupancies:
            raise ValueError("'occupancies' must have at least one occupancy.")
        loads_found = []
        for occupancy, loads in self.occupancies.items():
            if not isinstance(loads, dict) or not loads:
                raise ValueError(
                    f"Occupancy {occupancy!r} must be a non-empty dict of "
                    f"{{load_case: pressure}}, not {loads!r}"
                )
            loads_found.extend(loads.keys())
        self.load_cases_used = sorted(set(loads_found))

    @property
    def load_directions(self) -> frozenset[str]:
        """The load directions from papermodels that the direction mappings cover."""
        return frozenset(self.occupancy_distributed_load_direction_mapping) & frozenset(
            self.reaction_distributed_load_direction_mapping
        ) & frozenset(self.reaction_point_load_direction_mapping)

    def generate_rundown(
        self,
        artifacts_dir: Optional[str | pathlib.Path] = None,
        progress: bool = False,
        linear_wall_spread_angle: float = 0,
        linear_wall_minimum_point_spread: float = 1,
        exclude_members: Optional[list[str]] = None,
    ):
        self.execute_analyses(
            artifacts_dir=artifacts_dir,
            progress=progress,
            linear_wall_spread_angle=linear_wall_spread_angle,
            linear_wall_minimum_point_spread=linear_wall_minimum_point_spread,
            exclude_members=exclude_members,
        )

    def execute_analyses(
        self,
        artifacts_dir: Optional[str | pathlib.Path] = None,
        progress: bool = False,
        linear_wall_spread_angle: float = 0,
        linear_wall_minimum_point_spread: float = 1,
        exclude_members: Optional[list[str]] = None,
    ) -> None:
        """
        Executes the analyses to calculate reactions so that the
        entire geometry graph can be expressed as completely resolved
        analysis models.

        'exclude_members': A list of member tags to completely exclude from the load
            rundown process. If a member with this tag is encountered, it will not be
            analyzed. If this member applies loads to another member, these loads will
            be ignored. Excluding a joist array (e.g. "J1.0") excludes all of its joists.
        'linear_wall_spread_angle': The angle (degrees) at which loads spread down a
            wall. A non-zero angle requires a 'height' on each wall's annotation.
        """
        self.models = {}
        self.reactions = {}
        self.expanded_pm = {}
        self.ignored_reactions = {}
        self.issues = {}
        self.errors = {}
        exclude_members = set(exclude_members or [])
        loaded_elements = self.geometry_graph.create_loaded_elements()

        # Include subelements in the sorted nodes
        member_names = []
        for node_name in nx.topological_sort(self.geometry_graph):
            element = self.geometry_graph.nodes[node_name]["element"]
            if element.subelements is not None:
                member_names.extend(subelem.tag for subelem in element.subelements)
            else:
                member_names.append(element.tag)
        member_names = [m for m in member_names if not is_excluded(m, exclude_members)]
        papermodels = {m: loaded_elements[m].model() for m in member_names}
        self.issues.update(assign_wall_transfer_cells(papermodels))
        if progress:
            member_names = track(member_names)

        for member_name in member_names:
            try:
                self._analyse_member(
                    papermodels[member_name],
                    exclude_members,
                    linear_wall_spread_angle,
                    linear_wall_minimum_point_spread,
                )
            except LoadTracerError as e:
                if self.on_error == "raise":
                    raise
                self.errors[member_name] = e
            except Exception as e:
                error = AnalysisError(f"{type(e).__name__}: {e}", member_name)
                if self.on_error == "raise":
                    raise error from e
                error.__cause__ = e
                self.errors[member_name] = error

        if self.issues:
            warnings.warn(
                f"{sum(len(i) for i in self.issues.values())} input issue(s) were "
                f"corrected on {len(self.issues)} member(s); review LoadTracer.issues.",
                LoadTracerWarning,
                stacklevel=2,
            )
        if artifacts_dir:
            artifacts_path = pathlib.Path(artifacts_dir)
            artifacts_path.mkdir(parents=True, exist_ok=True)
            jsonchain.dump_json(self.models, artifacts_path / "models.json")
            jsonchain.dump_json(self.reactions, artifacts_path / "reaction_forces.json")

    def _analyse_member(
        self,
        papermodel: dict,
        exclude_members: set[str],
        linear_wall_spread_angle: float,
        linear_wall_minimum_point_spread: float,
    ) -> None:
        """
        Expands the loads of 'papermodel', builds and solves its analysis model and
        stores the results on self.
        """
        papermodel, issues = validate_papermodel(
            papermodel, directions=self.load_directions
        )
        element_attributes = papermodel["element_attributes"]
        tag = element_attributes["tag"]
        orientation = element_attributes["orientation"]
        reaction_type = element_attributes["reaction_type"]

        expanded_papermodel = expand_occupancy_loads(
            papermodel,
            self.occupancies,
            self.occupancy_distributed_load_direction_mapping,
            reaction_type=reaction_type,
        )
        expanded_papermodel, ignored_reactions = expand_reaction_loads(
            expanded_papermodel,
            self.reactions,
            self.reaction_distributed_load_direction_mapping,
            self.reaction_point_load_direction_mapping,
            missing_reactions=self.missing_reactions,
            exclude_members=exclude_members,
        )
        self.ignored_reactions.update(ignored_reactions)
        issues += conform_loads_to_member(expanded_papermodel)
        if issues:
            self.issues.setdefault(tag, []).extend(issues)
        self.expanded_pm[tag] = expanded_papermodel

        match orientation, reaction_type:
            case "vertical", "linear":
                member_model = LoadbearingWall(
                    expanded_papermodel,
                    vertical_spread_angle=linear_wall_spread_angle,
                    minimum_point_spread=linear_wall_minimum_point_spread,
                )
            case "vertical", "point":
                member_model = PointColumn(expanded_papermodel)
            case "horizontal", _:
                member_model = PyniteFrame(expanded_papermodel)
            case _:
                raise InvalidPapermodelError(
                    f"No analysis model for {orientation}/{reaction_type} members.", tag
                )

        self.models[tag] = member_model.dump_model()
        self.reactions[tag] = member_model.get_reactions()
