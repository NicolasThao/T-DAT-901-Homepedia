-- Plusieurs chargeurs exécutent ce fichier, parfois en même temps : le DDL (ALTER TABLE, verrou
-- exclusif) est sérialisé, sinon deux exécutions s'interbloquent (vu le 2026-11-14). Le verrou
-- tient jusqu'à la fin de la transaction qui exécute le fichier.
SELECT pg_advisory_xact_lock(901);

-- Schéma relationnel Homepedia (PostgreSQL 17 + PostGIS 3.5)
-- Idempotent : rejouable sans erreur (IF NOT EXISTS partout).
--
-- Clé pivot entre toutes les sources : code INSEE de la commune (5 caractères).
-- Le code postal n'est PAS une clé : un code postal couvre souvent plusieurs communes.
-- Les textes libres (descriptions d'annonces, avis) vivent dans MongoDB, pas ici.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS unaccent;   -- comparaison des noms de communes sans accents

-- ---------------------------------------------------------------------------
-- Référentiel géographique (source : geo.api.gouv.fr)
-- Trois niveaux imposés par le sujet : région > département > commune
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS region (
    code_region  varchar(3) PRIMARY KEY,
    nom          text NOT NULL
);

CREATE TABLE IF NOT EXISTS departement (
    code_departement  varchar(3) PRIMARY KEY,          -- '01'..'95', '2A', '2B', '971'..'976'
    nom               text NOT NULL,
    code_region       varchar(3) NOT NULL REFERENCES region
);

CREATE TABLE IF NOT EXISTS commune (
    code_insee           char(5) PRIMARY KEY,
    nom                  text NOT NULL,
    type                 text NOT NULL
                         CHECK (type IN ('commune-actuelle', 'arrondissement-municipal')),
    -- Paris, Lyon et Marseille : DVF est codé par arrondissement (75101, 69381, 13201...),
    -- chaque arrondissement pointe vers sa commune (75056, 69123, 13055).
    code_commune_parent  char(5) REFERENCES commune,
    code_departement     varchar(3) NOT NULL REFERENCES departement,
    codes_postaux        text[] NOT NULL DEFAULT '{}',
    population           integer,
    contour              geometry(MultiPolygon, 4326),
    centre               geometry(Point, 4326)            -- point garanti dans le contour
);

CREATE INDEX IF NOT EXISTS idx_departement_region   ON departement (code_region);
CREATE INDEX IF NOT EXISTS idx_commune_departement  ON commune (code_departement);
CREATE INDEX IF NOT EXISTS idx_commune_parent       ON commune (code_commune_parent);
CREATE INDEX IF NOT EXISTS idx_commune_codes_postaux ON commune USING gin (codes_postaux);
CREATE INDEX IF NOT EXISTS idx_commune_contour      ON commune USING gist (contour);

-- Contours pour la carte (ajout MVP carte, calculés par db/load_contours.py) :
-- départements et régions = union des contours des communes ; *_carte = version simplifiée
-- envoyée au navigateur (~500 m de tolérance pour régions/départements, ~50 m pour les
-- communes : France entière ≈ 0,6 Mo de GeoJSON, communes d'un département ≤ 0,8 Mo).
ALTER TABLE departement ADD COLUMN IF NOT EXISTS contour       geometry(MultiPolygon, 4326);
ALTER TABLE departement ADD COLUMN IF NOT EXISTS contour_carte geometry(MultiPolygon, 4326);
ALTER TABLE region      ADD COLUMN IF NOT EXISTS contour       geometry(MultiPolygon, 4326);
ALTER TABLE region      ADD COLUMN IF NOT EXISTS contour_carte geometry(MultiPolygon, 4326);
ALTER TABLE commune     ADD COLUMN IF NOT EXISTS contour_carte geometry(MultiPolygon, 4326);

-- Indicateurs de prix (ajout MVP carte), écrits par le job Spark jobs/indicateurs_prix.py.
-- Grain : (niveau_geo, code_geo, type_local, periode), cf. conventions AstroNey (ADR-040).
-- Paris, Lyon, Marseille : le niveau commune est l'arrondissement (codage DVF).
CREATE TABLE IF NOT EXISTS indicateurs_prix (
    niveau_geo       text NOT NULL CHECK (niveau_geo IN ('commune', 'departement', 'region')),
    code_geo         varchar(5) NOT NULL,
    type_local       text NOT NULL CHECK (type_local IN ('Maison', 'Appartement', 'Tous')),
    periode          integer NOT NULL,                  -- année des mutations
    prix_m2_median   double precision NOT NULL,
    nb_ventes        integer NOT NULL,
    _source          text NOT NULL,
    _date_ingestion  timestamptz NOT NULL,
    PRIMARY KEY (niveau_geo, code_geo, type_local, periode)
);
-- Indicateurs du marché (2026-11-18, pipeline prix OVHcloud) : dispersion, valeur et surface médianes, lot.
-- NULL tant que le job qui écrit la table ne les calcule pas. _source : dvf (Spark local), dvf-ovhcloud
-- (calculé sur OVHcloud Data Platform, chargé par db/ovh.py recuperer), dvf-lac-local (même chaîne, lac local).
ALTER TABLE indicateurs_prix ADD COLUMN IF NOT EXISTS prix_m2_d1 double precision;
ALTER TABLE indicateurs_prix ADD COLUMN IF NOT EXISTS prix_m2_q1 double precision;
ALTER TABLE indicateurs_prix ADD COLUMN IF NOT EXISTS prix_m2_q3 double precision;
ALTER TABLE indicateurs_prix ADD COLUMN IF NOT EXISTS prix_m2_d9 double precision;
ALTER TABLE indicateurs_prix ADD COLUMN IF NOT EXISTS valeur_mediane double precision;
ALTER TABLE indicateurs_prix ADD COLUMN IF NOT EXISTS surface_mediane double precision;
ALTER TABLE indicateurs_prix ADD COLUMN IF NOT EXISTS _batch_id text;

-- ---------------------------------------------------------------------------
-- Transactions DVF (une ligne par mutation, après dédoublonnage des lots)
-- Une mutation = un acte = une valeur foncière. Le CSV répète cette valeur sur chaque
-- ligne (lot, parcelle) de l'acte ; clé retenue : date + commune + nature + valeur.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS mutation_dvf (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cle_mutation        text NOT NULL UNIQUE,              -- id_mutation d'Etalab (cf. bloc multi-années)
    date_mutation       date NOT NULL,
    nature_mutation     text NOT NULL,
    valeur_fonciere     numeric(15, 2),
    code_insee_source   char(5) NOT NULL,                  -- code commune de la vente (celle du logement si plusieurs)
    code_insee          char(5) REFERENCES commune,        -- NULL si le code est absent du référentiel
    type_local          text,                              -- Maison / Appartement / Mixte / autre type / NULL (terrain seul)
    nb_logements        integer NOT NULL,                  -- logements de la vente (identiques comptés par culture)
    surface_bati_m2     numeric(12, 2),                    -- somme des surfaces des logements
    nb_pieces           integer,
    surface_terrain_m2  numeric(14, 2),                    -- somme sur (parcelle, culture) distincts
    nb_lignes_source    integer NOT NULL,                  -- lignes du fichier fusionnées dans la vente
    prix_m2             numeric(12, 2) GENERATED ALWAYS AS (
                            CASE WHEN surface_bati_m2 > 0 THEN valeur_fonciere / surface_bati_m2 END
                        ) STORED
);

-- Qualité (ajout étape 3ter) : les lignes douteuses sont marquées, jamais supprimées.
-- nb_adresses : adresses distinctes (voie + numéro) parmi les logements de la vente. Une vente de
-- logements à plusieurs adresses (ex. lots d'un programme) a un prix/m² = une valeur / somme des
-- surfaces qui ne représente aucun logement : prix_m2_douteux.
ALTER TABLE mutation_dvf ADD COLUMN IF NOT EXISTS nb_adresses integer;
ALTER TABLE mutation_dvf ADD COLUMN IF NOT EXISTS prix_m2_douteux boolean
    GENERATED ALWAYS AS (nb_adresses > 1) STORED;
-- Hors marché : échange, adjudication, expropriation, terrain à bâtir (seuls Vente et VEFA restent)
ALTER TABLE mutation_dvf ADD COLUMN IF NOT EXISTS hors_marche boolean
    GENERATED ALWAYS AS (nature_mutation NOT IN ('Vente', 'Vente en l''état futur d''achèvement')) STORED;

-- Multi-années (2026-11-14) : source DVF géolocalisées d'Etalab, 2022-2025 (db/load_dvf.py).
-- cle_mutation = id_mutation d'Etalab (unique dans une livraison, pas d'une livraison à l'autre :
-- une année est toujours rechargée en entier). code_insee_source = code commune actuel d'Etalab.
-- position = moyenne des points des logements de la vente (à défaut, de ses parcelles).
ALTER TABLE mutation_dvf ADD COLUMN IF NOT EXISTS position geometry(Point, 4326);
ALTER TABLE mutation_dvf ADD COLUMN IF NOT EXISTS _source text;
ALTER TABLE mutation_dvf ADD COLUMN IF NOT EXISTS _date_ingestion timestamptz;
CREATE INDEX IF NOT EXISTS idx_mutation_position ON mutation_dvf USING gist (position);

CREATE INDEX IF NOT EXISTS idx_mutation_commune_date ON mutation_dvf (code_insee, date_mutation);
CREATE INDEX IF NOT EXISTS idx_mutation_type_local   ON mutation_dvf (type_local);
-- Index partiel : les analyses de prix/m² ne portent que sur les ventes d'un seul logement
CREATE INDEX IF NOT EXISTS idx_mutation_logement_unique ON mutation_dvf (code_insee, prix_m2)
    WHERE nb_logements = 1;

-- ---------------------------------------------------------------------------
-- Annonces Orpi (champs structurés ; le JSON brut et la description sont dans MongoDB)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agence (
    id       integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nom      text NOT NULL,
    adresse  text NOT NULL,
    note     numeric(2, 1) CHECK (note BETWEEN 0 AND 5),
    nb_avis  integer CHECK (nb_avis >= 0),
    UNIQUE (nom, adresse)
    -- téléphone et e-mail volontairement non stockés (inutiles à l'app)
);

CREATE TABLE IF NOT EXISTS annonce (
    id_orpi               bigint PRIMARY KEY,               -- clé partagée avec MongoDB
    reference             text NOT NULL UNIQUE,         -- UUID ou référence d'agence, format libre
    url                   text NOT NULL,
    type_bien             text NOT NULL,
    sous_type             text,
    prix                  integer CHECK (prix > 0),         -- NULL si prix non affiché
    surface_habitable_m2  numeric(10, 2),
    surface_terrain_m2    numeric(12, 2),
    surface_sejour_m2     numeric(10, 2),
    nb_pieces             smallint,
    nb_chambres           smallint,
    nb_salles_de_bain     smallint,
    nb_places_parking     smallint,
    ascenseur             boolean,
    jardin                boolean,
    garage                boolean,
    piscine               boolean,
    cave                  boolean,
    grenier               boolean,
    terrasse              boolean,
    balcon                boolean,
    acces_handicape       boolean,
    etat_general          text,
    dpe_classe            char(1) CHECK (dpe_classe BETWEEN 'A' AND 'G'),
    ges_classe            char(1) CHECK (ges_classe BETWEEN 'A' AND 'G'),
    dpe_conso_kwh_m2_an   numeric(8, 2),
    ges_kgco2_m2_an       numeric(8, 2),
    dpe_date              date,
    code_postal           char(5),
    commune_source        text,                             -- nom de commune affiché par Orpi
    code_insee            char(5) REFERENCES commune,       -- résolu au chargement (GPS puis code postal)
    position              geometry(Point, 4326),
    date_mise_en_marche   date,
    agence_id             integer REFERENCES agence,
    description_longueur  integer,
    prix_m2               numeric(12, 2) GENERATED ALWAYS AS (
                              CASE WHEN surface_habitable_m2 > 0 THEN prix / surface_habitable_m2 END
                          ) STORED
);

CREATE INDEX IF NOT EXISTS idx_annonce_commune  ON annonce (code_insee);
CREATE INDEX IF NOT EXISTS idx_annonce_type     ON annonce (type_bien);
CREATE INDEX IF NOT EXISTS idx_annonce_agence   ON annonce (agence_id);
CREATE INDEX IF NOT EXISTS idx_annonce_position ON annonce USING gist (position);
