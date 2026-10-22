import collections

import pytest

from croustillant_classifier.classify import category_type, decide, head, name_type


@pytest.mark.parametrize("cat, t", [
    ("Entrées", "ENTREE"), ("Entrees", "ENTREE"), ("Entrée", "ENTREE"), ("1 entrée au choix", "ENTREE"),
    ("Plats", "PLAT"), ("Plat végétarien", "PLAT"), ("Plat du jour (formule étudiante)", "PLAT"),
    ("Accompagnements", "ACCOMPAGNEMENT"), ("Garnitures", "ACCOMPAGNEMENT"),
    ("Desserts", "DESSERT"), ("Pâtisseries", "DESSERT"), ("Compotes  yaourts    fruit frais", "DESSERT"),
    ("Fromages", "FROMAGE"), ("Boissons chaudes", "BOISSON"),
    ("Fermeture", "INFO"), ("Origines de nos viandes du jour", "INFO"),
    # catégories vagues ou mélangées : pas de vote
    ("A la carte", None), ("Formule panini", None), ("Entrées / desserts", None), ("Fromage/dessert", None),
    ("Menu midi", None), ("Self", None),
])
def test_category_type(cat, t):
    assert category_type(cat) == t


@pytest.mark.parametrize("label, t", [
    ("Café", "BOISSON"), ("Eau plate 50 cl", "BOISSON"), ("Diverses boissons", "BOISSON"),
    ("Camembert", "FROMAGE"), ("Brie ou comté", "FROMAGE"), ("Saint nectaire ou mimolette", "FROMAGE"),
    ("Fromage ou jambon de dinde fromage", None), ("Thé vert", "BOISSON"), ("Thé, café ou chocolat", "BOISSON"),
    ("The cafeteria is closed tuesday", None),
    ("Canette rôtie sauce poivre vert", None), ("Jus de couscous", None), ("Cappuccino de petits pois", None),
    ("Sirop d'érable", None), ("Canette 33cl", "BOISSON"), ("Jus d'orange pressé", "BOISSON"),
    ("Café au lait", "BOISSON"), ("Cappuccino", "BOISSON"), ("Coca cola zéro 33 cl", "BOISSON"),
    ("Yaourt nature", "DESSERT"), ("1 compote", "DESSERT"), ("Pomme", "DESSERT"),
    ("Tarte aux pommes", "DESSERT"), ("Pain au chocolat/croissant", "DESSERT"), ("Café gourmand", "DESSERT"), ("Flan pâtissier", "DESSERT"),
    ("Ratatouille", "PLAT"), ("Frites", "ACCOMPAGNEMENT"), ("Riz basmati", "ACCOMPAGNEMENT"), ("Haricots verts persillés", "ACCOMPAGNEMENT"),
    ("Carottes râpées", "ENTREE"), ("Potage minestrone", "ENTREE"), ("Pâté de campagne", "ENTREE"),
    # ambiguïtés qui ne doivent PAS être tranchées par le nom
    ("Pommes de terre sautées", "ACCOMPAGNEMENT"), ("Fruits de mer", None), ("Flan de légumes", None),
    ("Beignets de calamars", None), ("Croissant au jambon", None), ("Pâtes bolognaise", None),
])
def test_name_type(label, t):
    assert name_type(label) == t


def test_head():
    assert head("Sandwichs froids") == "sandwich"
    assert head("Ou 1 compote") == "compote"


def test_decide_conflict_goes_to_review():
    t, conf, src, review = decide(collections.Counter({"PLAT": 50}), "ENTREE", None, None)
    assert t == "ENTREE" and review


def test_decide_info_category():
    t, *_ = decide(collections.Counter({"INFO": 100}), None, None, None)
    assert t == "INFO"
