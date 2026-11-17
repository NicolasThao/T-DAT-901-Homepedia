"""Tests de l'app : python -m pytest app/test_app.py  (bases démarrées, job Spark déjà lancé)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from carte import (DIVERGENTE, GRIS_INSUFFISANT, RAMPE, SEUIL_VENTES, construire_carte,
                   construire_carte_evolution, couleur_evolution, variation)

MAIN = str(Path(__file__).resolve().parent / "main.py")
CARRE = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}


def zone(code, prix, ventes):
    return {"code": code, "nom": code, "geometrie": CARRE, "prix_m2_median": prix, "nb_ventes": ventes}


def test_zone_sous_le_seuil_grisee_et_jamais_coloree():
    zones = [zone(str(i), 1000 + 100 * i, 100) for i in range(10)]
    zones += [zone("rare", 99_999, SEUIL_VENTES - 1), zone("vide", None, 0)]
    _, collection, _ = construire_carte(zones)
    couleurs = {f["properties"]["code"]: f["properties"]["couleur"] for f in collection["features"]}
    assert couleurs["rare"] == GRIS_INSUFFISANT
    assert couleurs["vide"] == GRIS_INSUFFISANT
    significatives = [couleurs[str(i)] for i in range(10)]
    assert set(significatives) <= set(RAMPE)
    assert significatives[0] == RAMPE[0] and significatives[-1] == RAMPE[-1]  # min clair, max foncé


def test_couleur_croissante_avec_le_prix():
    zones = [zone(str(i), 1000 + 100 * i, 100) for i in range(30)]
    _, collection, _ = construire_carte(zones)
    rangs = [RAMPE.index(f["properties"]["couleur"]) for f in collection["features"]]
    assert rangs == sorted(rangs)


def test_peu_de_zones_distinctes():
    # Moins de valeurs distinctes que de classes : pas d'erreur, couleurs de la rampe
    _, collection, _ = construire_carte([zone("a", 3000, 50), zone("b", 3000, 50), zone("c", 5000, 40)])
    assert {f["properties"]["couleur"] for f in collection["features"]} <= set(RAMPE)


@pytest.mark.parametrize("region, departement, attendu_min", [
    (None, None, 17),    # France : régions (Mayotte sans contour de ventes mais affichée)
    ("11", None, 8),     # Île-de-France : ses 8 départements
    ("11", "75", 20),    # Paris : les 20 arrondissements
])
def test_page_carte_a_chaque_echelle(region, departement, attendu_min):
    app = AppTest.from_file(MAIN, default_timeout=120)
    app.session_state["region"] = region
    app.session_state["departement"] = departement
    app.run()
    assert not app.exception, app.exception
    tableau = app.dataframe[0].value
    assert len(tableau) >= attendu_min
    assert tableau["Prix médian (€/m²)"].notna().any()


def test_legende_couvre_les_prix():
    zones = [zone(str(i), 1000 + 100 * i, 100) for i in range(30)]
    _, _, legende = construire_carte(zones)
    assert [c for c, _, _ in legende] == RAMPE
    assert legende[0][1] == 1000 and legende[-1][2] == 3900
    assert all(lo < hi for _, lo, hi in legende)


@pytest.mark.parametrize("niveau, parent, lat, lon, attendu", [
    ("region", None, 48.8584, 2.2945, "11"),          # Tour Eiffel -> Île-de-France
    ("departement", "11", 48.8584, 2.2945, "75"),     # -> Paris
    ("commune", "75", 48.8584, 2.2945, "75107"),      # -> Paris 7e (arrondissement, pas 75056)
    ("departement", "84", 48.8584, 2.2945, None),     # point hors de la région affichée
])
def test_clic_vers_zone(niveau, parent, lat, lon, attendu):
    import donnees
    assert donnees.zone_au_point(niveau, parent, lat, lon) == attendu


# --- Mode évolution ---------------------------------------------------------------------------

def zone_evo(code, debut, fin, ventes_debut=100, ventes_fin=100):
    return {"code": code, "nom": code, "geometrie": CARRE, "prix_debut": debut, "prix_fin": fin,
            "ventes_debut": ventes_debut, "ventes_fin": ventes_fin,
            "serie": [(2022, debut, ventes_debut), (2025, fin, ventes_fin)]}


def test_variation_en_pourcentage():
    assert variation(zone_evo("a", 4000, 4400)) == pytest.approx(10)
    assert variation(zone_evo("b", 4000, 3600)) == pytest.approx(-10)


@pytest.mark.parametrize("ventes_debut, ventes_fin", [(SEUIL_VENTES - 1, 100), (100, SEUIL_VENTES - 1), (0, 0)])
def test_variation_absente_si_une_annee_sous_le_seuil(ventes_debut, ventes_fin):
    z = zone_evo("a", 4000 if ventes_debut else None, 4400 if ventes_fin else None, ventes_debut, ventes_fin)
    assert variation(z) is None
    _, collection, _ = construire_carte_evolution([z])
    assert collection["features"][0]["properties"]["couleur"] is None  # pas de remplissage


def test_couleurs_divergentes():
    assert couleur_evolution(-25) == DIVERGENTE[0]       # forte baisse : bleu foncé
    assert couleur_evolution(0) == DIVERGENTE[3]         # stable : gris neutre au milieu
    assert couleur_evolution(25) == DIVERGENTE[-1]       # forte hausse : rouge foncé
    rangs = [DIVERGENTE.index(couleur_evolution(v)) for v in range(-30, 31)]
    assert rangs == sorted(rangs)


@pytest.mark.parametrize("v, classe", [(-10.01, 0), (-10, 1), (-5.01, 1), (-5, 2), (-2.01, 2), (-2, 3),
                                       (2, 3), (2.01, 4), (5, 4), (5.01, 5), (10, 5), (10.01, 6)])
def test_bornes_conformes_a_la_legende(v, classe):
    # « baisse > 10 % » ne contient pas -10 exact ; « +5 à +10 % » contient +10 (symétrique)
    assert couleur_evolution(v) == DIVERGENTE[classe]


def test_legende_evolution_symetrique():
    _, _, legende = construire_carte_evolution([zone_evo("a", 4000, 4400)])
    assert [c for c, _ in legende] == DIVERGENTE
    assert legende[0][1] == "baisse > 10 %" and legende[-1][1] == "hausse > 10 %"


@pytest.mark.parametrize("region, departement, attendu_min", [(None, None, 17), ("11", None, 8), ("11", "75", 20)])
def test_page_evolution_a_chaque_echelle(region, departement, attendu_min):
    app = AppTest.from_file(MAIN, default_timeout=120)
    app.session_state["region"] = region
    app.session_state["departement"] = departement
    app.session_state["indicateur"] = "Évolution"
    app.run()
    assert not app.exception, app.exception
    tableau = app.dataframe[0].value
    assert len(tableau) >= attendu_min
    assert tableau["Variation (%)"].notna().any()


def test_zones_evolution_choisit_les_annees_sans_modifier_le_cache():
    import donnees
    serie = [{"code": "a", "nom": "a", "geometrie": CARRE, "serie": [(2022, 3000, 50), (2025, 3300, 40)]}]
    z = donnees.zones_evolution(serie, 2022, 2024)[0]
    assert (z["prix_debut"], z["ventes_debut"], z["prix_fin"], z["ventes_fin"]) == (3000, 50, None, 0)
    assert "prix_debut" not in serie[0]  # l'entrée mise en cache par Streamlit n'est pas modifiée
