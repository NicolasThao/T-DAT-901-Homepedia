"""
Follow-up 2 — captures de l'app (deck + plan B si la démo live plante).

Parcours : France (régions) -> clic Paris -> Île-de-France (départements) -> clic Paris -> arrondissements,
puis le même parcours en mode « Évolution » (années par défaut : la première et la dernière chargées).
Le clic passe par Leaflet (latLngToContainerPoint) : on clique un lieu, pas un pixel deviné.

Usage : app lancée sur http://localhost:8501, puis
        docs/followup2/.venv/Scripts/python docs/followup2/captures.py
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:8501"
SORTIE = Path(__file__).resolve().parent / "captures"
PARIS = (48.8566, 2.3522)


def frame_carte(page):
    """Iframe streamlit-folium qui contient la carte Leaflet."""
    page.wait_for_function("""() => [...document.querySelectorAll('iframe')].some(f => {
        try { return Object.keys(f.contentWindow).some(k => k.startsWith('map_')); } catch (e) { return false; } })""",
                           timeout=60_000)
    for f in page.frames:
        try:
            if f.evaluate("Object.keys(window).some(k => k.startsWith('map_'))"):
                return f
        except Exception:
            continue
    raise RuntimeError("carte Leaflet introuvable")


def attendre_rendu(page):
    page.wait_for_load_state("networkidle")
    page.wait_for_function("!document.querySelector('[data-testid=\"stStatusWidget\"]')", timeout=120_000)
    page.wait_for_timeout(3_000)  # tuiles du fond de carte


def cliquer(page, lat, lon):
    f = frame_carte(page)
    x, y = f.evaluate("""([lat, lon]) => {
        const m = window[Object.keys(window).find(k => k.startsWith('map_'))];
        const p = m.latLngToContainerPoint([lat, lon]), r = m.getContainer().getBoundingClientRect();
        return [r.left + p.x, r.top + p.y]; }""", [lat, lon])
    boite = f.frame_element().bounding_box()
    page.mouse.click(boite["x"] + x, boite["y"] + y)


def capturer(page, nom):
    attendre_rendu(page)
    page.mouse.move(5, 5)  # pas d'infobulle de survol sur la capture
    page.wait_for_timeout(500)
    page.screenshot(path=SORTIE / f"{nom}_app.png")
    frame_carte(page).frame_element().screenshot(path=SORTIE / f"{nom}_carte.png")
    print("capture", nom)


def main():
    SORTIE.mkdir(exist_ok=True)
    with sync_playwright() as p:
        nav = p.chromium.launch(channel="chrome")
        page = nav.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=2)
        page.goto(URL)
        capturer(page, "1_france")
        cliquer(page, *PARIS)
        page.get_by_role("button", name="Île-de-France").wait_for(timeout=60_000)
        capturer(page, "2_ile_de_france")
        cliquer(page, *PARIS)
        page.get_by_role("button", name="Paris").wait_for(timeout=60_000)
        capturer(page, "3_paris")
        page.goto(URL)  # nouvelle session Streamlit : retour à la France
        attendre_rendu(page)
        page.get_by_text("Évolution", exact=True).click()
        capturer(page, "4_evolution_france")
        cliquer(page, *PARIS)
        page.get_by_role("button", name="Île-de-France").wait_for(timeout=60_000)
        attendre_rendu(page)
        cliquer(page, *PARIS)
        page.get_by_role("button", name="Paris").wait_for(timeout=60_000)
        capturer(page, "5_evolution_paris")
        nav.close()


if __name__ == "__main__":
    main()
