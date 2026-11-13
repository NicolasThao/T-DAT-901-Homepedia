"""
Vérification des bases Homepedia : chaque contrôle rend PASS ou FAIL, code de sortie 1 si un FAIL.

Usage : python db/check.py
"""

import json
import sys

from config import DB_DIR, mongo, postgres

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


def check_dvf(cur):
    # Attendus recalculés depuis le CSV source, indépendamment du loader
    from load_postgres import lire_dvf
    staging = lire_dvf()
    nb_lignes, nb_mutations = len(staging), staging["cle"].nunique()
    codes_connus = {r[0] for r in cur.execute("SELECT code_insee FROM commune")}
    codes_inconnus = set(staging["code_insee"].unique()) - codes_connus

    n = cur.execute("SELECT count(*) FROM mutation_dvf").fetchone()[0]
    controle(f"mutation_dvf : {n} mutations", n == nb_mutations, f"attendu {nb_mutations}")

    lignes = cur.execute("SELECT sum(nb_lignes_source) FROM mutation_dvf").fetchone()[0]
    controle("aucune ligne DVF perdue à l'agrégation", lignes == nb_lignes, f"{lignes} / {nb_lignes}")

    sans_commune = cur.execute(
        "SELECT count(DISTINCT code_insee_source) FROM mutation_dvf WHERE code_insee IS NULL").fetchone()[0]
    controle("code_insee NULL uniquement pour les codes absents du référentiel",
             sans_commune == len(codes_inconnus), f"{sans_commune} codes, attendu {len(codes_inconnus)}")

    # Ordre de grandeur connu : Paris 6e / 7e ~15 000 €/m² (Follow-up 1, job 3)
    mediane = cur.execute("""
        SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY prix_m2) FROM mutation_dvf
        WHERE code_insee = '75106' AND nb_logements = 1 AND type_local = 'Appartement'
          AND nature_mutation = 'Vente'""").fetchone()[0]
    controle("médiane prix/m² Paris 6e plausible (10 000 - 20 000 €)",
             mediane is not None and 10_000 <= mediane <= 20_000, f"{mediane:.0f} €/m²" if mediane else "aucune")

    # Qualité (étape 3ter) : attendus recalculés depuis le CSV
    logements = staging[staging["type_local"].isin(["Maison", "Appartement"])]
    attendu = int((logements.groupby("cle")["adresse"].nunique() > 1).sum())
    n = cur.execute("SELECT count(*) FROM mutation_dvf WHERE prix_m2_douteux").fetchone()[0]
    controle("prix_m2_douteux = actes à logements d'adresses différentes", n == attendu,
             f"{n}, attendu {attendu}")

    natures_marche = ["Vente", "Vente en l'état futur d'achèvement"]
    hors = staging.drop_duplicates("cle")
    attendu = int((~hors["nature"].isin(natures_marche)).sum())
    n = cur.execute("SELECT count(*) FROM mutation_dvf WHERE hors_marche").fetchone()[0]
    controle("hors_marche = natures hors Vente / VEFA", n == attendu, f"{n}, attendu {attendu}")

    vefa_exclue = cur.execute(
        "SELECT count(*) FROM mutation_dvf WHERE hors_marche AND nature_mutation LIKE '%futur%'").fetchone()[0]
    controle("aucune VEFA classée hors marché (apostrophe du libellé)", vefa_exclue == 0, f"{vefa_exclue}")


