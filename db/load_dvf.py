"""
Charge DVF géolocalisées (Etalab) 2022-2025 dans PostgreSQL : une ligne de mutation_dvf par vente.

Prérequis : python db/load_referentiel.py (schéma + communes), python db/telecharger_dvf.py (fichiers).
Rejouable : chaque année est supprimée puis rechargée en entier, dans une seule transaction.
`id_mutation` d'Etalab n'est pas stable d'une livraison à l'autre : on ne le garde jamais d'une
livraison à la suivante, on recharge l'année.

Règles (identiques pour toutes les années) :
- une vente = un `id_mutation` (identifiant fourni par Etalab, plus de clé reconstruite) ;
- logement = (parcelle, type, surface, pièces, n° de lot). DVF répète chaque logement sur autant de
  lignes que sa parcelle a de natures de culture (sol, jardin…) : le nombre de logements identiques
  est le nombre de lignes pour UNE culture (le max sur les cultures), pas le nombre total de lignes ;
- surface de terrain sommée sur les couples (parcelle, nature de culture) distincts ;
- position de la vente = moyenne des points de ses logements, à défaut de toutes ses parcelles.

Usage : python db/load_dvf.py            (les 4 années)
        python db/load_dvf.py 2025       (une année)
"""

import io
import sys
import time

import pandas as pd

from config import DB_DIR, postgres
from telecharger_dvf import ANNEES, DOSSIER

SOURCE = "dvf-geolocalisees-etalab"
COLONNES = ["id_mutation", "date_mutation", "nature_mutation", "valeur_fonciere", "code_commune",
            "id_parcelle", "code_nature_culture", "adresse_code_voie", "adresse_numero", "type_local",
            "surface_reelle_bati", "nombre_pieces_principales", "lot1_numero", "surface_terrain",
            "longitude", "latitude"]

STAGING = """
CREATE TEMP TABLE dvf_brut (
    cle              text,
    date_mutation    date,
    nature           text,
    valeur           numeric(15, 2),
    code_insee       char(5),
    id_parcelle      text,
    culture          text,
    cle_local        text,
    adresse          text,
    type_local       text,
    surface_bati     numeric,
    nb_pieces        numeric,
    surface_terrain  numeric,
    lon              float8,
    lat              float8
) ON COMMIT DROP
"""

AGREGATION = """
INSERT INTO mutation_dvf (cle_mutation, date_mutation, nature_mutation, valeur_fonciere,
                          code_insee_source, code_insee, type_local, nb_logements,
                          surface_bati_m2, nb_pieces, surface_terrain_m2, nb_lignes_source,
                          nb_adresses, position, _source, _date_ingestion)
SELECT m.cle, m.date_mutation, m.nature, m.valeur, m.code_insee, c.code_insee,
       m.type_local, coalesce(l.nb_logements, 0), l.surface_bati, l.nb_pieces, t.surface_terrain,
       m.nb_lignes, l.nb_adresses,
       ST_SetSRID(ST_MakePoint(coalesce(l.lon, m.lon), coalesce(l.lat, m.lat)), 4326),
       %(source)s, now()
FROM (
    SELECT cle,
           min(date_mutation) AS date_mutation, min(valeur) AS valeur,
           -- Une ligne hors marché (échange, adjudication…) rend toute la vente hors marché :
           -- son prix unique n'est pas un prix de marché (~25 ventes par an mêlent les deux).
           coalesce(min(nature) FILTER (WHERE nature NOT IN ('Vente', 'Vente en l''état futur d''achèvement')),
                    min(nature)) AS nature,
           -- Vente sur plusieurs communes (~15 000 par an) : la commune du logement s'il y en a un.
           coalesce(min(code_insee) FILTER (WHERE type_local IN ('Maison', 'Appartement')),
                    min(code_insee)) AS code_insee,
           count(*) AS nb_lignes, avg(lon) AS lon, avg(lat) AS lat,
           CASE
               WHEN count(DISTINCT type_local) FILTER (WHERE type_local IN ('Maison', 'Appartement')) > 1
                   THEN 'Mixte'
               ELSE coalesce(max(type_local) FILTER (WHERE type_local IN ('Maison', 'Appartement')),
                             max(type_local) FILTER (WHERE type_local LIKE 'Local%%'),
                             max(type_local))
           END AS type_local
    FROM dvf_brut
    GROUP BY cle
) AS m
LEFT JOIN (
    SELECT cle, sum(n) AS nb_logements, count(DISTINCT adresse) AS nb_adresses,
           sum(surface_bati * n) AS surface_bati, sum(nb_pieces * n) AS nb_pieces,
           avg(lon) AS lon, avg(lat) AS lat
    FROM (  -- un groupe = un logement type ; n = logements identiques (lignes pour une même culture)
        SELECT cle, cle_local, max(n) AS n, min(adresse) AS adresse, min(surface_bati) AS surface_bati,
               min(nb_pieces) AS nb_pieces, avg(lon) AS lon, avg(lat) AS lat
        FROM (SELECT cle, cle_local, culture, count(*) AS n, min(adresse) AS adresse,
                     min(surface_bati) AS surface_bati, min(nb_pieces) AS nb_pieces,
                     avg(lon) AS lon, avg(lat) AS lat
              FROM dvf_brut WHERE type_local IN ('Maison', 'Appartement')
              GROUP BY cle, cle_local, culture) AS par_culture
        GROUP BY cle, cle_local) AS locaux
    GROUP BY cle
) AS l USING (cle)
LEFT JOIN (
    SELECT cle, sum(surface_terrain) AS surface_terrain
    FROM (SELECT DISTINCT cle, id_parcelle, culture, surface_terrain FROM dvf_brut) AS parcelles
    GROUP BY cle
) AS t USING (cle)
LEFT JOIN commune AS c ON c.code_insee = m.code_insee
"""


