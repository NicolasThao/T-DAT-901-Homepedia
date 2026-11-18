"""
Passerelle entre le poste local et le lac du pipeline prix (bucket OVHcloud Data Platform, ou data/lac en local).

  python db/ovh.py envoyer     bronze : fichiers DVF (db/data/dvf) + référentiel des communes (exporté de la base)
  python db/ovh.py recuperer   or : indicateurs du dernier lot validé -> table indicateurs_prix (l'app lit la base)
  python db/ovh.py etat        contenu du lac par couche
  Option --local : le lac est le dossier data/lac (mêmes chemins que le bucket), pour tester sans OVHcloud.

`recuperer` ne charge un lot que si le rapport or/controles est entièrement PASS et porte sur ce même lot.
Le chargement remplace toute la table en une transaction (rejouable) ; `_source` dit d'où viennent les chiffres.

Accès au bucket (db/.env, cf. db/.env.example ; clés API générées dans l'IAM de Data Platform) :
  OVH_S3_ENDPOINT=https://<projet>.eu.dataplatform.ovh.net/datastore   OVH_BUCKET=homepedia
  OVH_ACCESS_KEY=...   OVH_SECRET_KEY=...
"""

import argparse
import csv
import io
import shutil
import sys
from pathlib import Path

from config import DB_DIR, _env, postgres
from telecharger_dvf import ANNEES, DOSSIER as DOSSIER_DVF

LAC_LOCAL = DB_DIR.parent / "data" / "lac"
SOURCE = {"ovh": "dvf-ovhcloud", "local": "dvf-lac-local"}
COLONNES_OR = ["niveau_geo", "code_geo", "type_local", "periode", "prix_m2_median", "nb_ventes",
               "prix_m2_d1", "prix_m2_q1", "prix_m2_q3", "prix_m2_d9", "valeur_mediane", "surface_mediane",
               "_source", "_date_ingestion", "_batch_id"]
REFERENTIEL = """
    SELECT c.code_insee, c.code_departement, d.code_region
    FROM commune c LEFT JOIN departement d ON d.code_departement = c.code_departement
    ORDER BY c.code_insee"""


class LacLocal:
    def __init__(self, racine=LAC_LOCAL):
        self.racine = racine

    def taille(self, cle):
        f = self.racine / cle
        return f.stat().st_size if f.exists() else None

    def envoyer(self, fichier, cle):
        (self.racine / cle).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fichier, self.racine / cle)

    def lister(self, prefixe):
        base = self.racine / prefixe
        return sorted(str(p.relative_to(self.racine)).replace("\\", "/") for p in base.rglob("*") if p.is_file()) \
            if base.exists() else []

    def lire(self, cle):
        return (self.racine / cle).read_bytes()


class LacOVH:
    def __init__(self):
        import boto3
        from botocore.client import Config
        env = _env()
        manquantes = [k for k in ("OVH_S3_ENDPOINT", "OVH_ACCESS_KEY", "OVH_SECRET_KEY", "OVH_BUCKET") if not env.get(k)]
        if manquantes:
            raise SystemExit(f"db/.env : variables manquantes {manquantes} (cf. db/.env.example)")
        self.bucket = env["OVH_BUCKET"]
        self.s3 = boto3.client(
            "s3", endpoint_url=env["OVH_S3_ENDPOINT"], region_name="forepaas",
            aws_access_key_id=env["OVH_ACCESS_KEY"], aws_secret_access_key=env["OVH_SECRET_KEY"],
            config=Config(signature_version="s3v4", request_checksum_calculation="when_required"))

    def taille(self, cle):
        from botocore.exceptions import ClientError
        try:
            return self.s3.head_object(Bucket=self.bucket, Key=cle)["ContentLength"]
        except ClientError:
            return None

    def envoyer(self, fichier, cle):
        self.s3.upload_file(str(fichier), self.bucket, cle)

    def lister(self, prefixe):
        cles = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefixe):
            cles += [o["Key"] for o in page.get("Contents", [])]
        return sorted(cles)

    def lire(self, cle):
        return self.s3.get_object(Bucket=self.bucket, Key=cle)["Body"].read()


