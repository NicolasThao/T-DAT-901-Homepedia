"""
Etape 1 du plan scraping Orpi (plans/2026-09-21-t-dat-901-scraping-orpi.md).

Verifie sur un echantillon elargi et stratifie (type de bien + departement) :
  - le taux de pages mortes/redirigees dans le sitemap officiel des ventes
  - la presence et la longueur d'un texte descriptif libre (source textuelle)
  - la presence de caracteristiques detaillees (DPE, etage, chauffage...)

Respecte le robots.txt d'Orpi : les pages /annonce-vente-* ne sont pas
dans la liste des Disallow. User-Agent honnete et identifiable, rythme
de requetes volontairement lent (1 req/s) pour un simple echantillon
de reconnaissance.
"""

import random
import re
import time
from collections import Counter, defaultdict

import requests
from bs4 import BeautifulSoup

USER_AGENT = "T-DAT-901-Epitech-bootstrap (usage pedagogique, contact: projet Homepedia Epitech)"
SITEMAP_URL = "https://www.orpi.com/sitemap-biens-a-vendre-1.xml"
SAMPLE_SIZE = 30
REQUEST_DELAY_S = 1.0

URL_PATTERN = re.compile(r"annonce-vente-(?P<type>[a-z]+)-")

CARACTERISTIQUES_MOTS_CLES = [
    "DPE", "diagnostic de performance", "classe énergie", "classe energie",
    "GES", "chauffage", "étage", "etage", "année de construction",
    "annee de construction", "exposition", "ascenseur",
]


def charger_urls_sitemap(sitemap_url: str) -> list[str]:
    resp = requests.get(sitemap_url, headers={"User-Agent": USER_AGENT}, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "xml")
    return [loc.text.strip() for loc in soup.find_all("loc")]


def echantillonner(urls: list[str], n: int, seed: int = 42) -> list[str]:
    par_type: dict[str, list[str]] = defaultdict(list)
    for u in urls:
        m = URL_PATTERN.search(u)
        type_bien = m.group("type") if m else "inconnu"
        par_type[type_bien].append(u)

    print("Repartition des types dans le sitemap complet :")
    for t, lst in sorted(par_type.items(), key=lambda kv: -len(kv[1])):
        print(f"  {t:15s} {len(lst)}")

    rng = random.Random(seed)
    types_principaux = [t for t in par_type if t != "inconnu"]
    echantillon: list[str] = []
    par_type_restant = {t: list(v) for t, v in par_type.items()}
    i = 0
    while len(echantillon) < n and any(par_type_restant.values()):
        t = types_principaux[i % len(types_principaux)]
        if par_type_restant.get(t):
            pick = rng.choice(par_type_restant[t])
            par_type_restant[t].remove(pick)
            echantillon.append(pick)
        i += 1
    return echantillon


def analyser_page(url: str) -> dict:
    resp = requests.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=15, allow_redirects=True
    )
    resp.encoding = resp.apparent_encoding or "utf-8"
    result = {
        "url": url,
        "status": resp.status_code,
        "redirige": resp.url != url,
        "url_finale": resp.url,
    }
    if resp.status_code != 200 or result["redirige"]:
        result["vivante"] = False
        return result

    result["vivante"] = True
    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    texte = soup.get_text(separator=" | ", strip=True)

    # Recherche de blocs de texte "prose" (paragraphe descriptif) : on
    # prend les blocs texte de plus de 200 caracteres sans "|" trop frequent
    blocs = [b.strip() for b in texte.split("|") if len(b.strip()) > 200]
    result["a_description_longue"] = len(blocs) > 0
    result["longueur_description_max"] = max((len(b) for b in blocs), default=0)
    result["extrait_description"] = blocs[0][:180] if blocs else ""

    texte_lower = texte.lower()
    result["caracteristiques_trouvees"] = [
        m for m in CARACTERISTIQUES_MOTS_CLES if m.lower() in texte_lower
    ]

    prix_match = re.search(r"([\d\s]{3,})\s*&?nbsp;?€", resp.text)
    result["a_prix"] = bool(prix_match) or "€" in texte

    return result


def main() -> None:
    print(f"Chargement du sitemap {SITEMAP_URL} ...")
    urls = charger_urls_sitemap(SITEMAP_URL)
    print(f"{len(urls)} URLs trouvees dans le sitemap.\n")

    echantillon = echantillonner(urls, SAMPLE_SIZE)
    print(f"\nEchantillon retenu : {len(echantillon)} URLs\n")

    resultats = []
    for i, url in enumerate(echantillon, 1):
        print(f"[{i}/{len(echantillon)}] {url}")
        try:
            r = analyser_page(url)
        except requests.RequestException as e:
            r = {"url": url, "status": None, "erreur": str(e), "vivante": False}
        resultats.append(r)
        time.sleep(REQUEST_DELAY_S)

    vivantes = [r for r in resultats if r.get("vivante")]
    mortes = [r for r in resultats if not r.get("vivante")]

    print("\n" + "=" * 60)
    print("RAPPORT")
    print("=" * 60)
    print(f"Total teste            : {len(resultats)}")
    print(f"Pages vivantes (200, pas de redirection) : {len(vivantes)}")
    print(f"Pages mortes/redirigees : {len(mortes)}")
    for r in mortes:
        print(f"  - MORTE: {r['url']} -> status={r.get('status')} redirige={r.get('redirige')}")

    avec_desc = [r for r in vivantes if r.get("a_description_longue")]
    print(f"\nPages vivantes avec un bloc de texte > 200 caracteres : {len(avec_desc)}/{len(vivantes)}")
    if avec_desc:
        longueurs = [r["longueur_description_max"] for r in avec_desc]
        print(f"  Longueur min/moy/max du plus long bloc : {min(longueurs)}/{sum(longueurs)//len(longueurs)}/{max(longueurs)}")
        print(f"  Exemple : {avec_desc[0]['extrait_description']!r}")

    compteur_carac = Counter()
    for r in vivantes:
        compteur_carac.update(r.get("caracteristiques_trouvees", []))
    print(f"\nCaracteristiques detectees (sur {len(vivantes)} pages vivantes) :")
    for mot, n in compteur_carac.most_common():
        print(f"  {mot:30s} {n}")

    avec_prix = sum(1 for r in vivantes if r.get("a_prix"))
    print(f"\nPages avec un prix detecte : {avec_prix}/{len(vivantes)}")


if __name__ == "__main__":
    main()
