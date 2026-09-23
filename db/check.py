"""
Vérification des bases Homepedia : chaque contrôle rend PASS ou FAIL, code de sortie 1 si un FAIL.

Usage : python db/check.py
"""

import json
import sys

from config import DB_DIR, postgres

CACHE = DB_DIR / "data" / "geo"
resultats = []


def controle(nom, ok, detail=""):
    resultats.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {nom}" + (f" — {detail}" if detail else ""))


def nb_features(pattern):
    return sum(len(json.loads(f.read_text(encoding="utf-8"))["features"]) for f in CACHE.glob(pattern))


def check_referentiel(cur):
    # Comptes en base == comptes renvoyés par l'API (cache disque)
    attendus = {
        "region": len(json.loads((CACHE / "regions.json").read_text(encoding="utf-8"))),
        "departement": len(json.loads((CACHE / "departements.json").read_text(encoding="utf-8"))),
    }
    for table, attendu in attendus.items():
        n = cur.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        controle(f"{table} : {n} lignes", n == attendu, f"attendu {attendu}")

    for type_commune, pattern in [("commune-actuelle", "communes_*_com.geojson"),
                                  ("arrondissement-municipal", "communes_*_arr.geojson")]:
        attendu = nb_features(pattern)
        n = cur.execute("SELECT count(*) FROM commune WHERE type = %s", (type_commune,)).fetchone()[0]
        controle(f"commune {type_commune} : {n} lignes", n == attendu, f"attendu {attendu}")

    sans_contour = cur.execute("SELECT count(*) FROM commune WHERE contour IS NULL").fetchone()[0]
    controle("toutes les communes ont un contour", sans_contour == 0, f"{sans_contour} sans contour")

    invalides = cur.execute("SELECT count(*) FROM commune WHERE NOT ST_IsValid(contour)").fetchone()[0]
    controle("contours géométriquement valides", invalides == 0, f"{invalides} invalides")

    hors_contour = cur.execute(
        "SELECT count(*) FROM commune WHERE NOT ST_Contains(contour, centre)").fetchone()[0]
    controle("centre de chaque commune dans son contour", hors_contour == 0, f"{hors_contour} hors contour")

    arr_orphelins = cur.execute(
        "SELECT count(*) FROM commune WHERE type = 'arrondissement-municipal' "
        "AND code_commune_parent IS NULL").fetchone()[0]
    controle("chaque arrondissement a sa commune parente", arr_orphelins == 0)

    # Points connus -> commune attendue (valide le SRID et l'ordre longitude/latitude)
    reperes = [
        ("Tour Eiffel", 2.2945, 48.8584, "75107"),
        ("Place Bellecour, Lyon", 4.8320, 45.7578, "69382"),
        ("Église de Brou, Bourg-en-Bresse", 5.2366, 46.1978, "01053"),
        ("Cathédrale d'Ajaccio", 8.7378, 41.9170, "2A004"),
    ]
    for nom, lon, lat, attendu in reperes:
        row = cur.execute(
            "SELECT code_insee FROM commune "
            "WHERE ST_Contains(contour, ST_SetSRID(ST_MakePoint(%s, %s), 4326)) "
            "ORDER BY type = 'arrondissement-municipal' DESC LIMIT 1",
            (lon, lat),
        ).fetchone()
        trouve = row[0] if row else None
        controle(f"repère {nom} -> {attendu}", trouve == attendu, f"trouvé {trouve}")


def main():
    with postgres() as conn, conn.cursor() as cur:
        check_referentiel(cur)
    nb_fail = resultats.count(False)
    print(f"\n{'PASS' if nb_fail == 0 else 'FAIL'} — {len(resultats) - nb_fail}/{len(resultats)} contrôles OK")
    sys.exit(1 if nb_fail else 0)


if __name__ == "__main__":
    main()
