"""
Revue des plats canoniques marqués A_REVOIR, dans le navigateur.

    python -m tools.review                  # base du .env, http://127.0.0.1:8765
    python -m tools.review --dsn "postgresql://…" --port 8765

La file est triée par nombre d'apparitions en menu : les plats les plus servis
d'abord. Chaque décision est écrite immédiatement en base (SOURCE = 'humain',
CONFIANCE = 1, A_REVOIR = FALSE) et journalisée dans `out/review_log.jsonl`
(utile pour enrichir les règles du classifieur).

Raccourcis : 1-8 type · Entrée valider le type actuel · 0 pas un plat ·
→ passer · ← précédent · / rechercher.

Le serveur n'écoute que sur 127.0.0.1.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from croustillant_classifier import TYPES

from tools.load_db import connect

LOG = Path("out/review_log.jsonl")


# --------------------------------------------------------------------------- #
# Données
# --------------------------------------------------------------------------- #

class Store:
    def __init__(self, conn):
        self.conn = conn
        self.lock = threading.Lock()
        with conn.cursor() as cur:
            # le /dev/shm du conteneur de prod est petit : pas de hash join parallèle
            cur.execute("SET max_parallel_workers_per_gather = 0")
        conn.commit()

    def queue(self) -> list[dict]:
        t = time.time()
        with self.lock, self.conn.cursor() as cur:
            cur.execute("""
                SELECT IDPC, CLE, LIBELLE, TYPE_PLAT, SOURCE, CONFIANCE, REVUE
                FROM PLAT_CANONIQUE WHERE A_REVOIR
            """)
            dishes = {r[0]: {"idpc": r[0], "key": r[1], "label": r[2], "type": r[3], "source": r[4],
                             "confidence": r[5], "review": r[6] or [], "weight": 0,
                             "cats": collections.Counter(), "variants": collections.Counter()}
                      for r in cur.fetchall()}
            cur.execute("""
                SELECT pco.IDPC, p.LIBELLE, ca.TPCAT, count(co.PLATID)
                FROM PLAT_COMPOSANT pco
                JOIN PLAT_CANONIQUE pc ON pc.IDPC = pco.IDPC AND pc.A_REVOIR
                JOIN PLAT p ON p.PLATID = pco.PLATID
                LEFT JOIN COMPOSITION co ON co.PLATID = pco.PLATID
                LEFT JOIN CATEGORIE ca ON ca.CATID = co.CATID
                GROUP BY 1, 2, 3
            """)
            for idpc, libelle, tpcat, n in cur.fetchall():
                d = dishes.get(idpc)
                if not d:
                    continue
                d["weight"] += n
                d["variants"][libelle] += n
                if tpcat:
                    d["cats"][tpcat.strip()] += n
            self.conn.commit()
        out = []
        for d in sorted(dishes.values(), key=lambda d: -d["weight"]):
            d["cats"] = d["cats"].most_common(5)
            d["variants"] = d["variants"].most_common(6)
            out.append(d)
        print(f"{len(out)} plats à revoir chargés en {time.time() - t:.1f} s", flush=True)
        return out

    def set_type(self, idpc: int, type_plat: str, label: str | None) -> None:
        if type_plat not in TYPES:
            raise ValueError(f"type inconnu : {type_plat}")
        with self.lock, self.conn.cursor() as cur:
            cur.execute("""
                UPDATE PLAT_CANONIQUE
                SET TYPE_PLAT = %s, LIBELLE = COALESCE(NULLIF(%s, ''), LIBELLE), SOURCE = 'humain',
                    CONFIANCE = 1, A_REVOIR = FALSE, REVUE = NULL, MIS_A_JOUR = CURRENT_TIMESTAMP
                WHERE IDPC = %s
            """, (type_plat, (label or "").strip()[:500], idpc))
            if cur.rowcount != 1:
                self.conn.rollback()
                raise LookupError(f"plat canonique {idpc} introuvable")
            self.conn.commit()

    def not_a_dish(self, idpc: int) -> int:
        """
        Le plat canonique n'est pas un plat (information, consigne…) : les libellés qui
        ne contiennent que lui deviennent des INFO, il est retiré des autres, puis supprimé.
        """
        with self.lock, self.conn.cursor() as cur:
            cur.execute("""
                UPDATE PLAT_ANALYSE pa SET NATURE = 'INFO', TYPE_INFO = 'HUMAIN', TRAITE_LE = CURRENT_TIMESTAMP
                WHERE pa.PLATID IN (SELECT PLATID FROM PLAT_COMPOSANT WHERE IDPC = %s)
                  AND NOT EXISTS (SELECT 1 FROM PLAT_COMPOSANT o WHERE o.PLATID = pa.PLATID AND o.IDPC <> %s)
            """, (idpc, idpc))
            n = cur.rowcount
            cur.execute("DELETE FROM PLAT_COMPOSANT WHERE IDPC = %s", (idpc,))
            cur.execute("DELETE FROM PLAT_CANONIQUE WHERE IDPC = %s", (idpc,))
            self.conn.commit()
        return n


def log(entry: dict) -> None:
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), **entry}, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# Serveur
# --------------------------------------------------------------------------- #

def make_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):            # silencieux
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data) -> None:
            self._send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def do_GET(self):
            if self.path == "/":
                self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            elif self.path == "/api/queue":
                self._json(200, {"types": list(TYPES), "dishes": store.queue()})
            else:
                self._json(404, {"error": "introuvable"})

        def do_POST(self):
            if self.path != "/api/review":
                return self._json(404, {"error": "introuvable"})
            # protection minimale : seule la page servie ici peut écrire
            if self.headers.get("Origin") not in (None, f"http://{self.headers.get('Host')}"):
                return self._json(403, {"error": "origine refusée"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                idpc = int(body["idpc"])
                if body["action"] == "not_dish":
                    n = store.not_a_dish(idpc)
                    log({"idpc": idpc, "key": body.get("key"), "label": body.get("label"), "action": "not_dish",
                         "before": body.get("before")})
                    return self._json(200, {"ok": True, "info_rows": n})
                store.set_type(idpc, body["type"], body.get("label"))
                log({"idpc": idpc, "key": body.get("key"), "label": body.get("label"), "action": "type",
                     "type": body["type"], "before": body.get("before")})
                return self._json(200, {"ok": True})
            except (KeyError, ValueError, LookupError) as e:
                return self._json(400, {"error": str(e)})
            except Exception as e:                # noqa: BLE001 — renvoyé à la page
                return self._json(500, {"error": str(e)})

    return Handler


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    conn = connect(a.dsn)
    p = conn.get_dsn_parameters()
    print(f"base : {p.get('user')}@{p.get('host')}:{p.get('port')}/{p.get('dbname')}")
    server = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(Store(conn)))
    url = f"http://127.0.0.1:{a.port}"
    print(f"revue sur {url}  (Ctrl+C pour arrêter)", flush=True)
    if not a.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Revue des plats</title>
<style>
  :root {
    --bg: #f6f5f2; --panel: #ffffff; --ink: #1d1d1b; --muted: #6b6a66; --line: #e3e1db;
    --accent: #c2410c; --accent-soft: #fdeee6; --ok: #15803d; --warn: #b45309;
    --key: #f0eee9;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #161614; --panel: #1f1f1c; --ink: #ecebe6; --muted: #9b9a94; --line: #34332f;
      --accent: #fb923c; --accent-soft: #3a2416; --ok: #4ade80; --warn: #fbbf24; --key: #2a2a26;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  header { display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
           padding: 14px 20px; border-bottom: 1px solid var(--line); background: var(--panel); }
  header h1 { font-size: 16px; margin: 0 12px 0 0; }
  header .stat { color: var(--muted); font-variant-numeric: tabular-nums; }
  header .grow { flex: 1; }
  select, input[type=search] { font: inherit; color: var(--ink); background: var(--bg);
           border: 1px solid var(--line); border-radius: 6px; padding: 5px 8px; }
  main { max-width: 860px; margin: 24px auto; padding: 0 16px; }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 22px 24px; }
  .meta { display: flex; gap: 14px; flex-wrap: wrap; color: var(--muted); font-size: 13px; margin-bottom: 10px; }
  .meta b { color: var(--ink); font-weight: 600; font-variant-numeric: tabular-nums; }
  #label { width: 100%; font: 600 22px/1.3 inherit; color: var(--ink); background: transparent;
           border: 1px solid transparent; border-radius: 6px; padding: 4px 6px; margin: 0 -6px 6px; }
  #label:hover, #label:focus { border-color: var(--line); outline: none; background: var(--bg); }
  .reasons { display: flex; gap: 6px; flex-wrap: wrap; margin: 4px 0 16px; }
  .reason { font: 12px ui-monospace, monospace; background: var(--accent-soft); color: var(--accent);
            padding: 2px 7px; border-radius: 4px; }
  .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
  @media (max-width: 640px) { .cols { grid-template-columns: 1fr; } }
  h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin: 0 0 6px; }
  ul { list-style: none; margin: 0; padding: 0; }
  li { display: flex; justify-content: space-between; gap: 10px; padding: 3px 0;
       border-bottom: 1px dashed var(--line); font-size: 14px; }
  li span:last-child { color: var(--muted); font-variant-numeric: tabular-nums; }
  .types { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
  @media (max-width: 640px) { .types { grid-template-columns: repeat(2, 1fr); } }
  button { font: inherit; color: var(--ink); background: var(--bg); border: 1px solid var(--line);
           border-radius: 8px; padding: 9px 10px; cursor: pointer; text-align: left; }
  button:hover { border-color: var(--accent); }
  button.current { border-color: var(--accent); background: var(--accent-soft); }
  button kbd { font: 11px ui-monospace, monospace; background: var(--key); border-radius: 4px;
               padding: 1px 5px; margin-right: 6px; color: var(--muted); }
  .actions { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
  .actions .primary { background: var(--accent); color: #fff; border-color: var(--accent); }
  .actions .danger:hover { border-color: var(--warn); }
  #toast { position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%); background: var(--ink);
           color: var(--bg); padding: 8px 14px; border-radius: 8px; font-size: 14px; opacity: 0;
           transition: opacity .2s; pointer-events: none; }
  #toast.show { opacity: 1; }
  .empty { text-align: center; color: var(--muted); padding: 60px 0; }
  .help { color: var(--muted); font-size: 12px; margin-top: 14px; }
</style>
</head>
<body>
<header>
  <h1>Revue des plats</h1>
  <span class="stat" id="progress">chargement…</span>
  <span class="grow"></span>
  <select id="filterType" aria-label="Filtrer par type"><option value="">Tous les types</option></select>
  <input type="search" id="search" placeholder="Rechercher ( / )" aria-label="Rechercher">
</header>
<main>
  <div class="card" id="card"><div class="empty">Chargement de la file…</div></div>
  <p class="help">1-8 type · Entrée valider le type actuel · 0 pas un plat · → passer · ← précédent · / rechercher.
     Le libellé est modifiable : il est enregistré avec la décision.</p>
</main>
<div id="toast"></div>
<script>
const LABELS = {ENTREE: "Entrée", PLAT: "Plat", ACCOMPAGNEMENT: "Accompagnement", DESSERT: "Dessert",
                FROMAGE: "Fromage", BOISSON: "Boisson", FORMULE: "Formule", AUTRE: "Autre"};
let types = [], all = [], view = [], pos = 0, done = 0;

const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const fmt = n => n.toLocaleString("fr-FR");

function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("show"), 1600);
}

function applyFilter() {
  const t = $("filterType").value, q = $("search").value.trim().toLowerCase();
  view = all.filter(d => !d.done && (!t || d.type === t) &&
    (!q || d.label.toLowerCase().includes(q) || d.variants.some(([v]) => v.toLowerCase().includes(q))));
  pos = Math.min(pos, Math.max(view.length - 1, 0));
  render();
}

function render() {
  const left = all.filter(d => !d.done).length;
  $("progress").textContent = `${fmt(done)} traités · ${fmt(left)} restants` + (view.length !== left ? ` · ${fmt(view.length)} filtrés` : "");
  const d = view[pos];
  if (!d) { $("card").innerHTML = `<div class="empty">Rien à revoir ici 🎉</div>`; return; }
  const list = rows => rows.length ? rows.map(([k, n]) => `<li><span>${esc(k)}</span><span>${fmt(n)}</span></li>`).join("")
                                   : `<li><span>—</span><span></span></li>`;
  $("card").innerHTML = `
    <div class="meta">
      <span>#<b>${pos + 1}</b> / ${fmt(view.length)}</span>
      <span><b>${fmt(d.weight)}</b> apparitions</span>
      <span>proposé <b>${LABELS[d.type] || d.type}</b> par ${esc(d.source)} (${Math.round(d.confidence * 100)} %)</span>
    </div>
    <input id="label" value="${esc(d.label)}" aria-label="Libellé du plat">
    <div class="reasons">${d.review.map(r => `<span class="reason">${esc(r)}</span>`).join("")}</div>
    <div class="cols">
      <div><h3>Écrit comme</h3><ul>${list(d.variants)}</ul></div>
      <div><h3>Servi en</h3><ul>${list(d.cats)}</ul></div>
    </div>
    <div class="types">${types.map((t, i) =>
      `<button data-type="${t}" class="${t === d.type ? "current" : ""}"><kbd>${i + 1}</kbd>${LABELS[t] || t}</button>`).join("")}
    </div>
    <div class="actions">
      <button class="primary" id="validate"><kbd>↵</kbd>Valider « ${LABELS[d.type] || d.type} »</button>
      <button class="danger" id="notDish"><kbd>0</kbd>Pas un plat</button>
      <button id="prev"><kbd>←</kbd>Précédent</button>
      <button id="skip"><kbd>→</kbd>Passer</button>
    </div>`;
  document.querySelectorAll("[data-type]").forEach(b => b.onclick = () => decide(b.dataset.type));
  $("validate").onclick = () => decide(d.type);
  $("notDish").onclick = notDish;
  $("prev").onclick = () => move(-1);
  $("skip").onclick = () => move(1);
}

function move(step) { pos = Math.max(0, Math.min(view.length - 1, pos + step)); render(); }

async function post(body) {
  const r = await fetch("/api/review", {method: "POST", headers: {"Content-Type": "application/json"},
                                         body: JSON.stringify(body)});
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.status);
  return j;
}

async function decide(type) {
  const d = view[pos]; if (!d) return;
  const label = $("label").value.trim();
  try {
    await post({action: "type", idpc: d.idpc, key: d.key, type, label: label || d.label,
                before: {type: d.type, label: d.label, source: d.source}});
    d.done = true; d.type = type; d.label = label || d.label; done++;
    toast(`${d.label} → ${LABELS[type]}`);
    view.splice(pos, 1); render();
  } catch (e) { toast("Erreur : " + e.message); }
}

async function notDish() {
  const d = view[pos]; if (!d) return;
  if (!confirm(`« ${d.label} » n'est pas un plat ?\nSes libellés deviendront des informations et le plat canonique sera supprimé.`)) return;
  try {
    await post({action: "not_dish", idpc: d.idpc, key: d.key, label: d.label,
                before: {type: d.type, label: d.label, source: d.source}});
    d.done = true; done++; toast(`${d.label} → pas un plat`);
    view.splice(pos, 1); render();
  } catch (e) { toast("Erreur : " + e.message); }
}

document.addEventListener("keydown", e => {
  const inField = ["INPUT", "SELECT"].includes(document.activeElement.tagName);
  if (e.key === "/" && !inField) { e.preventDefault(); $("search").focus(); return; }
  if (e.key === "Escape") { document.activeElement.blur(); return; }
  if (e.key === "Enter" && document.activeElement.id !== "search") { e.preventDefault(); const d = view[pos]; if (d) decide(d.type); return; }
  if (inField) return;
  if (e.key === "ArrowRight") move(1);
  else if (e.key === "ArrowLeft") move(-1);
  else if (e.key === "0") notDish();
  else if (/^[1-8]$/.test(e.key) && types[+e.key - 1]) decide(types[+e.key - 1]);
});

(async () => {
  const r = await fetch("/api/queue"); const j = await r.json();
  types = j.types; all = j.dishes;
  $("filterType").innerHTML += types.map(t => `<option value="${t}">${LABELS[t] || t}</option>`).join("");
  $("filterType").onchange = () => { pos = 0; applyFilter(); };
  $("search").oninput = () => { pos = 0; applyFilter(); };
  applyFilter();
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
