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

    # Fond gris neutre sans clé API (les fonds CartoDB en exigent une désormais)
    # keyboard=False : la carte ne prend pas le focus au clic. Sinon, quand elle est à moitié
    # visible, le navigateur fait défiler la page au clic et Leaflet le prend pour un glissement.
    carte = folium.Map(tiles="Esri.WorldGrayCanvas", control_scale=True, zoom_snap=0.25,
                       keyboard=False)
    couche = folium.GeoJson(
        collection,
        style_function=lambda f: {"fillColor": f["properties"]["couleur"], "fillOpacity": 0.85,
                                  "color": BORDURE, "weight": 0.8},
        highlight_function=lambda f: {"weight": 2.5, "color": "#0b0b0b"},
        tooltip=folium.GeoJsonTooltip(fields=["nom", "prix", "ventes"],
                                      aliases=["", "Prix médian", "Ventes retenues"]),
    ).add_to(carte)
    carte.fit_bounds(cadrage or couche.get_bounds())
    return carte, collection, classes(echelle)
