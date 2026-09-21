"""
Etape 2 du plan scraping Orpi (plans/2026-09-21-t-dat-901-scraping-orpi.md).

Parser des pages annonces Orpi.

Decouverte cle (reconnaissance etape 2) : chaque page annonce embarque
un bloc JSON complet dans l'attribut `data-estate="{...}"` d'un <div
data-component="estate-poi-map">. Ce JSON (75-85 cles selon le type de
bien) contient deja tous les champs utiles a l'etat structure : prix,
surfaces detaillees, DPE/GES en indices numeriques, coordonnees GPS,
description longue redigee par l'agent, informations agence (avec avis
clients textuels), et meme un texte descriptif de la commune et du
departement. C'est beaucoup plus fiable qu'un parsing par classes CSS
(non documentees, utilitaires generiques type Tailwind) ou par regex
sur le texte affiche.

parse_listing(html, url) retourne un dict a plat, pret a etre stocke
en table.
"""

import html as htmlmod
import json
import re


def extract_estate_json(page_html: str) -> dict | None:
    marker = 'data-estate="'
    start = page_html.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = page_html.find('"', start)
    if end == -1:
        return None
    raw = page_html[start:end]
    decoded = htmlmod.unescape(raw)
    try:
        return json.loads(decoded)
    except json.JSONDecodeError:
        return None


def parse_listing(page_html: str, url: str) -> dict:
    estate = extract_estate_json(page_html)
    if estate is None:
        return {"url": url, "extraction_ok": False}

    city = estate.get("city") or {}
    department = estate.get("department") or {}
    region = estate.get("region") or {}
    agency = estate.get("agency") or {}
    reputation = agency.get("reputation") or {}

    return {
        "url": url,
        "extraction_ok": True,
        "id": estate.get("id"),
        "reference": estate.get("reference"),
        "type_bien": estate.get("type"),
        "sous_type": estate.get("subType"),
        "transaction": estate.get("transaction"),
        "prix": estate.get("price"),
        "surface_habitable_m2": estate.get("liveableSurface"),
        "surface_terrain_m2": estate.get("lotSurface"),
        "surface_sejour_m2": estate.get("livingroomSurface"),
        "nb_pieces": estate.get("nbRooms"),
        "nb_chambres": estate.get("nbBedrooms"),
        "nb_salles_de_bain": estate.get("nbWashrooms"),
        "nb_places_parking": estate.get("nbParkingSpaces"),
        "ascenseur": estate.get("elevator"),
        "jardin": estate.get("garden"),
        "garage": estate.get("garage"),
        "piscine": estate.get("swimmingPool"),
        "cave": estate.get("cellar"),
        "grenier": estate.get("attic"),
        "terrasse": estate.get("terrace"),
        "balcon": estate.get("balcony"),
        "acces_handicape": estate.get("disabledAccess"),
        "etat_general": estate.get("generalCondition"),
        "dpe_disponible": estate.get("dpeDisplay"),
        "dpe_classe_conso": estate.get("consumptionIndex"),
        "dpe_classe_emission": estate.get("emissionIndex"),
        "dpe_conso_valeur": estate.get("consumptionValue"),
        "dpe_emission_valeur": estate.get("emissionValue"),
        "dpe_date": estate.get("dpeDate"),
        "description": estate.get("longAd"),
        "date_mise_en_marche": estate.get("onMarketSince"),
        "code_postal": estate.get("zipCode"),
        "commune": city.get("name"),
        "commune_texte": city.get("edito"),
        "departement_code": department.get("id"),
        "departement_nom": department.get("name"),
        "departement_texte": department.get("edito"),
        "region_nom": region.get("name"),
        "longitude": estate.get("longitude"),
        "latitude": estate.get("latitude"),
        "agence_nom": agency.get("name"),
        "agence_telephone": agency.get("phone"),
        "agence_email": agency.get("email"),
        "agence_adresse": " ".join(
            filter(None, [agency.get("address1"), agency.get("zipcode"), agency.get("city")])
        ),
        "agence_note": reputation.get("notation"),
        "agence_nb_avis": reputation.get("votesCount"),
    }


# --- Validation manuelle sur un echantillon varie (>= 10 annonces, plusieurs types) ---
if __name__ == "__main__":
    import time

    import requests

    USER_AGENT = "T-DAT-901-Epitech-bootstrap (usage pedagogique, contact: projet Homepedia Epitech)"

    URLS_VALIDATION = [
        "https://www.orpi.com/annonce-vente-maison-t6-fillinges-74250-7e13c35f-c421-40d6-a849-52240521d13f/",
        "https://www.orpi.com/annonce-vente-appartement-t3-chateau-thierry-02400-caafe383-de16-4694-9e71-31c652ba97f6/",
        "https://www.orpi.com/annonce-vente-terrain-buxerolles-86180-1b4fb6ac-d603-41ba-ab8d-143143574a08/",
        "https://www.orpi.com/annonce-vente-stationnement-soisy-sous-montmorency-95230-518-084032-667/",
        "https://www.orpi.com/annonce-vente-immeuble-t4-valenciennes-59300-f7ba7637-ee0c-4db4-808c-413f8a7462ee/",
        "https://www.orpi.com/annonce-vente-programme-neuf-castelginest-31780-4f4e9190-492b-4b53-a051-327db70185b5/",
        "https://www.orpi.com/annonce-vente-maison-t4-bonne-74380-0c487b0e-8ff8-4904-9e7b-5abac9ab6190/",
        "https://www.orpi.com/annonce-vente-appartement-t4-nice-06100-28741e9b-5c52-433e-8cd1-a99b8fd496a0/",
        "https://www.orpi.com/annonce-vente-maison-t4-chassy-18800-e452466e-a71c-44d3-bf1e-c9089c993f9f/",
        "https://www.orpi.com/annonce-vente-appartement-t3-saint-julien-83560-3e628cc9-92fb-47fa-8f01-c3f23a80764f/",
        "https://www.orpi.com/annonce-vente-terrain-ussac-19270-192778-101034-418/",
        "https://www.orpi.com/annonce-vente-appartement-t2-cannes-06400-da889e3d-8c80-4cd2-8914-e55181640468/",
    ]

    ok, ko = 0, 0
    for i, url in enumerate(URLS_VALIDATION, 1):
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15, allow_redirects=True)
        resp.encoding = resp.apparent_encoding or "utf-8"
        if resp.url != url or resp.status_code != 200:
            print(f"[{i}] MORTE/REDIRIGEE : {url}")
            ko += 1
            time.sleep(1.0)
            continue

        row = parse_listing(resp.text, url)
        if not row["extraction_ok"]:
            print(f"[{i}] ECHEC EXTRACTION : {url}")
            ko += 1
        else:
            ok += 1
            print(
                f"[{i}] OK type={row['type_bien']:14s} prix={row['prix']!s:>10} "
                f"surf_hab={row['surface_habitable_m2']!s:>7} surf_ter={row['surface_terrain_m2']!s:>7} "
                f"pieces={row['nb_pieces']!s:>3} cp={row['code_postal']} commune={row['commune']} "
                f"dpe={row['dpe_classe_conso']}/{row['dpe_classe_emission']} "
                f"desc_len={len(row['description'] or '')} agence={row['agence_nom']!r} "
                f"note={row['agence_note']} avis={row['agence_nb_avis']}"
            )
        time.sleep(1.0)

    print(f"\nTotal : {ok} extractions reussies, {ko} echecs/mortes sur {len(URLS_VALIDATION)}")
