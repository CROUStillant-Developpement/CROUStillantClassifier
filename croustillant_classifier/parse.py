"""
Étape 1 — Parsing déterministe d'un libellé brut de plat.

Aucune dépendance externe, aucun modèle : chaque information parasite (points,
prix, allergènes, origine, régime, préfixe de section…) est *extraite* dans un
champ dédié au lieu d'être supprimée, et le reste devient le nom nettoyé.

    >>> p = parse("Sauté de porc aux pruneaux - 5 pts (1.3.7)")
    >>> p.name, p.points, p.allergen_ids
    ('Sauté de porc aux pruneaux', 5.0, [1, 3, 7])
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, asdict


# --------------------------------------------------------------------------- #
# Résultat
# --------------------------------------------------------------------------- #

KIND_DISH = "DISH"            # un vrai plat (ou un plateau à découper plus tard)
KIND_INFO = "INFO"            # information : fermeture, application, horaires…
KIND_PRICE_ONLY = "PRICE"     # "4.50 €" seul : se rattache à la ligne précédente
KIND_ALLERGEN_ONLY = "ALLERGENS"  # "(1.3.7.8)" seul : idem
KIND_JUNK = "JUNK"            # séparateurs, "Et", "OU", ".." …


@dataclass
class Parsed:
    raw: str
    kind: str = KIND_DISH
    name: str = ""                       # libellé nettoyé, casse "phrase"
    points: float | None = None
    points_note: str | None = None       # ex. "2 pour 1 point", "supplément"
    prices: list[float] = field(default_factory=list)
    allergen_ids: list[int] = field(default_factory=list)
    origins: list[str] = field(default_factory=list)   # "France", "Réunion"…
    labels: list[str] = field(default_factory=list)    # bio, maison, msc, bbc, vf…
    meats: list[str] = field(default_factory=list)     # porc, bœuf… (annoncés)
    vegetarian: bool = False
    details: list[str] = field(default_factory=list)   # "(chorizo, poivrons)" : description
    section_hint: str | None = None      # type suggéré par un préfixe ("Dessert : …")
    station: str | None = None           # "chaîne étudiants", "barquette"…
    info_kind: str | None = None         # CLOSURE, APP, NOTICE…
    flags: list[str] = field(default_factory=list)     # anomalies pour la revue

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Normalisation de base
# --------------------------------------------------------------------------- #

_WS = re.compile(r"\s+")
_QUOTES = str.maketrans({"’": "'", "‘": "'", "´": "'", "`": "'", "“": '"', "”": '"',
                         "–": "-", "—": "-", "…": "...", " ": " ", " ": " "})


def fold(text: str) -> str:
    """Minuscules sans accents — pour les comparaisons, jamais pour l'affichage."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.replace("œ", "oe").replace("æ", "ae")


def _base(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_QUOTES)
    return _WS.sub(" ", text).strip()


# --------------------------------------------------------------------------- #
# Informations (pas des plats)
# --------------------------------------------------------------------------- #

