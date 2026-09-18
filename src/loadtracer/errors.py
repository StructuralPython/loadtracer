"""
Exceptions and warnings raised by loadtracer.

Every error raised while processing a member carries that member's tag so
that a failure deep in a load rundown can be traced back to the drawing.
"""

from typing import Optional


class LoadTracerError(Exception):
    """
    Base class for all loadtracer errors.

    'tag': The tag of the member being processed when the error occurred
    """

    def __init__(self, message: str, tag: Optional[str] = None):
        self.tag = tag
        prefix = f"Member {tag}: " if tag is not None else ""
        super().__init__(f"{prefix}{message}")


class ReactionNotFoundError(LoadTracerError):
    """
    A member receives a load from a source member whose reactions are not
    available (the source was excluded, failed, or has no such reaction index).
    """


class UnstableMemberError(LoadTracerError):
    """
    A member cannot be analyzed because its supports do not make it stable
    (e.g. a beam with fewer than two supports).
    """


class InvalidPapermodelError(LoadTracerError):
    """
    A papermodel dict does not have the shape or values that loadtracer expects.
    """


class AnalysisError(LoadTracerError):
    """
    The analysis model of a member could not be built or solved.
    """


class LoadTracerWarning(UserWarning):
    """
    Base class for loadtracer warnings. Issued for input that loadtracer can
    process but that the designer should review.
    """
