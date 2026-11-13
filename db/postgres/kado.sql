-- Modélisation en étoile de KaDo (exercice bootstrap « Database organization with SQL »).

CREATE SCHEMA IF NOT EXISTS kado;

-- Dimension client : aucun attribut descriptif dans la source, seulement l'identifiant.
CREATE TABLE IF NOT EXISTS kado.dim_client (cli_id bigint PRIMARY KEY);

-- Dimension produit : famille, univers et maille restent des attributs à plat (pas de flocon),
-- car une même MAILLE apparaît sous plusieurs UNIVERS (30 mailles sur 34).
CREATE TABLE IF NOT EXISTS kado.dim_produit (
    produit_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY, -- clé de substitution
    libelle text NOT NULL UNIQUE, -- clé naturelle
    famille text NOT NULL,
    univers text NOT NULL,
    maille text NOT NULL
);

-- Dimension temps au grain du mois : la source n'a pas d'année.
CREATE TABLE IF NOT EXISTS kado.dim_temps (
    mois_vente smallint PRIMARY KEY CHECK (mois_vente BETWEEN 1 AND 12),
    nom_mois text NOT NULL,
    trimestre smallint NOT NULL CHECK (trimestre BETWEEN 1 AND 4)
);

-- Table de faits. Grain : 1 ligne = 1 article vendu dans un ticket.
-- ticket_id est une dimension dégénérée (identifiant sans attribut propre, gardé dans le fait).
CREATE TABLE IF NOT EXISTS kado.fait_vente (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, -- la source n'a pas de clé de ligne
    ticket_id bigint NOT NULL,
    cli_id bigint NOT NULL REFERENCES kado.dim_client,
    produit_id integer NOT NULL REFERENCES kado.dim_produit,
    mois_vente smallint NOT NULL REFERENCES kado.dim_temps,
    prix_net numeric(12, 2) NOT NULL -- mesure additive
);

-- Index sur les clés étrangères : chaque requête d'analyse joint le fait à ses dimensions.
CREATE INDEX IF NOT EXISTS idx_fait_vente_client ON kado.fait_vente (cli_id);

CREATE INDEX IF NOT EXISTS idx_fait_vente_produit ON kado.fait_vente (produit_id);

CREATE INDEX IF NOT EXISTS idx_fait_vente_mois ON kado.fait_vente (mois_vente);

CREATE INDEX IF NOT EXISTS idx_fait_vente_ticket ON kado.fait_vente (ticket_id);