_INFO_RULES: list[tuple[str, re.Pattern]] = [
    ("CLOSURE", re.compile(
        r"\b(structure|restaurant|resto|cafeteria|cafet|site|self|ilot|stand|service|ru)\s+"
        r"(est\s+)?ferm[eé]e?s?\b"
        r"|^ferm[eé]e?s?\b|\bfermeture\b|\bferm[eé]e?s?\s+(le|du|les|ce|pour|jusqu|a\s+partir|exceptionnellement|aujourd)"
        r"|\br[eé]ouverture\b|\bvacances\b|\bcong[eé]s?\b|\bpas\s+de\s+(service|restauration|repas)\b"
        r"|\bgr[eè]ve\b|\bjour\s+f[eé]ri[eé]\b|\btravaux\b|exceptionnellement\s+ferm|\bferm[eé]e?s?\s*[.!]*$"
        r"|\bpas\s+de\s+prestations?\b"
        r"|\b(is|are|will\s+be)\s+closed\b|\bclosed\s+(on|from|until|today)\b"
        r"|\b(est|sont)\s+(en\s+(r[eé]paration|panne)|indisponibles?|hors\s+service)\b", re.I)),
    ("APP", re.compile(r"t[eé]l[eé]charge[zr]?|\bapplication\b|\bappli\b|\bizly\b|\bqr\s*code\b|\bclick\s*(and|&|n)\s*collect\b", re.I)),
    ("NOTICE", re.compile(
        r"susceptibles?\s+d.[eê]tre\s+modifi|\bselon\s+(les\s+)?arrivages?\b|\bsous\s+r[eé]serve\b"
        r"|\bbon\s+app[eé]tit\b|\bmenu\s+non\s+communiqu|\bnon\s+communiqu|\b[aà]\s+venir\b"
        r"|\bliste\s+des\s+allerg|\ballerg[eè]nes?\s*:|\bhoraires?\b|\bouvert(ure)?\s+(de|du|le|à|a|jusqu)"
        r"|\bpour\s+les\s+[eé]tudiants\b|\bsur\s+pr[eé]sentation\b|\btarif\b"
        r"|\bpas\s+de\s+menu\b|\baucun\s+menu\b|\bmenu\s+(du\s+jour\s+)?(indisponible|non\s+disponible)"
        r"|\bbonnes?\s+app[eé]tit\b|\brdv\b|\bpromo(tion)?\b|\bpas\s+de\s+\w+\s+ce\s+jour\b"
        r"|\b\d{1,2}\s*h\s*\d{0,2}\s*(-|[aà]\b|jusqu)|\b(de|d[eè]s|[aà]\s+partir\s+de|avant|apr[eè]s)\s+\d{1,2}\s*h\b"
        r"|^(le\s+)?(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)s?\b"
        r"(?!.*\b(poulet|boeuf|bœuf|porc|poisson|p[aâ]tes|riz|salade|frites|pizza)\b)"
        r"|^(uniquement|sauf|seulement)\s+le\b"
        r"|\bau\s+choix\s+parmi\b|\blarge\s+choix\b|\bsont\s+([eé]galement\s+)?propos[eé]s\b", re.I)),
    # phrase adressée aux convives : "Notre équipe sera ravie de vous accueillir…"
    ("NOTICE", re.compile(r"^(?=.{30,}).*\b(vous|nous|notre|votre|vos|nos|[eé]quipe)\b", re.I)),
]

_NAMED_ALLERGENS = {
    "gluten": 1, "ble": 1, "crustace": 2, "crustaces": 2, "oeuf": 3, "oeufs": 3, "poisson": 4,
    "poissons": 4, "arachide": 5, "arachides": 5, "soja": 6, "lait": 7, "lactose": 7,
    "fruits a coque": 8, "fruit a coque": 8, "fruits secs": 8, "celeri": 9, "moutarde": 10,
    "sesame": 11, "sulfite": 12, "sulfites": 12, "lupin": 13, "mollusque": 14, "mollusques": 14,
}
_NAMED_ALLERGEN_LINE = re.compile(r"^\(?\s*allerg[eè]nes?\s*:?\s*([^()]*)\)?$", re.I)


def _info_kind(text: str) -> str | None:
    for kind, rx in _INFO_RULES:
        if rx.search(text):
            return kind
    return None


# --------------------------------------------------------------------------- #
# Allergènes : "(1.3.7)", "(1-3-7)", "(1,3,7)", "(7)", "(allergènes : 1, 7)"
# --------------------------------------------------------------------------- #

_ALLERGEN_GROUP = re.compile(
    r"[\(\[]\s*(?:allerg[eè]nes?\s*:?\s*)?((?:\d{1,4}\s*[.,;\-/ ]\s*)*\d{1,4})\s*[.,]?\s*[\)\]]", re.I)


