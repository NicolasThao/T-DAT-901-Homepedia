"""Construction de la carte choroplèthe (Folium), sans dépendance à Streamlit : testable seule."""

import folium
import numpy as np
from branca.colormap import StepColormap

SEUIL_VENTES = 30  # en dessous : zone grisée, jamais colorée ni interpolée (validé 2026-11-13)

# Rampe séquentielle bleue, clair -> foncé (skill dataviz, palette de référence)
RAMPE = ["#b7d3f6", "#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]
GRIS_INSUFFISANT = "#e1e0d9"
BORDURE = "#fcfcfb"
FRANCE_METROPOLE = [[41.3, -5.2], [51.1, 9.6]]


def echelle_couleurs(prix):
    """Classes par quantiles des zones significatives : chaque couleur couvre autant de zones."""
    if not prix:
        return None
    if len(set(prix)) < len(RAMPE):
        bornes = sorted(set(prix)) + [max(prix) + 1]
        couleurs = RAMPE[-(len(bornes) - 1):]
    else:
        bornes = list(np.quantile(prix, np.linspace(0, 1, len(RAMPE) + 1)))
        bornes[-1] += 1  # la valeur max doit tomber dans la dernière classe
        couleurs = RAMPE
    return StepColormap(couleurs, index=bornes, vmin=bornes[0], vmax=bornes[-1])


def classes(echelle):
    """[(couleur, borne basse, borne haute)] pour la légende (affichée hors de la carte)."""
    if echelle is None:
        return []
    b = echelle.index  # la dernière borne a été augmentée de 1 dans echelle_couleurs
    return [(echelle.rgb_hex_str(b[i])[:7], b[i], b[i + 1] - (1 if i == len(b) - 2 else 0))
            for i in range(len(b) - 1)]


def couleur(zone, echelle):
    if zone["nb_ventes"] < SEUIL_VENTES or echelle is None:
        return GRIS_INSUFFISANT
    return echelle(zone["prix_m2_median"])[:7]  # branca renvoie #rrggbbaa


def libelle_prix(zone):
    if zone["nb_ventes"] == 0:
        return "aucune vente retenue"
    if zone["nb_ventes"] < SEUIL_VENTES:
        return f"données insuffisantes (< {SEUIL_VENTES} ventes)"
    return f"{zone['prix_m2_median']:,.0f} €/m²".replace(",", " ")


def euros(x):
    return f"{x:,.0f}".replace(",", " ")


def _style(feature):
    c = feature["properties"]["couleur"]
    if c is None:  # données insuffisantes en mode évolution : pas de remplissage, contour pointillé
        return {"fillOpacity": 0, "color": CONTOUR_INSUFFISANT, "weight": 1, "dashArray": "4 3"}
    return {"fillColor": c, "fillOpacity": 0.85, "color": BORDURE, "weight": 0.8}


def _carte(collection, champs, alias, cadrage):
    # Fond gris neutre sans clé API (les fonds CartoDB en exigent une désormais)
    # keyboard=False : la carte ne prend pas le focus au clic. Sinon, quand elle est à moitié
    # visible, le navigateur fait défiler la page au clic et Leaflet le prend pour un glissement.
    carte = folium.Map(tiles="Esri.WorldGrayCanvas", control_scale=True, zoom_snap=0.25,
                       keyboard=False)
    couche = folium.GeoJson(
        collection, style_function=_style,
        highlight_function=lambda f: {"weight": 2.5, "color": "#0b0b0b"},
        tooltip=folium.GeoJsonTooltip(fields=champs, aliases=alias),
    ).add_to(carte)
    carte.fit_bounds(cadrage or couche.get_bounds())
    return carte


def construire_carte(zones, cadrage=None):
    """Carte des zones. `cadrage` : bornes [[lat, lon], [lat, lon]] ; par défaut, les zones affichées."""
    significatives = [z["prix_m2_median"] for z in zones if z["nb_ventes"] >= SEUIL_VENTES]
    echelle = echelle_couleurs(significatives)

    collection = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": z["geometrie"],
         "properties": {"code": z["code"], "nom": z["nom"], "prix": libelle_prix(z),
                        "ventes": f"{z['nb_ventes']:,}".replace(",", " "),
                        "couleur": couleur(z, echelle)}}
        for z in zones
    ]}
    carte = _carte(collection, ["nom", "prix", "ventes"], ["", "Prix médian", "Ventes retenues"], cadrage)
    return carte, collection, classes(echelle)


