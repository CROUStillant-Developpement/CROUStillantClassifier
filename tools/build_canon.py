"""
Construit le lexique et les plats canoniques à partir de `out/parsed.jsonl`.

    python -m tools.build_canon

Écrit :
  out/lexicon.json      tables figées (fautes de frappe, plats connus) pour la prod
  out/components.jsonl  platid → composants (nom, clé)
  out/canon.jsonl       un plat canonique par ligne : clé, libellé, variantes, poids
"""

import collections
import csv
import json
import random
import re
import sys
from pathlib import Path

from croustillant_classifier.canon import Lexicon, split_plate
from croustillant_classifier.parse import fold

RESOURCES = Path("croustillant_classifier/resources")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    out = Path("out")
    parsed = [json.loads(l) for l in open(out / "parsed.jsonl", encoding="utf-8")]
    dishes = [p for p in parsed if p["kind"] == "DISH"]

    # poids d'un plat = nombre d'apparitions dans les menus
    weight = collections.Counter()
    with open("data/plat_context.tsv", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            weight[int(r["platid"])] += int(r["n"])

    dictionary = {fold(w.strip()) for w in open("data/wordlist/fr.txt", encoding="utf-8")}
    lex = Lexicon.build([p["name"] for p in dishes], dictionary)
    lex.save(out / "lexicon.json")
    lex.save(RESOURCES / "lexicon.json")             # table figée livrée avec la librairie

    groups: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    platids: dict[str, set] = collections.defaultdict(set)
    split_by = collections.Counter()
    split_examples = collections.defaultdict(list)
    with open(out / "components.jsonl", "w", encoding="utf-8") as f:
        for p in dishes:
            parts, sep = split_plate(p["name"], lex)
            split_by[sep] += 1
            if sep:
                split_examples[sep].append(f'{p["name"]!r} → {parts}')
            comps = []
            for i, part in enumerate(parts):
                # le régime annoncé porte sur le plat principal, pas sur le riz qui l'accompagne
                k = lex.key(part, vegetarian=p["vegetarian"] and i == 0)
                if not k:
                    continue
                comps.append({"name": part, "key": k})
                groups[k][part] += max(weight[p["platid"]], 1)
                platids[k].add(p["platid"])
            f.write(json.dumps({"platid": p["platid"], "split": sep, "components": comps},
                               ensure_ascii=False) + "\n")

    canon = []
    for k, variants in groups.items():
        # libellé affiché : la variante propre la plus servie (sans quantité ni parenthèse)
        label = max(variants, key=lambda v: (not re.match(r"\d", v) and not re.search(r"[()\[\]]", v),
                                              variants[v], sum(c in "éèêàâîôûç" for c in v)))
        canon.append({"key": k, "label": label, "weight": sum(variants.values()),
                      "n_platids": len(platids[k]), "variants": dict(variants.most_common())})
    canon.sort(key=lambda c: -c["weight"])
    with open(out / "canon.jsonl", "w", encoding="utf-8") as f:
        for c in canon:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ rapport
    sizes = collections.Counter(min(c["n_platids"], 10) for c in canon)
    total_w = sum(c["weight"] for c in canon)
    single_w = sum(c["weight"] for c in canon if c["n_platids"] == 1)
    print(f"{len(dishes)} plats → {len({p['name'].lower() for p in dishes})} noms distincts "
          f"→ {len(canon)} plats canoniques")
    print(f"typos appris: {len(lex.typos)}   plats connus: {len(lex.known)}")
    print("découpage:", dict(split_by))
    print("taille des groupes (libellés bruts par plat canonique, 10 = 10+):", dict(sorted(sizes.items())))
    print(f"singletons: {sizes[1]} plats canoniques = {single_w / total_w:.1%} des apparitions en menu")

    random.seed(3)
    print("\n--- fautes corrigées (échantillon)")
    for t in random.sample(sorted(lex.typos), 40):
        print(f"   {t} → {lex.typos[t]}")
    for sep, ex in split_examples.items():
        print(f"\n--- découpage '{sep}' ({len(ex)})")
        for e in random.sample(ex, min(12, len(ex))):
            print("  ", e)
    print("\n--- plus gros groupes")
    for c in canon[:15]:
        print(f'   {c["label"]!r:40} {c["n_platids"]:5} libellés  ex: {list(c["variants"])[:5]}')
    print("\n--- groupes moyens (échantillon)")
    mid = [c for c in canon if 4 <= c["n_platids"] <= 30]
    for c in random.sample(mid, 15):
        print(f'   {c["label"]!r:40} {list(c["variants"])[:6]}')


if __name__ == "__main__":
    main()