def envoyer(lac):
    export = DB_DIR / "data" / "referentiel_communes.csv"
    export.parent.mkdir(parents=True, exist_ok=True)
    with postgres() as conn, open(export, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code_insee", "code_departement", "code_region"])
        w.writerows(conn.execute(REFERENTIEL))
    fichiers = [(export, "bronze/referentiel/communes.csv")]
    fichiers += [(DOSSIER_DVF / f"{a}.csv.gz", f"bronze/dvf/{a}.csv.gz") for a in ANNEES]
    for fichier, cle in fichiers:
        if not fichier.exists():
            raise SystemExit(f"{fichier} absent : lancer d'abord python db/telecharger_dvf.py")
        if lac.taille(cle) == fichier.stat().st_size and not cle.endswith("communes.csv"):
            print(f"déjà présent   {cle}")
            continue
        lac.envoyer(fichier, cle)
        print(f"envoyé         {cle} ({fichier.stat().st_size / 1e6:.0f} Mo)")


def lire_csv_spark(lac, prefixe):
    """Lignes du CSV écrit par Spark sous `prefixe` (un dossier contenant un ou plusieurs part-*.csv)."""
    parts = [c for c in lac.lister(prefixe + "/") if c.rsplit("/", 1)[-1].startswith("part-") and c.endswith(".csv")]
    if not parts:
        raise SystemExit(f"aucun fichier dans {prefixe}/ : lancer d'abord le pipeline (cf. docs/deploiement_ovh.md)")
    lignes = []
    for p in parts:
        lignes += list(csv.DictReader(io.StringIO(lac.lire(p).decode("utf-8"))))
    return lignes


def recuperer(lac, source):
    rapport = lire_csv_spark(lac, "or/controles")
    echecs = [r["controle"] for r in rapport if r["ok"].lower() != "true"]
    lots_rapport = {r["_batch_id"] for r in rapport}
    indicateurs = lire_csv_spark(lac, "or/indicateurs_prix")
    lots = {r["_batch_id"] for r in indicateurs}
    if echecs or len(lots_rapport) != 1 or lots != lots_rapport:
        raise SystemExit(f"lot refusé : contrôles en échec {echecs}, lot contrôlé {lots_rapport}, lot or {lots}")
    lot = lots.pop()

    buffer = io.StringIO()
    w = csv.writer(buffer)
    for r in indicateurs:
        w.writerow([source if c == "_source" else (r[c] if r[c] != "" else None) for c in COLONNES_OR])
    with postgres() as conn:
        conn.execute((DB_DIR / "postgres" / "schema.sql").read_text(encoding="utf-8"))
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("TRUNCATE indicateurs_prix")
            with cur.copy(f"COPY indicateurs_prix ({', '.join(COLONNES_OR)}) FROM STDIN WITH (FORMAT csv)") as copy:
                copy.write(buffer.getvalue())
            n = cur.execute("SELECT count(*) FROM indicateurs_prix").fetchone()[0]
    print(f"lot {lot} validé ({len(rapport)} contrôles PASS) : {n} indicateurs chargés, _source = {source}")
    print("vérification indépendante : python db/check.py (médianes recalculées en SQL sur les ventes locales)")


def etat(lac):
    for couche in ("bronze", "argent", "or"):
        cles = lac.lister(couche + "/")
        print(f"{couche:7} {len(cles)} fichiers")
        for c in cles[:12]:
            print(f"        {c}")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("commande", choices=["envoyer", "recuperer", "etat"])
    p.add_argument("--local", action="store_true", help="lac = data/lac au lieu du bucket OVHcloud")
    args = p.parse_args()
    lac = LacLocal() if args.local else LacOVH()
    if args.commande == "envoyer":
        envoyer(lac)
    elif args.commande == "recuperer":
        recuperer(lac, SOURCE["local" if args.local else "ovh"])
    else:
        etat(lac)


if __name__ == "__main__":
    sys.exit(main())
