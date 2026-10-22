"""
Charge `out/db/*.csv` (produits par tools/export_db.py) dans la base, sans psql :
même connexion que le reste des outils (.env), donc via ton tunnel / reverse proxy.

    python -m tools.load_db                 # base du .env, demande confirmation
    python -m tools.load_db --dsn "postgresql://user:pass@host:port/base"

À lancer une fois les tables créées (schema.sql de CROUStillant). Rejouable : les quatre tables sont vidées puis
rechargées dans une seule transaction (tout ou rien). Ne plus le relancer une fois le
worker déployé : le TRUNCATE effacerait les corrections faites à la main.
"""

import argparse
import sys
from pathlib import Path

import psycopg2

DB = Path("out/db")
TABLES = [
    ("PLAT_CANONIQUE", "IDPC, CLE, LIBELLE, TYPE_PLAT, VEGETARIEN, CONFIANCE, SOURCE, A_REVOIR, REVUE",
     "plat_canonique.csv"),
    ("PLAT_ANALYSE", "PLATID, NATURE, TYPE_INFO, LIBELLE_NET, POINTS, POINTS_NOTE, PRIX, ALLERGENES, ORIGINES, "
     "LABELS, VIANDES, DETAILS, VEGETARIEN, STATION, INDICE_SECTION, DRAPEAUX, VERSION", "plat_analyse.csv"),
    ("PLAT_COMPOSANT", "PLATID, ORDRE, IDPC, LIBELLE", "plat_composant.csv"),
    ("TYPE_CATEGORIE", "TPCAT, TYPE_PLAT", "type_categorie.csv"),
]


def connect(dsn: str | None):
    if dsn:
        return psycopg2.connect(dsn)
    env = dict(l.strip().split("=", 1) for l in open(".env", encoding="utf-8") if "=" in l and not l.startswith("#"))
    return psycopg2.connect(dbname=env["POSTGRES_DATABASE"], user=env["POSTGRES_USER"],
                            password=env["POSTGRES_PASSWORD"], host=env["POSTGRES_HOST"], port=env["POSTGRES_PORT"])


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn")
    ap.add_argument("--yes", action="store_true", help="ne pas demander de confirmation")
    a = ap.parse_args()

    for _, _, f in TABLES:
        if not (DB / f).exists():
            sys.exit(f"{DB / f} introuvable : lance d'abord python -m tools.export_db")

    conn = connect(a.dsn)
    p = conn.get_dsn_parameters()
    target = f"{p.get('user')}@{p.get('host')}:{p.get('port')}/{p.get('dbname')}"
    if not a.yes and input(f"Vider et recharger PLAT_CANONIQUE, PLAT_ANALYSE, PLAT_COMPOSANT, "
                           f"TYPE_CATEGORIE sur {target} ? [oui/N] ").strip().lower() != "oui":
        sys.exit("annulé")

    with conn:                                   # une seule transaction : tout ou rien
        with conn.cursor() as cur:
            cur.execute("TRUNCATE PLAT_COMPOSANT, PLAT_ANALYSE, PLAT_CANONIQUE, TYPE_CATEGORIE RESTART IDENTITY")
            for table, cols, f in TABLES:
                with open(DB / f, encoding="utf-8") as fh:
                    cur.copy_expert(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv)", fh)
                print(f"  {table:15} {cur.rowcount:7} lignes", flush=True)
            cur.execute("SELECT setval(pg_get_serial_sequence('plat_canonique', 'idpc'), "
                        "(SELECT max(IDPC) FROM PLAT_CANONIQUE))")
    conn.autocommit = True
    with conn.cursor() as cur:
        for table, _, _ in TABLES:
            cur.execute(f"ANALYZE {table}")
    conn.close()
    print(f"chargé sur {target}")


if __name__ == "__main__":
    main()
