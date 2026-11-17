# Fiche — Les bases de données, expliquées avec Homepedia

> Pour qui : étudiant·es qui débutent en data. Chaque notion est illustrée par du code réel du dossier `db/`.
> Schéma complet : `docs/schema_bdd.md`. Contrôles : `db/check.py`.

---

## 1. De quoi parle-t-on ?

| Terme | Définition | Dans Homepedia |
|---|---|---|
| **Base de données** | Programme qui stocke des données et répond à des questions (requêtes) | PostgreSQL et MongoDB |
| **Relationnelle (SQL)** | Données en **tables** (lignes × colonnes) liées entre elles par des clés | Communes, ventes DVF, champs d'une annonce |
| **Non relationnelle (NoSQL)** | Données en **documents** (JSON) sans structure imposée | L'annonce Orpi brute, avec sa description |
| **Clé primaire (PK)** | Colonne qui identifie une ligne de façon unique | `commune.code_insee` |
| **Clé étrangère (FK)** | Colonne qui pointe vers la clé primaire d'une autre table | `commune.code_departement` → `departement` |
| **Index** | Structure qui accélère les recherches sur une colonne (comme l'index d'un livre) | Index sur `code_insee`, sur les contours |
| **PostGIS** | Extension de PostgreSQL pour les données géographiques (points, polygones) | Contour de chaque commune |
| **Docker** | Outil qui lance un programme dans une boîte isolée, identique chez tout le monde | Les deux bases tournent dans Docker |
| **Idempotent** | Qu'on peut relancer sans changer le résultat | Chaque chargement peut être rejoué |

---

## 2. Le flux de données

```
 Orpi (web) ──► scraping ──► listings_raw.jsonl ──► nettoyage ──► listings_clean.csv ──┐
                                                                                        ├──► PostgreSQL + PostGIS ──┐
 DVF Etalab 2022-2025 (15,7 M lignes) ─────────────────────────────────────────────────┤                           ├──► requêtes croisées
 geo.api.gouv.fr (communes + contours) ────────────────────────────────────────────────┘                           │    (db/check.py)
                                                       listings_raw.jsonl ────────────────► MongoDB ───────────────┘
```

| Étape | Script | Rôle |
|---|---|---|
| Référentiel | `db/load_referentiel.py` | Régions, départements, communes, contours |
| Ventes DVF | `db/telecharger_dvf.py` puis `db/load_dvf.py` | DVF géolocalisées 2022-2025 (Etalab), une ligne par vente |
| Chargement SQL | `db/load_postgres.py` | Annonces Orpi (pandas) |
| Chargement NoSQL | `db/load_mongo.py` | Annonces brutes |
| Vérification | `db/check.py` | PASS ou FAIL sur chaque contrôle |

L'application Streamlit et le cluster Spark ne sont pas encore reliés à ces bases : les jobs PySpark du Follow-up 1 lisent le CSV directement (`docs/fiche_pyspark.md`).

---

## 3. SQL ou NoSQL : comment choisir

| Question à se poser | Plutôt SQL | Plutôt NoSQL |
|---|---|---|
| Les champs sont-ils les mêmes pour toutes les lignes ? | Oui (un prix, une surface, une date) | Non, ça change d'un document à l'autre |
| A-t-on besoin de **relier** les données entre elles ? | Oui (une vente → une commune → un département) | Rarement |
| La requête principale ? | Filtrer, trier, agréger, joindre | Retrouver un document, chercher dans un texte |
| Veut-on garantir l'intégrité (pas de commune inventée) ? | Oui : clés étrangères, contraintes | Non fourni par défaut |

Dans Homepedia, **la même annonce est dans les deux bases, mais pas pour la même raison** :

| Base | Ce qu'elle garde de l'annonce | Pourquoi |
|---|---|---|
| PostgreSQL | Prix, surface, DPE, position GPS, commune | On filtre, on agrège, on compare avec les ventes DVF |
| MongoDB | Le document complet, dont la `description` | Recherche dans le texte, champ `nlp` à venir sans migration |

Le lien entre les deux : `annonce.id_orpi` (Postgres) = `_id` (Mongo).

---

## 4. PostgreSQL : des tables qui se parlent

