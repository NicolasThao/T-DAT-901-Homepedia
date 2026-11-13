"""
Homepedia — page Carte : prix au m² médian (DVF), région -> département -> commune au clic.

Usage : .venv/Scripts/streamlit run app/main.py   (bases démarrées : docker compose -f db/docker-compose.yml up -d)
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).resolve().parent))
import donnees  # noqa: E402
from carte import (FRANCE_METROPOLE, GRIS_INSUFFISANT, SEUIL_VENTES,  # noqa: E402
                   construire_carte, libelle_prix)

ENFANT = {"region": "departement", "departement": "commune"}
LIBELLE_NIVEAU = {"region": "Régions", "departement": "Départements", "commune": "Communes"}

st.set_page_config(page_title="Homepedia — Carte des prix", layout="wide")

zones_cache = st.cache_data(ttl=3600, show_spinner="Chargement de la carte…")(donnees.zones)
nom_cache = st.cache_data(ttl=3600)(donnees.nom_zone)

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
col_type, col_periode = st.columns([3, 1])
type_local = col_type.radio("Type de bien", donnees.TYPES_BIEN, horizontal=True)
periode = col_periode.selectbox("Année des ventes", donnees.periodes())

# --- Fil d'Ariane
ariane = st.columns([1, 2, 2, 5])
ariane[0].button("France", on_click=aller, disabled=niveau == "region")
if st.session_state.region:
    ariane[1].button(nom_cache("region", st.session_state.region), on_click=aller,
                     args=(st.session_state.region,), disabled=niveau == "departement")
if st.session_state.departement:
    ariane[2].button(nom_cache("departement", st.session_state.departement), disabled=True)

# --- Carte
zones = zones_cache(niveau, parent, type_local, periode)
carte, _, legende = construire_carte(zones, cadrage=FRANCE_METROPOLE if niveau == "region" else None)


def euros(x):
    return f"{x:,.0f}".replace(",", " ")


def case(couleur, texte):
    return (f'<span style="display:inline-flex;align-items:center;gap:6px;margin-right:16px">'
            f'<span style="width:14px;height:14px;border-radius:3px;background:{couleur};'
            f'box-shadow:0 0 0 1px rgba(128,128,128,.4)"></span>{texte}</span>')

col_carte, col_table = st.columns([3, 2])
with col_carte:
    if niveau in ENFANT:
        st.caption(f"{LIBELLE_NIVEAU[niveau]} — cliquer une zone pour voir ses "
                   f"{LIBELLE_NIVEAU[ENFANT[niveau]].lower()}.")
    else:
        st.caption("Communes (arrondissements à Paris, Lyon et Marseille).")
    st.markdown(
        '<div style="font-size:0.85rem;line-height:1.9">Prix médian au m² : '
        + "".join(case(c, f"{euros(lo)} – {euros(hi)} €") for c, lo, hi in legende)
        + case(GRIS_INSUFFISANT, f"moins de {SEUIL_VENTES} ventes") + "</div>",
        unsafe_allow_html=True)
    sortie = st_folium(carte, key=f"carte-{niveau}-{parent}-{type_local}-{periode}",
                       height=620, use_container_width=True, returned_objects=["last_clicked"])
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

# --- Tableau (même données que la carte), triable et exportable
with col_table:
    tableau = pd.DataFrame({
        "Zone": [z["nom"] for z in zones],
        "Code": [z["code"] for z in zones],
        "Prix médian (€/m²)": [round(z["prix_m2_median"]) if z["nb_ventes"] >= SEUIL_VENTES else None
                               for z in zones],
        "Ventes retenues": [z["nb_ventes"] for z in zones],
        "Statut": ["" if z["nb_ventes"] >= SEUIL_VENTES else libelle_prix(z) for z in zones],
    }).sort_values("Prix médian (€/m²)", ascending=False, na_position="last")
    st.dataframe(tableau, hide_index=True, width="stretch", height=560)
    st.download_button("Exporter en CSV", tableau.to_csv(index=False).encode("utf-8"),
                       file_name=f"prix_m2_{niveau}_{parent or 'france'}_{type_local}_{periode}.csv",
                       mime="text/csv")

# --- Méthode et limites
st.caption(
    f"Source : DVF {periode} (DGFiP). Ventes de marché (Vente, VEFA) d'un seul logement, prix entre "
    f"200 et 30 000 €/m², médiane calculée par Spark. Zones grisées : moins de {SEUIL_VENTES} ventes. "
    f"Absents de DVF : Bas-Rhin, Haut-Rhin, Moselle (Livre foncier), Mayotte. "
    f"{euros(donnees.ventes_non_localisees(periode))} ventes de communes fusionnées depuis ne sont pas "
    f"localisées.")
