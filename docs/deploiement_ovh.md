# Déploiement du pipeline prix sur OVHcloud Data Platform

> Pour qui : l'équipe. Ce document dit quoi créer sur OVHcloud (une fois), dans quel ordre lancer le pipeline,
> et comment déployer une modification. Doc officielle lue le 2026-11-18 ; chaque point cite sa page, au même nom
> sur `https://docs.dataplatform.ovh.net/<page>` et `https://docs.ovhcloud.com/en/guides/public-cloud/data-platform/<page>`.
> Le site docs.dataplatform.ovh.net est plus complet (API de lancement, export/import de configuration) :
> tout y est dans `https://docs.dataplatform.ovh.net/llms-full.txt`.

## 1. Vue d'ensemble

```
 Poste local                         OVHcloud Data Platform (projet partagé, ADR-045)              Poste local
 ─────────────                       ────────────────────────────────────────────────              ───────────
 db/telecharger_dvf.py               bucket « homepedia »
 db/ovh.py envoyer  ───────────────▶  bronze/dvf/2022..2025.csv.gz, bronze/referentiel/communes.csv
                                        │  workflow PySpark « pipeline-prix »
                                        │   1. bronze_vers_argent  → argent/dvf/ (Parquet, une ligne par vente)
                                        │   2. argent_vers_or      → or/indicateurs_prix/ (CSV)
                                        │   3. controles           → or/controles/ (PASS/FAIL, échec = arrêt)
                                        ▼
                                      or/indicateurs_prix + or/controles ─────────▶ db/ovh.py recuperer
                                                                                    → PostgreSQL indicateurs_prix
                                                                                    → db/check.py (recalcul SQL)
                                                                                    → app Streamlit
```

- Couches (ADR-044) : **bronze** = fichiers tels que reçus, **argent** = une ligne par vente, qualité marquée,
  **or** = indicateurs par zone, type de bien et année. Un dossier du bucket par couche.
- L'app ne change pas de source : elle lit toujours PostgreSQL. `recuperer` y charge le dernier lot **validé**
  (rapport de contrôles 100 % PASS, même lot), et l'app affiche sa provenance sous la carte.
- Pourquoi un bucket comme point d'échange : aucune base à héberger ni à ouvrir sur Internet, et le coût se limite
  aux exécutions (mode serverless) et au stockage (ADR-046).

## 2. Ressources à créer (une fois, ~30 min, Project Admin)

