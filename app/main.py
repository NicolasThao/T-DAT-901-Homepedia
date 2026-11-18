"""
Homepedia — page Carte : prix au m² médian (DVF) et son évolution entre deux années,
région -> département -> commune au clic.

Usage : .venv/Scripts/streamlit run app/main.py   (bases démarrées : docker compose -f db/docker-compose.yml up -d)
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).resolve().parent))
import donnees  # noqa: E402
from carte import (CONTOUR_INSUFFISANT, FRANCE_METROPOLE, GRIS_INSUFFISANT, SEUIL_VENTES,  # noqa: E402
                   construire_carte, construire_carte_evolution, euros, libelle_prix, variation)

ENFANT = {"region": "departement", "departement": "commune"}
LIBELLE_NIVEAU = {"region": "Régions", "departement": "Départements", "commune": "Communes"}
PRIX, EVOLUTION = "Prix au m²", "Évolution"

st.set_page_config(page_title="Homepedia — Carte des prix", layout="wide")

zones_cache = st.cache_data(ttl=3600, show_spinner="Chargement de la carte…")(donnees.zones)
series_cache = st.cache_data(ttl=3600, show_spinner="Chargement de la carte…")(donnees.zones_series)
nom_cache = st.cache_data(ttl=3600)(donnees.nom_zone)
non_localisees_cache = st.cache_data(ttl=3600)(donnees.ventes_non_localisees)
provenance_cache = st.cache_data(ttl=3600)(donnees.provenance)
LIBELLE_SOURCE = {"dvf-ovhcloud": "calculés sur OVHcloud Data Platform", "dvf-lac-local": "calculés par le pipeline en local",
                  "dvf": "calculés par Spark en local"}

# --- Navigation : France (régions) -> une région (départements) -> un département (communes)
st.session_state.setdefault("region", None)
st.session_state.setdefault("departement", None)


def aller(region=None, departement=None):
    st.session_state.region, st.session_state.departement = region, departement


if st.session_state.departement:
    niveau, parent = "commune", st.session_state.departement
elif st.session_state.region:
    niveau, parent = "departement", st.session_state.region
else:
    niveau, parent = "region", None

# --- Filtres
st.title("Prix de l'immobilier en France")
annees = sorted(donnees.periodes())
col_ind, col_type, col_annees = st.columns([2, 3, 3])
indicateur = col_ind.radio("Indicateur", (PRIX, EVOLUTION), horizontal=True, key="indicateur")
type_local = col_type.radio("Type de bien", donnees.TYPES_BIEN, horizontal=True)
if indicateur == PRIX:
    periode = col_annees.selectbox("Année des ventes", annees[::-1])
elif len(annees) < 2:
    st.info("L'évolution demande au moins deux années de ventes chargées (db/load_dvf.py puis le job Spark).")
    st.stop()
else:
    c_debut, c_fin = col_annees.columns(2)
    debut = c_debut.selectbox("De", annees, index=0, key="debut")
    fin = c_fin.selectbox("À", annees, index=len(annees) - 1, key="fin")
    if debut >= fin:
        st.warning("Choisir une année de début antérieure à l'année de fin.")
        st.stop()

# --- Fil d'Ariane
ariane = st.columns([1, 2, 2, 5])
ariane[0].button("France", on_click=aller, disabled=niveau == "region")
if st.session_state.region:
    ariane[1].button(nom_cache("region", st.session_state.region), on_click=aller,
                     args=(st.session_state.region,), disabled=niveau == "departement")
if st.session_state.departement:
    ariane[2].button(nom_cache("departement", st.session_state.departement), disabled=True)

# --- Carte
cadrage = FRANCE_METROPOLE if niveau == "region" else None
if indicateur == PRIX:
    zones = zones_cache(niveau, parent, type_local, periode)
    carte, _, legende = construire_carte(zones, cadrage=cadrage)
else:
    zones = donnees.zones_evolution(series_cache(niveau, parent, type_local), debut, fin)
    carte, _, legende = construire_carte_evolution(zones, cadrage=cadrage)


def case(couleur, texte, pointille=False):
    bord = f"border:1px dashed {CONTOUR_INSUFFISANT}" if pointille else "box-shadow:0 0 0 1px rgba(128,128,128,.4)"
    fond = "transparent" if pointille else couleur
    return (f'<span style="display:inline-flex;align-items:center;gap:6px;margin-right:16px">'
            f'<span style="width:14px;height:14px;border-radius:3px;background:{fond};{bord}"></span>{texte}</span>')


if indicateur == PRIX:
    titre_legende = "Prix médian au m² : "
    cases = [case(c, f"{euros(lo)} – {euros(hi)} €") for c, lo, hi in legende]
    cases.append(case(GRIS_INSUFFISANT, f"moins de {SEUIL_VENTES} ventes"))
else:
    titre_legende = f"Variation du prix médian au m², {debut} → {fin} : "
    cases = [case(c, libelle) for c, libelle in legende]
    cases.append(case(None, f"moins de {SEUIL_VENTES} ventes une des deux années", pointille=True))

col_carte, col_table = st.columns([3, 2])
with col_carte:
    if niveau in ENFANT:
        st.caption(f"{LIBELLE_NIVEAU[niveau]} — cliquer une zone pour voir ses "
                   f"{LIBELLE_NIVEAU[ENFANT[niveau]].lower()}.")
    else:
        st.caption("Communes (arrondissements à Paris, Lyon et Marseille).")
    st.markdown(f'<div style="font-size:0.85rem;line-height:1.9">{titre_legende}{"".join(cases)}</div>',
                unsafe_allow_html=True)
    cle_carte = f"carte-{niveau}-{parent}-{type_local}-" + (str(periode) if indicateur == PRIX else f"{debut}-{fin}")
    sortie = st_folium(carte, key=cle_carte, height=620, use_container_width=True,
                       returned_objects=["last_clicked"])
    # Le composant renvoie le point cliqué (lat, lon) ; PostGIS dit quelle zone affichée le contient
    clic = (sortie or {}).get("last_clicked")
    if clic and niveau in ENFANT:
        code = donnees.zone_au_point(niveau, parent, clic["lat"], clic["lng"])
        if code:
            if niveau == "region":
                aller(region=code)
            else:
                aller(region=st.session_state.region, departement=code)
            st.rerun()

# --- Tableau (mêmes données que la carte), triable et exportable
with col_table:
    if indicateur == PRIX:
        def si_assez(z, cle, f=round):
            return f(z[cle]) if z["nb_ventes"] >= SEUIL_VENTES and z.get(cle) is not None else None
        tableau = pd.DataFrame({
            "Zone": [z["nom"] for z in zones],
            "Code": [z["code"] for z in zones],
            "Prix médian (€/m²)": [si_assez(z, "prix_m2_median") for z in zones],
            "Ventes retenues": [z["nb_ventes"] for z in zones],
            "Q1 (€/m²)": [si_assez(z, "prix_m2_q1") for z in zones],
            "Q3 (€/m²)": [si_assez(z, "prix_m2_q3") for z in zones],
            "Écart D9/D1": [round(z["prix_m2_d9"] / z["prix_m2_d1"], 1) if si_assez(z, "prix_m2_d1") else None
                            for z in zones],
            "Prix médian d'un bien (€)": [si_assez(z, "valeur_mediane", lambda v: round(v, -3)) for z in zones],
            "Surface médiane (m²)": [si_assez(z, "surface_mediane") for z in zones],
            "Statut": ["" if z["nb_ventes"] >= SEUIL_VENTES else libelle_prix(z) for z in zones],
        }).sort_values("Prix médian (€/m²)", ascending=False, na_position="last")
        tableau = tableau.dropna(axis="columns", how="all")
        nom_fichier = f"prix_m2_{niveau}_{parent or 'france'}_{type_local}_{periode}.csv"
    else:
        variations = [variation(z) for z in zones]
        tableau = pd.DataFrame({
            "Zone": [z["nom"] for z in zones],
            "Code": [z["code"] for z in zones],
            f"Prix {debut} (€/m²)": [round(z["prix_debut"]) if v is not None else None
                                     for z, v in zip(zones, variations)],
            f"Prix {fin} (€/m²)": [round(z["prix_fin"]) if v is not None else None
                                   for z, v in zip(zones, variations)],
            "Variation (%)": [round(v, 1) if v is not None else None for v in variations],
            f"Ventes {debut}": [z["ventes_debut"] for z in zones],
            f"Ventes {fin}": [z["ventes_fin"] for z in zones],
        }).sort_values("Variation (%)", ascending=False, na_position="last")
        nom_fichier = f"evolution_prix_m2_{niveau}_{parent or 'france'}_{type_local}_{debut}_{fin}.csv"
    st.dataframe(tableau, hide_index=True, width="stretch", height=560)
    st.download_button("Exporter en CSV", tableau.to_csv(index=False).encode("utf-8"),
                       file_name=nom_fichier, mime="text/csv")

# --- Méthode et limites
annees_texte = str(periode) if indicateur == PRIX else f"{debut} et {fin}"
non_localisees = sum(non_localisees_cache(a) for a in ([periode] if indicateur == PRIX else [debut, fin]))
zones_vides = (f"Zones grisées : moins de {SEUIL_VENTES} ventes." if indicateur == PRIX
               else f"Zones sans couleur : moins de {SEUIL_VENTES} ventes l'une des deux années.")
st.caption(
    f"Source : DVF géolocalisées (DGFiP, Etalab), ventes {annees_texte}. Ventes de marché (Vente, VEFA) "
    f"d'un seul logement, prix entre 200 et 30 000 €/m², médiane calculée par Spark. {zones_vides} "
    f"Absents de DVF : Bas-Rhin, Haut-Rhin, Moselle (Livre foncier), Mayotte. "
    f"{euros(non_localisees)} ventes de communes absentes du référentiel ne sont pas localisées.")
provenances = provenance_cache()
if provenances:
    source, lot, date = provenances[0]
    st.caption(f"Indicateurs {LIBELLE_SOURCE.get(source, source)}"
               + (f", lot {lot}" if lot else "") + (f", le {date.astimezone():%d/%m/%Y à %H:%M}" if date else "") + ".")
