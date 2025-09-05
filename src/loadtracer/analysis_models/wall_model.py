from dataclasses import dataclass
import pathlib
from typing import Optional, Any, Union
import io

from .analysis_model import AbstractAnalysisModel
from loadbearing_wall import LinearWallModel



@dataclass
class LoadbearingWall(AbstractAnalysisModel):
    pm: dict
    model: Optional[LinearWallModel]
    vertical_spread_angle: float = 0.0

    def __post_init__(self):
        self.model = build_linear_wall_model(self.pm, self.vertical_spread_angle)

    def get_reactions(self):
        reactions = self.model.get_reactions()
        return reactions
    
    def dump_model(self, fp: Optional[io.StringIO] = None, indent: int = 2) -> Optional[dict]:
        """
        Dumps the model to 'fp'. If 'fp' is None, then a Python
        dict is returned.
        """
        if fp is not None:
            return self.model.dump(self.model, fp, indent=indent)
        else:
            return self.model.dump_dict(self.model)


    def load_model(
        self, 
        fp: Optional[io.StringIO] = None, 
        model_data: Optional[dict] = None
    ) -> dict:
        """
        Loads the model from either 'fp' or 'model_data' and returns a dict
        """
        if fp is not None:
            return self.model.load(fp)
        else:
            return self.model.load_dict(model_data)

    @classmethod
    def from_papermodel(
        self,
        model_data: Optional[dict] = None,
        filepath: Optional[str | pathlib.Path] = None
    ) -> dict:
        """
        Loads the model from either 'fp' or 'model_data' and returns a dict
        """
        if filepath is not None:
            return LinearWallModel.from_json(filepath)
        else:
            return LinearWallModel.from_dict(model_data)
        

def build_linear_wall_model(pm: dict, spread_angle: float) -> LinearWallModel:
    """
    Returns a LinearWallModel based on the data within 'pm'
    """
    return LinearWallModel(
        pm['element_attributes']['height'],
        pm['element_attributes']['length'],
        vertical_spread_angle=spread_angle,
        gravity_dir="Fy",
        inplane_dir="Fx",
        out_of_plane_dir="Fz",
        magnitude_start_key="start_magnitude",
        magnitude_end_key="end_magnitude",
        location_start_key="start_loc",
        location_end_key="end_loc",
    )