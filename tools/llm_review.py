"""
Revue hors-ligne des plats incertains par un LLM local (Ollama). Jamais utilisé en prod :
les réponses retenues sont figées dans `croustillant_classifier/resources/overrides.json`.

    python -m tools.llm_review calibrate [--n 400]     # mesure l'accord avec les plats sûrs
    python -m tools.llm_review review [--limit 5000]   # étiquette la file de revue (reprenable)

Le cache `out/llm_labels.jsonl` garde chaque réponse : relancer ne refait que le manquant.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import random
import sys
import time
import urllib.request
from pathlib import Path

OLLAMA = "http://localhost:11434/api/chat"
LLM_TYPES = ["ENTREE", "PLAT", "ACCOMPAGNEMENT", "DESSERT", "FROMAGE", "BOISSON", "FORMULE", "AUTRE", "INFO"]
OUT = Path("out")

SYSTEM = """Tu classes des libellés de la carte des restaurants universitaires français (CROUS).
Pour chaque libellé, donne UN type :
- ENTREE : entrée froide ou chaude, crudités, salade d'entrée, potage, charcuterie, œuf mayo
- PLAT : plat principal (viande, poisson, plat végétarien, pâtes ou riz garnis), sandwich, panini, burger, pizza, salade-repas, wrap, quiche servie en plat
- ACCOMPAGNEMENT : garniture servie avec un plat : féculent ou légume seul (frites, riz, pâtes nature, haricots verts, purée, poêlée de légumes)
- DESSERT : dessert, fruit, yaourt, laitage sucré, pâtisserie, viennoiserie, biscuit, confiserie
- FROMAGE : fromage (portion, assiette)
- BOISSON : boisson chaude ou froide
- FORMULE : description d'une formule ou d'un menu composé ("1 sandwich + 1 boisson")
- AUTRE : produit alimentaire qui ne rentre dans aucun type (pain, sauce seule, chips)
- INFO : ce n'est pas un aliment (information, horaire, prix, consigne, nom de stand)
Les catégories du menu où le plat a été servi sont un indice, pas une vérité.
Réponds uniquement en JSON."""

SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "integer"}, "type": {"type": "string", "enum": LLM_TYPES}},
    "required": ["id", "type"]}}}, "required": ["items"]}


def ask(model: str, batch: list[dict]) -> dict[int, str]:
    lines = []
    for i, d in enumerate(batch):
        ctx = f' | servi en : {", ".join(d["cats"])}' if d["cats"] else ""
        var = f' | aussi écrit : {" ; ".join(d["variants"])}' if d["variants"] else ""
        lines.append(f'{i}. {d["label"]}{var}{ctx}')
    body = {"model": model, "stream": False, "think": False, "format": SCHEMA,
            "options": {"temperature": 0, "num_ctx": 8192},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": "\n".join(lines)}]}
    req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        content = json.loads(r.read())["message"]["content"]
    out = {}
    for it in json.loads(content).get("items", []):
        if 0 <= it.get("id", -1) < len(batch) and it.get("type") in LLM_TYPES:
            out[it["id"]] = it["type"]
    return out


def load_dishes() -> list[dict]:
    """Plats canoniques classés, avec variantes et catégories de menu."""
    canon = {c["key"]: c for c in map(json.loads, open(OUT / "canon.jsonl", encoding="utf-8"))}
    key_pids = collections.defaultdict(set)
    for line in open(OUT / "components.jsonl", encoding="utf-8"):
        row = json.loads(line)
        for c in row["components"]:
            key_pids[c["key"]].add(row["platid"])
    pid_cats = collections.defaultdict(collections.Counter)
    with open("data/plat_context.tsv", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            pid_cats[int(r["platid"])][r["tpcat"].strip()] += int(r["n"])
    dishes = []
    for r in map(json.loads, open(OUT / "classified.jsonl", encoding="utf-8")):
        cats = collections.Counter()
        for pid in list(key_pids[r["key"]])[:200]:
            cats.update(pid_cats[pid])
        variants = [v for v in canon[r["key"]]["variants"] if v != r["label"]][:2]
        dishes.append({**r, "cats": [c for c, _ in cats.most_common(3)], "variants": variants})
    return dishes


def run(model: str, dishes: list[dict], cache_path: Path, batch_size: int) -> dict[str, str]:
    cache = {}
    if cache_path.exists():
        for line in open(cache_path, encoding="utf-8"):
            d = json.loads(line)
            cache[(d["model"], d["key"])] = d["llm_type"]
    todo = [d for d in dishes if (model, d["key"]) not in cache]
    print(f"{len(dishes) - len(todo)} déjà en cache, {len(todo)} à demander", flush=True)
    t0 = time.time()
    with open(cache_path, "a", encoding="utf-8") as f:
        for b in range(0, len(todo), batch_size):
            batch = todo[b:b + batch_size]
            try:
                ans = ask(model, batch)
            except Exception as e:                       # noqa: BLE001 — on log et on continue
                print(f"  lot {b}: erreur {e}", flush=True)
                continue
            for i, d in enumerate(batch):
                if i in ans:
                    cache[(model, d["key"])] = ans[i]
                    f.write(json.dumps({"model": model, "key": d["key"], "label": d["label"],
                                        "llm_type": ans[i]}, ensure_ascii=False) + "\n")
            f.flush()
            done = b + len(batch)
            if done % (batch_size * 10) == 0 or done == len(todo):
                rate = done / (time.time() - t0)
                print(f"  {done}/{len(todo)}  ({rate:.1f} plats/s, reste ~{(len(todo) - done) / rate / 60:.0f} min)",
                      flush=True)
    return {d["key"]: cache[(model, d["key"])] for d in dishes if (model, d["key"]) in cache}


def calibrate(model: str, n: int, batch_size: int) -> None:
    dishes = load_dishes()
    # vérité terrain : règle de nom sûre, ou menus très nets et nombreux, sans conflit
    gold = [d for d in dishes if not d["review"] and d["type"] != "INFO"
            and ((d["source"] == "name" and d["confidence"] >= 0.97)
                 or (d["source"] == "menus" and d["confidence"] >= 0.9))]
    by_type = collections.defaultdict(list)
    for d in gold:
        by_type[d["type"]].append(d)
    random.seed(7)
    sample = [d for t, ds in by_type.items() for d in random.sample(ds, min(len(ds), n // len(by_type)))]
    labels = run(model, sample, OUT / "llm_labels.jsonl", batch_size)
    conf = collections.defaultdict(collections.Counter)
    for d in sample:
        if d["key"] in labels:
            conf[d["type"]][labels[d["key"]]] += 1
    ok = sum(c[t] for t, c in conf.items()); tot = sum(sum(c.values()) for c in conf.values())
    print(f"\naccord global {ok}/{tot} = {ok / tot:.1%}")
    for t, c in sorted(conf.items()):
        print(f"   {t:15} {c[t] / sum(c.values()):6.1%}  {dict(c.most_common())}")
    print("\ndésaccords (échantillon):")
    bad = [d for d in sample if d["key"] in labels and labels[d["key"]] != d["type"]]
    for d in bad[:40]:
        print(f"   {d['label'][:50]:50} vérité={d['type']:14} llm={labels[d['key']]:14} {d['cats']}")


def review(model: str, limit: int, batch_size: int) -> None:
    dishes = [d for d in load_dishes() if d["review"]][:limit]
    labels = run(model, dishes, OUT / "llm_labels.jsonl", batch_size)
    agree = collections.Counter((d["type"] == labels.get(d["key"])) for d in dishes if d["key"] in labels)
    print(f"\n{len(labels)} étiquetés ; accord avec la règle : {agree[True]} / désaccord : {agree[False]}")
    print("types LLM :", dict(collections.Counter(labels.values()).most_common()))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["calibrate", "review"])
    ap.add_argument("--model", default="qwen3:8b")
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--limit", type=int, default=100000)
    ap.add_argument("--batch", type=int, default=20)
    a = ap.parse_args()
    if a.mode == "calibrate":
        calibrate(a.model, a.n, a.batch)
    else:
        review(a.model, a.limit, a.batch)


if __name__ == "__main__":
    main()
