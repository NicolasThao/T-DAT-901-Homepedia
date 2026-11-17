"""
Étape 3 — Charge dans PostgreSQL les annonces Orpi (et leurs agences).
Prérequis : python db/load_referentiel.py (schéma + communes).
Les ventes DVF sont chargées par db/load_dvf.py (DVF géolocalisées 2022-2025, depuis le 2026-11-14).

Rejouable : upsert sur les clés naturelles (id_orpi, nom+adresse d'agence).

Usage : python db/load_postgres.py
"""


import numpy as np
import pandas as pd

from config import DB_DIR, postgres

ROOT = DB_DIR.parent
ORPI_CSV = ROOT / "scraping" / "orpi" / "data" / "orpi" / "listings_clean.csv"
ORPI_JSONL = ORPI_CSV.with_name("listings_raw.jsonl")

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
        charger_orpi(cur)
    with postgres() as conn:
        conn.autocommit = True
        conn.execute("VACUUM ANALYZE annonce")
        conn.execute("VACUUM ANALYZE agence")


if __name__ == "__main__":
    main()
