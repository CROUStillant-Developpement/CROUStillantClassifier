"""
Étape 4 — Type d'un plat canonique.

Trois sources, de la plus fiable à la moins fiable :

1. Règles sur le nom (`NAME_RULES`) : peu nombreuses, très précises
   ("café", "camembert", "yaourt", "frites"…).
2. Votes des catégories de menu (`categorie.tpcat`) où le plat a été servi, une
   fois la catégorie ramenée à un type (`CATEGORY_RULES`). Une catégorie vague
   ("A la carte", "Formule panini", "Self") ne vote pas.
3. Le mot de tête du libellé, appris sur les plats déjà votés ("tarte" → …).

Quand les sources se contredisent, le plat part en revue au lieu d'être deviné.
"""

from __future__ import annotations

import collections
import re

from .parse import fold

TYPES = ("ENTREE", "PLAT", "ACCOMPAGNEMENT", "DESSERT", "FROMAGE", "BOISSON", "FORMULE", "AUTRE")


# --------------------------------------------------------------------------- #
# Catégorie de menu → type
# --------------------------------------------------------------------------- #

# Une catégorie qui mélange deux types ("Entrées / desserts") ne vote pas.
_MIXED = re.compile(r"(entree|plat|dessert|fromage|boisson|accompagnement|legume|garniture).*"
                    r"[/&,+-]|\bet\b|\bou\b", re.I)

CATEGORY_RULES: list[tuple[str, str]] = [
    (r".*\b(fermeture|informations?|horaires?|covid|origines?\s+de\s+nos)\b.*", "INFO"),
    (r"(les\s+|1\s+)?(entrees?|hors\s*d.?oeuvres?|crudites?)(\s+(au\s+choix|du\s+jour|\(.*\)))?", "ENTREE"),
    (r"(les\s+|le\s+)?(plats?|plat\s+du\s+jour|plats?\s+du\s+jour|plats?\s+chauds?|plat\s+principal|"
     r"plats?\s+au\s+choix|plat\s+self|plats?\s+cuisines?|plat\s+vegetarien|vegetarien|offre\s+vegetarienne|"
     r"viandes?\s*-\s*poissons?|plat\s+viande\s+ou/?et\s+poisson|grill(ade)?s?|piste\s+traditionnelle|"
     r"chaine\s+(\d\s*:\s*)?traditionnelle|traditionnel(\s+\d)?|burgers?|pizzas?(\s+permanentes)?|"
     r"pates(\s+permanentes)?|sandwich(e)?s?(\s+(chauds?|froids?|maison|permanents?|du\s+moment|de\s+la\s+semaine))*|"
     r"paninis?(\s+permanents)?|sandwichs?\s*-?\s*paninis?|salades?(\s+de\s+la\s+semaine)?)"
     r"(\s*\(.*\))?", "PLAT"),
    (r"(les\s+)?(accompagnements?|garnitures?|legumes)", "ACCOMPAGNEMENT"),
    (r"(les\s+|nos\s+|les\s+petites\s+|caf\s+)?(desserts?|douceurs|patisseries?(\s+americaines)?|gourmandises|sucres|"
     r"desserts?\s*/\s*(patisseries?|fruits)|desserts?\s+(et|/)\s+patisseries?|dessert\s+patisserie|"
     r"desserts?\s+au\s+choix|compotes\s+yaourts\s+fruit\s+frais|viennoiseries(\s+(ou\s+autres|desserts))?)", "DESSERT"),
    (r"fromages?", "FROMAGE"),
    (r"(les\s+|nos\s+)?boissons?(\s+(chaudes?|froides?|fraiches?))?|nos\s+boissons\s+froides\s+et\s+chaudes", "BOISSON"),
]
_CATEGORY_RULES = [(re.compile(rx), t) for rx, t in CATEGORY_RULES]


def category_type(tpcat: str) -> str | None:
    f = re.sub(r"[^a-z0-9/&,+():\- ]", " ", fold(tpcat))
    f = re.sub(r"\s+", " ", f).strip()
    for rx, t in _CATEGORY_RULES:
        if rx.fullmatch(f):
            return t
    return None


# --------------------------------------------------------------------------- #
# Règles sur le nom (libellé plié, sans accents)
# --------------------------------------------------------------------------- #

