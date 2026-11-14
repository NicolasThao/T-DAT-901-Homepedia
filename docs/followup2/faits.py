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
            "dvf_codes_fusionnes": un(c, """SELECT count(DISTINCT code_insee_source)
                                            FROM mutation_dvf WHERE code_insee IS NULL"""),
            "ventes_retenues": un(c, f"SELECT count(*) FROM mutation_dvf WHERE code_insee IS NOT NULL AND {FILTRE_VENTES}"),
            "indicateurs_lignes": un(c, "SELECT count(*) FROM indicateurs_prix"),
            "regions": un(c, "SELECT count(*) FROM region"),
            "departements": un(c, "SELECT count(*) FROM departement"),
            "communes": un(c, "SELECT count(*) FROM commune WHERE type = 'commune-actuelle'"),
            "arrondissements": un(c, "SELECT count(*) FROM commune WHERE type = 'arrondissement-municipal'"),
            "communes_avec_prix": un(c, """SELECT count(*) FROM indicateurs_prix
                                          WHERE niveau_geo = 'commune' AND type_local = 'Tous'"""),
            "communes_fiables": un(c, """SELECT count(*) FROM indicateurs_prix
                                        WHERE niveau_geo = 'commune' AND type_local = 'Tous' AND nb_ventes >= 30"""),
            "annonces": un(c, "SELECT count(*) FROM annonce"),
            "agences": un(c, "SELECT count(*) FROM agence"),
            "annonces_sans_commune": un(c, "SELECT count(*) FROM annonce WHERE code_insee IS NULL"),
        }
        # Repères de démo (médianes du job Spark, type « Tous » sauf mention)
        rep = """SELECT round(prix_m2_median)::int FROM indicateurs_prix
                 WHERE niveau_geo = %s AND code_geo = %s AND type_local = %s"""
        f["prix_france_idf"] = un(c, rep, ("region", "11", "Tous"))
        f["prix_paris_6e_appart"] = un(c, rep, ("commune", "75106", "Appartement"))
        f["prix_paris"] = un(c, rep, ("departement", "75", "Tous"))
        f["ventes_spark"] = un(c, """SELECT sum(nb_ventes) FROM indicateurs_prix
                                    WHERE niveau_geo = 'region' AND type_local = 'Tous'""")
    return f


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


# Faits qui ne viennent pas d'une requête : inventaire du dépôt et calendrier du projet.
FAITS_DECLARES = {
    "sources_en_place": 3,           # DVF 2022, geo.api.gouv.fr, annonces Orpi
    "sources_visees": 12,            # sujet v2.1 p.3 : « at least a dozen »
    "sources_palier1": 4,            # revenus, population, DPE, argiles (feuille de route, d'ici le 13/12)
    "sources_restantes": 5,          # 12 - 3 en place - 4 du palier 1 (d'ici le 31/01)
    "seuil_ventes": 30,              # app/carte.py SEUIL_VENTES
    "annee_dvf": 2022,
    "etapes_sujet": 4,               # sujet v2.1 p.2 : gathering, database, big data, visualizations
    "bases": 2,                      # PostgreSQL + MongoDB
    "echelles": 3,                   # commune, département, région
    "clics_demo": 2,                 # France -> région -> département
}


def main():
    faits = {**faits_postgres(), **faits_mongo(), **faits_controles(), **FAITS_DECLARES}
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
