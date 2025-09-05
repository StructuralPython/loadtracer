from dataclasses import dataclass
import pathlib
from typing import Optional, Any, Union
import io

from .analysis_model import AbstractAnalysisModel
from .concentric_column import concentric_column as cc



@dataclass
class PointColumn(AbstractAnalysisModel):
    pm: dict
    model: Optional[cc.ConcentricColumn]

    def __post_init__(self):
        self.model = build_column_model(self.pm)

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
            return cc.ConcentricColumn.from_json(filepath)
        else:
            return cc.ConcentricColumn.from_dict(model_data)
        

def build_column_model(pm: dict) -> cc.ConcentricColumn:
    """
    Returns a LinearWallModel based on the data within 'pm'
    """
    column = cc.ConcentricColumn(
        pm['element_attributes']['height'],
        gravity_dir="Fx",
        strong_axis_dir="Fy",
        weak_axis_dir="Fz",
        reverse_reaction_sign=False
    )
    for point_load in pm['loads']['point_loads']:
        for pt_component in point_load['expanded']:
            column.add_point_load(**pt_component)
    return column

