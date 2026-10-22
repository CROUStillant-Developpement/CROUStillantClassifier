import pytest

from croustillant_classifier.canon import Lexicon, split_plate, tokens


@pytest.mark.parametrize("a, b", [
    ("Poulet à la basquaise", "Poulet basquaise"),
    ("Taboulé maison", "Taboulé"),
    ("POULET BASQUAISE", "poulet basquaise"),
    ("Petits pois à la française", "Petit pois a la francaise"),
    ("Pdt œufs mayo", "Pommes de terre oeufs mayo"),
    ("2 nems de poulet", "Nems de poulet"),
    ("Pizza quatre fromages", "Pizza 4 fromages"),
    ("Crumble aux fruits rouges", "Crumble de fruit rouge"),
])
def test_same_key(a, b):
    lex = Lexicon()
    assert lex.key(a) == lex.key(b)


@pytest.mark.parametrize("a, b", [
    ("Pizza margherita", "Pizza 4 fromages"),
    ("Pâtes bolognaise", "Pâté de campagne"),
    ("Pâté de foie", "Pâtes au foie"),
    ("Pâtés", "Pâtes"),
])
def test_different_key(a, b):
    lex = Lexicon()
    assert lex.key(a) != lex.key(b)


def test_vegetarian_is_part_of_identity():
    lex = Lexicon()
    assert lex.key("Burger", vegetarian=True) != lex.key("Burger")


def test_typos_skip_dictionary_words():
    names = ["Pâtes à la vanille"] * 30 + ["Salade canaille", "Poulet volalle"] + ["Volaille rôtie"] * 30
    lex = Lexicon.build(names, dictionary={"canaille"})
    assert "canaille" not in lex.typos
    assert lex.typos.get("volalle") == "volaille"


@pytest.fixture
def lex():
    known = ["Poisson pané", "Riz", "Ratatouille", "Éclair vanille", "Éclair chocolat", "Chocolat",
             "Petits pois", "Courgette", "Boulette agneau", "Sauce moutarde", "Salade de blé", "Tomates", "Maïs"]
    return Lexicon.build(known * 3)


@pytest.mark.parametrize("name, parts", [
    ("Poisson pané, riz, ratatouille", ["Poisson pané", "Riz", "Ratatouille"]),
    ("Éclair vanille ou chocolat", ["Éclair vanille", "Éclair chocolat"]),
    ("Petits pois ou courgette", ["Petits pois", "Courgette"]),
    ("Boulette agneau, sauce moutarde", ["Boulette agneau sauce moutarde"]),
    ("Salade de blé/tomates/maïs", ["Salade de blé/tomates/maïs"]),       # contenant : pas de découpage
    ("Poisson pané, purée de céleri", ["Poisson pané, purée de céleri"]),  # morceau inconnu : pas de découpage
])
def test_split(lex, name, parts):
    assert split_plate(name, lex)[0] == parts


def test_tokens_drop_noise():
    assert tokens("2 Nems x6 maison bio") == ["nem"]
