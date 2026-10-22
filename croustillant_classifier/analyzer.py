"""
API publique : analyse d'un libellé brut tel que reçu du CROUS.

    from croustillant_classifier import Classifier

    clf = Classifier()                      # charge les tables figées (une fois)
    a = clf.analyse("Sauté de porc - 5 pts (1.3.7)", category="Plats")
    a.parsed.points            # 5.0
    a.components[0].key        # clé du plat canonique ("porc saute")
    a.components[0].type       # "PLAT"

Aucune dépendance, aucun réseau, aucun modèle : uniquement des règles et les
tables JSON de `resources/`, régénérées hors-ligne par `tools/`.

Le type renvoyé est le type *proposé* pour un plat canonique encore inconnu. Si la
clé existe déjà en base (PLAT_CANONIQUE), c'est le type stocké — éventuellement
revu — qui fait foi.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path

from .canon import Lexicon, split_plate, vegetarian_components
from .classify import category_type, decide, head, name_type
from .parse import KIND_DISH, Parsed, parse

import collections

VERSION = "2.1.0"


@dataclass
class Component:
    label: str                 # libellé affichable du composant
    key: str                   # clé du plat canonique
    type: str                  # type proposé (ENTREE, PLAT, …)
    confidence: float
    source: str                # name | section | menus | head | none
    vegetarian: bool
    review: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return bool(self.review)


@dataclass
class Analysis:
    parsed: Parsed
    components: list[Component]
    category_type: str | None  # type déduit de la catégorie du menu (None si vague)
    split: str | None          # séparateur utilisé pour découper un plateau
    version: str = VERSION

    @property
    def vegetarian(self) -> bool:
        """Le plat entier est végétarien (tous ses composants)."""
        return bool(self.components) and all(c.vegetarian for c in self.components)

    @property
    def is_dish(self) -> bool:
        return self.parsed.kind == KIND_DISH and bool(self.components)

    def to_dict(self) -> dict:
        return asdict(self)


class Classifier:
    def __init__(self, resources_dir: str | Path | None = None):
        base = Path(resources_dir) if resources_dir else resources.files("croustillant_classifier") / "resources"
        self.lexicon = Lexicon(**json.loads((base / "lexicon.json").read_text(encoding="utf-8")))
        self.head_rules: dict[str, str] = json.loads((base / "head_rules.json").read_text(encoding="utf-8"))

    def analyse(self, raw: str, category: str | None = None) -> Analysis:
        p = parse(raw)
        cat_t = category_type(category) if category else None
        if p.kind != KIND_DISH:
            return Analysis(p, [], cat_t, None)

        parts, sep = split_plate(p.name, self.lexicon)
        vegs = vegetarian_components(parts, p.vegetarian, p.veg_scope, p.veg_anchors)
        comps = []
        for i, part in enumerate(parts):
            veg = vegs[i]
            key = self.lexicon.key(part, vegetarian=veg)
            if not key:
                continue
            # une seule occurrence : la catégorie ne vote que pour le plat principal, avec le
            # poids minimal qu'il faut pour être prise en compte par `decide`
            votes = collections.Counter({cat_t: 2}) if cat_t and i == 0 else collections.Counter()
            t, conf, src, review = decide(votes, name_type(part), self.head_rules.get(head(part)),
                                          p.section_hint if i == 0 else None)
            if t == "INFO":
                # servi dans une catégorie d'information : on garde la trace, pas un plat
                p.kind, p.info_kind = "INFO", "CATEGORY"
                return Analysis(p, [], cat_t, sep)
            comps.append(Component(part, key, t, conf, src, veg, review))
        return Analysis(p, comps, cat_t, sep)

    def key(self, name: str, vegetarian: bool = False) -> str:
        return self.lexicon.key(name, vegetarian)


# --------------------------------------------------------------------------- #
# Type d'une occurrence (plat servi dans une catégorie donnée)
# --------------------------------------------------------------------------- #

# Réinterprétations acceptées : (type par défaut du plat, type de la catégorie).
# Une pizza servie en "Entrées" est une entrée ce jour-là ; une purée servie en
# "Plats" reste un accompagnement (les sites rangent souvent leurs garnitures là).
# ⚠ Doit rester identique au CASE de la vue V_COMPOSITION_TYPEE (schema.sql de CROUStillant).
OCCURRENCE_OVERRIDES = {
    ("PLAT", "ENTREE"), ("ENTREE", "PLAT"),
    ("DESSERT", "BOISSON"),                      # "Orange" en boissons = jus d'orange
    ("DESSERT", "FROMAGE"), ("FROMAGE", "DESSERT"),
}


def occurrence_type(default_type: str, category: str | None, main_component: bool = True) -> str:
    cat_t = category_type(category) if category else None
    if main_component and cat_t and (default_type, cat_t) in OCCURRENCE_OVERRIDES:
        return cat_t
    return default_type
