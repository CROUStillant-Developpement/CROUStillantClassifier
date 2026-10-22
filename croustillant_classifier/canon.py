"""
Étape 2/3 — Découpage des plateaux et clé canonique d'un plat.

La clé canonique est déterministe : deux libellés ayant la même clé sont le même
plat. Elle ignore la casse, les accents, l'ordre des mots, les mots outils
("à la", "aux", "sauce"…), les étiquettes (maison, bio), les quantités, le
pluriel, les abréviations et les fautes de frappe connues.

    "Poulet à la basquaise" / "Poulet basquaise" / "POULET BASQUAISE (maison)"
        → "basquaise poulet"

Les deux tables apprises sur le corpus (corrections orthographiques, plats
connus servant à valider un découpage) sont figées dans `Lexicon` pour être
rechargées telles quelles en production.
"""

from __future__ import annotations

import collections
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .parse import fold


# --------------------------------------------------------------------------- #
# Tokenisation
# --------------------------------------------------------------------------- #

STOPWORDS = {
    "a", "au", "aux", "de", "d", "des", "du", "en", "et", "avec", "le", "la", "les", "l",
    "sa", "son", "ses", "sur", "un", "une", "facon", "style", "sauce", "sc", "maison",
    "bio", "fait", "accompagne", "accompagnee", "servi", "servie", "garni", "garnie",
    "petit", "petite", "petits", "petites", "notre", "nos", "recette", "nouveau",
    "igp", "aop", "coupelle", "portion", "barquette", "pot",
}
# Marqueur ajouté à la clé d'un plat annoncé végétarien : "Burger VG" ≠ "Burger".
VEG_MARK = "~vg"
NUMBER_WORDS = {"deux": "2", "trois": "3", "quatre": "4", "cinq": "5", "six": "6", "sept": "7",
                "huit": "8", "neuf": "9", "dix": "10"}
# abréviations : remplacées avant découpage en mots
ABBREVIATIONS = [
    (r"\bp\.?\s*d\.?\s*t\.?\b|\bpdts?\b|\bpom\.?\s+de\s+terre\b", "pommes de terre"),
    (r"\bbbq\b", "barbecue"),
    (r"\bs/\s*", "sauce "),
    (r"\bcte\b", "cote"),
    (r"\bvol\.\b", "volaille"),
    (r"\bfrom\.\b", "fromage"),
    (r"\bchoco\b", "chocolat"),
    (r"\bmozza\b", "mozzarella"),
    (r"\bspag(h)?(s|etti|ettis|hettis?)?\b", "spaghetti"),
    (r"\boeuf\b", "oeuf"),
]
_ABBR = [(re.compile(a), b) for a, b in ABBREVIATIONS]
# "pâté" (charcuterie) ≠ "pâtes" (pâtes alimentaires) : la distinction disparaît une
# fois les accents retirés, on la fige donc avant le pliage.
_PATE_CHARCUTERIE = re.compile(
    r"\bp[aâ]t[eé]s?\b(?=\s+(de\s+(campagne|foie|lapin|volaille|canard|porc|t[eê]te)|en\s+cro[uû]te|"
    r"cro[uû]te|lorrain|henaff|forestier|breton|basque))"
    r"|\bp[aâ]t[éÉ]s?\b", re.I)


def tokens(name: str) -> list[str]:
    text = _PATE_CHARCUTERIE.sub(" patecharcuterie ", name)
    text = fold(text)
    for rx, repl in _ABBR:
        text = rx.sub(repl, text)
    out = []
    for i, tok in enumerate(re.findall(r"[a-z0-9]+", text)):
        tok = NUMBER_WORDS.get(tok, tok)
        if tok in STOPWORDS:
            continue
        if tok.isdigit() and i == 0:        # quantité en tête : "2 nems"
            continue
        if re.fullmatch(r"x\d+|\d+x|\d+g|\d+cl|\d+ml|\d+(e|eme)", tok):
            continue
        out.append(singular(tok))
    return out


def singular(tok: str) -> str:
    if len(tok) > 3 and tok[-1] in "sx" and not tok.endswith(("ss", "us", "is", "os")):
        tok = tok[:-1]
    return tok


# --------------------------------------------------------------------------- #
# Lexique appris sur le corpus
# --------------------------------------------------------------------------- #

def _edits1(w: str) -> set[str]:
    letters = "abcdefghijklmnopqrstuvwxyz"
    splits = [(w[:i], w[i:]) for i in range(len(w) + 1)]
    return ({a + b[1:] for a, b in splits if b}
            | {a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1}
            | {a + c + b[1:] for a, b in splits if b for c in letters}
            | {a + c + b for a, b in splits for c in letters})


