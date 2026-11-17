# Follow-up 1 — T-DAT-901 Homepedia

Exercices `bootstrap/exo.md` : modélisation en étoile de KaDo + pipeline PySpark map / reduceByKey / sortByKey sur les ventes immobilières.
Mis à jour le 2026-09-24 : clé de dédoublonnage corrigée, jobs relancés, KaDo chargé en base. Tous les chiffres ci-dessous sont ceux des dernières exécutions.

---

## 1. Sources

| # | Dataset | Fichier | Origine |
|---|---|---|---|
| 1 | **KaDo** | `bootstrap/data/KaDo.csv` (766 Mo, 7 245 522 lignes) | Bootstrap pédagogique — tickets de caisse d'une parfumerie |
| 2 | **Ventes immobilières France 2022** | `bootstrap/data/france_total_real_estate_sales_2022.csv.zip` (430 Mo décompressé, 3 803 885 lignes) | Même structure que **DVF — Demandes de Valeurs Foncières** (DGFiP, open data `data.gouv.fr`). Fourni retraité dans le bootstrap — origine exacte à confirmer |
| 3 | **Référentiel géographique** | API `geo.api.gouv.fr` (régions, départements, communes + contours) | Open data officiel, clé = code INSEE |
| 4 | **Annonces Orpi** | `scraping/orpi/` — 500 annonces de vente | Scraping du site Orpi, cf. `scraping/orpi/docs/methodologie.md` |

Couverture DVF : **pas de données pour la Moselle, le Bas-Rhin, le Haut-Rhin (57, 67, 68) ni Mayotte (976)**. L'Alsace-Moselle relève du Livre foncier et n'est pas publiée dans DVF.

---

## 2. Schéma de BDD

### KaDo — étoile, chargée dans PostgreSQL (schéma `kado`)

Conception : [`schema/schema_kado.md`](schema/schema_kado.md) · DDL : `db/postgres/kado.sql` · chargement : `db/load_kado.py`

```
            Dim_Client (cli_id)
                  │
Dim_Temps ── Fait_Vente ── Dim_Produit
(mois, trimestre)  ticket_id (dimension dégénérée)   produit_id, libelle,
                   cli_id, produit_id, mois_vente    famille, univers, maille
                   prix_net (mesure)
```

| Table | Lignes |
|---|---|
| `kado.fait_vente` | 7 245 522 |
| `kado.dim_client` | 853 514 |
| `kado.dim_produit` | 1 484 |
| `kado.dim_temps` | 12 |

Chiffre d'affaires total : 43 256 372,18 €, identique au CSV au centime près (`db/check.py`).

### Homepedia — PostgreSQL/PostGIS + MongoDB (en cours)

Plan `2026-09-23-t-dat-901-stockage-bdd`, étapes 1-3 faites : référentiel géographique (18 régions, 101 départements, 34 875 communes + 45 arrondissements), `mutation_dvf` (1 403 428 actes), `annonce` (500) et `agence` (369). Clé pivot entre toutes les sources = **code INSEE de la commune**. MongoDB (JSON brut des annonces, textes) à venir.

Vérification : `python db/check.py` → **26/26 PASS** (référentiel, DVF, Orpi, KaDo).

---

## 3. Pipeline PySpark sur les ventes immobilières

Lecture et nettoyage communs : `bootstrap/dvf.py`. Périmètre : `Type local` ∈ {Appartement, Maison}, valeur foncière renseignée, surface bâtie > 0, soit **1 156 643 lignes** sur 3 803 885 (19 exclues pour surface nulle).

### Le piège : une ligne n'est pas une vente

Une **mutation** (un acte) apparaît sur autant de lignes qu'elle a de lots, **avec la valeur de l'acte entier répétée sur chaque ligne**. Clé d'une mutation = date + code INSEE commune + nature + valeur (la même que le chargement PostgreSQL).

> Correction par rapport à la première version : la clé ajoutait section + n° de plan, ce qui coupait en morceaux les actes portant sur plusieurs parcelles. Doublons : 226 186 → **241 242** ; écart brut / dédoublonné : 568,9 → **602,2 Md€**.

### Job 1 — `map()` : prix au m² de chaque ligne (`scripts/job1_map_prix_m2.py`)
`rdd.map(lambda r: (..., round(valeur / surface, 2)))`, transformation 1 → 1. Prix/m² moyen 13 145 €, maximum **46,6 M€/m²** : c'est le symptôme du piège ci-dessus (valeur d'un acte entier divisée par la surface d'un seul lot).

