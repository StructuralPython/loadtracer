from abc import ABC, abstractmethod
import io
from typing import Any, Optional
import pathlib


class AbstractAnalysisModel(ABC):
    """
    An abstract base class ("abc") to describe the interface required
    of any and all classes used as analysis models within loadtracer.

    'pm': A papermodels model (dict)
    'model': An attribute to store the analysis model while it is being used
    """
    pm: dict
    model: Optional[Any] = None

    def get_reactions(self, *args, **kwargs):
        raise NotImplementedError

    def dump_model(self, fp: Optional[io.StringIO] = None) -> Optional[dict]:
        """
        If 'fp' is None, then a dict is returned
        """
        raise NotImplementedError
    
    def load_model(self, fp: Optional[io.StringIO] = None, model_data: Optional[dict] = None): 
        raise NotImplementedError

    @classmethod
    def from_papermodel(self, filepath: Optional[str | pathlib.Path] = None, model_data: Optional[dict] = None):
        raise NotImplementedError
    
