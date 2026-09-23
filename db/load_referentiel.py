"""
Étape 2 — Applique le schéma PostgreSQL et charge le référentiel géographique
(régions, départements, communes + arrondissements municipaux) depuis geo.api.gouv.fr.

Les réponses de l'API sont mises en cache dans db/data/geo/ : un second lancement
ne refait aucune requête et produit exactement le même contenu (upsert).

Usage : python db/load_referentiel.py
"""

import json
import time
from pathlib import Path

import requests
from psycopg.types.json import Json

from config import DB_DIR, postgres

API = "https://geo.api.gouv.fr"
CACHE = DB_DIR / "data" / "geo"
HEADERS = {"User-Agent": "Homepedia-Epitech/1.0 (projet etudiant T-DAT-901)"}
COMMUNE_FIELDS = "nom,code,codeDepartement,codesPostaux,population,type"

# Seules communes découpées en arrondissements municipaux (codes INSEE officiels)
COMMUNES_A_ARRONDISSEMENTS = {"75": "75056", "69": "69123", "13": "13055"}


def fetch(path, params, cache_name):
    """GET sur l'API avec cache disque. Le cache est la source de vérité une fois créé."""
    cache_file = CACHE / cache_name
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    response = requests.get(API + path, params=params, headers=HEADERS, timeout=120)
    response.raise_for_status()
    data = response.json()
    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    time.sleep(0.2)  # l'API tolère 50 req/s, on reste très en dessous
    return data


def communes_geojson(code_departement, type_commune):
    suffix = "arr" if type_commune == "arrondissement-municipal" else "com"
    return fetch(
        "/communes",
        {
            "codeDepartement": code_departement,
            "type": type_commune,
            "fields": COMMUNE_FIELDS,
            "format": "geojson",
            "geometry": "contour",
        },
        f"communes_{code_departement}_{suffix}.geojson",
    )["features"]


UPSERT_COMMUNE = """
INSERT INTO commune (code_insee, nom, type, code_commune_parent, code_departement,
                     codes_postaux, population, contour, centre)
SELECT %(code)s, %(nom)s, %(type)s, %(parent)s, %(dep)s, %(cp)s, %(pop)s, g, ST_PointOnSurface(g)
FROM (SELECT ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s::text), 4326)) AS g) AS geo
ON CONFLICT (code_insee) DO UPDATE SET
    nom = EXCLUDED.nom, type = EXCLUDED.type, code_commune_parent = EXCLUDED.code_commune_parent,
    code_departement = EXCLUDED.code_departement, codes_postaux = EXCLUDED.codes_postaux,
    population = EXCLUDED.population, contour = EXCLUDED.contour, centre = EXCLUDED.centre
"""


def commune_rows(features, parent=None):
    for f in features:
        p = f["properties"]
        yield {
            "code": p["code"],
            "nom": p["nom"],
            "type": p["type"],
            "parent": parent,
            "dep": p["codeDepartement"],
            "cp": p.get("codesPostaux", []),
            "pop": p.get("population"),
            "geom": Json(f["geometry"]) if f.get("geometry") else None,
        }


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    regions = fetch("/regions", {}, "regions.json")
    departements = fetch("/departements", {}, "departements.json")

    with postgres() as conn, conn.cursor() as cur:
        cur.execute((DB_DIR / "postgres" / "schema.sql").read_text(encoding="utf-8"))

        cur.executemany(
            "INSERT INTO region (code_region, nom) VALUES (%(code)s, %(nom)s) "
            "ON CONFLICT (code_region) DO UPDATE SET nom = EXCLUDED.nom",
            regions,
        )
        cur.executemany(
            "INSERT INTO departement (code_departement, nom, code_region) "
            "VALUES (%(code)s, %(nom)s, %(codeRegion)s) "
            "ON CONFLICT (code_departement) DO UPDATE SET nom = EXCLUDED.nom, "
            "code_region = EXCLUDED.code_region",
            departements,
        )

        attendu = {"commune-actuelle": 0, "arrondissement-municipal": 0}
        for dep in departements:
            code = dep["code"]
            features = communes_geojson(code, "commune-actuelle")
            cur.executemany(UPSERT_COMMUNE, list(commune_rows(features)))
            attendu["commune-actuelle"] += len(features)
            print(f"  {code:>3} {dep['nom']:<28} {len(features):>5} communes")

        # Les arrondissements après leur commune parente (clé étrangère)
        for dep_code, parent in COMMUNES_A_ARRONDISSEMENTS.items():
            features = communes_geojson(dep_code, "arrondissement-municipal")
            cur.executemany(UPSERT_COMMUNE, list(commune_rows(features, parent)))
            attendu["arrondissement-municipal"] += len(features)

        cur.execute("ANALYZE region, departement, commune")

    print(f"\nRégions : {len(regions)} | Départements : {len(departements)} | "
          f"Communes : {attendu['commune-actuelle']} | "
          f"Arrondissements : {attendu['arrondissement-municipal']}")


if __name__ == "__main__":
    main()