_CHEESES = (r"camembert|brie|emmental|comte|cantal|edam|gouda|mimolette|coulommiers|saint\s*paulin|st\s*paulin|"
            r"tomme|reblochon|roquefort|bleu\s+d.auvergne|fourme|munster|morbier|pont\s*l.eveque|carre\s+de\s+l.est|"
            r"chevre|vache\s+qui\s+rit|babybel|kiri|saint\s*nectaire|raclette|fromage\s+a\s+la\s+coupe|"
            r"assiette\s+de\s+fromages?|plateau\s+de\s+fromages?|fromages?|portion\s+de\s+fromage|buchette|"
            r"petit\s+suisse|fromage\s+fondu|maroilles|livarot|neufchatel|ossau|beaufort|abondance|feta")
_FRUITS = (r"fruits?|pommes?|poires?|bananes?|oranges?|clementines?|mandarines?|kiwis?|raisins?|peches?|"
           r"nectarines?|abricots?|ananas|pasteque|prunes?|fraises?|framboises?|cerises?|mangues?|litchis?")
_DESSERT_HEADS = (
    r"yaourts?|yogourts?|fromage\s+blanc|compotes?|compotee|mousse\s+au\s+chocolat|"
    r"mousse\s+(chocolat|citron|framboise|aux\s+fruits|fruits?\s+rouges?|mangue|passion|caramel|praline)|"
    r"creme\s+(dessert|caramel|brulee|anglaise|vanille|chocolat|aux\s+oeufs|renversee)|"
    r"ile\s+flottante|riz\s+au\s+lait|semoule\s+au\s+lait|panna\s*cotta|tiramisu|eclairs?|"
    r"choux?\s+a\s+la\s+creme|profiteroles?|donuts?|cookies?|muffins?|brownies?|madeleines?|gaufres?|"
    r"gateaux?|tartelettes?|crumble|clafoutis|far\s+breton|financiers?|mille\s*-?\s*feuilles?|"
    r"paris\s*-?\s*brest|viennoiseries?|pains?\s+au\s+chocolat|pain\s+aux\s+raisins|chaussons?\s+aux\s+pommes|"
    r"macarons?|glaces?|sorbets?|esquimaux?|cones?\s+glaces?|liegeois|coupe\s+glacee|patisseries?|desserts?|"
    r"douceurs?|entremets?|salade\s+de\s+fruits|cafe\s+gourmand|fondant\s+au\s+chocolat|moelleux\s+au\s+chocolat|"
    r"tarte\s+(aux|au|a\s+la)\s+(pommes?|poires?|fraises?|framboises?|abricots?|citron|chocolat|myrtilles?|"
    r"fruits?|figues?|prunes?|rhubarbe|sucre|flan|normande|amandine|bourdaloue|tatin|daim|noix\s+de\s+coco)|"
    r"tarte\s+tatin|cheesecake|cheese\s*cake|crepes?\s+(au\s+)?(sucre|chocolat|nutella|confiture|caramel)|"
    r"fruit\s+frais|fruits\s+frais|fruits?\s+de\s+saison|corbeille\s+de\s+fruits|pruneaux")
