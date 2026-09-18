"""
LoadTracer is a package that converts JSON output from papermodels
into analysis models. By default the frame member analysis models
are in PyNiteFEA and wall models are from loadbearing_wall.LinearWallModel.
"""

__version__ = "0.6.0"

from .errors import (
    AnalysisError,
    InvalidPapermodelError,
    LoadTracerError,
    LoadTracerWarning,
    ReactionNotFoundError,
    UnstableMemberError,
)
from .joist_load_conversion import JoistLoadVariabilityWarning, JoistTribWidthWarning
