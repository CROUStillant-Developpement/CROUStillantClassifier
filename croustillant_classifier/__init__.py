"""
CROUStillant Classifier — nettoyage, dédoublonnage et typage des plats du CROUS.

    from croustillant_classifier import Classifier
    a = Classifier().analyse("Endives aux lardons 2 pts", category="Entrées")
"""

from .analyzer import VERSION, Analysis, Classifier, Component, occurrence_type
from .classify import TYPES, category_type
from .parse import Parsed, parse

__all__ = ["VERSION", "Analysis", "Classifier", "Component", "Parsed", "TYPES",
           "category_type", "occurrence_type", "parse"]
__version__ = VERSION
