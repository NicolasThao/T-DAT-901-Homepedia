"""
Follow-up 2 — extrait de la base tous les chiffres affichés dans le deck (-> faits.json).

Aucun chiffre du deck n'est recopié à la main : build_deck.py lit faits.json, verif_deck.py
refuse tout nombre du deck absent de faits.json.

Usage (bases démarrées) : .venv/Scripts/python docs/followup2/faits.py
"""

import json
import re
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "db"))
from config import mongo, postgres  # noqa: E402

SORTIE = Path(__file__).resolve().parent / "faits.json"
DEBUT, FIN = 2022, 2025  # années DVF chargées (db/telecharger_dvf.py ANNEES) ; l'app affiche FIN par défaut

# Filtre des ventes retenues par le job Spark (jobs/indicateurs_prix.py)
FILTRE_VENTES = """NOT hors_marche AND NOT prix_m2_douteux AND nb_logements = 1
    AND type_local IN ('Maison', 'Appartement') AND prix_m2 BETWEEN 200 AND 30000"""


def un(conn, sql, params=None):
    return conn.execute(sql, params).fetchone()[0]


def faits_postgres():
    with postgres() as c:
        f = {
            "dvf_lignes_csv": un(c, "SELECT sum(nb_lignes_source) FROM mutation_dvf"),
            "dvf_mutations": un(c, "SELECT count(*) FROM mutation_dvf"),
            "dvf_douteuses": un(c, "SELECT count(*) FROM mutation_dvf WHERE prix_m2_douteux"),
            "dvf_hors_marche": un(c, "SELECT count(*) FROM mutation_dvf WHERE hors_marche"),
            "dvf_codes_inconnus": un(c, """SELECT count(DISTINCT code_insee_source)
                                           FROM mutation_dvf WHERE code_insee IS NULL"""),
            "dvf_ventes_fin": un(c, "SELECT count(*) FROM mutation_dvf WHERE date_mutation >= make_date(%s, 1, 1)",
                                 (FIN,)),
            "dvf_locaux_fin": un(c, """SELECT count(*) FROM mutation_dvf WHERE type_local LIKE 'Local%%'
                                       AND date_mutation >= make_date(%s, 1, 1)""", (FIN,)),
            "dvf_terrains_fin": un(c, """SELECT count(*) FROM mutation_dvf WHERE type_local IS NULL
                                         AND date_mutation >= make_date(%s, 1, 1)""", (FIN,)),
            "ventes_retenues": un(c, f"SELECT count(*) FROM mutation_dvf WHERE code_insee IS NOT NULL AND {FILTRE_VENTES}"),
            "indicateurs_lignes": un(c, "SELECT count(*) FROM indicateurs_prix"),
            "regions": un(c, "SELECT count(*) FROM region"),
            "departements": un(c, "SELECT count(*) FROM departement"),
            "communes": un(c, "SELECT count(*) FROM commune WHERE type = 'commune-actuelle'"),
            "arrondissements": un(c, "SELECT count(*) FROM commune WHERE type = 'arrondissement-municipal'"),
            "communes_avec_prix": un(c, """SELECT count(*) FROM indicateurs_prix
                                          WHERE niveau_geo = 'commune' AND type_local = 'Tous' AND periode = %s""",
                                     (FIN,)),
            "communes_fiables": un(c, """SELECT count(*) FROM indicateurs_prix WHERE niveau_geo = 'commune'
                                        AND type_local = 'Tous' AND nb_ventes >= 30 AND periode = %s""", (FIN,)),
            "annonces": un(c, "SELECT count(*) FROM annonce"),
            "agences": un(c, "SELECT count(*) FROM agence"),
            "annonces_sans_commune": un(c, "SELECT count(*) FROM annonce WHERE code_insee IS NULL"),
        }
        # Repères de démo (médianes du job Spark de l'année FIN, celle que l'app affiche par défaut)
        rep = """SELECT round(prix_m2_median)::int FROM indicateurs_prix
                 WHERE niveau_geo = %s AND code_geo = %s AND type_local = %s AND periode = %s"""
        f["prix_france_idf"] = un(c, rep, ("region", "11", "Tous", FIN))
        f["prix_paris_6e_appart"] = un(c, rep, ("commune", "75106", "Appartement", FIN))
        f["prix_paris"] = un(c, rep, ("departement", "75", "Tous", FIN))
        f.update(faits_evolution(c))
        f["ventes_spark"] = un(c, """SELECT sum(nb_ventes) FROM indicateurs_prix
                                    WHERE niveau_geo = 'region' AND type_local = 'Tous'""")
    return f


