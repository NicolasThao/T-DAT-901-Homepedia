# Follow-up 1 — T-DAT-901 Homepedia

Préparé pour le point du vendredi 2026-09-25, à partir des exercices `bootstrap/exo.md` (modélisation en étoile de KaDo + pipeline PySpark map/reduceByKey/sortByKey sur les ventes immobilières).

---

## 1. Sources

| Dataset | Fichier | Origine | Statut |
|---|---|---|---|
| **KaDo** | `bootstrap/data/KaDo.csv` (766 Mo, 7 245 522 lignes) | Dataset bootstrap fourni par la pédagogie — données de caisse (tickets de vente en parfumerie/cosmétique). Origine précise non documentée dans le bootstrap. | Interne à l'exercice |
| **Ventes immobilières France 2022** | `bootstrap/data/france_total_real_estate_sales_2022.csv.zip` (64 Mo compressé / 430 Mo décompressé, 3 803 885 lignes) | Structure de colonnes identique aux exports officiels **DVF — Demandes de Valeurs Foncières** (`Date mutation`, `Nature mutation`, `Valeur fonciere`, `Code departement`, `Type local`, ...), publiés en open data sur `data.gouv.fr` / `cadastre.data.gouv.fr`. **À reconfirmer avec le pédago** : le nom du fichier suggère un retraitement/agrégation 2022 fourni tel quel dans le bootstrap, pas un téléchargement direct effectué par nous. | Bootstrap, probable dérivé DVF |

**Pour le projet Homepedia complet** (au-delà de ce follow-up) : le sujet recommande de privilégier des sources ouvertes/publiques (INSEE, data.gouv.fr) et d'atteindre une douzaine de sources minimum, dont au moins une textuelle (traitée par sentiment analysis). Non couvert par ce follow-up — à traiter dans une itération suivante.

---

## 2. Schéma de BDD

Modélisation en étoile réalisée sur KaDo (exercice de modélisation demandé), documentée en détail dans [`bootstrap/docs/schema/schema_kado.md`](schema/schema_kado.md).

**Résumé** :
- `Fait_Ventes` (grain = 1 ligne = 1 article vendu dans un ticket) — mesure `prix_net`, clés étrangères vers `Dim_Client`, `Dim_Produit`, `Dim_Temps`, `ticket_id` en dimension dégénérée
- `Dim_Client` (`cli_id`) — dimension minimale, aucun attribut démographique dans la source
- `Dim_Produit` (`produit_id`, `libelle`, `famille`, `univers`, `maille`) — attributs plats, **pas** un snowflake : `MAILLE` ne descend pas hiérarchiquement de `UNIVERS` (constat data, voir section 3)
- `Dim_Temps` (`mois_vente`, 1-12) — pas d'année dans la source

Le schéma relationnel + NoSQL du projet Homepedia complet (au-delà de ce bootstrap) reste à concevoir une fois les sources additionnelles identifiées — hors périmètre de ce follow-up.

---

## 3. Pipeline PySpark sur les ventes immobilières (france-real)

Trois jobs réalisés sur `france_total_real_estate_sales_2022.csv`, tous filtrés sur `Type local` ∈ {Appartement, Maison} avec surface bâtie renseignée et positive (1 156 643 lignes valides sur 1 159 521 candidates, 3 803 885 lignes au total dans le fichier).

### Job 1 — Map : prix au m² (`scripts/job1_map_prix_m2.py`)
Calcule `prix_m2 = Valeur fonciere / Surface reelle bati` pour chaque vente. **Anomalie détectée** : `prix_m2` atteint jusqu'à 46 M€/m² sur certaines lignes — symptôme du problème documenté au job suivant.

### Job 2 — ReduceByKey : valeur foncière par département (`scripts/job2_reduce_valeur_departement.py`)
**Problème de données identifié** : une même mutation (transaction) peut apparaître sur plusieurs lignes du CSV quand elle porte sur plusieurs lots (ex. maison + dépendance + garage vendus ensemble), avec la **même `Valeur fonciere` répétée sur chaque ligne**. Une somme brute par département compte donc cette valeur plusieurs fois.

- **226 186 lignes en doublon sur 1 156 643 (~19,6 %)**, identifiées par une clé de mutation (date + département + commune + section + numéro de plan + valeur foncière)
- Écart entre somme brute et somme dédupliquée : **568,9 milliards € au niveau national**, avec un facteur très variable selon département (ex. département 22 : ×10,6 ; Paris : ×3,5 ; département 93 : ×8,3)
- **Décision retenue** : la valeur foncière par département dédupliquée est l'indicateur à retenir pour Homepedia — la somme brute est trompeuse malgré le fait qu'elle corresponde à la lecture littérale de l'exercice bootstrap.

### Job 3 — SortByKey : top 10 communes les plus chères par département (`scripts/job3_sortbykey_top10_communes.py`)
Construit sur le même périmètre dédupliqué. Deux choix méthodologiques supplémentaires :
- Indicateur de prix = **médiane** du prix/m² par commune plutôt que la moyenne, pour ne pas laisser les valeurs aberrantes du Job 1 dominer le classement
- **Seuil minimum de 5 ventes par commune** pour entrer au classement, afin d'éviter qu'une commune à une seule vente (donc une donnée potentiellement isolée) ressorte en tête faute de volume

30 672 communes évaluées, 19 326 au-dessus du seuil de volume. **Vérification de cohérence** : Paris 06 et Paris 07 en tête du département 75 (~15 200-15 245 €/m²), Saint-Jean-Cap-Ferrat en tête des Alpes-Maritimes (16 436 €/m²) — cohérent avec les communes reconnues comme les plus chères de France.

---

## 4. Méthodologie de nettoyage — synthèse

| Problème rencontré | Traitement appliqué |
|---|---|
| `Valeur fonciere` au format français (`"55000,00"`, virgule décimale, guillemets) | Parsing explicite (`,` → `.`, cast double) avant tout calcul |
| Lignes sans `Type local` ou hors {Appartement, Maison} (terrains, locaux commerciaux, dépendances seules...) | Exclues (hors périmètre "marché résidentiel") |
| Surface bâtie nulle ou absente (2 878 lignes) | Exclues (division par zéro / non calculable) |
| Mutations multi-lots comptées plusieurs fois (~19,6 % des lignes) | Dédupliquées par clé composite (date + localisation + valeur) pour les agrégats (Job 2, Job 3) |
| Valeurs de `prix_m2` aberrantes (jusqu'à 46 M€/m²) | Non filtrées au Job 1 (map brut demandé par l'exercice), neutralisées au Job 3 par l'usage de la médiane + seuil de volume plutôt qu'un filtrage arbitraire |
| Hiérarchie produit KaDo supposée à 3 niveaux (FAMILLE > UNIVERS > MAILLE) | Invalidée par les données (`MAILLE` traverse plusieurs `UNIVERS`) — modélisée en attributs plats |

---

## 5. Points ouverts pour le pédago

1. Confirmation de la source exacte du fichier `france_total_real_estate_sales_2022.csv` (DVF officiel retraité, ou autre origine ?)
2. Plateforme pour le cluster Spark du projet complet (Databricks free edition, VM locale, tokens campus ?)
3. Le `prix_m2` maximal de 46 M€/m² mérite-t-il un audit plus approfondi (erreur de saisie DVF vs cas réel type vente partielle/indivision) avant le rendu final, ou est-ce acceptable de le documenter comme limite connue ?