### Job 2 — `reduceByKey()` : valeur foncière par département (`scripts/job2_reduce_valeur_departement.py`)

| | Valeur |
|---|---|
| Lignes | 1 156 643 |
| Mutations uniques | 915 401 |
| Lignes en doublon | 241 242 (**20,9 %**) |
| Total brut (lecture littérale de l'exercice) | 856,7 Md€ |
| **Total dédoublonné (à retenir)** | **254,5 Md€** |

Brut ÷ dédoublonné : Paris ×3,6 · Seine-Saint-Denis ×8,9 · **Côtes-d'Armor ×109**. Cas extrême vérifié en base : un seul acte du 2022-06-14 à 59 M€ couvre **1 735 logements** (vente en bloc). Répété sur ses lignes, il pèse à lui seul ~100 Md€ dans la somme brute.

Deux `reduceByKey` : l'un garde une seule valeur par mutation (`lambda a, b: a`), l'autre somme par département (`add`).

### Job 3 — `sortByKey()` : top 10 des communes les plus chères par département (`scripts/job3_sortbykey_top10_communes.py`)
- Prix/m² calculé **par mutation**, seulement sur les ventes (`Vente`) **d'un seul logement** : 769 976 ventes.
- **Médiane** par commune (robuste aux valeurs aberrantes), **5 ventes minimum** : 15 651 communes classées sur 29 008.
- Top 10 par département (fonction de fenêtre), puis `sortByKey()` sur le code département normalisé (01 … 2A, 2B … 95, 971 … 974).

| Contrôle de cohérence | Médiane €/m² | Ventes |
|---|---|---|
| 75 — Paris 6e | 15 000 | 921 |
| 75 — Paris 7e | 14 846 | 1 073 |
| 06 — Saint-Jean-Cap-Ferrat | 12 500 | 56 |

Paris 6e recoupé par PostgreSQL : 14 998 €/m² (appartements seuls, médiane exacte).

---

## 4. Méthodologie de nettoyage — synthèse

| Problème | Traitement |
|---|---|
| `Valeur fonciere` au format français (`"55000,00"`) | `,` → `.` puis cast en double |
| Codes département non normalisés (`"6"`, `"972"`) | Complétés sur 2 caractères (`"06"`), sans tronquer les codes DOM |
| Lignes hors {Appartement, Maison} | Exclues (marché résidentiel) |
| Valeur foncière absente (2 859 lignes) ou surface nulle (19 lignes) | Exclues |
| Actes multi-lots comptés plusieurs fois (20,9 % des lignes) | Clé de mutation pour les agrégats |
| Prix/m² d'un acte à plusieurs logements non interprétable | Ventes d'un seul logement uniquement (job 3) |
| Valeurs aberrantes | Médiane + seuil de volume plutôt qu'un filtrage arbitraire |
| Hiérarchie produit KaDo supposée FAMILLE > UNIVERS > MAILLE | Invalidée (30 MAILLE sur 34 sous plusieurs UNIVERS) → attributs à plat, pas de flocon |

---

## 5. Reproduire

```bash
# Spark (bootstrap/.venv)
bootstrap/.venv/Scripts/python bootstrap/scripts/job1_map_prix_m2.py        # idem job2, job3

# Bases (.venv racine)
docker compose -f db/docker-compose.yml --env-file db/.env up -d --wait
.venv/Scripts/python db/load_referentiel.py && .venv/Scripts/python db/load_postgres.py && .venv/Scripts/python db/load_kado.py
# Depuis le 2026-11-14, les ventes DVF sont chargées à part (DVF Etalab 2022-2025) :
.venv/Scripts/python db/telecharger_dvf.py && .venv/Scripts/python db/load_dvf.py
.venv/Scripts/python db/check.py
```

---

## 6. Points ouverts pour le pédago

1. Source exacte du fichier `france_total_real_estate_sales_2022.csv` (DVF officiel retraité ?)
2. Plateforme pour le cluster Spark du projet complet (Databricks, VM, Spark en Docker ?)
3. Scraping : le bootstrap suggère ville-ideale.fr (avis d'habitants) — Orpi retenu pour la richesse du JSON embarqué et un `robots.txt` permissif ; ville-ideale reste une piste pour la source textuelle / sentiment.


Partir sur Mongo + MySQL

LakeHouse + format parquet