def faits_evolution(c):
    """Variation du prix médian DEBUT -> FIN, mêmes règles que l'app (app/carte.py variation) :
    seulement si les deux années ont au moins 30 ventes."""
    sql = """SELECT a.code_geo, round(((b.prix_m2_median / a.prix_m2_median - 1) * 100)::numeric, 1)::float
             FROM indicateurs_prix a JOIN indicateurs_prix b USING (niveau_geo, code_geo, type_local)
             WHERE a.niveau_geo = %s AND a.type_local = 'Tous' AND a.periode = %s AND b.periode = %s
               AND a.nb_ventes >= 30 AND b.nb_ventes >= 30"""
    var = {niveau: dict(c.execute(sql, (niveau, DEBUT, FIN)).fetchall()) for niveau in ("region", "departement")}
    paris = dict(c.execute(sql.replace("a.niveau_geo = %s", "a.niveau_geo = %s AND a.code_geo LIKE '751%%'"),
                           ("commune", DEBUT, FIN)).fetchall())
    return {
        "variation_idf_pct": var["region"]["11"],
        "variation_paris_pct": var["departement"]["75"],
        "arrondissements_en_baisse": sum(v < 0 for v in paris.values()),
        "arrondissements_compares": len(paris),
        "departements_en_baisse": sum(v < 0 for v in var["departement"].values()),
        "departements_compares": len(var["departement"]),
        "regions_en_baisse": sum(v < 0 for v in var["region"].values()),
        "regions_comparees": len(var["region"]),
    }


def faits_mongo():
    db = mongo()
    return {
        "annonces_mongo": db.annonces_brutes.count_documents({}),
        "annonces_texte_balcon": db.annonces_brutes.count_documents({"$text": {"$search": "balcon"}}),
    }


def faits_controles():
    """Rejoue les contrôles : le deck n'affiche que des résultats réellement obtenus."""
    py = str(RACINE / ".venv" / "Scripts" / "python")
    check = subprocess.run([py, "db/check.py"], cwd=RACINE, capture_output=True, text=True, encoding="utf-8")
    ok, total = map(int, re.search(r"(\d+)/(\d+) contrôles OK", check.stdout).groups())
    tests = subprocess.run([py, "-m", "pytest", "app/test_app.py", "-q"], cwd=RACINE,
                           capture_output=True, text=True, encoding="utf-8")
    passes = int(re.search(r"(\d+) passed", tests.stdout).group(1))
    if check.returncode or tests.returncode or ok != total:
        raise SystemExit(f"Contrôles en échec : check {ok}/{total}, pytest code {tests.returncode}")
    # check.py recalcule en SQL la médiane de toutes les zones et compte les écarts avec Spark
    ecarts = int(re.search(r"médianes différentes (\d+)", check.stdout).group(1))
    return {"controles_bdd": total, "tests_app": passes, "ecarts_spark_sql": ecarts}


def faits_pipeline():
    """Dernier rapport or/controles du pipeline prix (pipelines/prix, lac local data/lac : même code que sur OVH)."""
    import csv
    parts = sorted((RACINE / "data" / "lac" / "or" / "controles").glob("part-*.csv"))
    if not parts:
        raise SystemExit("rapport du pipeline absent : lancer pipelines/prix (docs/deploiement_ovh.md, section 5)")
    lignes = [r for p in parts for r in csv.DictReader(p.open(encoding="utf-8"))]
    ok = sum(r["ok"].lower() == "true" for r in lignes)
    if ok != len(lignes):
        raise SystemExit(f"pipeline : {len(lignes) - ok} contrôle(s) en échec")
    return {"controles_pipeline": len(lignes)}


# Faits qui ne viennent pas d'une requête : inventaire du dépôt et calendrier du projet.
FAITS_DECLARES = {
    "sources_en_place": 3,           # DVF 2022-2025, geo.api.gouv.fr, annonces Orpi
    "sources_visees": 12,            # sujet v2.1 p.3 : « at least a dozen »
    "sources_palier1": 4,            # socio-éco : revenus, population, DPE, argiles (palier 11/01 – 31/01)
    "sources_restantes": 5,          # 12 - 3 en place - 4 socio-éco (même palier, d'ici le 31/01)
    "seuil_ventes": 30,              # app/carte.py SEUIL_VENTES
    "annee_debut": DEBUT,
    "annee_fin": FIN,
    "annees_dvf": FIN - DEBUT + 1,
    "etapes_sujet": 4,               # sujet v2.1 p.2 : gathering, database, big data, visualizations
    "bases": 2,                      # PostgreSQL + MongoDB
    "echelles": 3,                   # commune, département, région
    "clics_demo": 2,                 # France -> région -> département
    "etapes_pipeline": 3,            # pipelines/prix : bronze->argent, argent->or, contrôles
    "indicateurs_marche": 7,         # médiane, Q1, Q3, D1, D9, prix d'un bien, surface (pipelines/prix/argent_vers_or.py)
    "ecarts_parite": 0,              # pipelines/prix/parite_argent.py, 2026-11-18 : 0 écart sur toutes les ventes
}


def main():
    faits = {**faits_postgres(), **faits_mongo(), **faits_controles(), **faits_pipeline(), **FAITS_DECLARES}
    # Contrôles de cohérence : un fait faux doit casser ici, pas devant le jury
    assert faits["annonces"] == faits["annonces_mongo"], "Postgres et Mongo n'ont pas les mêmes annonces"
    assert faits["ecarts_spark_sql"] == 0, "médianes Spark différentes du recalcul SQL"
    assert faits["ventes_spark"] == faits["ventes_retenues"], "ventes Spark != filtre SQL"
    SORTIE.write_text(json.dumps(faits, indent=2, ensure_ascii=False), encoding="utf-8")
    for k, v in faits.items():
        print(f"{k:28} {v}")
    print(f"\n-> {SORTIE.relative_to(RACINE)}")


if __name__ == "__main__":
    main()