### Clés primaires et étrangères

Extrait de `db/postgres/schema.sql` :

```sql
    code_insee           char(5) PRIMARY KEY,
    code_departement     varchar(3) NOT NULL REFERENCES departement,
```

La commune est identifiée par son code INSEE. `REFERENCES departement` interdit d'insérer une commune dont le département n'existe pas : c'est l'**intégrité référentielle**.

### Contraintes : refuser une donnée fausse

```sql
    dpe_classe            char(1) CHECK (dpe_classe BETWEEN 'A' AND 'G'),
```

Une classe DPE « Z » est rejetée par la base elle-même, pas seulement par le script.

### Colonne calculée par la base

```sql
    prix_m2             numeric(12, 2) GENERATED ALWAYS AS (
                            CASE WHEN surface_bati_m2 > 0 THEN valeur_fonciere / surface_bati_m2 END
                        ) STORED
```

On ne peut pas oublier de mettre à jour le prix au m² : la base le recalcule seule. `CASE WHEN surface > 0` évite la division par zéro (le résultat est alors NULL, pas 0).

### Index : chercher vite

```sql
CREATE INDEX IF NOT EXISTS idx_commune_contour      ON commune USING gist (contour);
```

Sans index, « quelle commune contient ce point ? » compare le point aux 34 920 contours. Avec un index **GiST** (conçu pour les formes géographiques), la base écarte presque tous les contours d'un coup.

Un index peut aussi être **partiel** :

```sql
-- Index partiel : les analyses de prix/m² ne portent que sur les ventes d'un seul logement
CREATE INDEX IF NOT EXISTS idx_mutation_logement_unique ON mutation_dvf (code_insee, prix_m2)
    WHERE nb_logements = 1;
```

Il ne contient que les lignes utiles : plus petit, donc plus rapide.

### PostGIS : une question géographique en SQL

Extrait de `db/load_postgres.py` :

```sql
        UPDATE annonce AS a SET code_insee = (
            SELECT c.code_insee FROM commune AS c
            WHERE ST_Contains(c.contour, a.position)
            ORDER BY c.type = 'arrondissement-municipal' DESC LIMIT 1)
        WHERE a.code_insee IS NULL
```

`ST_Contains(contour, position)` répond « ce point est-il dans cette commune ? ». C'est ainsi qu'une annonce reçoit sa commune à partir de ses coordonnées GPS.

### Rejouer un chargement sans doublon : l'upsert

```sql
ON CONFLICT (id_orpi) DO UPDATE SET
```

« Insérer ; si cette annonce existe déjà, la mettre à jour. » On peut relancer `load_postgres.py` dix fois : mêmes 500 annonces.

DVF fait autrement : l'identifiant de vente d'Etalab change d'une livraison à l'autre, donc `load_dvf.py` supprime une année puis la recharge en entier, dans une seule transaction. Si le chargement plante, l'année d'avant reste intacte.

---

## 5. MongoDB : des documents

Une **collection** est l'équivalent d'une table ; un **document** est l'équivalent d'une ligne, mais en JSON et sans colonnes imposées.

Extrait de `db/load_mongo.py` :

```python
        {
            "_id": a["id"],
            "annonce_id": a["id"],
            "code_insee": codes[a["id"]],
            **{k: v for k, v in a.items() if k not in CHAMPS_NON_CHARGES | {"id"}},
            "nlp": None,
        }
```

Le document reprend tous les champs de l'annonce, ajoute le code INSEE trouvé dans Postgres, et réserve un champ `nlp` vide pour le futur sentiment. Ajouter ce champ plus tard ne demande **aucune migration** : c'est la force du NoSQL.

Le téléphone et l'e-mail de l'agence sont exclus (`CHAMPS_NON_CHARGES`) : on ne garde pas de données personnelles inutiles.

### Chargement et index

```python
    collection = mongo()[COLLECTION]
    collection.bulk_write([pymongo.ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in documents])
    collection.create_index("code_insee")
    collection.create_index([("description", pymongo.TEXT)], default_language="french", name="texte_description")
```

- `ReplaceOne(..., upsert=True)` : même idée que `ON CONFLICT` en SQL, pour rejouer sans doublon.
- L'index **texte** en français découpe la description en mots (en ignorant « le », « de »…) pour chercher dedans.

