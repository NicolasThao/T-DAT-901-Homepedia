"""
Étape 4 — Charge dans MongoDB les annonces Orpi brutes (collection annonces_brutes).
Prérequis : python db/load_postgres.py (le code INSEE résolu est lu dans la table annonce).

Un document = une annonce telle que scrapée + le lien avec PostgreSQL :
  _id = annonce_id = annonce.id_orpi, code_insee = code INSEE résolu côté PostgreSQL.
Le téléphone et l'e-mail de l'agence ne sont pas chargés (même règle que PostgreSQL).
Le champ nlp est vide : il recevra le sentiment et les thèmes, sans changer la structure.

Rejouable : remplacement par _id (upsert), les index sont recréés sans effet s'ils existent.

Usage : python db/load_mongo.py
"""

import json

import pymongo

from config import mongo, postgres
from load_postgres import ORPI_JSONL

COLLECTION = "annonces_brutes"
CHAMPS_NON_CHARGES = {"agence_telephone", "agence_email"}


def lire_annonces():
    with open(ORPI_JSONL, encoding="utf-8") as f:
        return [json.loads(ligne) for ligne in f if ligne.strip()]


def code_insee_par_annonce():
    with postgres() as conn:
        return dict(conn.execute("SELECT id_orpi, code_insee FROM annonce").fetchall())


def main():
    annonces = lire_annonces()
    codes = code_insee_par_annonce()
    manquantes = [a["id"] for a in annonces if a["id"] not in codes]
    if manquantes:
        raise SystemExit(f"{len(manquantes)} annonces absentes de PostgreSQL : lancer db/load_postgres.py")

    documents = [
        {
            "_id": a["id"],
            "annonce_id": a["id"],
            "code_insee": codes[a["id"]],
            **{k: v for k, v in a.items() if k not in CHAMPS_NON_CHARGES | {"id"}},
            "nlp": None,
        }
        for a in annonces
    ]

    collection = mongo()[COLLECTION]
    collection.bulk_write([pymongo.ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in documents])
    collection.create_index("code_insee")
    collection.create_index([("description", pymongo.TEXT)], default_language="french", name="texte_description")
    print(f"Mongo : {len(documents)} annonces dans {COLLECTION}, "
          f"{sum(d['code_insee'] is None for d in documents)} sans code INSEE")


if __name__ == "__main__":
    main()