def check_orpi(cur):
    import pandas as pd
    from load_postgres import ORPI_CSV
    o = pd.read_csv(ORPI_CSV, dtype={"code_postal": str})

    n = cur.execute("SELECT count(*) FROM annonce").fetchone()[0]
    controle(f"annonce : {n} lignes", n == len(o), f"attendu {len(o)}")

    attendu = len(o[["agence_nom", "agence_adresse"]].drop_duplicates())
    n = cur.execute("SELECT count(*) FROM agence").fetchone()[0]
    controle(f"agence : {n} lignes", n == attendu, f"attendu {attendu}")

    hors_france = int((~o["departement_valide_france"]).sum())
    sans_commune = cur.execute("SELECT count(*) FROM annonce WHERE code_insee IS NULL").fetchone()[0]
    controle("seules les annonces hors France sont sans commune", sans_commune == hors_france,
             f"{sans_commune} sans commune, {hors_france} hors France")

    plm_non_detaille = cur.execute(
        "SELECT count(*) FROM annonce WHERE code_insee IN ('75056', '69123', '13055')").fetchone()[0]
    controle("Paris/Lyon/Marseille rattachées à l'arrondissement", plm_non_detaille == 0)


def check_mongo(cur):
    from load_postgres import ORPI_JSONL
    attendus = {json.loads(l)["id"] for l in open(ORPI_JSONL, encoding="utf-8") if l.strip()}
    collection = mongo()["annonces_brutes"]

    n = collection.count_documents({})
    controle(f"annonces_brutes : {n} documents", n == len(attendus), f"attendu {len(attendus)}")

    # Lien Postgres <-> Mongo : mêmes identifiants et même code INSEE des deux côtés
    pg = dict(cur.execute("SELECT id_orpi, code_insee FROM annonce").fetchall())
    mg = {d["annonce_id"]: d["code_insee"] for d in collection.find({}, {"annonce_id": 1, "code_insee": 1})}
    controle("0 annonce sans lien Postgres <-> Mongo", set(pg) == set(mg), f"{len(set(pg) ^ set(mg))} écarts")
    controle("code_insee identique dans Postgres et Mongo", pg == mg,
             f"{sum(pg[i] != mg[i] for i in pg.keys() & mg.keys())} différents")

    n = collection.count_documents({"$or": [{"agence_telephone": {"$exists": True}}, {"agence_email": {"$exists": True}}]})
    controle("aucun téléphone ni e-mail d'agence", n == 0, f"{n} documents")

    index = set(collection.index_information())
    controle("index code_insee et texte sur description", {"code_insee_1", "texte_description"} <= index, str(sorted(index)))
    trouves = collection.count_documents({"$text": {"$search": "balcon"}})
    controle("recherche plein texte « balcon » renvoie des annonces", trouves > 0, f"{trouves} annonces")


# Prix/m² médian des appartements : DVF (ventes d'un seul logement, hors marché exclu) face aux
# annonces Orpi, par code INSEE. La clé pivot relie les deux sources et les deux bases.
REQUETE_CROISEE = """
WITH dvf AS (
    SELECT code_insee, percentile_cont(0.5) WITHIN GROUP (ORDER BY prix_m2) AS dvf_m2, count(*) AS nb_ventes
    FROM mutation_dvf
    WHERE nb_logements = 1 AND type_local = 'Appartement' AND NOT hors_marche AND code_insee IS NOT NULL
    GROUP BY code_insee),
orpi AS (
    SELECT code_insee, percentile_cont(0.5) WITHIN GROUP (ORDER BY prix / surface_habitable_m2) AS orpi_m2,
           count(*) AS nb_annonces
    FROM annonce
    WHERE type_bien = 'appartement' AND prix IS NOT NULL AND surface_habitable_m2 > 0 AND code_insee IS NOT NULL
    GROUP BY code_insee)
SELECT code_insee, nb_annonces, nb_ventes, orpi_m2, dvf_m2 FROM orpi JOIN dvf USING (code_insee)
"""


def check_croise(cur):
    lignes = cur.execute(REQUETE_CROISEE).fetchall()
    controle("requête croisée DVF x Orpi par code INSEE renvoie des communes", len(lignes) > 0, f"{len(lignes)} communes")
    plausibles = all(200 <= orpi <= 30_000 and 200 <= dvf <= 30_000 for _, _, _, orpi, dvf in lignes)
    controle("prix/m² médians DVF et Orpi plausibles (200 - 30 000 €, garde-fou d'unité)", plausibles)

    # Mongo -> Postgres : chaque commune d'annonce stockée dans Mongo existe dans le référentiel
    codes = [c for c in mongo()["annonces_brutes"].distinct("code_insee") if c]
    connus = {r[0] for r in cur.execute("SELECT code_insee FROM commune WHERE code_insee = ANY(%s)", (codes,))}
    controle("communes des annonces Mongo présentes dans le référentiel Postgres", set(codes) == connus,
             f"{len(connus)} / {len(codes)}")


