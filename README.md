# T-DAT-901 — Homepedia

Analyse du marché immobilier français (Epitech). Ce dépôt contient :

| Dossier | Contenu |
|---|---|
| `bootstrap/` | Exercices du bootstrap : 3 jobs PySpark sur les ventes immobilières, modélisation en étoile de KaDo |
| `scraping/orpi/` | Collecte de 500 annonces de vente Orpi |
| `db/` | Bases PostgreSQL/PostGIS + MongoDB (Docker), chargements et contrôles |
| `docs/` | Fiches explicatives (PySpark, scraping) |

Résultats et méthodologie du Follow-up 1 : [`bootstrap/docs/followup1.md`](bootstrap/docs/followup1.md).

---

## 1. Prérequis

| Outil | Version | Pour |
|---|---|---|
| Python | 3.14 | tout |
| Java (JDK) | 17 | Spark tourne dans la JVM |
| Docker + Docker Compose | récent | bases de données uniquement |

Il y a **deux environnements Python** :

| venv | requirements | Sert à |
|---|---|---|
| `bootstrap/.venv` | `bootstrap/requirements.txt` (pyspark, pandas) | jobs Spark |
| `.venv` (racine) | `requirements.txt` (psycopg, pymongo, requests, beautifulsoup4) | scripts `db/` et `scraping/` |

### Installation (une seule fois)

Windows (PowerShell), depuis la racine du dépôt :

```powershell
# Environnement Spark
python -m venv bootstrap\.venv
bootstrap\.venv\Scripts\pip install -r bootstrap\requirements.txt

# JDK 17 dans ~\.jdk (retrouvé automatiquement par bootstrap/spark_session.py)
bootstrap\.venv\Scripts\python -c "import jdk; jdk.install('17')"

# Environnement bases de données + scraping
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

macOS / Linux : mêmes commandes avec `bin/` au lieu de `Scripts\`. Installer un JDK 17 et définir `JAVA_HOME` (la détection automatique de `spark_session.py` ne concerne que Windows).

> Si le chemin du JDK installé diffère de `~\.jdk\jdk-17.0.20.1+1`, définir `JAVA_HOME` à la main : `$env:JAVA_HOME = "C:\chemin\vers\jdk-17..."`.

### Données (non versionnées)

Les fichiers de données ne sont pas dans git (trop volumineux). Les récupérer sur le Sharepoint du bootstrap et les placer ici :

```
bootstrap/data/
├── KaDo.csv
├── france_total_real_estate_sales_2022.csv.zip
└── france_total_real_estate_sales_2022.csv      ← le zip décompressé (lu par les jobs Spark)
```

```powershell
Expand-Archive bootstrap\data\france_total_real_estate_sales_2022.csv.zip -DestinationPath bootstrap\data
```

---

## 2. Lancer les jobs PySpark

Depuis la racine du dépôt, avec le venv Spark :

```powershell
bootstrap\.venv\Scripts\python bootstrap\scripts\job1_map_prix_m2.py
bootstrap\.venv\Scripts\python bootstrap\scripts\job2_reduce_valeur_departement.py
bootstrap\.venv\Scripts\python bootstrap\scripts\job3_sortbykey_top10_communes.py
```

Chaque job prend quelques minutes. **Les lancer un par un** : en parallèle sur une même machine, la mémoire sature et le worker Python de Spark plante.

| Job | Primitive | Calcule | Sortie (`bootstrap/data/processed/`) |
|---|---|---|---|
| `job1_map_prix_m2.py` | `map()` | Prix au m² de chaque ligne Appartement / Maison | `ventes_prix_m2.csv` |
| `job2_reduce_valeur_departement.py` | `reduceByKey()` | Valeur foncière par département, brute et dédoublonnée par mutation | `valeur_fonciere_par_departement.csv` |
| `job3_sortbykey_top10_communes.py` | `sortByKey()` | Top 10 des communes les plus chères (médiane €/m², ventes d'un seul logement, ≥ 5 ventes) par département | `top10_communes_par_departement.csv` |

La lecture et le nettoyage du CSV (format des montants, codes département, clé de mutation) sont communs aux 3 jobs : `bootstrap/dvf.py`.

### Ce qu'on doit voir

Job 2 (extrait) :

```
LIGNES (ventes valides Appartement/Maison) 1156643
MUTATIONS UNIQUES 915401
LIGNES EN DOUBLON (autres lots d'une meme mutation) 241242 (20.9%)
...
TOTAL DEDUP 254484347536.01
```

Job 3 (extrait) :

```
VERIFICATION - top 3 du departement 75 (Paris)
('75', (1, '75106', 'PARIS 06', 15000.0, 921))
('75', (2, '75107', 'PARIS 07', 14846.15, 1073))
```

### Problèmes fréquents

| Message | Cause | Solution |
|---|---|---|
| `JAVA_HOME is not set` / `Java gateway process exited` | JDK introuvable | Installer le JDK 17 (section 1) ou définir `JAVA_HOME` |
| `Path does not exist: ...france_total_real_estate_sales_2022.csv` | Zip pas décompressé | `Expand-Archive` (section 1) |
| `Python worker exited unexpectedly (crashed)` | Mémoire saturée (plusieurs jobs ou gros programmes en même temps) | Fermer ce qui consomme, relancer le job seul |
| `WARN Shell: Did not find winutils.exe` | Binaires Hadoop absents sous Windows | Avertissement sans conséquence ici, à ignorer |

---

## 3. Bases de données (optionnel pour les jobs)

Avec le venv racine. Copier d'abord `db/.env.example` vers `db/.env` et changer les mots de passe.

```powershell
docker compose -f db/docker-compose.yml --env-file db/.env up -d --wait

.venv\Scripts\python db\load_referentiel.py   # régions, départements, communes (API geo.api.gouv.fr)
.venv\Scripts\python db\load_postgres.py      # mutations DVF + annonces Orpi (~8 min)
.venv\Scripts\python db\load_kado.py          # KaDo en schéma en étoile (~4 min)

.venv\Scripts\python db\check.py              # contrôles PASS/FAIL, attendu : 26/26
```

PostgreSQL écoute sur le port **5433** de la machine (`POSTGRES_PORT` dans `db/.env`). Tous les chargements sont rejouables : les relancer ne crée pas de doublons.

---

## 4. Scraping Orpi (optionnel)

Les 500 annonces sont déjà collectées dans `scraping/orpi/data/` (non versionné). Pour recollecter :

```powershell
cd scraping\orpi
..\..\.venv\Scripts\python collecte.py --n 500 --seed 42 --out data/listings_raw.jsonl   # ~10 min (1 requête/s)
..\..\.venv\Scripts\python nettoyage.py                                                 # -> data/listings_clean.csv
```

Règles de collecte (robots.txt, rythme, User-Agent) : [`scraping/orpi/docs/methodologie.md`](scraping/orpi/docs/methodologie.md).
