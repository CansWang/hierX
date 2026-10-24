"""D2-authored architecture presentation, separate from extraction graphs."""

from .model import ArchitectureDocument, ArchitectureError
from .service import load_architecture

__all__ = ["ArchitectureDocument", "ArchitectureError", "load_architecture"]