def _split_codes(group: str) -> list[int] | None:
    """Renvoie les ids 1..14, en réparant "910" → 9,10 ; None si ce n'en est pas."""
    out: list[int] = []
    for tok in re.findall(r"\d+", group):
        n = int(tok)
        if 1 <= n <= 14:
            out.append(n)
        elif len(tok) in (3, 4):          # chiffres collés : 910, 1011, 1112
            for a in range(1, len(tok)):
                l, r = int(tok[:a]), int(tok[a:])
                if 1 <= l <= 14 and 1 <= r <= 14 and tok[a] != "0":
                    out += [l, r]
                    break
            else:
                return None
        else:
            return None
    return out


# --------------------------------------------------------------------------- #
# Points : "4 pts", "(4pts)", "- 5 points", "4p", "( 4 points )", "supplément 2 points",
#          "(2 pour 1 point)", "4 points+", et un entier nu final "Omelette 4"
# --------------------------------------------------------------------------- #

_NUM = r"(\d+(?:[.,]5)?)"
_POINTS = re.compile(
    rf"[\(\[]?\s*[-/,]?\s*(?P<supp>suppl[eé]ment(?:aire)?s?\s*:?\s*\+?\s*)?"
    rf"(?:(?P<qty>\d+)\s*pour\s*)?{_NUM}\s*(?:pts?|points?|ps|pt?s?\.)(?=[\s\)\].,;:+/\-]|$)\.?\s*\+?\s*"
    rf"(?:suppl[eé]ment(?:aire)?s?)?\s*[\)\]]?", re.I)
# "4p" seulement en fin de chaîne (sinon trop ambigu)
_POINTS_P = re.compile(rf"\s*[-/,]?\s*\(?\s*{_NUM}\s*p\s*\)?\s*$", re.I)
# entier nu en fin de libellé, après un mot ("Omelette au fromage 4")
_TRAILING_INT = re.compile(r"(?<=[a-zà-ÿœ\)])\s*[-/]?\s+([1-9])\s*$", re.I)


# --------------------------------------------------------------------------- #
# Prix : "4.50 €", "3,80€ HT", "à 1 €", "2 euros"
# --------------------------------------------------------------------------- #

_PRICE = re.compile(
    r"[\(\[]?\s*[-:,]?\s*(?:[aà]\s+)?(\d+(?:[.,]\d{1,2})?)\s*(?:€|euros?\b|eur\b)\s*(?:ht|ttc)?\s*[\)\]]?", re.I)


# --------------------------------------------------------------------------- #
# Attributs entre parenthèses ou en fin de libellé
# --------------------------------------------------------------------------- #

_VEG = r"v[eé]g[eé]?(?:tarien(?:ne)?s?)?|veggie|vg|vgt|sans\s+viande|plat\s+v[eé]g[eé]tarien|v[eé]gan|v[eé]g[eé]talien(?:ne)?"
_MEATS = {"porc": "porc", "boeuf": "bœuf", "bœuf": "bœuf", "veau": "veau", "volaille": "volaille",
          "poulet": "poulet", "dinde": "dinde", "agneau": "agneau", "viande": "viande", "poisson": "poisson"}
_COUNTRIES = ("france", "réunion", "reunion", "pologne", "espagne", "irlande", "union européenne",
              "union europeenne", "ue", "ce", "belgique", "allemagne", "pays-bas", "italie", "brésil",
              "bresil", "nouvelle-zélande", "nouvelle zelande", "royaume-uni", "thaïlande", "thailande",
              "europe", "hors ue", "danemark", "uruguay", "argentine", "chili", "vietnam", "chine",
              "madagascar", "maurice", "guadeloupe", "martinique", "guyane", "mayotte")
_COUNTRIES_F = {fold(c) for c in _COUNTRIES}
_ORIGIN_ABBR = {"fr": "France", "vf": "France", "vbf": "France", "vpf": "France",
                "vvf": "France", "vof": "France", "ue": "Union européenne"}
