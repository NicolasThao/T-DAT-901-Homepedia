# Point d'équipe — Homepedia, 19 novembre 2026 (veille du Follow-up 2)

> Pour : l'équipe. Ce que j'ai fait, ce que j'ai repris de votre travail, ce qui reste, et comment s'y mettre.
> Tous les chiffres viennent de la base (`docs/followup2/faits.json`) ou d'une commande rejouable.

## 1. En une phrase

Les 4 étapes du sujet tournent de bout en bout en local (collecte → bases → Spark → carte interactive) sur 4 ans de
ventes DVF, et le pipeline Spark du domaine prix est prêt pour OVHcloud Data Platform. **Il n'est pas encore déployé** :
c'est le premier chantier du palier qui commence le 23/11.

## 2. Ce qui est fait

| Étape du sujet | Ce qui existe | Preuve |
|---|---|---|
| Collecte | DVF géolocalisées Etalab 2022-2025 (15 708 373 lignes), référentiel geo.api.gouv.fr (communes, contours), 500 annonces Orpi scrapées | `db/telecharger_dvf.py`, `scraping/orpi/` |
| Bases | PostgreSQL/PostGIS (ventes, communes, contours, indicateurs) + MongoDB (annonces brutes) ; 5 593 305 ventes, qualité marquée (hors marché, prix douteux), jamais supprimée | `db/check.py` : **75/75 PASS** |
| Big data | Pipeline Spark en 3 étapes (bronze → argent → or, puis contrôles) : 274 820 indicateurs (médiane, quartiles, déciles, prix d'un bien, surface, nombre de ventes) par commune, département, région, type de bien et année | 22/22 contrôles du pipeline ; argent Spark = base actuelle, **0 écart** sur les 5,6 M ventes ; chaque indicateur recalculé en SQL, 0 écart |
| Visualisation | App Streamlit : carte région → département → commune, modes Prix et Évolution (2 années au choix), tableau triable et exportable avec les nouveaux indicateurs, provenance des chiffres affichée | `app/test_app.py` : **34 passed** |
| Cloud | Pipeline écrit au format « action PySpark » d'OVHcloud Data Platform, testé sous Spark 3.4 et 4.0 (mêmes résultats) ; procédure de déploiement, commandes OVHcloud Shell, script d'API `ovh/dp.sh` | `docs/deploiement_ovh.md` ; **déploiement réel : pas fait** |
| Deck FU2 | 14 slides, chiffres extraits de la base par script, vérifiés automatiquement | `docs/followup2/verif_deck.py` PASS |

Décisions prises (registre de décisions, résumé) :
- Spark tourne sur **OVHcloud Data Platform** (mode serverless : on ne paie que pendant les calculs).
- Priorité au **déploiement automatisé des pipelines** avant les nouvelles sources : ensuite, une source = une étape de plus.
- Données organisées en **3 domaines** (prix, texte, socio-éco) qui traversent **3 couches** bronze / argent / or.
- **Un seul projet OVH partagé à 4**, sur le voucher de Nicolas ; vos projets perso servent de bac à sable.
- Le lac est un **bucket** (un dossier par couche) ; l'app ne lit que PostgreSQL, l'or y est chargé seulement si les
  contrôles sont 100 % PASS. L'app ne dépend donc pas du cloud pour fonctionner.

## 3. Ce que j'ai repris de votre travail

La doc de conception du dépôt `AstroNey/Data` (RECAP, architecture, schéma v4, specs) est la **référence de
conventions** du projet. Ce qui en vient, et où c'est dans le code :

| Repris de la doc AstroNey/Data | Où dans T-DAT-901 |
|---|---|
| Architecture medallion (Landing → Bronze → Silver → Gold → Serving) | couches **bronze / argent / or** de `pipelines/prix/` ; PostgreSQL joue le Serving |
| `code_insee` pivot, texte de 5 caractères | clé de toutes les tables et jointures |
| Lignes douteuses marquées, jamais supprimées | colonnes `hors_marche`, `prix_m2_douteux` (ventes conservées, exclues du calcul) |
| Colonnes techniques `_source`, `_date_ingestion`, `_batch_id` | couches argent et or, table `indicateurs_prix` |
| Grain Gold `(niveau_geo, code_geo, periode)` | clé de `indicateurs_prix` (+ type de bien) |
| L'app ne lit que la couche Serving | l'app ne lit que PostgreSQL, jamais les fichiers |
| Paliers de sources (étape 1 → 3, 12 sources visées) | feuille de route du deck (slides 3 et 14) |
| « Pipeline bout en bout sur 1 source (DVF) avant d'étendre » | c'est exactement le pipeline prix |

Écarts assumés par rapport à la doc :
- pas de Delta Lake ni de couche Landing séparée : un bucket avec 3 dossiers suffit pour l'instant ;
- contours geo.api.gouv.fr au lieu d'Admin Express (déjà chargés, contrôlés) ;
- orchestrateur = workflows de Data Platform au lieu d'Airflow/Prefect (inclus dans la plateforme, rien à héberger) ;
- volet texte : les annonces Orpi sont en place ; la source d'avis (sentiment) arrive au palier 2.

Sources de l'« étape 1 » de la TODO : DVF ✔, contours ✔ (geo.api), revenus INSEE ✘ (palier 3), avis textuels ✘ (palier 2).

## 4. Ce qui reste

| Palier | Quoi | Prérequis |
|---|---|---|
| Avant le 23/11 | Vous ajouter au projet OVH (Project Admin) et au dépôt GitHub ; confirmer avec le pédago si les vouchers peuvent se cumuler | Nicolas |
| 23/11 – 13/12 | Déployer le pipeline prix (ressources R1-R7, workflow planifié) ; vérifier le coût réel d'un projet au repos ; puis automatiser les autres chaînes | `docs/deploiement_ovh.md` |
| 14/12 – 10/01 | Analyse de texte : caractéristiques des annonces + sentiment sur une source d'avis | pipeline texte sur le même modèle |
| 11/01 – 31/01 | Sources socio-éco (revenus, population, DPE, argiles) + 5 autres → 12 ; pages Fiche territoire et Comparateur | une ingestion par source |
| 01/02 – 07/02 | Gel, documentation (schéma, méthode de nettoyage, IA), répétition | — |

Proposition de répartition (à valider ensemble) : un responsable par domaine, chacun avec son pipeline dans
`pipelines/<domaine>/` sur le modèle de `pipelines/prix/` (un fichier par étape, contrôles PASS/FAIL, test local
avant tout push).

## 5. S'y mettre en local (~20 min)

```powershell
git clone <dépôt> ; cd T-DAT-901
python -m venv .venv ; .venv\Scripts\pip install -r requirements.txt
copy db\.env.example db\.env                                   # puis changer les mots de passe
docker compose -f db/docker-compose.yml --env-file db/.env up -d --wait
.venv\Scripts\python db\load_referentiel.py ; .venv\Scripts\python db\load_contours.py
.venv\Scripts\python db\telecharger_dvf.py ; .venv\Scripts\python db\load_dvf.py     # ~30 min pour 4 ans
.venv\Scripts\python db\load_postgres.py ; .venv\Scripts\python db\load_mongo.py      # annonces Orpi
.venv\Scripts\python db\check.py                                # PASS attendu
.venv\Scripts\streamlit run app\main.py
```

Indicateurs : soit le job Spark local (`bootstrap\.venv\Scripts\python jobs\indicateurs_prix.py`, cf. README), soit le
pipeline dans le conteneur Spark (`docs/deploiement_ovh.md`, section 5) puis `db\ovh.py recuperer --local`.

À lire, dans cet ordre : `README.md`, `docs/schema_bdd.md`, `docs/deploiement_ovh.md`, `docs/followup2/demo.md`.

## 6. Demain (Follow-up 2)

Deck : `docs/followup2/Homepedia_Follow-up_2.pptx` (14 slides, notes du présentateur sur chaque slide).
Démo : `docs/followup2/demo.md` (déroulé, phrases, plan B avec captures). Message clé : tout tourne de bout en bout,
les chiffres sont contrôlés automatiquement, et le pipeline prix est prêt à partir sur OVHcloud dès la semaine prochaine.
