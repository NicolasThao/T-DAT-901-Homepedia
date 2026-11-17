"""
Télécharge DVF géolocalisées (Etalab, data.gouv.fr) pour les années complètes 2022-2025.

Source : https://www.data.gouv.fr/datasets/demandes-de-valeurs-foncieres-geolocalisees/
Fichiers : https://files.data.gouv.fr/geo-dvf/latest/csv/<année>/full.csv.gz -> db/data/dvf/<année>.csv.gz
Rejouable : un fichier déjà présent et de même taille que sur le serveur n'est pas retéléchargé.

Usage : .venv/Scripts/python db/telecharger_dvf.py
"""

import gzip
from pathlib import Path

import requests

ANNEES = (2022, 2023, 2024, 2025)
URL = "https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/full.csv.gz"
DOSSIER = Path(__file__).resolve().parent / "data" / "dvf"
ENTETE = {"User-Agent": "homepedia-etudiant/1.0 (projet academique Epitech)"}


def telecharger(annee):
    url, cible = URL.format(annee=annee), DOSSIER / f"{annee}.csv.gz"
    tete = requests.head(url, headers=ENTETE, timeout=60, allow_redirects=True)
    tete.raise_for_status()
    taille = int(tete.headers["Content-Length"]) if "Content-Length" in tete.headers else None
    if cible.exists() and taille is not None and cible.stat().st_size == taille:
        return cible, taille, "déjà présent"
    partiel = cible.with_suffix(".part")
    with requests.get(url, headers=ENTETE, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(partiel, "wb") as f:
            for bloc in r.iter_content(1 << 20):
                f.write(bloc)
    if taille is not None and partiel.stat().st_size != taille:
        raise SystemExit(f"{annee} : taille reçue {partiel.stat().st_size} != {taille} annoncée")
    partiel.replace(cible)
    return cible, cible.stat().st_size, "téléchargé"


def main():
    DOSSIER.mkdir(parents=True, exist_ok=True)
    for annee in ANNEES:
        cible, taille, etat = telecharger(annee)
        lignes = ""
        if etat == "téléchargé":  # compter coûte une décompression complète : seulement après téléchargement
            with gzip.open(cible, "rt", encoding="utf-8") as f:
                lignes = f"{sum(1 for _ in f) - 1:>10,} lignes".replace(",", " ")  # sans l'en-tête
        print(f"{annee}  {taille / 1e6:6.1f} Mo  {lignes}  {etat}")


if __name__ == "__main__":
    main()