| # | Ressource | Où | Valeur | Doc |
|---|---|---|---|---|
| R1 | Projet Data Platform partagé | Console OVHcloud, Public Cloud → Data Platform | collègues invités en **Project Admin** (ADR-045) | `manage-projects-create.md`, `iam-users.md` |
| R2 | Bucket | Lakehouse Manager → Buckets → **+ New Bucket** | nom `homepedia` | `lakehouse-manager-buckets.md` |
| R3 | Compte de service + clés API | Identity Access Manager → **Service Accounts** → compte `homepedia-pipeline` → **API Access** → **Add access** | copier clé et secret **tout de suite** (le secret n'est plus affichable ensuite) | `iam-service-accounts.md`, `tutorials-generate-api-keys.md` |
| R4 | Source Connectors « Buckets » | Connectors → Platform store → *Buckets* → **Select** | Bucket `homepedia`, Path vide, **nom technique `homepedia`** (non modifiable ensuite) | `connectors-sources-dataplatform-buckets.md` |
| R5 | Dépôt d'actions relié à GitHub | Data Processing Engine → Actions → roue dentée du dépôt → **Connect to Git** | URL SSH `git@github.com:NicolasThao/T-DAT-901-Homepedia.git` → **FETCH** → branche `master` → copier la clé SSH publique affichée et l'ajouter côté GitHub | `tutorials-versioning-basics.md` |
| R6 | 3 actions **Custom PySpark** | Actions → **New Action** → *Custom PySpark* | une action par fichier de `pipelines/prix/` (tableau ci-dessous) | `dpe-actions-custom-pyspark.md` |
| R7 | Workflow PySpark | Data Processing Engine → Workflows | `pipeline-prix` : étape 1 → 2 → 3, **Auto Flushall désactivé**, **Stop workflow on failure activé** (sinon l'or serait recalculé sur un argent périmé si l'étape 1 échoue) ; trigger CRON optionnel dans les préférences | `dpe-workflows.md`, `dpe-jobs-preferences.md` |

Actions (R6). Le code est un seul fichier par action, sans import local (« no multi-file package structure
inside a single action », `dpe-actions-manage.md`) ; le point d'entrée est `customfunc(event)`.

| Action | Fichier | Exécuteurs (départ) | Lit → écrit |
|---|---|---|---|
| `prix-bronze-argent` | `pipelines/prix/bronze_vers_argent.py` | 4 × 2 DPU, driver 2 DPU | bronze → argent (15,7 M lignes → 5,6 M ventes ; 11 min en local sur 12 cœurs) |
| `prix-argent-or` | `pipelines/prix/argent_vers_or.py` | 2 × 2 DPU, driver 2 DPU | argent → or (~275 000 indicateurs) |
| `prix-controles` | `pipelines/prix/controles.py` | 1 × 2 DPU, driver 2 DPU | contrôles → or/controles |

Rien à paramétrer si R2 et R4 s'appellent `homepedia`. Sinon, variables d'environnement des actions (lues dans
`PARAMS` du SDK, `dpe-jobs-preferences.md`) : `HOMEPEDIA_SOURCE` (nom technique de R4), `HOMEPEDIA_BUCKET` (nom de R2).
Chaque job s'exécute sous le **compte de service** associé à l'action ou au workflow (`dpe-jobs-preferences.md`,
« Service account ») : ce compte doit avoir accès au bucket.

Sur le poste, ajouter à `db/.env` (jamais versionné) :

```
OVH_S3_ENDPOINT=https://<sous-domaine-du-projet>.eu.dataplatform.ovh.net/datastore
OVH_BUCKET=homepedia
OVH_ACCESS_KEY=<clé R3>
OVH_SECRET_KEY=<secret R3>
```

Endpoint, région `forepaas` et signature `s3v4` : `tutorials-bucket-s3-access.md`.

### Commandes OVHcloud Shell

OVHcloud Shell = terminal ouvert depuis l'icône en haut à droite du Control Panel, déjà authentifié, avec le
CLI `ovhcloud` (`getting-started-ovhcloudshell.md`, section *cross-functional*).

**Ce qui se scripte, ce qui reste en console** (doc lue le 2026-11-18) :

| Ressource | Shell ? | Pourquoi |
|---|---|---|
| R1 projet Public Cloud (identifiant) | oui, lecture | `ovhcloud cloud project list` |
| R2 bucket, dépôt du bronze, lecture des couches | **oui** | le datastore est compatible S3 : AWS CLI avec `--endpoint-url` (`tutorials-bucket-s3-access.md` cite `s3 mb`, `s3 cp`, `s3 ls`) |
| R3 compte de service, clés API | non | création dans l'IAM (console) ; les clés servent ensuite à obtenir un jeton : `POST /iam/login` (`auth_mode: apikey`) |
| R4 source | non | pas d'API de création documentée ; export/import possible côté Connectors (`/dwh/v4/configuration/...`) |
| R6 actions, R7 workflow | **oui, après la 1re création** | `GET /dpe/v3/configuration/export` puis `POST .../import` : la configuration devient une archive rejouable dans un autre projet (bac à sable d'un collègue, ADR-045) ; `tutorials-export-import-config.md` |
| Lancer une action | **oui** | `POST /dpe/v3/actions/<id>/start?...&token=` (« Launching Actions and Workflows ») |
| Lancer le workflow | à vérifier | même forme en `/dpe/v3/workflows/<id>/start` : **déduit**, la doc annonce le lancement de workflows mais ne montre que l'URL des actions |

Le CLI `ovhcloud` gère l'Object Storage *Public Cloud* (`ovhcloud cloud storage-s3`), qui n'est **pas** le
datastore de Data Platform : on ne l'utilise pas ici.

Session type, à coller dans le Shell après avoir créé les clés R3 dans la console (rien n'est écrit en dur) :

```bash
# 0. Outils : la doc ne garantit que le CLI ovhcloud ; installer l'AWS CLI s'il manque
ovhcloud version
command -v aws curl python3 || true
command -v aws || { python3 -m pip install --user awscli && export PATH="$HOME/.local/bin:$PATH"; }

# 1. Projet Public Cloud qui porte la Data Platform (R1)
ovhcloud cloud project list

# 2. Accès S3 au datastore du projet Data Platform (clés R3, lues au clavier, jamais dans l'historique)
export DP_URL="https://<sous-domaine-du-projet>.eu.dataplatform.ovh.net"
read -rp "Clé API R3 : " CLE; read -rsp "Secret R3 : " SECRET; echo
aws configure set aws_access_key_id "$CLE" --profile homepedia
aws configure set aws_secret_access_key "$SECRET" --profile homepedia
aws configure set region forepaas --profile homepedia
aws configure set s3.signature_version s3v4 --profile homepedia
unset CLE SECRET
dp() { aws --profile homepedia --endpoint-url "$DP_URL/datastore" "$@"; }
dp s3 ls                                   # test des clés : liste les buckets (dont project-<id>)

# 3. Bucket du lac (R2, si pas créé dans la console)
dp s3 mb s3://homepedia

# 4. Bronze DVF : téléchargé depuis data.gouv directement vers le bucket, sans passer par le poste ni le disque
for a in 2022 2023 2024 2025; do
  curl -fsSL "https://files.data.gouv.fr/geo-dvf/latest/csv/$a/full.csv.gz" | dp s3 cp - "s3://homepedia/bronze/dvf/$a.csv.gz"
done

# 5. État du lac par couche, et rapport de contrôles du dernier lot (après le workflow)
dp s3 ls --recursive s3://homepedia/ | awk '{print $3, $4}'
dp s3 cp "s3://homepedia/$(dp s3 ls --recursive s3://homepedia/or/controles/ | awk '/part-.*\.csv$/ {print $4}')" - | column -s, -t
```

Pilotage de Data Platform par API (`ovh/dp.sh`, testé contre un faux serveur : chemins, en-têtes et corps conformes
aux exemples de la doc ; à confirmer sur le vrai projet) :

```bash
git clone https://github.com/NicolasThao/T-DAT-901-Homepedia.git && cd T-DAT-901-Homepedia   # dépôt privé : jeton GitHub
export DP_URL="https://<sous-domaine-du-projet>.eu.dataplatform.ovh.net"
source ovh/dp.sh                         # demande clé et secret R3, garde le jeton en mémoire
dp_exporter ovh/dpe-config.tar           # sauvegarde actions + workflow après leur création (R6, R7)
dp_lancer_workflow <id_workflow>         # id dans l'URL : .../dpe/#/workflow/<id> ; à défaut, une action à la fois :
dp_lancer_action <id_prix-bronze-argent> # .../dpe/#/action/<id>
```

Le référentiel des communes (`bronze/referentiel/communes.csv`) vient de la base locale : il reste envoyé par
`db/ovh.py envoyer` (étape suivante). `envoyer` saute un fichier DVF de même taille et remplace un fichier de taille
différente par celui du poste : si Etalab a publié une livraison plus récente que celle chargée en local, le bronze
redevient celle du poste, cohérente avec la base, et `db/check.py` peut comparer les mêmes ventes. Pour passer à la
nouvelle livraison : `db/telecharger_dvf.py` puis `db/load_dvf.py` en local, et `envoyer`.

## 3. Ordre d'exécution

Premier lancement (puis à chaque nouvelle livraison DVF, avril et octobre) :

```powershell
.venv\Scripts\python db\telecharger_dvf.py      # fichiers Etalab 2022-2025 dans db/data/dvf (si absents)
.venv\Scripts\python db\ovh.py envoyer          # bronze → bucket (~415 Mo ; ne renvoie pas un fichier identique)
.venv\Scripts\python db\ovh.py etat             # vérifier : 5 fichiers dans bronze
```

Variante sans envoyer 415 Mo depuis le poste : étapes 2 à 4 des commandes OVHcloud Shell (section 2), puis
`db\ovh.py envoyer` qui n'ajoute que le référentiel des communes.

Puis, dans Data Platform : Workflows → `pipeline-prix` → **…** → **Run**. Suivre l'exécution dans la console
(icône *Console*, Logs Explorer). Chaque étape écrit ses comptes dans les logs ; la 3e se termine par
`PASS — n/n contrôles OK (lot …)`, ou échoue et arrête le workflow.

```powershell
.venv\Scripts\python db\ovh.py recuperer        # charge le lot or validé dans indicateurs_prix
.venv\Scripts\python db\check.py                # PASS attendu : indicateurs OVH = recalcul SQL local, 0 écart
.venv\Scripts\streamlit run app\main.py         # sous la carte : « Indicateurs calculés sur OVHcloud Data Platform, lot … »
```

**Coût** (grille officielle ovhcloud.com/fr/public-cloud/prices, relevée le 2026-11-18) : Data Processing Engine
0,08 € HT/DPU/heure, mesuré à la seconde ; stockage 0,0000274 € HT/Go/heure (≈ 0,02 €/Go/mois) ; requêtes Analytics
5,47 € HT/To ; Connectors, Control Center et IAM inclus ; pas de frais par projet ni de transfert. Une exécution
complète ≈ 10 DPU × ~20 min ≈ 0,30 € ; le bucket (~1 Go) ≈ 0,02 €/mois.

**À vérifier dès la création du projet** : la doc dit aussi « Even when it is idle, your Project uses a handful of DPUs
by default », réglable dans le Control Center (`manage-projects.md`), sans dire si c'est facturé. Si 2 DPU l'étaient en
continu : 2 × 0,08 × 730 h ≈ 117 €/mois, plus que le voucher. Donc, 1 à 2 h après la création : roue dentée → *Billing
information* (estimation de la prochaine facture) et Control Center → *Infrastructure Monitoring* (instances
déployées). Mettre aussi un quota de DPU bas sur l'organisation (`manage-organizations-settings.md#quotas`). Ne pas
laisser de notebook ouvert ni d'action en mode *always-up* : ils consomment le voucher même inactifs.

**Si une étape échoue au premier lancement** (points non documentés, à constater) :

| Symptôme | Cause probable | Correction |
|---|---|---|
| erreur sur `connect("dwh/homepedia/")` ou `get_spark_url` | nom technique de la source ≠ `homepedia`, ou chaîne de connexion différente pour une source sans fichier | renseigner `HOMEPEDIA_SOURCE` ; à défaut, `HOMEPEDIA_URL_LAC=s3a://homepedia` (adresse directe, contourne le SDK) |
| `AccessDenied` depuis `db/ovh.py` | rôle du compte de service sans accès au bucket | donner au compte R3 un rôle sur le projet (`iam-roles-conditions.md`), ou utiliser les clés API de son utilisateur |
| mémoire insuffisante à l'étape 1 | 4 années d'un coup | plus d'exécuteurs ou de DPU par exécuteur ; pour un essai, `HOMEPEDIA_ANNEES=2025` sur **les 3 actions** (sinon les contrôles échouent), mais ne pas `recuperer` ce lot : il remplacerait les 4 années de l'app par une seule |
| `recuperer` : « lot refusé » | contrôles en échec ou lot or plus récent que le rapport | lire `or/controles` (`db/ovh.py etat`), corriger, relancer le workflow |

## 4. Déployer une modification (procédure d'automatisation)

Ce que dit la doc (2026-11-18) : pas d'API CRUD par action ; « changing an action means a commit into the linked Git
repository, followed by a pull from the platform » (`dpe-actions-manage.md`). Le dépôt d'actions a une version
**déployée** (celle qu'exécutent les jobs) et une version **en édition** ; on déploie une version avec **Play**
(`tutorials-versioning-basics.md`). En revanche, toute la configuration DPE (actions, workflows, environnements)
s'exporte et s'importe par API (`tutorials-export-import-config.md`), et un job se lance par API, par CRON ou à la main.

Procédure :

1. **Développer** dans `pipelines/<domaine>/`, un fichier par étape (bloc `contexte()` recopié tel quel).
2. **Tester en local** (section 5) : la chaîne complète sur `data/lac`, puis `db/ovh.py recuperer --local` et
   `db/check.py` → PASS. Rien n'est poussé sans ce PASS.
3. **Pousser** sur une branche, revue, merge dans `master`.
4. **Déployer** : dans Data Platform, dépôt d'actions → flèche **↓** (pull de `master`) → **Play** sur la nouvelle
   version. Retour arrière : **Play** sur la version précédente.
5. **Exécuter** : le workflow tourne sur la version déployée, à la main ou par CRON. Contrôles en échec = workflow
   arrêté, et `recuperer` refuse le lot : un calcul faux n'atteint jamais l'app.

Ajouter une source ou un indicateur = ajouter un fichier d'étape (ou une colonne à l'or), une action et une
étape du workflow ; `db/ovh.py`, la base et l'app ne changent pas tant que la table or garde ses colonnes.

Scripté par `ovh/dp.sh` : sauvegarde de la configuration (`dp_exporter`, archive versionnée dans `ovh/`), recréation
dans un autre projet (`dp_importer`), lancement (`dp_lancer_workflow`). Reste manuel : le pull + Play du code (2 clics).

Prochaine étape d'automatisation : une CI GitHub Actions qui rejoue le test local (section 5) à chaque pull request,
puis, après merge, lance le workflow avec `dp.sh` (clé et secret R3 en secrets GitHub). Pour supprimer aussi le
pull + Play : regarder l'arborescence de l'archive exportée ; si le code des actions y figure en clair, la CI pourra
y recopier `pipelines/prix/*.py` et la réimporter (à vérifier sur le premier export).

## 5. Tester en local (sans OVHcloud)

Spark sous Windows ne peut pas écrire de fichiers (winutils manquant) : on lance les étapes dans l'image Spark
officielle, plus proche de la plateforme. Le lac local `data/lac` a la même arborescence que le bucket.

```powershell
docker pull spark:4.0.1-scala2.13-java17-python3-ubuntu
.venv\Scripts\python db\ovh.py envoyer --local
$img = "spark:4.0.1-scala2.13-java17-python3-ubuntu"
$run = "docker run --rm -v ${PWD}:/work -w /work $img /opt/spark/bin/spark-submit --driver-memory 5g"
foreach ($etape in "bronze_vers_argent", "argent_vers_or", "controles") { Invoke-Expression "$run pipelines/prix/$etape.py" }
# Parité argent Spark = mutation_dvf (SQL), vente par vente (base locale démarrée)
Invoke-Expression "$run --jars jobs/lib/postgresql-42.7.4.jar pipelines/prix/parite_argent.py"
.venv\Scripts\python db\ovh.py recuperer --local
.venv\Scripts\python db\check.py
```
