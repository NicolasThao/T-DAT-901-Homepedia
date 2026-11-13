# Fiche — PySpark, expliqué avec les ventes immobilières DVF

> Pour qui : étudiant·es qui débutent en data. Chaque notion est illustrée par le code réel de `bootstrap/` :
> `spark_session.py`, `dvf.py` (lecture commune) et `scripts/job1..3_*.py`.

---

## 1. Pourquoi Spark ?

pandas charge **tout le fichier dans la mémoire d'une seule machine**. Quand les données dépassent la RAM (ou quand on veut aller plus vite), il faut **répartir** le travail.

| Terme | Définition |
|---|---|
| **Big data** | Données trop volumineuses, rapides ou variées pour les outils classiques (les « 3 V » : Volume, Vélocité, Variété) |
| **Calcul distribué** | Découper les données en morceaux et les traiter en parallèle sur plusieurs cœurs ou plusieurs machines |
| **Scalabilité horizontale** | Aller plus vite en *ajoutant des machines* (plutôt qu'en achetant une machine plus grosse : scalabilité verticale) |
| **Hadoop** | Écosystème historique du big data : **HDFS** (stockage distribué), **YARN** (répartition des ressources), **MapReduce** (modèle de calcul, écrit sur disque entre chaque étape) |
| **Apache Spark** | Moteur de calcul distribué qui garde les données **en mémoire** entre les étapes → beaucoup plus rapide que MapReduce |
| **PySpark** | L'API Python de Spark (Spark est écrit en Scala et tourne dans la JVM Java) |

Notre fichier `france_total_real_estate_sales_2022.csv` : **3 803 885 lignes, 430 Mo**. pandas s'en sortirait encore, mais c'est l'exercice idéal pour apprendre les mécanismes qui, eux, passent à l'échelle.

---

## 2. Architecture : qui fait quoi ?

```
            ┌──────────── Driver (ton script Python) ────────────┐
            │ SparkSession · construit le plan · collecte le résultat │
            └──────────────┬──────────────────────┬───────────────┘
                           │ tâches               │ tâches
                   ┌───────▼───────┐      ┌───────▼───────┐
                   │   Executor    │      │   Executor    │   ← font le calcul,
                   │ partitions 1,2│      │ partitions 3,4│     chacun sur ses morceaux
                   └───────────────┘      └───────────────┘
```

| Terme | Rôle |
|---|---|
| **Driver** | Le programme principal : il décrit le calcul et reçoit le résultat final |
| **Executor** | Processus qui exécute les calculs sur une partie des données |
| **Partition** | Un morceau des données. Une **tâche** (*task*) = une partition traitée par un cœur |
| **Cluster manager** | Attribue les machines : YARN, Kubernetes, Spark standalone… |
| **`local[*]`** | Mode local : driver et executors sur **ta** machine, `*` = autant de threads que de cœurs |

Dans le projet (`spark_session.py`) :

```python
SparkSession.builder.appName(app_name).master("local[*]").getOrCreate()
```

La **SparkSession** est le point d'entrée unique : lire des fichiers, créer des DataFrames, exécuter du SQL.

---

## 3. RDD et DataFrame : les deux façons de manipuler les données

| | **RDD** (*Resilient Distributed Dataset*) | **DataFrame** |
|---|---|---|
| C'est quoi | Collection distribuée d'objets Python quelconques (tuples, dicts…) | Table distribuée avec des **colonnes nommées et typées** (un schéma) |
| On écrit | Des fonctions Python (`lambda`) | Des expressions de colonnes (`F.col`, `F.sum`) ou du SQL |
| Optimisé par Spark ? | Non : Spark ne voit pas l'intérieur de tes `lambda` | Oui : l'optimiseur **Catalyst** réécrit le plan, le moteur **Tungsten** gère la mémoire |
| Performance | Plus lent (les données font l'aller-retour JVM ↔ Python) | Plus rapide (tout reste dans la JVM) |
| Quand l'utiliser | Pour apprendre les primitives (`map`, `reduceByKey`), logique très libre | **Par défaut** en pratique |

- **Resilient** : si une partition est perdue, Spark la recalcule grâce à son **lignage** (*lineage*), c'est-à-dire l'historique des transformations qui l'ont produite. Pas besoin de copier les données pour être tolérant aux pannes.
- **Immuable** : on ne modifie jamais un RDD, chaque transformation en crée un nouveau.
- Passer de l'un à l'autre : `df.rdd` (DataFrame → RDD de `Row`), `rdd.toDF(schema)` (RDD → DataFrame).

Le projet utilise les deux : **DataFrame** pour lire et nettoyer (`dvf.py`), **RDD** pour les primitives demandées par l'exercice.

---

## 4. Transformations, actions et évaluation paresseuse

| | **Transformation** | **Action** |
|---|---|---|
| Rôle | Décrit un nouveau jeu de données | Demande un résultat |
| Exécute quelque chose ? | **Non** (paresseuse) | **Oui**, déclenche tout le calcul |
| Exemples | `map`, `filter`, `reduceByKey`, `sortByKey`, `select`, `groupBy` | `count`, `collect`, `show`, `take`, `toPandas`, écriture de fichier |

**Évaluation paresseuse** (*lazy evaluation*) : tant qu'aucune action n'est appelée, Spark se contente d'empiler les transformations dans un plan. À l'action, il construit un **DAG** (graphe orienté acyclique des opérations), l'optimise, le découpe en **stages** puis en **tasks**.

Conséquence pratique : chaque action **relit le CSV depuis le début**. D'où le `.cache()` du job 2, qui garde le RDD en mémoire parce qu'il sert à plusieurs calculs :

```python
lignes = ventes_valides.select("cle_mutation", "code_departement", "valeur_fonciere").rdd.cache()
```

---

## 5. Transformations étroites, larges et le shuffle

| | **Étroite** (*narrow*) | **Large** (*wide*) |
|---|---|---|
| Principe | Chaque partition de sortie ne dépend que d'une partition d'entrée | Une partition de sortie a besoin de données venant de **toutes** les partitions |
| Exemples | `map`, `filter` | `reduceByKey`, `groupByKey`, `sortByKey`, `join`, `groupBy` |
| Coût | Faible, tout reste sur place | Élevé : **shuffle** |

**Shuffle** : redistribution des données entre executors pour regrouper les lignes qui ont la même clé (écriture sur disque + transfert réseau). C'est l'opération la plus coûteuse de Spark ; elle marque la frontière entre deux **stages**. Réduire les shuffles = optimiser un job.

---

## 6. Les 3 primitives de l'exercice

### `map()` — Job 1 : prix au m² de chaque vente

Transformation **1 → 1** : chaque élément en entrée donne exactement un élément en sortie. Étroite, pas de shuffle.

```python
rdd_ventes = ventes_valides.select(*colonnes).rdd          # (dept, commune, type, valeur, surface)
rdd_prix_m2 = rdd_ventes.map(lambda r: (r[0], r[1], r[2], r[3], r[4], round(r[3] / r[4], 2)))
```

Cousins : **`flatMap`** (1 → 0..N éléments, ex. découper un texte en mots), **`filter`** (garde ou jette), **`mapValues`** (ne touche que la valeur d'une paire).

### `reduceByKey()` — Job 2 : valeur foncière par département

Fonctionne sur un **pair RDD** (RDD de paires `(clé, valeur)`). Combine toutes les valeurs d'une même clé avec une fonction à deux arguments.

```python
from operator import add
valeur_brute_par_dept = lignes.map(lambda r: (r[1], r[2])).reduceByKey(add)
#                                        (dept, valeur)          a + b
```

La fonction doit être **associative** et **commutative** (l'ordre des additions n'importe pas), parce que Spark l'applique d'abord **localement dans chaque partition** (*map-side combine*, comme un *combiner* Hadoop), puis fusionne les résultats partiels après le shuffle.

**`reduceByKey` vs `groupByKey`** : `groupByKey` envoie *toutes* les valeurs sur le réseau puis les regroupe ; `reduceByKey` envoie seulement **un sous-total par clé et par partition**. Pour une somme, `reduceByKey` est toujours préférable.

Astuce du job 2 : `reduceByKey` sert aussi à **dédoublonner** — en gardant une seule valeur par clé :

```python
mutations = lignes.map(lambda r: (r[0], (r[1], r[2]))).reduceByKey(lambda a, b: a)   # 1 valeur par mutation
valeur_dedup_par_dept = mutations.map(lambda kv: kv[1]).reduceByKey(add)
```

### `sortByKey()` — Job 3 : top 10 des communes par département

Trie un pair RDD par clé. Transformation **large** : Spark **échantillonne** les clés pour découper l'intervalle en tranches (**RangePartitioner**), envoie chaque tranche à une partition, puis trie localement.

```python
rdd_top10 = top10.select("code_departement", "rang", ...).rdd.map(lambda r: (r[0], (r[1], ...)))
resultat = rdd_top10.sortByKey().collect()
```

Les clés sont des **chaînes** : le tri est **alphabétique** (lexicographique). D'où la normalisation des codes département sur 2 caractères dans `dvf.py` (« 6 » → « 06 »), sinon « 6 » serait classé après « 59 ». Piège rencontré : `F.lpad(col, 2, "0")` **tronque** aussi les chaînes plus longues (« 972 » → « 97 ») — d'où la fonction `completer()`.

---

## 7. Les outils DataFrame utilisés

| Outil | Rôle | Où |
|---|---|---|
| `spark.read.csv(..., header=True)` | Lire un CSV (toutes les colonnes en texte si pas de schéma) | `dvf.py` |
| `F.regexp_replace(col, ",", ".").cast("double")` | Nettoyer le format français `"55000,00"` puis **caster** en nombre | `dvf.py` |
| `F.concat_ws("\|", ...)` | Construire une **clé composite** | `dvf.py` (`cle_mutation`) |
| `filter` / `isin` / `isNotNull` | Filtrer | tous les jobs |
| `groupBy().agg(F.count, F.sum, F.first)` | Agréger (l'équivalent DataFrame de `reduceByKey`) | job 3 |
| `percentile_approx(prix_m2, 0.5)` | **Médiane approchée** : un quantile exact demanderait de trier toutes les valeurs, l'approximation est bien plus rapide à grande échelle | job 3 |
| `Window.partitionBy().orderBy()` + `F.row_number()` | **Fonction de fenêtre** : numéroter les lignes *à l'intérieur de chaque groupe* sans les fusionner → top N par groupe | job 3 |
| `StructType([StructField(...)])` | **Schéma explicite** : types connus d'avance, pas d'inférence | job 1 |
| `describe()` | Statistiques descriptives (count, mean, stddev, min, max) | job 1 |
| `collect()` | **Action** qui rapatrie tout le résultat sur le driver | jobs 2, 3 |
| `toPandas()` | Idem, en DataFrame pandas | jobs 1, 2, 3 |

**Attention à `collect()` / `toPandas()`** : tout le résultat arrive dans la mémoire du driver. Sans risque sur ~100 départements, dangereux sur des millions de lignes (erreur *out of memory*). Sur un vrai cluster, on écrit plutôt le résultat en fichier (Parquet) avec `df.write`.

---

## 8. Le vrai sujet : la qualité des données

L'exercice demandé tient en trois lignes de code. Le travail réel, c'est de **comprendre ce que représente une ligne**.

| Constat | Conséquence | Traitement |
|---|---|---|
| Une ligne DVF = un **lot**, pas une vente. Un acte (mutation) portant sur une maison + un garage fait 2 lignes, **avec la valeur de l'acte entier répétée** | Somme brute par département gonflée ; prix/m² absurdes (jusqu'à 46 M€/m²) | **Clé de mutation** (date + code INSEE + nature + valeur) pour regrouper les lignes d'un même acte |
| Première clé essayée : + section + n° de plan | Coupait en morceaux les actes qui portent sur plusieurs parcelles → doublons sous-estimés | Clé corrigée, la même que le chargement PostgreSQL (`db/load_postgres.py`) |
| Un acte de 3 appartements a une seule valeur | Pas de prix/m² interprétable | Prix/m² calculé seulement sur les **ventes d'un seul logement** |
| Valeurs aberrantes restantes | La moyenne serait tirée vers le haut | **Médiane**, indicateur **robuste** (aussi utilisé par les notaires) |
| Communes avec 1 ou 2 ventes | Classement dominé par le hasard | **Seuil** de 5 ventes minimum |

Vocabulaire : **grain** (ce que représente une ligne) · **clé composite** · **dédoublonnage** · **valeur aberrante** (*outlier*) · **indicateur robuste** · **biais des petits effectifs** · **contrôle de cohérence** (Paris 6e / 7e en tête du 75, Saint-Jean-Cap-Ferrat en tête du 06).

---

## 9. Pièges rencontrés sur Windows

| Symptôme | Cause | Parade |
|---|---|---|
| `Python worker exited unexpectedly (crashed)` au moment d'un `toDF()` | Sans schéma, `toDF()` lance un `take(1)` pour deviner les types ; ce `take` coupe le worker Python en pleine lecture | Passer un **schéma explicite** (job 1) |
| Même erreur sous forte charge mémoire | Plusieurs gros traitements en parallèle sur la machine | Lancer les jobs un par un |
| `Did not find winutils.exe` | Spark cherche les binaires Hadoop pour Windows | Simple avertissement en lecture seule, sans conséquence ici |
| `JAVA_HOME` absent | Spark tourne dans la JVM et a besoin de Java 17 | `spark_session.py` pointe vers un JDK local |

---

## 10. Et après ? (projet Homepedia)

- **Parquet** : format colonne compressé, bien plus rapide à relire qu'un CSV.
- **Spark SQL** : `df.createOrReplaceTempView("ventes")` puis `spark.sql("SELECT ...")`.
- **JDBC** : Spark lit et écrit directement dans PostgreSQL.
- **Cluster** : Databricks, ou un Spark standalone en Docker, pour passer de `local[*]` à plusieurs machines.

---

## 11. Glossaire express

SparkSession · driver · executor · partition · task · stage · DAG · `local[*]` · RDD · lignage · immuable · DataFrame · schéma · Catalyst · Tungsten · transformation · action · évaluation paresseuse · cache · étroite / large · shuffle · pair RDD · `map` / `flatMap` / `filter` · `reduceByKey` (associative, commutative, map-side combine) · `groupByKey` · `sortByKey` (RangePartitioner) · `collect` · fonction de fenêtre · `percentile_approx` · MapReduce · HDFS · YARN · Parquet.
