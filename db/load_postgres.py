"""
Étape 3 — Charge dans PostgreSQL les transactions DVF 2022 et les annonces Orpi.
Prérequis : python db/load_referentiel.py (schéma + communes).

Rejouable : upsert sur les clés naturelles (cle_mutation, id_orpi, nom+adresse d'agence).

Usage : python db/load_postgres.py
"""

import io
import time

import numpy as np
import pandas as pd

from config import DB_DIR, postgres

ROOT = DB_DIR.parent
DVF_ZIP = ROOT / "bootstrap" / "data" / "france_total_real_estate_sales_2022.csv.zip"
ORPI_CSV = ROOT / "scraping" / "orpi" / "data" / "orpi" / "listings_clean.csv"
ORPI_JSONL = ORPI_CSV.with_name("listings_raw.jsonl")

# ---------------------------------------------------------------------------
# DVF
# ---------------------------------------------------------------------------

STAGING_DVF = """
CREATE TEMP TABLE dvf_brut (
    cle              text,
    date_mutation    date,
    nature           text,
    valeur           numeric(15, 2),
    code_insee       char(5),
    section          text,
    no_plan          text,
    adresse          text,
    type_local       text,
    surface_bati     numeric,
    nb_pieces        numeric,
    surface_terrain  numeric
) ON COMMIT DROP
"""

# Une ligne par acte. Les surfaces de terrain sont sommées sur les parcelles distinctes,
# car le CSV répète la parcelle pour chaque local qu'elle porte.
AGREGATION_DVF = """
INSERT INTO mutation_dvf (cle_mutation, date_mutation, nature_mutation, valeur_fonciere,
                          code_insee_source, code_insee, type_local, nb_logements,
                          surface_bati_m2, nb_pieces, surface_terrain_m2, nb_lignes_source,
                          nb_adresses)
SELECT m.cle, m.date_mutation, m.nature, m.valeur, m.code_insee, c.code_insee,
       m.type_local, m.nb_logements, m.surface_bati, m.nb_pieces, t.surface_terrain, m.nb_lignes,
       m.nb_adresses
FROM (
    SELECT cle,
           min(date_mutation) AS date_mutation, min(nature) AS nature,
           min(valeur) AS valeur, min(code_insee) AS code_insee,
           count(*) AS nb_lignes,
           count(*) FILTER (WHERE type_local IN ('Maison', 'Appartement')) AS nb_logements,
           count(DISTINCT adresse) FILTER (WHERE type_local IN ('Maison', 'Appartement')) AS nb_adresses,
           sum(surface_bati) FILTER (WHERE type_local IN ('Maison', 'Appartement')) AS surface_bati,
           sum(nb_pieces) FILTER (WHERE type_local IN ('Maison', 'Appartement')) AS nb_pieces,
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
    SELECT cle, sum(surface_terrain) AS surface_terrain
    FROM (SELECT DISTINCT cle, section, no_plan, surface_terrain FROM dvf_brut) AS parcelles
    GROUP BY cle
) AS t USING (cle)
LEFT JOIN commune AS c ON c.code_insee = m.code_insee
ON CONFLICT (cle_mutation) DO UPDATE SET
    date_mutation = EXCLUDED.date_mutation, nature_mutation = EXCLUDED.nature_mutation,
    valeur_fonciere = EXCLUDED.valeur_fonciere, code_insee_source = EXCLUDED.code_insee_source,
    code_insee = EXCLUDED.code_insee, type_local = EXCLUDED.type_local,
    nb_logements = EXCLUDED.nb_logements, surface_bati_m2 = EXCLUDED.surface_bati_m2,
    nb_pieces = EXCLUDED.nb_pieces, surface_terrain_m2 = EXCLUDED.surface_terrain_m2,
    nb_lignes_source = EXCLUDED.nb_lignes_source, nb_adresses = EXCLUDED.nb_adresses
"""


def lire_dvf():
    # Pas de drop_duplicates : le fichier n'a pas de numéro de lot, deux lignes identiques
    # sont le plus souvent deux lots distincts (ex. deux caves de même surface sur une parcelle).
    df = pd.read_csv(DVF_ZIP, dtype=str, encoding="utf-8", keep_default_na=False)

    dep = df["Code departement"].str.zfill(2)
    com = df["Code commune"].str.zfill(3)
    # DOM : département sur 3 caractères (971) + 2 derniers chiffres de la commune -> 97101
    code_insee = np.where(dep.str.len() == 3, dep + com.str[-2:], dep + com)
    d = df["Date mutation"]  # jj/mm/aaaa
    date_iso = d.str[6:10] + "-" + d.str[3:5] + "-" + d.str[0:2]
    valeur = df["Valeur fonciere"].str.replace(",", ".", regex=False)

    staging = pd.DataFrame({
        "cle": date_iso + "|" + code_insee + "|" + df["Nature mutation"] + "|" + valeur,
        "date_mutation": date_iso,
        "nature": df["Nature mutation"],
        "valeur": valeur,
        "code_insee": code_insee,
        "section": df["Section"],
        "no_plan": df["No plan"],
        "adresse": df["Code voie"] + "|" + df["No voie"],
        "type_local": df["Type local"],
        "surface_bati": df["Surface reelle bati"],
        "nb_pieces": df["Nombre pieces principales"],
        "surface_terrain": df["Surface terrain"],
    })
    return staging


