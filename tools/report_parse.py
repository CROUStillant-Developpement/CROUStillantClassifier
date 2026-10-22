"""
Rapport de couverture du parsing sur l'extraction locale `data/plat.txt`.

    python -m tools.report_parse [data/plat.txt]

Écrit `out/parsed.jsonl` (un objet par plat) et affiche les statistiques par
champ, puis un échantillon des lignes restées suspectes (drapeaux).
"""

import collections
import json
import random
import sys
from pathlib import Path

from croustillant_classifier.parse import parse


def main(path: str = "data/plat.txt") -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    rows = [l.rstrip("\n").split(";", 1) for l in open(path, encoding="utf-8") if ";" in l]
    out = Path("out"); out.mkdir(exist_ok=True)

    kinds, infos, flags, hints = (collections.Counter() for _ in range(4))
    has = collections.Counter()
    by_flag: dict[str, list[str]] = collections.defaultdict(list)
    names = collections.Counter()

    with open(out / "parsed.jsonl", "w", encoding="utf-8") as f:
        for platid, raw in rows:
            p = parse(raw)
            f.write(json.dumps({"platid": int(platid), **p.to_dict()}, ensure_ascii=False) + "\n")
            kinds[p.kind] += 1
            if p.info_kind:
                infos[p.info_kind] += 1
            if p.section_hint:
                hints[p.section_hint] += 1
            for k in ("points", "prices", "allergen_ids", "origins", "labels", "meats", "vegetarian", "station"):
                if getattr(p, k):
                    has[k] += 1
            for fl in p.flags:
                flags[fl] += 1
                by_flag[fl].append(f"{raw!r:70} → {p.name!r}")
            if p.kind == "DISH":
                names[p.name.lower()] += 1

    n = len(rows)
    print(f"{n} libellés bruts → {len(names)} noms nettoyés distincts (DISH, insensible à la casse)\n")
    print("kind:", dict(kinds.most_common()))
    print("info:", dict(infos.most_common()))
    print("section_hint:", dict(hints.most_common()))
    print("\nchamps extraits:")
    for k, v in has.most_common():
        print(f"  {k:14} {v:7}  ({v / n:.1%})")
    print("\ndrapeaux de revue:")
    for k, v in flags.most_common():
        print(f"  {k:20} {v:7}  ({v / n:.1%})")

    random.seed(0)
    for fl in ("digit_in_name", "paren_in_name", "colon_in_name", "bare_number_points"):
        sample = random.sample(by_flag[fl], min(15, len(by_flag[fl])))
        print(f"\n--- {fl}")
        for s in sample:
            print("  ", s)


if __name__ == "__main__":
    main(*sys.argv[1:])