_LABELS = {"bio": "bio", "ab": "bio", "maison": "maison", "fait maison": "maison", "msc": "msc",
           "asc": "asc", "bbc": "bleu-blanc-cœur", "bleu blanc coeur": "bleu-blanc-cœur",
           "bleu-blanc-cœur": "bleu-blanc-cœur", "label rouge": "label rouge", "lr": "label rouge",
           "aop": "aop", "igp": "igp", "hve": "hve", "local": "local", "halal": "halal",
           "sans porc": "sans porc", "fermier": "fermier", "plein air": "plein air",
           "de saison": "de saison", "selon disponibilité": "selon disponibilité",
           "selon disponibilite": "selon disponibilité", "au choix": "au choix",
           "plat complet": "plat complet", "plat unique": "plat complet", "nouveau": "nouveau",
           "nouveauté": "nouveau", "fait maison": "maison", "recette maison": "maison"}

_PAREN = re.compile(r"\s*[\(\[]([^()\[\]]*)[\)\]]")


def _classify_paren(inner: str, p: Parsed) -> bool:
    """Absorbe le contenu d'une parenthèse s'il s'agit d'une méta-donnée."""
    f = fold(inner).strip(" .,;:-*")
    if not f:
        return True
    parts = [x.strip(" .") for x in re.split(r"\s*[/,;]\s*|\s+-\s+|\s+et\s+", f) if x.strip(" .")]
    absorbed = True
    for part in parts:
        if re.fullmatch(_VEG, part):
            p.vegetarian = True
        elif part in _MEATS:
            p.meats.append(_MEATS[part])
        elif m := re.fullmatch(r"(?:(?:viande|porc|boeuf|volaille|poulet)\s+)?(?:d'\s*)?(?:origine|orig\.?|provenance)\s*:?\s*(.+)", part):
            o = m.group(1).strip()
            p.origins.append("France" if o.startswith(("francaise", "francais", "fr")) else o.title())
        elif m := re.fullmatch(r"label\s+(.+)", part):
            p.labels.append(_LABELS.get(m.group(1), m.group(1)))
        elif part in ("hors formule", "en supplement", "supplement"):
            p.labels.append(part)
        elif part in _NAMED_ALLERGENS:
            p.allergen_ids.append(_NAMED_ALLERGENS[part])
        elif part in _ORIGIN_ABBR:
            p.origins.append(_ORIGIN_ABBR[part])
        elif part in _COUNTRIES_F:
            p.origins.append(part.title())
        elif part in _LABELS:
            p.labels.append(_LABELS[part])
        elif m := re.fullmatch(r"(porc|boeuf|bœuf|veau|volaille|poulet|dinde|agneau)\s+(fr|ue|france)", part):
            p.meats.append(_MEATS[m.group(1)]); p.origins.append(_ORIGIN_ABBR.get(m.group(2), "France"))
        else:
            absorbed = False
    return absorbed


# --------------------------------------------------------------------------- #
# Préfixes "Xxx : …"
# --------------------------------------------------------------------------- #

