"""
Pipeline de collecte :
  - User-Agent identifiable (pas de spoof navigateur)
  - Rate limit (1 req/s + jitter), pas de parallelisme
  - Pas de retry agressif : un echec est logge, pas re-tente en boucle
  - Arret immediat si trop d'echecs consecutifs (signal probable de
    blocage) plutot que d'insister
  - Ecriture incrementale (JSONL, une ligne par annonce) pour ne rien
    perdre en cas d'interruption

Usage :
    python collecte.py --n 500 --seed 42 --out data/listings_raw.jsonl
"""

import argparse
import json
import random
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from parser import parse_listing

USER_AGENT = "T-DAT-901-Epitech-bootstrap (usage pedagogique, contact: projet Homepedia Epitech)"
SITEMAP_URL = "https://www.orpi.com/sitemap-biens-a-vendre-1.xml"
RATE_LIMIT_S = 1.0
JITTER_S = 0.3
MAX_CONSECUTIVE_ERREURS = 10
MARGE_SUR_ECHANTILLONNAGE = 1.2  # compense le taux de pages mortes (~7%)


def charger_urls_sitemap(sitemap_url: str) -> list[str]:
    resp = requests.get(sitemap_url, headers={"User-Agent": USER_AGENT}, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "xml")
    return [loc.text.strip() for loc in soup.find_all("loc")]


def echantillon_aleatoire(urls: list[str], n: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    n_tire = min(int(n * MARGE_SUR_ECHANTILLONNAGE), len(urls))
    return rng.sample(urls, n_tire)


def collecter(urls: list[str], n_cible: int, output_path: Path) -> dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    n_ok, n_mortes, n_echec_extraction, n_erreur_reseau = 0, 0, 0, 0
    consecutives_en_echec = 0

    with output_path.open("a", encoding="utf-8") as f:
        for i, url in enumerate(urls, 1):
            if n_ok >= n_cible:
                print(f"Cible de {n_cible} annonces atteinte, arret.")
                break

            try:
                resp = requests.get(
                    url, headers={"User-Agent": USER_AGENT}, timeout=15, allow_redirects=True
                )
                resp.encoding = resp.apparent_encoding or "utf-8"
            except requests.RequestException as e:
                print(f"[{i}] ERREUR RESEAU {url} -> {e}")
                n_erreur_reseau += 1
                consecutives_en_echec += 1
            else:
                if resp.status_code != 200 or resp.url != url:
                    print(f"[{i}] MORTE/REDIRIGEE {url}")
                    n_mortes += 1
                    consecutives_en_echec += 1
                else:
                    row = parse_listing(resp.text, url)
                    if not row["extraction_ok"]:
                        print(f"[{i}] ECHEC EXTRACTION {url}")
                        n_echec_extraction += 1
                        consecutives_en_echec += 1
                    else:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
                        f.flush()
                        n_ok += 1
                        consecutives_en_echec = 0
                        print(f"[{i}] OK ({n_ok}/{n_cible}) {row['type_bien']} {row['code_postal']}")

            if consecutives_en_echec >= MAX_CONSECUTIVE_ERREURS:
                print(
                    f"\nARRET : {consecutives_en_echec} echecs consecutifs — "
                    "signal probable de blocage, on ne force pas."
                )
                break

            time.sleep(RATE_LIMIT_S + random.uniform(0, JITTER_S))

    return {
        "n_ok": n_ok,
        "n_mortes": n_mortes,
        "n_echec_extraction": n_echec_extraction,
        "n_erreur_reseau": n_erreur_reseau,
        "n_teste": n_ok + n_mortes + n_echec_extraction + n_erreur_reseau,
    }


def main() -> None:
    parser_cli = argparse.ArgumentParser()
    parser_cli.add_argument("--n", type=int, default=500, help="nombre d'annonces valides visees")
    parser_cli.add_argument("--seed", type=int, default=42)
    parser_cli.add_argument("--out", type=str, default="data/listings_raw.jsonl")
    args = parser_cli.parse_args()

    output_path = Path(__file__).parent / args.out

    print(f"Chargement du sitemap {SITEMAP_URL} ...")
    urls = charger_urls_sitemap(SITEMAP_URL)
    print(f"{len(urls)} URLs disponibles.")

    echantillon = echantillon_aleatoire(urls, args.n, args.seed)
    print(f"Echantillon tire (avec marge x{MARGE_SUR_ECHANTILLONNAGE}) : {len(echantillon)} URLs")
    print(f"Sortie : {output_path}\n")

    stats = collecter(echantillon, args.n, output_path)

    print("\n" + "=" * 50)
    print("BILAN DE COLLECTE")
    print("=" * 50)
    for k, v in stats.items():
        print(f"  {k:20s} {v}")


if __name__ == "__main__":
    main()