def check_kado(cur):
    # Attendus recalculés depuis le CSV source, indépendamment du loader
    import pandas as pd
    from load_kado import KADO_CSV
    k = pd.read_csv(KADO_CSV, usecols=["PRIX_NET", "LIBELLE", "CLI_ID"])

    for table, attendu in [("fait_vente", len(k)), ("dim_client", k["CLI_ID"].nunique()),
                           ("dim_produit", k["LIBELLE"].nunique()), ("dim_temps", 12)]:
        n = cur.execute(f"SELECT count(*) FROM kado.{table}").fetchone()[0]
        controle(f"kado.{table} : {n} lignes", n == attendu, f"attendu {attendu}")

    # Somme en centimes entiers : comparaison exacte, sans erreur d'arrondi flottant
    centimes_csv = int((k["PRIX_NET"] * 100).round().astype("int64").sum())
    centimes_bdd = cur.execute("SELECT (sum(prix_net) * 100)::bigint FROM kado.fait_vente").fetchone()[0]
    controle("kado : chiffre d'affaires total identique au CSV", centimes_bdd == centimes_csv,
             f"{centimes_bdd / 100:.2f} € / {centimes_csv / 100:.2f} €")

    tickets_multi_clients = cur.execute("""
        SELECT count(*) FROM (SELECT ticket_id FROM kado.fait_vente
                              GROUP BY ticket_id HAVING count(DISTINCT cli_id) > 1) AS t""").fetchone()[0]
    controle("kado : chaque ticket appartient à un seul client (dimension dégénérée)",
             tickets_multi_clients == 0, f"{tickets_multi_clients} tickets multi-clients")


def check_contours(cur):
    # Contours des départements / régions (union des communes) et versions simplifiées pour la carte
    for table, attendu in (("departement", 101), ("region", 18)):
        ok = cur.execute(f"""SELECT count(*) FROM {table}
                             WHERE contour IS NOT NULL AND ST_IsValid(contour)
                               AND contour_carte IS NOT NULL AND NOT ST_IsEmpty(contour_carte)
                               AND ST_IsValid(contour_carte)""").fetchone()[0]
        controle(f"{table} : contours valides (complet + carte)", ok == attendu, f"{ok} / {attendu}")

    ko = cur.execute("""SELECT count(*) FROM commune WHERE contour_carte IS NULL
                        OR ST_IsEmpty(contour_carte) OR NOT ST_IsValid(contour_carte)""").fetchone()[0]
    controle("communes : contour carte présent et valide", ko == 0, f"{ko} manquants ou invalides")

    # La Tour Eiffel tombe dans Paris (75) et en Île-de-France (11), y compris sur les contours simplifiés
    zones = cur.execute("""
        SELECT (SELECT code_departement FROM departement WHERE ST_Contains(contour_carte, p)),
               (SELECT code_region FROM region WHERE ST_Contains(contour_carte, p))
        FROM ST_SetSRID(ST_Point(2.2945, 48.8584), 4326) AS p""").fetchone()
    controle("repère Tour Eiffel -> département 75, région 11 (contours carte)",
             zones == ("75", "11"), f"trouvé {zones}")

    # Poids envoyé au navigateur : France entière par département < 1 Mo de GeoJSON
    mo = cur.execute("SELECT sum(length(ST_AsGeoJSON(contour_carte, 5))) / 1e6 FROM departement").fetchone()[0]
    controle("carte des départements < 1 Mo de GeoJSON", mo < 1, f"{mo:.2f} Mo")


