from dataclasses import dataclass
import pathlib
from typing import Optional, Any, Union
import io

from .analysis_model import AbstractAnalysisModel
from ..errors import InvalidPapermodelError
from loadbearing_wall import LinearWallModel


@dataclass
class LoadbearingWall(AbstractAnalysisModel):
    pm: dict
    model: Optional[LinearWallModel]
    vertical_spread_angle: float = 0
    minimum_point_spread: float = 0.5

    def __post_init__(self):
        self.model = build_linear_wall_model(
            self.pm, self.vertical_spread_angle, self.minimum_point_spread
        )

    def get_reactions(self) -> dict[int, dict]:
        """
        Returns the reactions of the wall on its (single, continuous) support as
        distributed loads: {0: {dir: {case: [dist_load, ...]}}}.

        The magnitudes are the forces on the support, which is the same sign
        convention as the frame and column models (the opposite sign of the
        applied loads).
        """
        return {0: self.model.get_reactions()}

    def dump_model(
        self, filepath: Optional[str | pathlib.Path] = None, indent: int = 2
    ) -> Optional[dict]:
        """
        Dumps the model to 'filepath'. If 'filepath' is None, then a Python
        dict is returned.
        """
        if filepath is not None:
            return self.model.to_json(self.model, filepath, indent=indent)
        else:
            return self.model.dump_dict()

    def load_model(
        self,
        filepath: Optional[str | pathlib.Path] = None,
        model_data: Optional[dict] = None,
    ) -> dict:
        """
        Loads the model from either 'filepath' or 'model_data' and returns a dict
        """
        if filepath is not None:
            return self.model.from_json(filepath)
        else:
            return self.model.from_dict(model_data)

    @classmethod
    def from_papermodel(
        self,
        model_data: Optional[dict] = None,
        filepath: Optional[str | pathlib.Path] = None,
    ) -> dict:
        """
        Loads the model from either 'fp' or 'model_data' and returns a dict
        """
        if filepath is not None:
            return LinearWallModel.from_json(filepath)
        else:
            return LinearWallModel.from_dict(model_data)


# LinearWallModel only uses the wall height to spread loads down the wall at
# the vertical spread angle. With no spread angle, the height has no effect and
# this placeholder is used so that loadtracer does not require wall heights.
PLACEHOLDER_WALL_HEIGHT = 1.0


def get_wall_height(pm: dict, vertical_spread_angle: float) -> float:
    """
    Returns the wall height to use in the LinearWallModel for 'pm'.

    The height is only needed when 'vertical_spread_angle' is not zero. It is
    then read from the "height" value that the designer annotated on the wall
    (element_attributes.user_defined.height).
    """
    if vertical_spread_angle == 0:
        return PLACEHOLDER_WALL_HEIGHT
    tag = pm["element_attributes"]["tag"]
    match pm["element_attributes"].get("user_defined") or {}:
        case {"height": int() | float() as height} if height > 0:
            return float(height)
        case {"height": str(height)} if _is_positive_number(height):
            return float(height)
        case user_defined:
            raise InvalidPapermodelError(
                f"A vertical spread angle of {vertical_spread_angle} needs the wall "
                "height. Add a numeric 'height' to the wall's annotation, or use a "
                f"spread angle of 0. Annotated values: {user_defined!r}",
                tag,
            )


def _is_positive_number(s: str) -> bool:
    try:
        return float(s) > 0
    except ValueError:
        return False


def build_linear_wall_model(
    pm: dict, vertical_spread_angle: float, minimum_point_spread: float
) -> LinearWallModel:
    """
    Returns a LinearWallModel based on the data within 'pm'.

    The loads in 'pm' must be on the wall (see validation.conform_loads_to_member).
    """
    length = pm["element_attributes"]["length"]
    wall_model = LinearWallModel(
        height=get_wall_height(pm, vertical_spread_angle),
        length=length,
        vertical_spread_angle=vertical_spread_angle,
        minimum_point_spread=minimum_point_spread,
        gravity_dir="FY",
        inplane_dir="FX",
        out_of_plane_dir="FZ",
        magnitude_start_key="start_magnitude",
        magnitude_end_key="end_magnitude",
        location_start_key="start_loc",
        location_end_key="end_loc",
        # Report the forces on the support, as the frame and column models do
        reverse_reaction_force_direction=True,
    )
    for dist_load in pm["loads"]["distributed_loads"]:
        for dt in dist_load.get("expanded", []):
            wall_model.add_dist_load(
                magnitude_start=dt["start_magnitude"],
                magnitude_end=dt["end_magnitude"],
                location_start=dt["start_loc"],
                location_end=dt["end_loc"],
                case=dt["case"],
                dir=dt["dir"],
            )
    for point_load in pm["loads"]["point_loads"]:
        for pt in point_load.get("expanded", []):
            wall_model.add_point_load(
                magnitude=pt["magnitude"],
                location=pt["location"],
                case=pt["case"],
                dir=pt["dir"],
            )
    return wall_model
