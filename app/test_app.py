"""Tests de l'app : python -m pytest app/test_app.py  (bases démarrées, job Spark déjà lancé)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from carte import GRIS_INSUFFISANT, RAMPE, SEUIL_VENTES, construire_carte

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
