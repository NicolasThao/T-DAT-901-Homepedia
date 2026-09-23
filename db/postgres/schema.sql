-- Schéma relationnel Homepedia (PostgreSQL 17 + PostGIS 3.5)
-- Idempotent : rejouable sans erreur (IF NOT EXISTS partout).
--
-- Clé pivot entre toutes les sources : code INSEE de la commune (5 caractères).
-- Le code postal n'est PAS une clé : un code postal couvre souvent plusieurs communes.
-- Les textes libres (descriptions d'annonces, avis) vivent dans MongoDB, pas ici.

CREATE EXTENSION IF NOT EXISTS postgis;

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

-- ---------------------------------------------------------------------------
-- Transactions DVF (une ligne par mutation, après dédoublonnage des lots)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS mutation_dvf (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cle_mutation        text NOT NULL UNIQUE,              -- clé naturelle calculée au chargement
    date_mutation       date NOT NULL,
    nature_mutation     text NOT NULL,
    valeur_fonciere     numeric(15, 2),
    code_insee_source   char(5) NOT NULL,                  -- code tel que lu dans DVF
    code_insee          char(5) REFERENCES commune,        -- NULL si commune fusionnée depuis 2022
    type_local          text,                              -- type du local principal
    surface_bati_m2     numeric(10, 2),
    nb_pieces           smallint,
    surface_terrain_m2  numeric(12, 2),
    nb_lignes_source    smallint NOT NULL,                 -- lignes CSV fusionnées dans la mutation
    prix_m2             numeric(12, 2) GENERATED ALWAYS AS (
                            CASE WHEN surface_bati_m2 > 0 THEN valeur_fonciere / surface_bati_m2 END
                        ) STORED
);

CREATE INDEX IF NOT EXISTS idx_mutation_commune_date ON mutation_dvf (code_insee, date_mutation);
CREATE INDEX IF NOT EXISTS idx_mutation_type_local   ON mutation_dvf (type_local);

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
    reference             uuid NOT NULL UNIQUE,
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