def fichier(annee):
    return DOSSIER / f"{annee}.csv.gz"


def lire_annee(annee, chunksize=None):
    """Lignes du fichier Etalab, au format de la table de staging (texte, vide = NULL)."""
    morceaux = pd.read_csv(fichier(annee), dtype=str, keep_default_na=False, usecols=COLONNES,
                           encoding="utf-8", chunksize=chunksize)
    for df in ([morceaux] if chunksize is None else morceaux):
        yield pd.DataFrame({
            "cle": df["id_mutation"],
            "date_mutation": df["date_mutation"],
            "nature": df["nature_mutation"],
            "valeur": df["valeur_fonciere"],
            "code_insee": df["code_commune"],
            "id_parcelle": df["id_parcelle"],
            "culture": df["code_nature_culture"],
            "cle_local": (df["id_parcelle"] + "|" + df["type_local"] + "|" + df["surface_reelle_bati"]
                          + "|" + df["nombre_pieces_principales"] + "|" + df["lot1_numero"]),
            "adresse": df["adresse_code_voie"] + "|" + df["adresse_numero"],
            "type_local": df["type_local"],
            "surface_bati": df["surface_reelle_bati"],
            "nb_pieces": df["nombre_pieces_principales"],
            "surface_terrain": df["surface_terrain"],
            "lon": df["longitude"],
            "lat": df["latitude"],
        })


def charger_annee(conn, annee):
    t0 = time.time()
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(STAGING)
        lignes = 0
        with cur.copy("COPY dvf_brut FROM STDIN WITH (FORMAT csv)") as copy:
            for morceau in lire_annee(annee, chunksize=500_000):
                buffer = io.StringIO()
                morceau.to_csv(buffer, index=False, header=False)  # champ vide non quoté -> NULL
                copy.write(buffer.getvalue())
                lignes += len(morceau)
        cur.execute("DELETE FROM mutation_dvf WHERE date_mutation >= make_date(%s, 1, 1) "
                    "AND date_mutation < make_date(%s + 1, 1, 1)", (annee, annee))
        supprimees = cur.rowcount
        cur.execute(AGREGATION, {"source": SOURCE})
        print(f"{annee} : {lignes} lignes -> {cur.rowcount} ventes ({supprimees} remplacées, "
              f"{time.time() - t0:.0f} s)")


def main():
    annees = [int(a) for a in sys.argv[1:]] or list(ANNEES)
    with postgres() as conn:
        conn.execute((DB_DIR / "postgres" / "schema.sql").read_text(encoding="utf-8"))
        conn.commit()
        for annee in annees:
            charger_annee(conn, annee)
    with postgres() as conn:
        conn.autocommit = True
        conn.execute("VACUUM ANALYZE mutation_dvf")


if __name__ == "__main__":
    main()