NAME_RULES: list[tuple[str, str]] = [
    # desserts : têtes non ambiguës (n'importe quelle suite), fruits seuls, et quelques têtes ambiguës
    # seulement avec une suite sucrée ("Flan pâtissier" oui, "Flan de légumes" non)
    (rf"({_DESSERT_HEADS})([\s/,].*)?"
     rf"|({_FRUITS})(\s+(bio|frais|fraiches?|au\s+choix|du\s+jour|entieres?|de\s+saison|ou\s+.*|/.*|,.*))*"
     r"|(flan|beignets?|cakes?|croissants?|brioches?|crepes?)(\s+(nature|sucre|patissier|vanille|chocolat|"
     r"au\s+chocolat|a\s+la\s+vanille|aux\s+pommes|aux\s+fruits|confiture|nutella|au\s+beurre|pur\s+beurre|"
     r"aux\s+pepites\s+de\s+chocolat|au\s+citron|marbre|breton|framboise))*", "DESSERT"),
    # boissons
    # "thé" plié devient "the" : seul ou avec un parfum, jamais suivi de n'importe quoi
    (r"the(\s+(vert|noir|menthe|a\s+la\s+menthe|glace|nature|aromatise|citron|peche|earl\s+grey|infusion))*"
     r"(\s*(,|ou)\s+.*)?", "BOISSON"),
    # têtes sans ambiguïté : n'importe quelle suite
    (r"(eau|coca|pepsi|orangina|ice\s*tea|fuze\s*tea|fanta|sprite|oasis|schweppes|perrier|evian|vittel|"
     r"cristaline|sodas?|boissons?|limonade|red\s*bull|monster|capri\s*sun|lipton|tropico|minute\s+maid)"
     r"(\s+.*)?", "BOISSON"),
    # têtes ambiguës ("Canette rôtie", "Jus de couscous", "Cappuccino de petits pois") :
    # seulement avec une suite de boisson
    (r"(cafe|chocolat\s+chaud|cappuccino|expresso|espresso|latte|infusion|tisane|nectar|smoothies?|"
     r"milk\s*shakes?|jus|sirop|lait|canettes?)"
     r"(\s+(\d+\s*(cl|ml|l)|au\s+lait|creme|allonge|noisette|long|court|serre|decafeine|double|grand|petit|"
     r"bio|nature|vanille|caramel|frais|presse|maison|glace|aromatise|chaud|froid|de\s+fruits?|d.orange|"
     r"de\s+pommes?|de\s+raisin|d.ananas|de\s+tomate|multifruits?|de\s+(menthe|grenadine|fraise|citron|peche)|"
     r"a\s+la\s+(menthe|grenadine|fraise)|banane|fraise|fruits\s+rouges|mangue|soda|coca|en\s+bouteille|"
     r"bouteille|canette|orange|pomme|abricot|ananas|exotique|de\s+saison|du\s+jour|cacao))*"
     r"(\s*(,|ou|/|et)\s+.*)?", "BOISSON"),
    # fromages seuls
    (rf"({_CHEESES})(\s+(aop|bio|fermier|affine|du\s+jour|au\s+choix))?"
     rf"(\s*(ou|/|,)\s*({_CHEESES})(\s+(aop|bio|fermier|affine))?)*", "FROMAGE"),
    # plats décidés à la main (choix éditorial, prioritaire sur les catégories)
    (r"ratatouille(\s+(maison|bio|nicoise|provencale))*", "PLAT"),
    # accompagnements
    (r"(frites?|potatoes|pommes?\s+(de\s+terre\s+)?(vapeur|sautees?|rissolees?|noisettes?|frites|dauphines?|"
     r"grenailles?|campagnardes?|paillasson)|pommes\s+de\s+terre|puree|gratin\s+dauphinois|"
     r"riz|riz\s+pilaf|riz\s+cantonais|semoule|boulgour|ble|quinoa|pates|coquillettes|penne|fusill?i|"
     r"spaghetti|tagliatelles?|torsades?|macaronis?|tortis?|lentilles|haricots\s+(verts?|blancs?|rouges?|beurre)|"
     r"flageolets|petits?\s+pois|carottes(\s+vichy)?|brocolis?|chou\s*-?\s*fleur|epinards|courgettes|"
     r"poelee\s+de\s+legumes|legumes(\s+(vapeur|du\s+jour|de\s+saison|verts|grilles|sautes))?|"
     r"jardiniere|haricots|garnitures?|accompagnements?)"
     r"(\s+(bio|vapeur|persillee?s?|au\s+beurre|nature|sautees?|a\s+l.ail|aux\s+herbes|basmati|"
     r"thai|complet|pilaf|parfume|provencale|braises?|rotis?|glaces?|a\s+la\s+creme))*", "ACCOMPAGNEMENT"),
    # entrées
    (r"(potage|soupe|veloute|creme\s+de\s+(legumes|potiron|poireaux|champignons|carottes|tomates?)|gaspacho|"
     r"crudites|carottes\s+rapees|celeri\s+remoulade|betteraves?(\s+vinaigrette)?|taboule|"
     r"salade\s+(verte|composee|de\s+(tomates?|concombres?|lentilles|pommes\s+de\s+terre|riz|pates|ble|"
     r"chou|carottes|betteraves?|haricots|pois\s+chiches|museau|boulgour|quinoa|mais))|"
     r"oeufs?\s+(mayo|mayonnaise|durs?)|terrine|pate\s+(de\s+(campagne|foie|lapin|volaille|canard)|en\s+croute)|"
     r"rillettes|saucisson|jambon\s+cru|museau|macedoine|avocat|pamplemousse|melon|radis|concombres?|"
     r"tomates?\s+(vinaigrette|mozzarella)|nems?|samoussas?|accras?|"
     r"entrees?|hors\s+d.oeuvres?|charcuterie|assiette\s+de\s+charcuterie)(\s+.*)?", "ENTREE"),
]
_NAME_RULES = [(re.compile(rx), t) for rx, t in NAME_RULES]


