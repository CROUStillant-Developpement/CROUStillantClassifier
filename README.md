<div align="center">
<img src="https://croustillant.menu/logo.png" alt="CROUStillant Logo"/>
  
# CROUStillant Classifier
CROUStillant est un projet qui a pour but de fournir les menus des restaurants universitaires en France et en Outre-Mer. 

</div>
  
# 📖 • Sommaire

- [🚀 • Présentation](#--présentation)
- [📦 • Installation](#--installation)
- [💻 • Développement](#--développement)
- [📄 • Utilisation](#--utilisation)
- [🧠 • Fonctionnement](#--fonctionnement)
- [🗃️ • Base de données](#️--base-de-données)
- [🛠️ • Pipeline hors-ligne](#️--pipeline-hors-ligne)
- [🚢 • Déploiement](#--déploiement)
- [📃 • Crédits](#--crédits)
- [📝 • License](#--license)

# 🚀 • Présentation

Ce dépôt contient le code source d'une librairie interne de CROUStillant en Python qui nettoie, dédoublonne et type les plats saisis à la main par les restaurants du CROUS.

```
"Sauté de porc aux pruneaux - 5 pts (1.3.7)"   →  Sauté de porc aux pruneaux · PLAT · 5 points · allergènes 1, 3, 7
"Poisson pané , riz , ratatouille"             →  Poisson pané [PLAT] + Riz [ACCOMPAGNEMENT] + Ratatouille [PLAT]
"Structure fermée du lundi 5 mai 2025 …"       →  INFO (fermeture), pas un plat
"Poulet à la basquaise" / "POULET BASQUAISE"   →  même plat canonique
```

La librairie n'a **aucune dépendance** et ne fait **aucun appel réseau** : uniquement des règles déterministes et deux tables JSON figées (`croustillant_classifier/resources/`). Un LLM local ([Ollama](https://ollama.com)) n'est utilisé qu'**hors-ligne**, pour départager les cas douteux avant l'import initial.

# 📦 • Installation

```bash
pip install git+https://github.com/CROUStillant-Developpement/CROUStillantClassifier
```

Ou avec [uv](https://github.com/astral-sh/uv) :

```bash
uv add git+https://github.com/CROUStillant-Developpement/CROUStillantClassifier
```

# 💻 • Développement

Pour installer la librairie en mode de développement, exécutez les commandes suivantes :

1. Cloner le dépôt
```bash
git clone https://github.com/CROUStillant-Developpement/CROUStillantClassifier
```

2. Se placer dans le répertoire du projet
```bash
cd CROUStillantClassifier
```

3. Créer un environnement virtuel et installer les dépendances
```bash
uv sync
```

4. Lancer les tests
```bash
uv run pytest
```

# 📄 • Utilisation

```python
from croustillant_classifier import Classifier, occurrence_type


# Charge les tables figées (une seule fois, à garder en mémoire)
classifier = Classifier()

# Analyser un libellé brut, avec la catégorie du menu où il apparaît
analyse = classifier.analyse("Endives aux lardons 2 pts (1.7)", category="Entrées")

analyse.is_dish                     # True : un vrai plat (pas une fermeture, un horaire...)
analyse.parsed.name                 # "Endives aux lardons"
analyse.parsed.points               # 2.0
analyse.parsed.allergen_ids         # [1, 7] : codes déclarés dans le libellé

# Un libellé peut contenir plusieurs plats ("Poisson pané, riz, ratatouille")
for composant in analyse.components:
    composant.label                 # "Endives aux lardons"
    composant.key                   # clé du plat canonique
    composant.type                  # "ENTREE" : type proposé pour un plat canonique encore inconnu
    composant.needs_review          # True si les signaux se contredisent

# Calculer la clé canonique d'un libellé
classifier.key("Poulet à la basquaise") == classifier.key("POULET BASQUAISE (maison)")  # True

# Type d'une occurrence : une pizza servie en "Entrées" est une entrée ce jour-là
occurrence_type("PLAT", "Entrées")          # "ENTREE"
occurrence_type("ACCOMPAGNEMENT", "Plats")  # "ACCOMPAGNEMENT" : une purée reste une garniture
```

Dans [CROUStillant](https://github.com/CROUStillant-Developpement/CROUStillant), `CROUStillant/dishes.py` analyse chaque nouveau `PLAT` à l'ingestion, enregistre le type des nouvelles catégories et rattrape, à chaque tâche complète, les plats jamais analysés ou analysés par une autre version du classifieur.

# 🧠 • Fonctionnement

| Étape | Module | Rôle |
|---|---|---|
| 1. Parsing | `parse.py` | Extrait points, prix, allergènes, origines, labels, régime, préfixes de section ; détecte les informations (fermetures, horaires, application...) |
| 2. Découpage | `canon.py` | Découpe les plateaux (`,` `/` `+` `ou` `-`) seulement si chaque morceau est un plat connu ; rattache les sauces au plat qui les précède |
| 3. Clé canonique | `canon.py` | Ignore casse, accents, ordre des mots, mots outils, quantités, pluriel ; corrige abréviations et fautes de frappe connues |
| 4. Type | `classify.py` | Règles sur le nom, puis catégories de menu, puis mot de tête ; en cas de contradiction, le plat part en revue |

**Types** : `ENTREE`, `PLAT`, `ACCOMPAGNEMENT`, `DESSERT`, `FROMAGE`, `BOISSON`, `FORMULE`, `AUTRE`.

Quelques choix de conception :

- **Précision avant tout** : les allergènes et valeurs nutritionnelles seront calculés à partir de ces données. Dans le doute, un plat est marqué à revoir plutôt que deviné.
- **Un mot du dictionnaire n'est jamais « corrigé »** : sans ce garde-fou, *canaille* devenait *vanille*.
- **Le régime fait partie de l'identité** : `Burger VG` et `Burger` sont deux plats différents.
- **Les variantes restent distinctes** : `Pizza margherita` et `Pizza 4 fromages` ne sont pas fusionnées.
- **Type par défaut + type d'occurrence** : chaque plat canonique a un type par défaut, que la catégorie du jour peut réinterpréter (`OCCURRENCE_OVERRIDES`).

# 🗃️ • Base de données

| Table | Contenu |
|---|---|
| `PLAT_ANALYSE` | Une ligne par libellé brut : nature (`DISH`, `INFO`, `JUNK`...), libellé net, points, prix, allergènes déclarés, origines, labels, régime, drapeaux |
| `PLAT_COMPOSANT` | Libellé brut → 1..n plats canoniques (plateaux découpés) |
| `PLAT_CANONIQUE` | Le plat réel : clé, libellé, **type par défaut**, confiance, source, `A_REVOIR` |
| `TYPE_CATEGORIE` | Type porté par une catégorie de menu (`NULL` si vague, ex : « A la carte ») |
| `V_COMPOSITION_TYPEE` | Type d'une occurrence = type par défaut, sauf réinterprétation par la catégorie |

> [!IMPORTANT]
> Un plat canonique existant n'est **jamais modifié** par l'ingestion : un type corrigé à la main en base fait foi.

# 🛠️ • Pipeline hors-ligne

Le dossier `tools/` (non livré avec la librairie) régénère les tables figées et prépare l'import en base. Il utilise des données locales, non versionnées, dans `data/` :

| Fichier | Contenu |
|---|---|
| `data/plat.txt` | Extraction des plats (`platid;libelle`) |
| `data/plat_context.tsv` | Plat × catégorie × restaurant (extrait en lecture seule) |
| `data/wordlist/fr.txt` | Liste de mots français (garde-fou des corrections orthographiques) |

```bash
uv run python -m tools.report_parse          # data/plat.txt → out/parsed.jsonl (+ rapport)
uv run python -m tools.build_canon           # découpage, clés → resources/lexicon.json
uv run python -m tools.build_classify        # types → resources/head_rules.json
uv run python -m tools.llm_review calibrate  # accord du LLM local avec les plats sûrs
uv run python -m tools.llm_review review     # LLM sur la file de revue (reprenable)
uv run python -m tools.build_classify        # relancer pour intégrer les réponses du LLM
uv run python -m tools.export_db             # out/db/*.csv, chargés par tools.load_db
```

Le LLM (`qwen3:8b` par défaut) n'est **jamais** seul juge : il départage des signaux en conflit, confirme un signal faible ou propose un type quand il n'y en a aucun (le plat reste alors à revoir). Il ne contredit jamais une règle de nom et ne tranche pas entre `PLAT` et `ACCOMPAGNEMENT`.

# 🚢 • Déploiement

1. Pousser ce dépôt, puis mettre à jour la dépendance dans CROUStillant
```bash
uv lock --upgrade-package croustillant-classifier
```

2. Créer les tables : elles sont définies dans le `schema.sql` de CROUStillant (une base existante doit recevoir les mêmes `CREATE TABLE` / `CREATE VIEW` à la main).

3. Charger le résultat hors-ligne (via la connexion du `.env`, tunnel compris)
```bash
uv run python -m tools.load_db
```

4. Déployer CROUStillant.

> [!WARNING]
> Toute modification des règles change les clés : incrémenter `VERSION` dans `croustillant_classifier/analyzer.py`. La tâche complète réanalysera alors les libellés. Ne plus relancer `tools.load_db` une fois le worker déployé : il efface aussi les corrections faites à la main.

# 📃 • Crédits

- [CROUStillant Développement](https://croustillant.menu/fr/about#team) - L'équipe de CROUStillant Développement

# 📝 • License

CROUStillant Classifier est sous licence [GNU Affero General Public License v3.0](LICENSE).

```
Copyright (C) 2026 CROUStillant Développement

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
```
