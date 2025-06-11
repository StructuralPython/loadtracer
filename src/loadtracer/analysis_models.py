from dataclasses import dataclass
from typing import Optional, Any, Union

from . import beams
from . import linear_reactions as lr
from . import point_reactions as pr

@dataclass
class BeamModel:
    structured_beam_toml: dict
    model: Optional["FEModel3D"] = None

    def __post_init__(self):
        self.model = beams.build_toml_beam(self.structured_beam_toml)

    def get_reactions(self):
        self.model.analyze()
        member_reactions = beams.get_node_reactions(self.model)
        return member_reactions
    

@dataclass
class LinearWallModel:
    structured_beam_toml: dict
    model: Optional[lr.LinearReactionString] = None

    def __post_init__(self):
        applied_dist_loads = {}
        for dist_load in self.structured_beam_toml['loads']['distributed_loads']:
            applied_dist_load = {
                "x0": dist_load['start_loc'],
                "x1": dist_load['end_loc'],
                "w0": dist_load['start_magnitude'],
                "w1": dist_load['end_magnitude'],
            }
            applied_dist_loads.append(applied_dist_load)
        self.model = lr.LinearReactionString(applied_dist_loads)


    def get_reactions(self):
        reactions = {}
        for 
        return self.model(0, self.structured_beam_toml['element_attributes']['length'])
    

@dataclass
class ColumnModel:
    structured_beam_toml: dict
    model: Optional[pr.PointReactionCollection] = None

    def __post_init__(self):
        self.model = pr.PointReactionCollection.from_point_loads(
            self.structured_beam_toml['loads']['point_loads']
        )

    def get_reactions(self, case: str, load_dir: str):
        return self.model.extract_reactions(case, load_dir)