# préfixes de section : on les retire et ils donnent un indice de type
_SECTION_PREFIX: list[tuple[str, str]] = [
    (r"entr[eé]es?(\s+(chaudes?|froides?))?|hors\s*d.?oeuvres?", "ENTREE"),
    (r"(autres?\s+)?plats?(\s+(du\s+jour|chauds?|principal|principaux|garnis?))?|plat\s+unique|grill(ade)?s?|chaud", "PLAT"),
    (r"accompagnements?|garnitures?|l[eé]gumes?", "ACCOMPAGNEMENT"),
    (r"desserts?(\s+suppl[eé]ment)?|douceurs?|p[aâ]tisseries?(\s+am[eé]ricaines?)?", "DESSERT"),
    (r"fromages?|produits?\s+laitiers?|laitages?", "FROMAGE"),
    (r"boissons?(\s+(chaudes?|froides?))?", "BOISSON"),
    (r"soupe\s+du\s+jour|potages?|soupes?", "ENTREE"),
    (r"formule(\s+[a-zéè]+)?|menu\s+[eé]tudiants?|hors\s+formule", "FORMULE"),
    (r"fruits?", "DESSERT"),
]
# préfixes de régime
_DIET_PREFIX = re.compile(rf"^(?:(?:plats?|options?|menus?|alternatives?|propositions?)\s+)?(?:{_VEG})\s*[:\-]\s*", re.I)
# préfixes de chaîne / stand : retirés, conservés dans `station`
_STATION_PREFIX = re.compile(
    r"^'?\s*(cha[iî]ne\s+(?:personnels?|perso|[eé]tudiant(?:e|s|es)?|[a-z0-9]+)|personnels?|[eé]tudiants?|"
    r"barquette|salade\s+bar|stand\s+\w+|ligne\s+\w+|p[oô]le\s+\w+|[iî]lot\s+\w+|bio|snack|"
    r"suppl[eé]ments?|prix|nouveau(?:t[eé])?|sp[eé]cialit[eé]\s+du\s+chef|le\s+chef\s+vous\s+propose)\s*:\s*", re.I)
# "Pizza : 4 fromages" → "Pizza 4 fromages" (le préfixe fait partie du nom)
_MERGE_PREFIX = re.compile(
    r"^(pizza|p[aâ]tes|panini|wrap|burger|bagel|sandwich|salade|quiche|tarte|croque|galette|cr[eê]pe|"
    r"omelette|poisson|viande|bowl|poke|box|bun|tacos|wok|risotto|gratin|curry|tartine|bruschetta|"
    r"le\s+wrap|la\s+baguettine|baguettine|hot\s*dog|kebab|club)\s*:\s*", re.I)


_CONNECTOR = re.compile(r"^(?:\s*(?:ou\s+bien|ou\s+alors|ou|et|avec|au\s+choix|d'une?|\+)\b\s*:?\s*)+", re.I)


def _strip_prefixes(text: str, p: Parsed) -> str:
    for _ in range(3):                    # préfixes empilés : "Chaîne étudiants : Plat végétarien : …"
        before = text
        if m := _STATION_PREFIX.match(text):
            p.station = fold(m.group(1)).strip()
            text = text[m.end():]
        if m := _DIET_PREFIX.match(text):
            p.vegetarian = True
            text = text[m.end():]
        if ":" in text:
            head, tail = text.split(":", 1)
            fh = fold(head).strip(" '\"")
            for rx, kind in _SECTION_PREFIX:
                if re.fullmatch(rx, fh) and tail.strip():
                    p.section_hint = p.section_hint or kind
                    if kind != "FORMULE":     # "Menu étudiant : sandwich + yaourt" reste entier
                        text = tail
                    break
        if m := _MERGE_PREFIX.match(text):
            text = m.group(1) + " " + text[m.end():]
        text = text.strip()
        if text == before:
            break
    return text


# --------------------------------------------------------------------------- #
# Mise en forme finale
# --------------------------------------------------------------------------- #

_LEADING_JUNK = re.compile(r"^[\s\-*•·.,;:/+>_=~#'\"]+")
_TRAILING_JUNK = re.compile(r"[\s\-*•·,;:/+>_=~#'\"(]+$")
_SPACE_PUNCT = re.compile(r"\s+([,.)])")
_PUNCT_SPACE = re.compile(r"([,])(?=\S)")
_OPEN_SPACE = re.compile(r"\(\s+")
_SLASH = re.compile(r"\s*/\s*")


