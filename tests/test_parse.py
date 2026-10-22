import pytest

from croustillant_classifier.parse import parse


@pytest.mark.parametrize("raw, name, points", [
    ("Endives aux lardons 2 pts", "Endives aux lardons", 2),
    ("Salade de blé/tomates/maïs (1 point)", "Salade de blé/tomates/maïs", 1),
    ("Bruschetta (4 points)", "Bruschetta", 4),
    ("Sauté de porc aux pruneaux - 5 pts", "Sauté de porc aux pruneaux", 5),
    ("Pilon de poulet tex mex (4pts)", "Pilon de poulet tex mex", 4),
    ("Assiette de poulets pâtes crudités ( 4 points )", "Assiette de poulets pâtes crudités", 4),
    ("Galette tofu emmental (4points)", "Galette tofu emmental", 4),
    ("Poisson pané 4p", "Poisson pané", 4),
    ("2 nems de poulet 2p", "2 nems de poulet", 2),
    ("Omelette au fromage 4", "Omelette au fromage", 4),
    ("Pâtes poivrons \t 1pt", "Pâtes poivrons", 1),
    ("Quiche lorraine", "Quiche lorraine", None),
])
def test_points(raw, name, points):
    p = parse(raw)
    assert p.kind == "DISH"
    assert p.name == name
    assert p.points == points


def test_points_quantity():
    p = parse("Assortiment de gâteaux (2 pour 1 point)")
    assert (p.name, p.points, p.points_note) == ("Assortiment de gâteaux", 1, "2 pour 1 point(s)")


@pytest.mark.parametrize("raw, ids", [
    ("Pâté de foie (1,3,6,7,10,12)", [1, 3, 6, 7, 10, 12]),
    ("Taboule maison (12-6-9)", [6, 9, 12]),
    ("Pâtes sauce champignons (1.3.6.7.9.12.13)", [1, 3, 6, 7, 9, 12, 13]),
    ("Carottes (9)", [9]),
    ("Compote pomme cassis (1.3.7", [1, 3, 7]),
    ("Betterave (1.6.8.910)", [1, 6, 8, 9, 10]),
    ("Haricot vert aux amandes (fruit à coque)", [8]),
])
def test_allergen_codes(raw, ids):
    p = parse(raw)
    assert p.allergen_ids == ids
    assert "(" not in p.name


def test_points_and_allergens_together():
    p = parse("Brochette bœuf marinee sauce tartare estragon 5 points (3-10-12)")
    assert (p.name, p.points, p.allergen_ids) == ("Brochette bœuf marinee sauce tartare estragon", 5, [3, 10, 12])


@pytest.mark.parametrize("raw", [
    "Plat végétarien : tajine de légumes aux herbes",
    "Plat sans viande : samoussa légumes",
    "Plats sans viande : korma de légumes",
    "VG : lasagnes aux légumes",
    "Lasagnes aux légumes VG",
    "Lasagnes aux légumes (végé)",
    "Lasagnes aux légumes (veggie)",
    "Pâtes à la carbonara végé (1.3.7), salade verte",
])
def test_vegetarian(raw):
    p = parse(raw)
    assert p.vegetarian
    assert "végé" not in p.name.lower() and "viande" not in p.name.lower()
    assert not p.name.lower().endswith(" vg")


@pytest.mark.parametrize("raw, origins, labels, meats", [
    ("Entrecôte (origine pays-bas)", ["Pays-Bas"], [], []),
    ("Saucisse (porc - fr)", ["France"], [], ["porc"]),
    ("Rôti de porc laqué aux épices ( viande d'origine française )", ["France"], [], []),
    ("Brochette de dinde à l'indienne (label bbc)", [], ["bleu-blanc-cœur"], []),
    ("Filet de colin (MSC)", [], ["msc"], []),
])
def test_metadata(raw, origins, labels, meats):
    p = parse(raw)
    assert (p.origins, p.labels, p.meats) == (origins, labels, meats)
    assert "(" not in p.name


def test_price():
    p = parse("Poke bowl poulet pané 5.00 €")
    assert (p.name, p.prices) == ("Poke bowl poulet pané", [5.0])
    assert parse("4.50 €").kind == "PRICE"


def test_details_kept_out_of_name():
    p = parse("Gnocchi à l'espagnole (chorizo, poivrons)")
    assert (p.name, p.details) == ("Gnocchi à l'espagnole", ["chorizo, poivrons"])


def test_station_and_section_prefixes():
    p = parse("Chaîne étudiants : Plat végétarien : tajine de légumes")
    assert (p.name, p.station, p.vegetarian) == ("Tajine de légumes", "chaine etudiants", True)
    p = parse("Accompagnements : purée")
    assert (p.name, p.section_hint) == ("Purée", "ACCOMPAGNEMENT")
    assert parse("Pizza : 4 fromages").name == "Pizza 4 fromages"


@pytest.mark.parametrize("raw, info", [
    ("Structure fermée du jeudi 16 avril 2026 au vendredi 17 avril 2026", "CLOSURE"),
    ("Réouverture le 12 janvier", "CLOSURE"),
    ("Ilot ferme", "CLOSURE"),
    ("Exceptionnellement fermé", "CLOSURE"),
    ("Téléchargez l'application et faites votre choix !", "APP"),
    ("Les menus sont susceptibles d'être modifiés en fonction des arrivages", "NOTICE"),
    ("Jeudi      de 11h45  a 13h20", "NOTICE"),
    ("Service de 11h30 à 13h30", "NOTICE"),
    ("Bon appétit et bonne reprise", "NOTICE"),
])
def test_info(raw, info):
    p = parse(raw)
    assert (p.kind, p.info_kind) == ("INFO", info)


@pytest.mark.parametrize("raw", [
    "Poulet fermier rôti", "Œufs de ferme brouillés", "Poisson du jour sauce bercy",
    "Salade du jour piémontaise fromage", "Couscous merguez",
])
def test_not_info(raw):
    assert parse(raw).kind == "DISH"


@pytest.mark.parametrize("raw", ["Et", "OU", "..", "-------------------------", "- - - - ¤¤¤ - - - - -"])
def test_junk(raw):
    assert parse(raw).kind == "JUNK"


def test_allergen_only_line():
    assert parse("(1.3.7.8)").kind == "ALLERGENS"
    p = parse("(allergène : lactose, gluten)")
    assert (p.kind, p.allergen_ids) == ("ALLERGENS", [1, 7])


@pytest.mark.parametrize("raw, kind, hint", [
    ("Menu halloween", "INFO", None),
    ("Menu d'automne", "INFO", None),
    ("Menu étudiant : sandwich + yaourt + dessert", "DISH", "FORMULE"),
    ("Menu trio 20€", "DISH", "FORMULE"),
    ("Formule panini", "DISH", "FORMULE"),
])
def test_menu(raw, kind, hint):
    p = parse(raw)
    assert (p.kind, p.section_hint) == (kind, hint)


@pytest.mark.parametrize("raw, name", [
    ("Ou 1 compote", "1 compote"),
    ("Au choix: un café, un thé ou un chocolat", "Un café, un thé ou un chocolat"),
    ("Et frites", "Frites"),
    ("Oeufs mayonnaise", "Oeufs mayonnaise"),
])
def test_leading_connectors(raw, name):
    assert parse(raw).name == name


def test_generic_and_case():
    assert "generic" in parse("Plat du jour").flags
    assert parse("POULET BASQUAISE").name == "Poulet basquaise"