### Chercher dans le texte

Extrait de `db/check.py` :

```python
    trouves = collection.count_documents({"$text": {"$search": "balcon"}})
```

Résultat : 80 annonces sur 500 mentionnent un balcon. Impossible à faire aussi simplement dans une colonne SQL ordinaire.

---

## 6. Docker : lancer les bases sans rien installer

Extrait de `db/docker-compose.yml` :

```yaml
  postgres:
    image: postgis/postgis:17-3.5
```
```yaml
      # 5433 côté hôte : 5432 est déjà occupé par un autre projet local
      - "127.0.0.1:${POSTGRES_PORT}:5432"
```
```yaml
      - pg_data:/var/lib/postgresql/data
```

| Notion | Rôle |
|---|---|
| **Image** (`postgis/postgis:17-3.5`) | Modèle de la boîte : PostgreSQL 17 avec PostGIS 3.5 déjà installés |
| **Port** (`5433:5432`) | Porte d'entrée. Côté ordinateur 5433, côté boîte 5432. Le mot `127.0.0.1` limite l'accès à ta machine |
| **Volume** (`pg_data`) | Dossier qui survit à l'arrêt de la boîte. Sans lui, les données disparaîtraient |
| **`${POSTGRES_PORT}`** | Valeur lue dans `db/.env`, qui n'est pas versionné : les mots de passe restent hors de git |

---

## 7. Démarrer

Depuis la racine du dépôt (Docker installé) :

```bash
cp db/.env.example db/.env        # puis changer les mots de passe
docker compose -f db/docker-compose.yml --env-file db/.env up -d
python db/load_referentiel.py     # communes + contours (appel à geo.api.gouv.fr, long la 1re fois)
python db/telecharger_dvf.py      # DVF 2022-2025 (~415 Mo, une seule fois)
python db/load_dvf.py             # ventes DVF, une transaction par année
python db/load_postgres.py        # annonces Orpi
python db/load_mongo.py           # annonces brutes
python db/check.py                # doit finir par « PASS »
```

Chaque chargement est rejouable. `check.py` sort avec un code d'erreur s'il y a un FAIL.

---

## 8. Pièges courants

| Piège | Explication | Où c'est géré |
|---|---|---|
| **Code postal ≠ code INSEE** | Un code postal couvre souvent plusieurs communes ; seul le code INSEE identifie une commune | `docs/schema_bdd.md`, section 3 |
| **Zéros de tête perdus** | `01053` lu comme nombre devient `1053`. On lit tout en texte et on complète | `load_postgres.py` : `o["code_postal"].str.zfill(5)` |
| **NULL ≠ 0** | Un prix non affiché n'est pas un prix de 0 €. NULL = « inconnu », il ne fausse pas les moyennes | `schema.sql` : `prix integer CHECK (prix > 0)` |
| **« Sans schéma » ≠ « sans structure »** | Mongo accepte tout, donc c'est à nous de rester cohérents | `load_mongo.py` construit chaque document de la même façon |
| **Oublier les index** | La requête marche, mais lentement sur 5,6 M de ventes | `docs/schema_bdd.md`, section 4 |
| **Mot de passe dans git** | Un secret commité reste dans l'historique | `db/.env` ignoré, seul `.env.example` est versionné |
| **Une vente, plusieurs lignes** | DVF répète une vente sur autant de lignes que de lots, parcelles et natures de culture : compter des lignes surestime les ventes et les logements | `load_dvf.py`, `docs/schema_bdd.md` |
| **Un contrôle qui passe n'est pas une preuve de qualité** | `check.py` vérifie des comptes et des liens, pas que les prix soient justes | À garder en tête avant de présenter un chiffre |

---

## 9. À essayer

1. Combien de communes ont à la fois des ventes DVF et des annonces Orpi ? (Réponse attendue : 135 d'après `REQUETE_CROISEE` dans `db/check.py`.)
2. Trouver dans `schema.sql` une colonne calculée et dire quelle erreur elle évite.
3. Chercher dans MongoDB les annonces qui parlent d'une « vue mer » (`$search`), puis regarder leur `code_insee` : sont-elles bien en bord de mer ?