def name_type(label: str) -> str | None:
    f = fold(label)
    f = re.sub(r"^(\d+\s+|(un|une|le|la|les|l')\s*|(divers|diverses|assortiment\s+de|assortiment\s+d'|"
               r"selection\s+de|choix\s+de)\s+)+", "", f)
    f = re.sub(r"[^a-z0-9' /,]", " ", f)
    f = re.sub(r"\s+", " ", f).strip()
    if re.match(r"(pommes?\s+de\s+terre|fruits?\s+de\s+mer)\b", f):   # pas des desserts
        rules = [(rx, t) for rx, t in _NAME_RULES if t != "DESSERT"]
    else:
        rules = _NAME_RULES
    for rx, t in rules:
        if rx.fullmatch(f):
            return t
    return None


_HEAD_SKIP = {"le", "la", "les", "l", "un", "une", "d", "de", "du", "ou", "et", "divers", "diverses",
              "assortiment", "selection", "choix", "au", "nos", "notre"}


def head(label: str) -> str:
    """Premier mot significatif, au singulier : "Sandwichs froids" → "sandwich"."""
    toks = [t for t in re.findall(r"[a-z]+", fold(label)) if t not in _HEAD_SKIP]
    if not toks:
        return ""
    t = toks[0]
    return t[:-1] if len(t) > 3 and t[-1] in "sx" and not t.endswith(("ss", "us", "is")) else t


# --------------------------------------------------------------------------- #
# Décision
# --------------------------------------------------------------------------- #

def decide(votes: collections.Counter, by_name: str | None, by_head: str | None,
           section_hint: str | None) -> tuple[str, float, str, list[str]]:
    """Renvoie (type, confiance, source, raisons de revue)."""
    review: list[str] = []
    total = sum(v for k, v in votes.items() if k != "INFO")
    top, top_v = next(((k, v) for k, v in votes.most_common() if k != "INFO"), (None, 0))
    share = top_v / total if total else 0.0
    info_share = votes.get("INFO", 0) / max(sum(votes.values()), 1)

    if info_share >= 0.5:
        review.append("served_in_info_category")
        if info_share >= 0.8 and not by_name:
            # "France" sous "Origines de nos viandes du jour" : une information, pas un plat
            return "INFO", round(info_share, 2), "menus", review

    if section_hint == "FORMULE":
        return "FORMULE", 0.95, "section", review

    if by_name:
        if top and share >= 0.6 and top != by_name and total >= 3:
            # le nom et les menus se contredisent : le nom gagne, mais on vérifie
            review.append(f"name={by_name}_vs_menus={top}({share:.0%})")
            return by_name, 0.6, "name", review
        return by_name, 0.97, "name", review

    if section_hint and section_hint in TYPES:
        if top and share >= 0.6 and top != section_hint and total >= 3:
            review.append(f"prefix={section_hint}_vs_menus={top}({share:.0%})")
        return section_hint, 0.9, "section", review

    if top and total >= 2 and share >= 0.75:
        conf = min(0.95, 0.6 + 0.35 * share * min(total, 20) / 20)
        if by_head and by_head != top:
            review.append(f"menus={top}_vs_head={by_head}")
            conf -= 0.2
        elif by_head == top:
            conf = min(0.95, conf + 0.15)
        return top, round(conf, 2), "menus", review

    if by_head:
        if top and top != by_head and share >= 0.5:
            review.append(f"head={by_head}_vs_menus={top}({share:.0%})")
            return by_head, 0.5, "head", review
        return by_head, 0.75, "head", review

    if top:
        review.append(f"weak_menus={top}({share:.0%},{total:g})")
        return top, round(0.4 * share, 2), "menus", review

    review.append("no_signal")
    return "AUTRE", 0.0, "none", review
