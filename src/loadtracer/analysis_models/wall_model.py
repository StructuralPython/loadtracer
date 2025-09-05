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
        print(f"WALL MODEL: {self.pm['element_attributes']['tag']=}")
        self.model = build_linear_wall_model(self.pm, self.vertical_spread_angle)

    def get_reactions(self):
        reactions = self.model.get_reactions()
        print(reactions)
        return reactions
    
    def dump_model(self, filepath: Optional[str | pathlib.Path] = None, indent: int = 2) -> Optional[dict]:
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
        model_data: Optional[dict] = None
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
    wall_model = LinearWallModel(
        height=pm['element_attributes']['height'],
        length=pm['element_attributes']['length'],
        vertical_spread_angle=spread_angle,
        gravity_dir="Fy",
        inplane_dir="Fx",
        out_of_plane_dir="Fz",
        magnitude_start_key="start_magnitude",
        magnitude_end_key="end_magnitude",
        location_start_key="start_loc",
        location_end_key="end_loc",
    )
    for dist_load in pm['loads']['distributed_loads']:
        for dt in dist_load['expanded']:
            wall_model.add_dist_load(
                magnitude_start=dt['start_magnitude'],
                magnitude_end=dt['end_magnitude'],
                location_start=dt['start_loc'],
                location_end=dt['end_loc'],
                case=dt['case'],
                dir='Fy'
            )
    return wall_model