def charger_dvf(cur):
    t0 = time.time()
    staging = lire_dvf()
    print(f"DVF : {len(staging)} lignes lues ({time.time() - t0:.0f} s)")

    cur.execute(STAGING_DVF)
    buffer = io.StringIO()
    staging.to_csv(buffer, index=False, header=False)  # champ vide non quoté -> NULL en COPY CSV
    buffer.seek(0)
    with cur.copy("COPY dvf_brut FROM STDIN WITH (FORMAT csv)") as copy:
        while chunk := buffer.read(1 << 20):
            copy.write(chunk)

    cur.execute(AGREGATION_DVF)
    print(f"DVF : {cur.rowcount} mutations insérées/mises à jour ({time.time() - t0:.0f} s)")


# ---------------------------------------------------------------------------
# Orpi
# ---------------------------------------------------------------------------

UPSERT_AGENCE = """
INSERT INTO agence (nom, adresse, note, nb_avis) VALUES (%(nom)s, %(adresse)s, %(note)s, %(nb_avis)s)
ON CONFLICT (nom, adresse) DO UPDATE SET note = EXCLUDED.note, nb_avis = EXCLUDED.nb_avis
"""

COLONNES_ANNONCE = [
    "id_orpi", "reference", "url", "type_bien", "sous_type", "prix",
    "surface_habitable_m2", "surface_terrain_m2", "surface_sejour_m2",
    "nb_pieces", "nb_chambres", "nb_salles_de_bain", "nb_places_parking",
    "ascenseur", "jardin", "garage", "piscine", "cave", "grenier", "terrasse", "balcon",
    "acces_handicape", "etat_general", "dpe_classe", "ges_classe", "dpe_conso_kwh_m2_an",
    "ges_kgco2_m2_an", "dpe_date", "code_postal", "commune_source", "longitude", "latitude",
    "date_mise_en_marche", "agence_id", "description_longueur",
]
COLONNES_TABLE = [c for c in COLONNES_ANNONCE if c not in ("longitude", "latitude")] + ["position"]

UPSERT_ANNONCE = (
    f"INSERT INTO annonce ({', '.join(COLONNES_TABLE)}) VALUES ("
    + ", ".join(f"%({c})s" for c in COLONNES_ANNONCE if c not in ("longitude", "latitude"))
    + ", ST_SetSRID(ST_MakePoint(%(longitude)s, %(latitude)s), 4326)) "
    + "ON CONFLICT (id_orpi) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in COLONNES_TABLE if c != "id_orpi")
)

# Résolution du code INSEE, de la plus fiable à la moins fiable. La position GPS d'Orpi est
# approximative (jusqu'à ~1 km de la commune affichée) : le nom de commune affiché fait foi.
NOM_NORMALISE = "lower(unaccent(replace({}, '-', ' ')))"
RESOLUTION_INSEE = [
    ("nom + code postal", f"""
        UPDATE annonce AS a SET code_insee = c.code_insee FROM commune AS c
        WHERE a.code_insee IS NULL AND a.code_postal = ANY (c.codes_postaux)
          AND {NOM_NORMALISE.format('c.nom')} = {NOM_NORMALISE.format('a.commune_source')}
    """),
    ("nom à moins de 5 km du GPS", f"""
        UPDATE annonce AS a SET code_insee = c.code_insee FROM commune AS c
        WHERE a.code_insee IS NULL
          AND {NOM_NORMALISE.format('c.nom')} = {NOM_NORMALISE.format('a.commune_source')}
          AND ST_DWithin(c.contour::geography, a.position::geography, 5000)
    """),
    ("code postal d'une seule commune", """
        UPDATE annonce AS a SET code_insee = (
            SELECT min(c.code_insee) FROM commune AS c
            WHERE a.code_postal = ANY (c.codes_postaux) AND c.type = 'commune-actuelle'
            HAVING count(*) = 1)
        WHERE a.code_insee IS NULL AND a.code_postal IS NOT NULL
    """),
    ("point GPS dans le contour", """
        UPDATE annonce AS a SET code_insee = (
            SELECT c.code_insee FROM commune AS c
            WHERE ST_Contains(c.contour, a.position)
            ORDER BY c.type = 'arrondissement-municipal' DESC LIMIT 1)
        WHERE a.code_insee IS NULL
    """),
    # Paris / Lyon / Marseille : descendre au niveau arrondissement, comme DVF
    ("arrondissement via code postal", """
        UPDATE annonce AS a SET code_insee = arr.code_insee FROM commune AS arr
        WHERE arr.code_commune_parent = a.code_insee AND a.code_postal = ANY (arr.codes_postaux)
    """),
    ("arrondissement via GPS", """
        UPDATE annonce AS a SET code_insee = arr.code_insee FROM commune AS arr
        WHERE arr.code_commune_parent = a.code_insee AND ST_Contains(arr.contour, a.position)
    """),
]


