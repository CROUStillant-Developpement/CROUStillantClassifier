import pytest

from croustillant_classifier import Classifier, occurrence_type


@pytest.fixture(scope="module")
def clf():
    return Classifier()


def test_dish_with_points_and_allergens(clf):
    a = clf.analyse("Sauté de porc aux pruneaux - 5 pts (1.3.7)", category="Plats")
    assert a.is_dish
    assert (a.parsed.points, a.parsed.allergen_ids) == (5.0, [1, 3, 7])
    [c] = a.components
    assert (c.label, c.type) == ("Sauté de porc aux pruneaux", "PLAT")


def test_plate_is_split(clf):
    a = clf.analyse("Poisson pané, riz, ratatouille", category="Plats")
    assert [c.label for c in a.components] == ["Poisson pané", "Riz", "Ratatouille"]
    assert [c.type for c in a.components] == ["PLAT", "ACCOMPAGNEMENT", "PLAT"]  # ratatouille = PLAT par défaut


def test_info_is_not_a_dish(clf):
    assert not clf.analyse("Structure fermée du lundi 5 mai 2025 au mardi 6 mai 2025", "Fermeture").is_dish
    assert not clf.analyse("France", "Origines de nos viandes du jour").is_dish


def test_same_key_as_offline(clf):
    assert clf.key("Poulet à la basquaise") == clf.key("POULET BASQUAISE (maison)")


@pytest.mark.parametrize("default, cat, main, expected", [
    ("PLAT", "Entrées", True, "ENTREE"),           # pizza servie en entrée
    ("ACCOMPAGNEMENT", "Plats", True, "ACCOMPAGNEMENT"),  # la purée reste une garniture
    ("DESSERT", "Boissons froides", True, "BOISSON"),
    ("PLAT", "Entrées", False, "PLAT"),            # composant secondaire d'un plateau
    ("PLAT", "A la carte", True, "PLAT"),          # catégorie vague
])
def test_occurrence_type(default, cat, main, expected):
    assert occurrence_type(default, cat, main) == expected