# Recalcul indépendant (SQL pur) des indicateurs écrits par le job Spark jobs/indicateurs_prix.py
INDICATEURS_SQL = """
WITH v AS (
    SELECT m.code_insee, c.code_departement, d.code_region,
           extract(year FROM m.date_mutation)::int AS periode, t.type_local, m.prix_m2::float8 AS prix_m2
    FROM mutation_dvf m
    JOIN commune c ON c.code_insee = m.code_insee
    JOIN departement d ON d.code_departement = c.code_departement
    CROSS JOIN LATERAL (VALUES (m.type_local), ('Tous')) AS t(type_local)
    WHERE NOT m.hors_marche AND NOT m.prix_m2_douteux AND m.nb_logements = 1
      AND m.type_local IN ('Maison', 'Appartement') AND m.prix_m2 BETWEEN 200 AND 30000
)
SELECT 'commune', code_insee, type_local, periode,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY prix_m2), count(*) FROM v GROUP BY 2, 3, 4
UNION ALL
SELECT 'departement', code_departement, type_local, periode,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY prix_m2), count(*) FROM v GROUP BY 2, 3, 4
UNION ALL
SELECT 'region', code_region, type_local, periode,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY prix_m2), count(*) FROM v GROUP BY 2, 3, 4
"""


def check_indicateurs(cur):
    lignes = cur.execute("SELECT count(*) FROM indicateurs_prix").fetchone()[0]
    controle("indicateurs_prix rempli par le job Spark", lignes > 0, f"{lignes} lignes")

    ecarts = cur.execute(f"""
        SELECT count(*) FILTER (WHERE i.code_geo IS NULL)  AS absents_spark,
               count(*) FILTER (WHERE s.code_geo IS NULL)  AS en_trop_spark,
               count(*) FILTER (WHERE i.nb_ventes <> s.nb)  AS comptes_differents,
               count(*) FILTER (WHERE abs(i.prix_m2_median - s.med) > 0.01) AS medianes_differentes
        FROM ({INDICATEURS_SQL}) AS s(niveau_geo, code_geo, type_local, periode, med, nb)
        FULL JOIN indicateurs_prix i USING (niveau_geo, code_geo, type_local, periode)""").fetchone()
    controle("indicateurs Spark = recalcul SQL (toutes zones, médianes à 0,01 € près)",
             ecarts == (0, 0, 0, 0),
             "absents {}, en trop {}, comptes différents {}, médianes différentes {}".format(*ecarts))

    # Chaque vente compte une fois par niveau : même total de ventes aux 3 échelles
    totaux = dict(cur.execute("""SELECT niveau_geo, sum(nb_ventes) FROM indicateurs_prix
                                 WHERE type_local = 'Tous' GROUP BY niveau_geo""").fetchall())
    controle("même nombre de ventes aux échelles commune, département, région",
             len(set(totaux.values())) == 1, str(totaux))

    paris6 = cur.execute("""SELECT prix_m2_median FROM indicateurs_prix WHERE niveau_geo = 'commune'
                            AND code_geo = '75106' AND type_local = 'Appartement'""").fetchone()
    controle("repère : médiane appartements Paris 6e entre 10 000 et 20 000 €/m²",
             paris6 is not None and 10_000 <= paris6[0] <= 20_000, f"{paris6[0] if paris6 else None:.0f} €/m²")


def main():
    with postgres() as conn, conn.cursor() as cur:
        check_referentiel(cur)
        check_contours(cur)
        check_indicateurs(cur)
        check_dvf(cur)
        check_orpi(cur)
        check_mongo(cur)
        check_croise(cur)
        check_kado(cur)
    nb_fail = resultats.count(False)
    print(f"\n{'PASS' if nb_fail == 0 else 'FAIL'} — {len(resultats) - nb_fail}/{len(resultats)} contrôles OK")
    sys.exit(1 if nb_fail else 0)


if __name__ == "__main__":
    main()