def valeur_sql(v):
    """NaN pandas -> NULL SQL ; types numpy -> types Python."""
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
        return None
    return v.item() if isinstance(v, np.generic) else v


def charger_orpi(cur):
    o = pd.read_csv(ORPI_CSV, dtype={"code_postal": str, "reference": str})

    agences = (o[["agence_nom", "agence_adresse", "agence_note", "agence_nb_avis"]]
               .drop_duplicates(["agence_nom", "agence_adresse"]))
    cur.executemany(UPSERT_AGENCE, [
        {"nom": a.agence_nom, "adresse": a.agence_adresse,
         # une note de 0 sans aucun avis signifie « pas de note », pas « noté 0/5 »
         "note": None if a.agence_nb_avis == 0 else valeur_sql(a.agence_note),
         "nb_avis": int(a.agence_nb_avis)}
        for a in agences.itertuples()
    ])
    ids_agence = {(nom, adr): i for i, nom, adr in cur.execute("SELECT id, nom, adresse FROM agence")}

    code_postal = o["code_postal"].str.zfill(5)
    code_postal = code_postal.where(code_postal != "00000")  # 00000 = annonce hors France
    lignes = pd.DataFrame({
        "id_orpi": o["id"],
        "reference": o["reference"],
        "url": o["url"],
        "type_bien": o["type_bien"],
        "sous_type": o["sous_type"],
        "prix": o["prix"].where(~o["prix_indisponible"]),
        "surface_habitable_m2": o["surface_habitable_m2"],
        "surface_terrain_m2": o["surface_terrain_m2"],
        "surface_sejour_m2": o["surface_sejour_m2"],
        "nb_pieces": o["nb_pieces"],
        "nb_chambres": o["nb_chambres"],
        "nb_salles_de_bain": o["nb_salles_de_bain"],
        "nb_places_parking": o["nb_places_parking"],
        **{c: o[c] for c in ["ascenseur", "jardin", "garage", "piscine", "cave", "grenier",
                             "terrasse", "balcon", "acces_handicape", "etat_general"]},
        "dpe_classe": o["dpe_lettre"],
        "ges_classe": o["ges_lettre"],
        "dpe_conso_kwh_m2_an": o["dpe_conso_valeur"],
        "ges_kgco2_m2_an": o["dpe_emission_valeur"],
        "dpe_date": o["dpe_date"].str[:10],                        # date locale de l'ISO 8601
        "code_postal": code_postal,
        "commune_source": o["commune"],
        "longitude": o["longitude"],
        "latitude": o["latitude"],
        "date_mise_en_marche": o["date_mise_en_marche"].str[:10],
        "agence_id": [ids_agence[(n, a)] for n, a in zip(o["agence_nom"], o["agence_adresse"])],
        "description_longueur": o["description_longueur"],
    })
    lignes = lignes.astype(object)
    cur.executemany(UPSERT_ANNONCE, [
        {k: valeur_sql(v) for k, v in row.items()} for row in lignes.to_dict("records")
    ])
    print(f"Orpi : {len(agences)} agences, {len(lignes)} annonces insérées/mises à jour")

    cur.execute("UPDATE annonce SET code_insee = NULL")
    for methode, sql in RESOLUTION_INSEE:
        cur.execute(sql)
        print(f"Orpi : code INSEE résolu par {methode} : {cur.rowcount}")
    non_resolues = cur.execute("SELECT count(*) FROM annonce WHERE code_insee IS NULL").fetchone()[0]
    print(f"Orpi : non résolu : {non_resolues}")


def main():
    with postgres() as conn, conn.cursor() as cur:
        cur.execute((DB_DIR / "postgres" / "schema.sql").read_text(encoding="utf-8"))
        charger_dvf(cur)
        charger_orpi(cur)
    with postgres() as conn:
        conn.autocommit = True
        conn.execute("VACUUM ANALYZE mutation_dvf")
        conn.execute("VACUUM ANALYZE annonce")
        conn.execute("VACUUM ANALYZE agence")


if __name__ == "__main__":
    main()