@dataclass
class Lexicon:
    typos: dict[str, str] = field(default_factory=dict)   # token rare → token fréquent
    known: dict[str, int] = field(default_factory=dict)   # clé → nb de libellés entiers

    # --- construction ---------------------------------------------------- #
    @classmethod
    def build(cls, names: list[str], dictionary: set[str] = frozenset(), min_known: int = 3) -> "Lexicon":
        """
        `dictionary` : mots français pliés (fold). Un mot du dictionnaire n'est jamais
        "corrigé", même s'il est rare : "canaille" ne doit pas devenir "vanille".
        """
        freq = collections.Counter(t for n in names for t in tokens(n))
        typos = {}
        for tok, n in freq.items():
            if n > 3 or len(tok) < 5 or tok.isdigit():
                continue
            if tok in dictionary or tok + "s" in dictionary or tok + "x" in dictionary:
                continue
            cands = [c for c in _edits1(tok) if freq.get(c, 0) >= max(20, 10 * n)]
            if len(tok) >= 8 and not cands:
                cands = [c2 for c1 in _edits1(tok) for c2 in _edits1(c1)
                         if freq.get(c2, 0) >= max(50, 25 * n)]
            if cands:
                typos[tok] = max(cands, key=freq.__getitem__)
        lex = cls(typos=typos)
        lex.known = dict(collections.Counter(lex.key(n) for n in names if lex.key(n)))
        lex.known = {k: v for k, v in lex.known.items() if v >= min_known}
        return lex

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"typos": self.typos, "known": self.known},
                                   ensure_ascii=False, indent=0), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Lexicon":
        return cls(**json.loads(path.read_text(encoding="utf-8")))

    # --- usage ------------------------------------------------------------ #
    def key(self, name: str, vegetarian: bool = False) -> str:
        toks = {self.typos.get(t, t) for t in tokens(name)}
        if vegetarian and toks:
            toks.add(VEG_MARK)
        return " ".join(sorted(toks))

    def is_known(self, name: str) -> bool:
        return self.key(name) in self.known


def vegetarian_components(parts: list[str], vegetarian: bool, scope: str | None,
                          anchors: list[str]) -> list[bool]:
    """
    Composants concernés par une mention végétarienne.

    - "Plat végétarien : boulgour, carotte" / "…, riz, veggie" (portée ALL) → tous ;
    - "Cordon bleu, falafel de pois chiche (vg)" → seulement l'élément qui porte la mention ;
    - mention dont l'élément est introuvable → aucun (mieux vaut ne rien affirmer que de
      déclarer végétarien un cordon bleu).
    """
    if not vegetarian:
        return [False] * len(parts)
    if scope == "ALL" or len(parts) == 1:
        return [True] * len(parts)
    anchor_toks = {t for a in anchors for t in tokens(a)}
    return [bool(set(tokens(part)) & anchor_toks) for part in parts]


# --------------------------------------------------------------------------- #
# Découpage des plateaux
# --------------------------------------------------------------------------- #

# Un libellé qui commence par un "contenant" décrit un seul plat composé : ce qui
# suit est sa garniture, pas d'autres plats ("Salade de blé/tomates/maïs").
CONTAINERS = re.compile(
    r"^(salade|assiette|duo|trio|po[eê]l[eé]e|m[eé]lange|panach[eé]|wrap|sandwich|panini|pizza|bowl|"
    r"poke|tarte|tartine|quiche|galette|cr[eê]pe|croque|burger|bagel|gratin|brochette|crumble|"
    r"velout[eé]|soupe|potage|cr[eè]me|pur[eé]e|jus|smoothie|cocktail|plateau|box|bun|tacos|wok|"
    r"club|baguette|pain|fajitas?|burrito|quesadilla|lasagnes?|tian|cake|muffin|cookie|coupe|"
    r"verrine|bo[iî]te|barquette|formule|menu|buddha|bento|bibimbap|couscous|paella|tajine|"
    r"risotto|omelette|clafoutis|flan|yaourt|fromage\s+blanc|compot[eé]e?|macédoine|macedoine|"
    r"jardini[eè]re|ratatouille|piperade|chili|curry|blanquette|pot[eé]e|choucroute|cassoulet|"
    r"assortiment|plancha|piqu[eé]|sushi|maki|nems?|samoussas?)\b", re.I)

SEPARATORS = [
    ("alt", re.compile(r"\s+ou\s+|\s*\bou\b\s*/|\s*/\s*ou\s+", re.I)),
    ("plus", re.compile(r"\s*\+\s*")),
    ("comma", re.compile(r"\s*[,;]\s*")),
    ("slash", re.compile(r"\s*/\s*")),
    ("dash", re.compile(r"\s+-\s+")),
]


_SAUCE = re.compile(r"^(sauce|jus|coulis|nappage|vinaigrette)\b", re.I)


def _expand_ellipsis(first: str, part: str, lex: Lexicon) -> str:
    """"Éclair vanille ou chocolat" : "chocolat" → "Éclair chocolat" si ce plat existe."""
    fw = first.split()
    if len(part.split()) == 1 and len(fw) >= 2:
        cand = " ".join(fw[:-1] + [part])
        if lex.key(cand) != lex.key(part) and lex.is_known(cand):
            return cand
    return part


def split_plate(name: str, lex: Lexicon) -> tuple[list[str], str | None]:
    """
    Découpe un libellé en composants si — et seulement si — chaque morceau est
    lui-même un plat connu. Renvoie (composants, séparateur utilisé ou None).
    """
    if CONTAINERS.match(name) or not re.search(r"[,/;+]|\s-\s|\bou\b", name, re.I):
        return [name], None
    for label, rx in SEPARATORS:
        parts = [p.strip(" .-") for p in rx.split(name) if p.strip(" .-")]
        if len(parts) < 2:
            continue
        if label in ("alt", "slash"):
            parts = parts[:1] + [_expand_ellipsis(parts[0], p, lex) for p in parts[1:]]
        # découpage récursif : "Poisson pané, riz / ratatouille"
        flat: list[str] = []
        for part in parts:
            sub, _ = split_plate(part, lex)
            flat.extend(sub)
        if all(lex.is_known(p) for p in flat):
            # une sauce appartient au plat qui la précède : "Boulette agneau, sauce moutarde"
            merged: list[str] = []
            for p in flat:
                if merged and _SAUCE.match(p):
                    merged[-1] = f"{merged[-1]} {p[:1].lower()}{p[1:]}"
                else:
                    merged.append(p)
            if len(merged) == 1:
                return merged, label + "+sauce"
            return [p[:1].upper() + p[1:] for p in merged], label
    return [name], None
