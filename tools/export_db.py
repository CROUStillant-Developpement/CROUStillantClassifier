"""
Exporte le résultat hors-ligne vers des CSV, chargés ensuite par `tools/load_db.py`.

    python -m tools.export_db

Écrit `out/db/*.csv`. Rien n'est envoyé en base.
"""

import collections
import csv
import json
import sys
from pathlib import Path

from croustillant_classifier import VERSION, category_type

OUT = Path("out")
DB = OUT / "db"


def pg_array(values) -> str | None:
    if not values:
        return None
    items = []
    for v in values:
        s = str(v).replace("\\", "\\\\").replace('"', '\\"')
        items.append(f'"{s}"')
    return "{" + ",".join(items) + "}"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    DB.mkdir(parents=True, exist_ok=True)
    classified = {r["key"]: r for r in map(json.loads, open(OUT / "classified.jsonl", encoding="utf-8"))}

    # --- plats canoniques (les "INFO" n'en sont pas : leurs libellés deviennent des infos)
    idpc = {}
    with open(DB / "plat_canonique.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for r in classified.values():
            if r["type"] == "INFO":
                continue
            idpc[r["key"]] = len(idpc) + 1
            w.writerow([idpc[r["key"]], r["key"], r["label"][:500], r["type"], "~vg" in r["key"].split(),
                        r["confidence"], r["source"], bool(r["review"]), pg_array(r["review"])])

    # --- composants + analyses
    comps_by_pid = {}
    for line in open(OUT / "components.jsonl", encoding="utf-8"):
        row = json.loads(line)
        comps_by_pid[row["platid"]] = row["components"]

    natures = collections.Counter()
    with open(DB / "plat_analyse.csv", "w", newline="", encoding="utf-8") as fa, \
         open(DB / "plat_composant.csv", "w", newline="", encoding="utf-8") as fc:
        wa, wc = csv.writer(fa), csv.writer(fc)
        for p in map(json.loads, open(OUT / "parsed.jsonl", encoding="utf-8")):
            nature, info = p["kind"], p["info_kind"]
            comps = [c for c in comps_by_pid.get(p["platid"], []) if c["key"] in idpc]
            if nature == "DISH" and not comps:
                nature, info = "INFO", "CATEGORY"     # servi uniquement dans des catégories d'info
            natures[nature] += 1
            wa.writerow([p["platid"], nature, info, (p["name"] or None) and p["name"][:500], p["points"],
                         p["points_note"], pg_array(p["prices"]), pg_array(p["allergen_ids"]),
                         pg_array(p["origins"]), pg_array(p["labels"]), pg_array(p["meats"]),
                         pg_array(p["details"]), p["vegetarian"], p["station"], p["section_hint"],
                         pg_array(p["flags"]), VERSION])
            if nature == "DISH":
                for i, c in enumerate(comps):
                    wc.writerow([p["platid"], i, idpc[c["key"]], c["name"][:500]])

    # --- type des catégories
    cats = set()
    with open("data/plat_context.tsv", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r["tpcat"].strip():                 # catégorie vide : rien à typer
                cats.add(r["tpcat"])
    with open(DB / "type_categorie.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for c in sorted(cats):
            w.writerow([c, category_type(c)])

    print(f"plat_canonique: {len(idpc)}   plat_analyse: {sum(natures.values())} {dict(natures)}"
          f"   type_categorie: {len(cats)}")
    print("→ out/db/*.csv (chargement : python -m tools.load_db)")


if __name__ == "__main__":
    main()
