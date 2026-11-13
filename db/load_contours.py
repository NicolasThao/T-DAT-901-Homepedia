"""
MVP carte — Contours des départements et des régions, et contours simplifiés pour la carte.

Départements = union des contours de leurs communes (hors arrondissements municipaux, qui
recouvrent Paris, Lyon et Marseille). Régions = union des contours de leurs départements.
Les colonnes *_carte sont des versions simplifiées, assez légères pour le navigateur.

Rejouable : chaque lancement recalcule tout depuis commune.contour (~1 min).

Usage : python db/load_contours.py
"""

from config import DB_DIR, postgres

TOLERANCE_ZONE = 0.005      # degrés, ~500 m : régions et départements
TOLERANCE_COMMUNE = 0.0005  # degrés, ~50 m : communes (affichées un département à la fois)

# La simplification peut emboîter des petites îles côtières dans le continent (« nested
# shells », 14 départements touchés) : ST_MakeValid répare, ST_CollectionExtract(..., 3)
# ne garde que les polygones.
SIMPLIFIER = ("ST_Multi(ST_CollectionExtract(ST_MakeValid("
              "ST_SimplifyPreserveTopology({col}, {tol})), 3))")

ETAPES = [
    ("départements", f"""
        UPDATE departement d SET contour = u.contour
        FROM (SELECT code_departement, ST_Multi(ST_Union(contour)) AS contour
              FROM commune WHERE type = 'commune-actuelle'
              GROUP BY code_departement) u
        WHERE d.code_departement = u.code_departement"""),
    ("régions", """
        UPDATE region r SET contour = u.contour
        FROM (SELECT code_region, ST_Multi(ST_Union(contour)) AS contour
              FROM departement GROUP BY code_region) u
        WHERE r.code_region = u.code_region"""),
    ("contours simplifiés", f"""
        UPDATE departement SET contour_carte = {SIMPLIFIER.format(col='contour', tol=TOLERANCE_ZONE)};
        UPDATE region      SET contour_carte = {SIMPLIFIER.format(col='contour', tol=TOLERANCE_ZONE)};
        UPDATE commune     SET contour_carte = {SIMPLIFIER.format(col='contour', tol=TOLERANCE_COMMUNE)}"""),
]


def main():
    with postgres() as conn, conn.cursor() as cur:
        cur.execute((DB_DIR / "postgres" / "schema.sql").read_text(encoding="utf-8"))
        for nom, sql in ETAPES:
            print(f"Calcul : {nom}...", flush=True)
            cur.execute(sql)
        cur.execute("ANALYZE region, departement, commune")
        for table in ("region", "departement", "commune"):
            n = cur.execute(f"SELECT count(*) FROM {table} WHERE contour_carte IS NOT NULL").fetchone()[0]
            print(f"{table} : {n} contours pour la carte")


if __name__ == "__main__":
    main()
