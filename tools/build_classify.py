"""
Classe chaque plat canonique de `out/canon.jsonl`.

    python -m tools.build_classify

Écrit `out/classified.jsonl` et `out/head_rules.json` (règles de mot de tête
apprises, figées pour la prod).
"""

import collections
import csv
import json
import random
import sys
from pathlib import Path

from croustillant_classifier.classify import category_type, decide, head, name_type


def arbitrate(t, conf, src, review, llm_t, votes, by_name, by_head, hint):
    """
    Le LLM ne décide jamais seul face aux règles : il départage des signaux en
    conflit, confirme un signal faible, ou propose un type quand il n'y a rien.
    """
    signals = {s for s in (by_name, by_head, hint) if s}
    signals |= {x for x, v in votes.items() if x != "INFO" and v >= 0.25 * sum(votes.values())}
    if src == "none":
        # sans signal, "AUTRE" n'est qu'une valeur par défaut : rien que le LLM puisse confirmer
        return ("INFO" if llm_t == "INFO" else llm_t), 0.6, "llm", ["llm_only"]
    if llm_t == t:
        return t, max(conf, 0.85), src + "+llm", []
    # le LLM (≈84 % d'accord) ne contredit jamais une règle de nom (≈97 %), et ne tranche pas
    # PLAT/ACCOMPAGNEMENT : il y range les garnitures servies en "Plats" (≈76 % sur ce couple)
    if t == by_name or {t, llm_t} == {"PLAT", "ACCOMPAGNEMENT"}:
        return t, conf, src, review + [f"llm={llm_t}"]
    if llm_t in signals:
        return llm_t, 0.8, "llm_arbitre", []
    if src == "none":
        return ("INFO" if llm_t == "INFO" else llm_t), 0.6, "llm", ["llm_only"]
    return t, conf, src, review + [f"llm={llm_t}"]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    out = Path("out")
    canon = {c["key"]: c for c in map(json.loads, open(out / "canon.jsonl", encoding="utf-8"))}
    parsed = {p["platid"]: p for p in map(json.loads, open(out / "parsed.jsonl", encoding="utf-8"))}

    # votes par platid : type de catégorie → nombre d'apparitions
    row_votes: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    cat_cache: dict[str, str | None] = {}
    with open("data/plat_context.tsv", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            cat = r["tpcat"]
            if cat not in cat_cache:
                cat_cache[cat] = category_type(cat)
            if t := cat_cache[cat]:
                row_votes[int(r["platid"])][t] += int(r["n"])

    votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    hints: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for line in open(out / "components.jsonl", encoding="utf-8"):
        row = json.loads(line)
        rv, comps = row_votes.get(row["platid"], {}), row["components"]
        hint = parsed[row["platid"]]["section_hint"]
        for i, c in enumerate(comps):
            if hint:
                hints[c["key"]][hint] += 1
            # dans un plateau découpé, seule la tête hérite (à moitié) de la catégorie :
            # le "Brie" d'un "Plat, riz, brie" servi en "Plats" n'est ni un plat ni une garniture
            if len(comps) > 1 and i > 0:
                continue
            for t, n in rv.items():
                votes[c["key"]][t] += n if len(comps) == 1 else 0.5 * n

    # règles de mot de tête apprises sur les plats aux votes nets
    head_stats: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for k, c in canon.items():
        v = votes[k]
        tot = sum(x for t, x in v.items() if t != "INFO")
        if tot >= 3:
            t, x = max(((t, x) for t, x in v.items() if t != "INFO"), key=lambda kv: kv[1])
            if x / tot >= 0.8:
                head_stats[head(c["label"])][t] += 1
    head_rules = {}
    for h, cnt in head_stats.items():
        t, x = cnt.most_common(1)[0]
        if h and sum(cnt.values()) >= 8 and x / sum(cnt.values()) >= 0.85:
            head_rules[h] = t
    for target in (out / "head_rules.json", Path("croustillant_classifier/resources/head_rules.json")):
        target.write_text(json.dumps(head_rules, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")

    # réponses du LLM local (tools/llm_review), si disponibles
    llm = {}
    if (out / "llm_labels.jsonl").exists():
        for line in open(out / "llm_labels.jsonl", encoding="utf-8"):
            d = json.loads(line)
            llm[d["key"]] = d["llm_type"]

    results = []
    for k, c in canon.items():
        hint = hints[k].most_common(1)[0][0] if hints[k] else None
        by_name, by_head = name_type(c["label"]), head_rules.get(head(c["label"]))
        t, conf, src, review = decide(votes[k], by_name, by_head, hint)
        if review and k in llm:
            t, conf, src, review = arbitrate(t, conf, src, review, llm[k], votes[k], by_name, by_head, hint)
        results.append({"key": k, "label": c["label"], "type": t, "confidence": conf, "source": src,
                        "review": review, "weight": c["weight"], "n_platids": c["n_platids"],
                        "votes": {a: round(b, 1) for a, b in votes[k].most_common()}})
    results.sort(key=lambda r: -r["weight"])
    with open(out / "classified.jsonl", "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ rapport
    W = sum(r["weight"] for r in results)
    print(f"{len(results)} plats canoniques, {len(head_rules)} règles de tête apprises\n")
    for name, keyf in (("type", lambda r: r["type"]), ("source", lambda r: r["source"])):
        cnt, wt = collections.Counter(), collections.Counter()
        for r in results:
            cnt[keyf(r)] += 1; wt[keyf(r)] += r["weight"]
        print(f"par {name}:")
        for k2, v in cnt.most_common():
            print(f"   {k2:15} {v:6} plats   {wt[k2] / W:6.1%} des apparitions")
    rev = [r for r in results if r["review"]]
    print(f"\nà revoir: {len(rev)} plats = {sum(r['weight'] for r in rev) / W:.1%} des apparitions")
    reasons = collections.Counter(x.split("=")[0].split("_vs")[0] for r in rev for x in r["review"])
    print("   raisons:", dict(reasons.most_common()))
    top_rev = [r for r in results[:3000] if r["review"]]
    print(f"   dont {len(top_rev)} parmi les 3000 plats les plus servis")

    random.seed(4)
    for t in ("ENTREE", "PLAT", "ACCOMPAGNEMENT", "DESSERT", "FROMAGE", "BOISSON", "FORMULE", "AUTRE"):
        pool = [r for r in results[:5000] if r["type"] == t]
        print(f"\n--- {t} ({len(pool)} dans le top 5000)")
        for r in random.sample(pool, min(10, len(pool))):
            print(f"   {r['label'][:55]:55} {r['confidence']:.2f} {r['source']:7} {r['review'] or ''}")
    print("\n--- conflits les plus servis")
    for r in [r for r in results if any("_vs_" in x for x in r["review"])][:30]:
        print(f"   {r['label'][:50]:50} → {r['type']:14} {r['review']}  {r['votes']}")


if __name__ == "__main__":
    main()