def _sentence_case(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6:
        text = text.lower()               # "POULET BASQUAISE" → "poulet basquaise"
    return text[:1].upper() + text[1:] if text else text


def _finish(text: str) -> str:
    text = _OPEN_SPACE.sub("(", text)
    text = _SPACE_PUNCT.sub(r"\1", text)
    text = _PUNCT_SPACE.sub(r"\1 ", text)
    text = _SLASH.sub("/", text)
    text = text.replace("()", "").replace("[]", "")
    # guillemets simples isolés ("Endives au 'bleu") mais pas les apostrophes ("à l'ail")
    text = re.sub(r"(?<![a-zà-ÿœ])'|'(?![a-zà-ÿœ])", " ", text, flags=re.I)
    # parenthèse orpheline : "Fruit)", "(sandwich"
    if text.count("(") != text.count(")"):
        text = text.replace("(", " ").replace(")", " ")
    text = _WS.sub(" ", text)
    for _ in range(3):
        text = _LEADING_JUNK.sub("", text)
        text = _TRAILING_JUNK.sub("", text)
        text = text.rstrip(".")
    return _sentence_case(text.strip())


# "Plat du jour", "Végé du jour", "Laitage" : un plat réel mais au contenu inconnu
_GENERIC = re.compile(
    r"(plats?|vege(tarien)?|legumes?|laitages?|desserts?|entrees?|potages?|soupes?|poissons?|viandes?|"
    r"fruits?|fromages?|patisseries?|garnitures?|accompagnements?|salades?|suggestions?|specialites?|"
    r"crudites?|yaourts?)(\s+(vegetariens?|chauds?|froids?))?"
    r"(\s+(du|de|de la|de\s+saison|au\s+choix)(\s+(jour|semaine|moment|marche|saison|chef))?)?")


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #

def parse(raw: str) -> Parsed:
    p = Parsed(raw=raw)
    text = _base(raw)

    if not re.search(r"[a-zà-ÿœ]", text, re.I):
        codes = [c for g in _ALLERGEN_GROUP.findall(text) if (c := _split_codes(g))]
        if codes:
            p.kind, p.allergen_ids = KIND_ALLERGEN_ONLY, sorted({x for c in codes for x in c})
        elif _PRICE.search(text):
            p.kind = KIND_PRICE_ONLY
            p.prices = [float(x.replace(",", ".")) for x in _PRICE.findall(text)]
        else:
            p.kind = KIND_JUNK
        return p

    if m := _NAMED_ALLERGEN_LINE.match(text):
        p.kind = KIND_ALLERGEN_ONLY
        for part in re.split(r"\s*[,;/]\s*|\s+et\s+", fold(m.group(1))):
            if (part := part.strip(" .")) in _NAMED_ALLERGENS:
                p.allergen_ids.append(_NAMED_ALLERGENS[part])
            elif part:
                p.flags.append(f"unknown_allergen:{part}")
        p.allergen_ids = sorted(set(p.allergen_ids))
        return p

    if kind := _info_kind(text):
        p.kind, p.info_kind, p.name = KIND_INFO, kind, _finish(text)
        return p

    # 1. allergènes
    def _allergens(m: re.Match) -> str:
        codes = _split_codes(m.group(1))
        if codes is None:
            return m.group(0)
        p.allergen_ids.extend(codes)
        return " "
    text = _ALLERGEN_GROUP.sub(_allergens, text)
    # parenthèse jamais fermée : "Compote pomme cassis (1.3.7"
    if (m := re.search(r"[\(\[]\s*((?:\d{1,2}\s*[.,\-/]\s*)*\d{1,2})\s*$", text)) and (c := _split_codes(m.group(1))):
        p.allergen_ids.extend(c)
        text = text[:m.start()]

    # 2. prix
    def _price(m: re.Match) -> str:
        p.prices.append(float(m.group(1).replace(",", ".")))
        return " "
    text = _PRICE.sub(_price, text)

    # 3. points
    def _points(m: re.Match) -> str:
        val = float(m.group(3).replace(",", "."))
        if p.points is not None and p.points != val:
            p.flags.append("multiple_points")
        p.points = val if p.points is None else p.points
        if m.group("qty"):
            p.points_note = f"{m.group('qty')} pour {m.group(3)} point(s)"
        if m.group("supp") or re.search(r"suppl", m.group(0), re.I):
            p.points_note = "supplément"
        return " "
    text = _POINTS.sub(_points, text)
    if p.points is None and (m := _POINTS_P.search(text)) and re.search(r"[a-zà-ÿ]", text[:m.start()], re.I):
        p.points = float(m.group(1).replace(",", "."))
        text = text[:m.start()]
    text = text.strip(" -/,")
    if p.points is None and (m := _TRAILING_INT.search(text)):
        p.points = float(m.group(1))
        p.flags.append("bare_number_points")
        text = text[:m.start()]

    # 4. connecteurs de liste ("Ou 1 compote", "Au choix : un café…") puis préfixes
    text = _CONNECTOR.sub("", text)
    text = _strip_prefixes(text, p)

    # 5. parenthèses de méta-données
    def _paren(m: re.Match) -> str:
        if _classify_paren(m.group(1), p):
            return " "
        # une description n'est sortie du nom que s'il reste un vrai nom devant elle
        if re.search(r"[a-zà-ÿ]{3}", m.string[:m.start()], re.I):
            p.details.append(_finish(m.group(1)).lower())
            return " "
        return m.group(0)
    text = _PAREN.sub(_paren, text)

    # 6. régime annoncé en fin de morceau : "Pâtes carbonara végé, salade verte"
    def _veg_mid(m: re.Match) -> str:
        p.vegetarian = True
        return ""
    text = re.sub(rf"\s+-?\s*\b(?:{_VEG})\b(?=\s*[,/+;])", _veg_mid, text, flags=re.I)

    # étiquettes en fin de libellé sans parenthèses : "… bio", "… VG", "… - porc FR"
    for _ in range(3):
        m = re.search(rf"\s*[-,]?\s*\b({_VEG}|bio|msc|bbc|vf|vbf|vpf|label\s+rouge|porc\s+fr|origine\s+[a-zéè\- ]+)\s*$",
                      text, re.I)
        if not m or not re.search(r"[a-zà-ÿ]{3}", text[:m.start()], re.I):
            break
        if not _classify_paren(m.group(1), p):
            break
        text = text[:m.start()]

    p.name = _finish(text)

    # "Menu étudiant : sandwich + yaourt", "Formule panini", "Menu trio 20€" → formule ;
    # "Menu halloween", "Menu d'automne" → annonce de thème, pas un plat
    if re.match(r"(menus?|formules?)\b", fold(p.name)):
        if re.search(r"[:+]", p.name) or p.prices or fold(p.name).startswith("formule"):
            p.section_hint = "FORMULE"
        elif not p.section_hint:
            p.kind, p.info_kind = KIND_INFO, "THEME"
            return p

    p.allergen_ids = sorted(set(p.allergen_ids))
    p.origins = sorted(set(p.origins))
    p.labels = sorted(set(p.labels))
    p.meats = sorted(set(p.meats))

    # 7. drapeaux de revue
    if not p.name:
        p.kind = KIND_JUNK
    elif len(re.sub(r"[^a-zà-ÿ]", "", fold(p.name))) <= 2 or fold(p.name) in {"et", "ou", "ou bien", "au choix", "ou au choix"}:
        p.kind = KIND_JUNK
    else:
        if _GENERIC.fullmatch(fold(p.name)):
            p.flags.append("generic")
        if re.search(r"\d", p.name):
            p.flags.append("digit_in_name")
        if re.search(r"[()\[\]]", p.name):
            p.flags.append("paren_in_name")
        if ":" in p.name:
            p.flags.append("colon_in_name")
        if len(p.prices) > 1:
            p.flags.append("multiple_prices")
        if re.search(r",|\s\+\s|\s-\s|/| et | ou ", p.name):
            p.flags.append("multi_item")
    return p