# --- Mode évolution : variation du prix médian entre deux années ------------------------------

# Divergente bleu (baisse) <-> rouge (hausse), milieu gris neutre (skill dataviz, palette de
# référence). Chaque bras validé avec validate_palette.js --ordinal (2026-11-14). Le gris du milieu
# est plus foncé que celui de la référence (#f0efec) : sur le fond de carte gris, il disparaissait.
DIVERGENTE = ["#104281", "#2a78d6", "#86b6ef", "#d2d0c8", "#ef9a95", "#e34948", "#a3201f"]
BORNES_EVOLUTION = [-10, -5, -2, 2, 5, 10]  # en %, classes fixes et symétriques autour de 0
CONTOUR_INSUFFISANT = "#8a8984"


def variation(zone):
    """Variation en % entre les deux années, ou None si l'une des deux a moins de SEUIL_VENTES ventes."""
    if min(zone["ventes_debut"], zone["ventes_fin"]) < SEUIL_VENTES:
        return None
    return (zone["prix_fin"] / zone["prix_debut"] - 1) * 100


def couleur_evolution(v):
    """Classes symétriques : < −10, [−10, −5), [−5, −2), [−2, +2], (+2, +5], (+5, +10], > +10 (en %)."""
    if v is None:
        return None
    if -2 <= v <= 2:
        return DIVERGENTE[3]
    if v < 0:  # -12 -> 0, -10 -> 1, -5 -> 2 : une borne appartient à la classe la moins extrême
        return DIVERGENTE[sum(v >= b for b in BORNES_EVOLUTION[:3])]
    return DIVERGENTE[3 + sum(v > b for b in BORNES_EVOLUTION[3:])]  # 5 -> 4, 10 -> 5, 12 -> 6


def classes_evolution():
    """[(couleur, libellé)] dans l'ordre de la légende."""
    b = BORNES_EVOLUTION
    libelles = ([f"baisse > {-b[0]} %"]
                + [f"{b[i]:+d} à {b[i + 1]:+d} %".replace("-", "−") for i in range(len(b) - 1)]
                + [f"hausse > {b[-1]} %"])
    return list(zip(DIVERGENTE, libelles))


def libelle_serie(zone):
    """Prix de chaque année disponible, pour l'infobulle : « 2022 : 3 100 € · 2023 : … »."""
    morceaux = [f"{p} : {euros(prix)} €" if n >= SEUIL_VENTES else f"{p} : —" for p, prix, n in zone["serie"]]
    return " · ".join(morceaux) or "aucune vente retenue"


def construire_carte_evolution(zones, cadrage=None):
    features = []
    for z in zones:
        v = variation(z)
        features.append({"type": "Feature", "geometry": z["geometrie"], "properties": {
            "code": z["code"], "nom": z["nom"], "couleur": couleur_evolution(v),
            "variation": f"{v:+.1f} %".replace("-", "−").replace(".", ",") if v is not None
                         else f"données insuffisantes (< {SEUIL_VENTES} ventes une des deux années)",
            "serie": libelle_serie(z)}})
    collection = {"type": "FeatureCollection", "features": features}
    carte = _carte(collection, ["nom", "variation", "serie"], ["", "Variation", "Prix médian au m²"], cadrage)
    return carte, collection, classes_evolution()
