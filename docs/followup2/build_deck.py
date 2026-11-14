"""
Follow-up 2 — génère Homepedia_Follow-up_2.pptx à partir de faits.json et des captures.

DA reprise du sujet (homepedia-project.pdf) : bleu Epitech, blanc, accent orange, titres condensés.
Règles : ~25 mots visibles par slide, détail dans les notes, un visuel par slide, aucun coin arrondi.

Usage : docs/followup2/.venv/Scripts/python docs/followup2/build_deck.py
"""

import json
from pathlib import Path

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

ICI = Path(__file__).resolve().parent
F = json.loads((ICI / "faits.json").read_text(encoding="utf-8"))
SORTIE = ICI / "Homepedia_Follow-up_2.pptx"

BLEU = RGBColor(0x00, 0x33, 0xFF)
BLEU_CLAIR = RGBColor(0x7B, 0x9D, 0xFF)
BLEU_PALE = RGBColor(0xDC, 0xE4, 0xFF)
ORANGE = RGBColor(0xFF, 0x55, 0x33)
VERT = RGBColor(0x2E, 0xE6, 0xA6)
BLANC = RGBColor(0xFF, 0xFF, 0xFF)
ENCRE = RGBColor(0x0B, 0x10, 0x20)
GRIS = RGBColor(0x4A, 0x52, 0x66)
FILET = RGBColor(0xD5, 0xDA, 0xE6)
# Dégradé de la carte de l'app (clair = moins cher), pour la mini-légende de la slide démo
DEGRADE = [RGBColor(0xC6, 0xDB, 0xF7), RGBColor(0x93, 0xBD, 0xEF), RGBColor(0x6B, 0xA5, 0xE7),
           RGBColor(0x45, 0x8B, 0xDB), RGBColor(0x2E, 0x5B, 0x9E)]

TITRE = "Bahnschrift SemiBold Condensed"
CORPS = "Bahnschrift"
LEGER = "Bahnschrift Light"

L, H = Inches(13.333), Inches(7.5)
MARGE = Inches(0.8)
LARGEUR = L - 2 * MARGE


def n(x):
    """Nombre au format français (espace insécable fine pour les milliers)."""
    return f"{x:,}".replace(",", " ")


# --- Primitives ------------------------------------------------------------------------------

def fond(slide, couleur):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = couleur


def texte(slide, x, y, w, h, contenu, taille=18, police=CORPS, couleur=ENCRE, align=PP_ALIGN.LEFT,
          ancre=MSO_ANCHOR.TOP, interligne=1.0):
    """Zone de texte. `contenu` : str, ou liste de lignes, ou liste de [(texte, {style})] par ligne."""
    tb = slide.shapes.add_textbox(*map(int, (x, y, w, h)))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = ancre
    lignes = contenu if isinstance(contenu, list) else [contenu]
    for i, ligne in enumerate(lignes):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = interligne
        morceaux = ligne if isinstance(ligne, list) else [(ligne, {})]
        for t, style in morceaux:
            r = p.add_run()
            r.text = t.replace(" :", " :").replace(" ?", " ?")  # typographie française
            r.font.name = style.get("police", police)
            r.font.size = Pt(style.get("taille", taille))
            r.font.color.rgb = style.get("couleur", couleur)
            r.font.bold = False
    return tb


def sans_effet(forme):
    """Supprime ombre et effets hérités du thème (rendu plat)."""
    spPr = forme._element.spPr
    if spPr.find(qn("a:effectLst")) is None:
        etree.SubElement(spPr, qn("a:effectLst"))


def rect(slide, x, y, w, h, remplissage=None, contour=None, epaisseur=1.0):
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, *map(int, (x, y, w, h)))
    if remplissage is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.rgb = remplissage
    if contour is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = contour
        s.line.width = Pt(epaisseur)
    s.shadow.inherit = False
    return s


def trait(slide, x1, y1, x2, y2, couleur=FILET, epaisseur=1.0):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, *map(int, (x1, y1, x2, y2)))
    c.line.color.rgb = couleur
    c.line.width = Pt(epaisseur)
    sans_effet(c)
    return c


def image(slide, chemin, x, y, w, h, cadre=True):
    """Image ajustée dans la boîte (x, y, w, h) sans déformation, calée en haut à gauche."""
    iw, ih = Image.open(chemin).size
    echelle = min(w / iw, h / ih)
    pic = slide.shapes.add_picture(str(chemin), int(x), int(y), int(iw * echelle), int(ih * echelle))
    if cadre:
        rect(slide, pic.left, pic.top, pic.width, pic.height, contour=FILET, epaisseur=0.75)
    return pic


def notes(slide, contenu):
    slide.notes_slide.notes_text_frame.text = contenu.strip()


def rubrique(slide, numero, libelle, sombre=False):
    texte(slide, MARGE, Inches(0.5), Inches(8), Inches(0.4),
          [[(f"{numero:02d}", {"couleur": BLANC if sombre else ORANGE}), (f"   {libelle.upper()}", {})]],
          taille=16, police=CORPS, couleur=BLANC if sombre else BLEU).name = "chrome rubrique"


def entete(slide, numero, libelle, titre, sombre=False):
    """Rubrique (numéro de slide + section) + titre-assertion sur une ligne."""
    rubrique(slide, numero, libelle, sombre)
    texte(slide, MARGE, Inches(0.95), LARGEUR, Inches(1.3), titre, taille=40, police=TITRE,
          couleur=BLANC if sombre else ENCRE, interligne=0.9)
    pied(slide, sombre)


def pied(slide, sombre=False):
    texte(slide, MARGE, H - Inches(0.55), Inches(6), Inches(0.3), "HOMEPEDIA_  ·  Follow-up 2",
          taille=12, police=CORPS, couleur=BLANC if sombre else GRIS).name = "chrome pied"


def carres_deco(slide):
    """Les deux carrés bleu clair du sujet, en haut à droite."""
    rect(slide, L - Inches(1.6), 0, Inches(1.6), Inches(1.6), remplissage=BLEU_CLAIR)
    rect(slide, L - Inches(3.2), Inches(1.6), Inches(1.6), Inches(1.6), remplissage=BLEU_CLAIR)


def soulignement(slide, x, y, couleur=ORANGE):
    rect(slide, x, y, Inches(0.55), Inches(0.1), remplissage=couleur)


# --- Slides --------------------------------------------------------------------------------

def s01_titre(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fond(s, BLEU)
    carres_deco(s)
    texte(s, MARGE, Inches(2.5), Inches(10), Inches(1.6), [[("HOMEPEDIA", {}), ("_", {"couleur": ORANGE})]],
          taille=110, police=TITRE, couleur=BLANC)
    texte(s, MARGE, Inches(4.25), Inches(10), Inches(0.5),
          [[("< ", {"couleur": VERT}), ("EXPLORING HOUSING INSIGHTS", {}), (" />", {"couleur": VERT})]],
          taille=22, police=LEGER, couleur=BLANC)
    texte(s, MARGE, Inches(6.2), Inches(8), Inches(0.4), "Follow-up 2  ·  20 novembre 2026  ·  T-DAT-901",
          taille=16, police=CORPS, couleur=BLANC)
    notes(s, """
Bonjour. Point d'avancement Homepedia, deuxième follow-up.
Plan : où en est-on sur les 4 étapes obligatoires du sujet, ce qui tourne déjà (avec une démo live
de l'application), la plateforme cloud où Spark va tourner (OVHcloud Data Platform), puis la feuille
de route jusqu'au rendu du 7 février 2027.
""")


def s02_etapes(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fond(s, BLANC)
    entete(s, 2, "Où on en est", f"Les {F['etapes_sujet']} étapes du sujet tournent déjà de bout en bout")
    colonnes = [
        ("COLLECTE", f"{F['sources_en_place']} sources chargées"),
        ("BASES DE DONNÉES", "PostgreSQL + MongoDB"),
        ("BIG DATA", "Médianes par Spark"),
        ("VISUALISATION", f"Carte sur {F['echelles']} échelles"),
    ]
    gap = Inches(0.4)
    w = (LARGEUR - 3 * gap) / 4
    for i, (etape, etat) in enumerate(colonnes):
        x = MARGE + i * (w + gap)
        rect(s, x, Inches(3.0), w, Inches(0.09), remplissage=BLEU)
        texte(s, x, Inches(3.35), w, Inches(0.7), etape, taille=30, police=TITRE)
        texte(s, x, Inches(4.15), w, Inches(1.0), etat, taille=22, police=LEGER, couleur=GRIS)
    notes(s, f"""
Le sujet impose 4 étapes : collecte, organisation en bases, analyse big data, visualisation interactive.
Chacune a déjà une brique qui fonctionne de bout en bout, de la donnée brute jusqu'à l'écran.
- Collecte : DVF 2022 (ventes réelles, DGFiP), référentiel géographique geo.api.gouv.fr, {F['annonces']} annonces Orpi.
- Bases : PostgreSQL/PostGIS pour le tabulaire et le spatial, MongoDB pour le texte des annonces.
- Big data : un job Spark calcule les prix médians, recontrôlé en SQL.
- Visualisation : application Streamlit, carte région → département → commune.
La suite consiste à élargir chaque brique : plus de sources, l'analyse de texte, Spark sur OVHcloud Data Platform.
""")


def s03_sources(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fond(s, BLANC)
    entete(s, 3, "Collecte", f"{F['sources_en_place']} sources chargées, {F['sources_visees']} au rendu")
    en_place = ["Ventes DVF", "Référentiel géo", "Annonces Orpi"]
    palier1 = ["Revenus INSEE", "Population INSEE", "DPE ADEME", "Risque argiles"]
    assert len(palier1) == F["sources_palier1"]
    gap = Inches(0.25)
    cw, ch = (LARGEUR - 3 * gap) / 4, Inches(1.25)
    cases = ([(nom, BLEU, BLANC) for nom in en_place] + [(nom, BLEU_PALE, ENCRE) for nom in palier1])
    for i, (nom, fond_case, encre) in enumerate(cases):
        ligne, col = divmod(i, 4)
        x, y = MARGE + col * (cw + gap), Inches(2.5) + ligne * (ch + gap)
        rect(s, x, y, cw, ch, remplissage=fond_case)
        texte(s, x + Inches(0.25), y, cw - Inches(0.5), ch, nom, taille=24, police=TITRE, couleur=encre,
              ancre=MSO_ANCHOR.MIDDLE)
    # 8e case : les sources restantes, sans cases vides
    x, y = MARGE + 3 * (cw + gap), Inches(2.5) + ch + gap
    rect(s, x, y, cw, ch, contour=BLEU, epaisseur=1.5)
    texte(s, x + Inches(0.25), y, cw - Inches(0.5), ch,
          f"+{F['sources_restantes']} sources", taille=28, couleur=BLEU,
          police=TITRE, ancre=MSO_ANCHOR.MIDDLE)
    y_leg = Inches(5.55)
    for j, (style, libelle) in enumerate([((BLEU, None), "chargées en base"), ((BLEU_PALE, None), "d'ici le 13/12"),
                                          ((None, BLEU), "d'ici le 31/01")]):
        x = MARGE + j * Inches(3.0)
        rect(s, x, y_leg + Inches(0.06), Inches(0.22), Inches(0.22), remplissage=style[0], contour=style[1])
        texte(s, x + Inches(0.35), y_leg, Inches(2.6), Inches(0.4), libelle, taille=16, couleur=GRIS)
    notes(s, f"""
Le sujet demande au moins une douzaine de sources, dont une textuelle.
En place et chargées en base :
1. DVF 2022 (Demandes de Valeurs Foncières, DGFiP) : {n(F['dvf_lignes_csv'])} lignes, toutes les ventes immobilières de l'année.
2. Référentiel géographique geo.api.gouv.fr : {F['regions']} régions, {F['departements']} départements, {n(F['communes'])} communes et leurs contours.
3. Annonces Orpi : {F['annonces']} annonces de vente collectées par scraping (robots.txt respecté, 1 requête par seconde),
   avec la description en texte libre — c'est notre source textuelle.
D'ici le 13/12, {F['sources_palier1']} sources en open data, reliées par le code INSEE de la commune : revenus (INSEE Filosofi),
population, diagnostics énergétiques (ADEME), risque retrait-gonflement des argiles (Géorisques — répond à la
question du sujet sur le risque climatique à 15 ans).
D'ici le 31/01, {F['sources_restantes']} de plus pour atteindre {F['sources_visees']} : établissements scolaires, gares, chômage localisé (INSEE),
Base Adresse Nationale, et une source d'avis textuels.
""")


def s04_bases(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fond(s, BLANC)
    entete(s, 4, "Bases de données", f"{F['bases']} bases reliées par le code INSEE")
    bw, bh, y = Inches(4.6), Inches(3.1), Inches(2.6)
    x_g, x_d = MARGE, L - MARGE - bw
    for x, nom, role, contenu in [
        (x_g, "PostgreSQL + PostGIS", "RELATIONNEL", ["Référentiel géographique", "Ventes DVF", "Annonces structurées"]),
        (x_d, "MongoDB", "DOCUMENTS", ["Annonces brutes", "Texte libre indexé"]),
    ]:
        rect(s, x, y, bw, bh, contour=ENCRE, epaisseur=1.25)
        rect(s, x, y, bw, Inches(0.09), remplissage=BLEU)
        texte(s, x + Inches(0.35), y + Inches(0.35), bw, Inches(0.3), role, taille=14, couleur=ORANGE)
        texte(s, x + Inches(0.35), y + Inches(0.7), bw - Inches(0.5), Inches(0.6), nom, taille=30, police=TITRE)
        texte(s, x + Inches(0.35), y + Inches(1.5), bw - Inches(0.5), Inches(1.5), contenu, taille=19,
              police=LEGER, couleur=GRIS, interligne=1.2)
    ym = y + bh / 2
    trait(s, x_g + bw, ym, x_d, ym, couleur=BLEU, epaisseur=2.5)
    texte(s, x_g + bw, ym - Inches(0.6), x_d - x_g - bw, Inches(0.45), "code INSEE", taille=24,
          police=TITRE, couleur=BLEU, align=PP_ALIGN.CENTER)
    notes(s, f"""
Le sujet impose une base relationnelle ET une base non relationnelle : on a choisi selon la nature de la donnée.
- PostgreSQL + PostGIS : référentiel géographique (hiérarchie région → département → commune, contours),
  {n(F['dvf_mutations'])} actes de vente DVF, et les champs structurés des annonces (prix, surface, DPE, position).
  Index B-tree sur les clés de jointure, index spatiaux GiST sur les géométries.
- MongoDB : l'annonce brute telle que scrapée, dont la description. Structure variable, index plein texte
  (ex. « balcon » renvoie {F['annonces_texte_balcon']} annonces), et un champ réservé au résultat de l'analyse de sentiment.
Le pivot entre toutes les sources est le code INSEE de la commune (5 caractères, pas le code postal,
qui peut couvrir plusieurs communes). Chaque annonce existe des deux côtés avec le même identifiant, sans doublon de contenu.
Le schéma complet est documenté dans docs/schema_bdd.md.
""")


def s05_nettoyage(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fond(s, BLEU)
    entete(s, 5, "Nettoyage", "Lignes regroupées par vente, aucune perdue", sombre=True)
    y = Inches(3.0)
    texte(s, MARGE, y, Inches(5.0), Inches(1.4), n(F["dvf_lignes_csv"]), taille=80, police=TITRE, couleur=BLANC)
    texte(s, MARGE, y + Inches(1.45), Inches(5.0), Inches(0.5), "lignes du fichier DVF", taille=20,
          police=LEGER, couleur=BLANC)
    texte(s, MARGE + Inches(4.9), y - Inches(0.25), Inches(1.9), Inches(0.4), "regroupées", taille=18,
          police=CORPS, couleur=VERT, align=PP_ALIGN.CENTER)
    texte(s, MARGE + Inches(4.9), y + Inches(0.05), Inches(1.9), Inches(1.3), "→", taille=72, police=LEGER,
          couleur=VERT, align=PP_ALIGN.CENTER)
    texte(s, MARGE + Inches(6.8), y, Inches(5.0), Inches(1.4), n(F["dvf_mutations"]), taille=80, police=TITRE,
          couleur=BLANC)
    texte(s, MARGE + Inches(6.8), y + Inches(1.45), Inches(5.0), Inches(0.5), "ventes distinctes", taille=20,
          police=LEGER, couleur=BLANC)
    soulignement(s, MARGE, Inches(5.65))
    texte(s, MARGE, Inches(5.85), Inches(11), Inches(0.5), "Ventes douteuses marquées, jamais supprimées.",
          taille=20, police=CORPS, couleur=BLANC)
    notes(s, f"""
Le fichier DVF a une ligne par lot ou par parcelle : un même acte de vente apparaît sur plusieurs lignes,
avec le prix total répété. Compter les lignes revient à compter plusieurs fois la même vente.
On regroupe donc les lignes par acte (date + commune + nature + valeur) : {n(F['dvf_lignes_csv'])} lignes → {n(F['dvf_mutations'])} ventes.
Ce n'est pas une perte : un contrôle automatique vérifie que la somme des lignes sources de chaque vente
redonne exactement le total du fichier.
Standardisation : codes INSEE sur 5 caractères (y compris outre-mer), dates ISO, virgules décimales, arrondissements de Paris/Lyon/Marseille.
Rien n'est supprimé, tout est marqué :
- {n(F['dvf_douteuses'])} ventes avec un prix au m² douteux (plusieurs logements à des adresses différentes) ;
- {n(F['dvf_hors_marche'])} ventes hors marché (échanges, adjudications, expropriations) ;
- {F['dvf_codes_fusionnes']} codes de communes fusionnées depuis 2022, conservés et comptés.
L'app affiche ces limites en clair sous la carte. Méthodologie complète : docs/schema_bdd.md.
""")


def s06_spark(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fond(s, BLANC)
    entete(s, 6, "Big data", "Spark calcule les prix médians, SQL les vérifie")
    y, w, gap = Inches(2.6), Inches(3.0), Inches(1.37)
    etapes = [(n(F["ventes_retenues"]), "ventes retenues", ENCRE), ("Spark", "médiane par zone", BLEU),
              (n(F["indicateurs_lignes"]), "indicateurs en base", ENCRE)]
    for i, (gros, petit, couleur) in enumerate(etapes):
        x = MARGE + i * (w + gap)
        texte(s, x, y, w, Inches(1.2), gros, taille=64, police=TITRE, couleur=couleur)
        texte(s, x, y + Inches(1.2), w, Inches(0.5), petit, taille=19, police=LEGER, couleur=GRIS)
        if i < 2:
            texte(s, x + w, y + Inches(0.1), gap, Inches(1), "→", taille=48, police=LEGER, couleur=ORANGE,
                  align=PP_ALIGN.CENTER)
    trait(s, MARGE, Inches(4.75), L - MARGE, Inches(4.75))
    texte(s, MARGE, Inches(4.95), Inches(2.2), Inches(1.4), str(F["ecarts_spark_sql"]), taille=96, police=TITRE,
          couleur=BLEU)
    texte(s, MARGE + Inches(1.3), Inches(5.35), Inches(9), Inches(0.9),
          ["écart avec le recalcul SQL,", "zone par zone"],
          taille=22, police=LEGER, couleur=ENCRE)
    notes(s, f"""
Le job Spark (jobs/indicateurs_prix.py) lit les ventes dans PostgreSQL et ne garde que les ventes de marché
d'un seul logement (maison ou appartement, prix entre 200 et {n(30000)} €/m²) : {n(F['ventes_retenues'])} ventes.
Les autres ne sont pas perdues : elles restent en base, marquées (ventes de plusieurs logements, locaux d'activité, hors marché).
Il calcule la médiane du prix au m² pour chaque commune, département et région, par type de bien.
Résultat : {n(F['indicateurs_lignes'])} indicateurs écrits en base, avec leur source et leur date de calcul.
Pourquoi la médiane : une vente aberrante ne la déplace pas, contrairement à la moyenne.
Vérification : un contrôle recalcule en SQL la médiane de TOUTES les zones et compare avec Spark :
{F['ecarts_spark_sql']} écart. Relancer le job redonne la même table (idempotence vérifiée).
Aujourd'hui Spark tourne en local sur une machine ; il passera sur OVHcloud Data Platform (slide 9).
""")


def capture_recadree():
    """Carte France sans les contrôles Leaflet (zoom, échelle, attribution, citée sous l'image)."""
    src, dst = ICI / "captures" / "1_france_carte.png", ICI / "captures" / "1_france_carte_recadree.png"
    Image.open(src).crop((230, 60, 1420, 1170)).save(dst)
    return dst


def s07_demo(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fond(s, BLANC)
    entete(s, 7, "Démo", f"De la France à l'arrondissement en {F['clics_demo']} clics")
    pic = image(s, capture_recadree(), MARGE, Inches(2.0), Inches(6.2), Inches(4.65))
    texte(s, MARGE, pic.top + pic.height + Inches(0.08), pic.width, Inches(0.25), "Fond de carte © Esri",
          taille=10, couleur=GRIS).name = "chrome attribution"
    x = MARGE + Inches(6.9)
    texte(s, x, Inches(2.2), Inches(4.8), Inches(0.4), "PRIX MÉDIAN AU M²", taille=14, couleur=GRIS)
    for i, c in enumerate(DEGRADE):
        rect(s, x + i * Inches(0.6), Inches(2.65), Inches(0.6), Inches(0.3), remplissage=c)
    texte(s, x, Inches(3.05), Inches(3.0), Inches(0.4), [[("moins cher", {}), ("  →  ", {"couleur": GRIS}), ("plus cher", {})]],
          taille=16, police=LEGER, couleur=ENCRE)
    texte(s, x, Inches(4.0), Inches(4.8), Inches(0.4), [[("Île-de-France  ", {"couleur": GRIS}),
                                                          (f"{n(F['prix_france_idf'])} €/m²", {"couleur": ENCRE, "police": TITRE, "taille": 24})]],
          taille=16, police=LEGER)
    soulignement(s, x, Inches(5.3))
    texte(s, x, Inches(5.5), Inches(4.8), Inches(0.8), "Bascule sur l'application →", taille=32, police=TITRE,
          couleur=ORANGE)
    notes(s, f"""
[BASCULER SUR L'APP — http://localhost:8501 — déroulé dans docs/followup2/demo.md]
1. France par région, toutes ventes : l'Île-de-France ressort à {n(F['prix_france_idf'])} €/m².
2. Clic sur l'Île-de-France → ses départements. Paris : {n(F['prix_paris'])} €/m².
3. Clic sur Paris → les arrondissements. Appartements du 6e : {n(F['prix_paris_6e_appart'])} €/m² (filtre Appartement).
4. Le tableau à droite reprend exactement les chiffres de la carte, se trie et s'exporte en CSV.
5. Zones grisées : moins de {F['seuil_ventes']} ventes — on préfère ne rien afficher qu'un prix non significatif.
Si la démo ne répond pas : captures du parcours dans docs/followup2/captures/.
""")


def s08_controles(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fond(s, BLEU)
    entete(s, 8, "Qualité", "Bases et application vérifiées automatiquement", sombre=True)
    for i, (gros, petit) in enumerate([(F["controles_bdd"], "contrôles sur les bases"),
                                        (F["tests_app"], "tests de l'application")]):
        x = MARGE + i * Inches(5.6)
        texte(s, x, Inches(2.7), Inches(5), Inches(1.8), str(gros), taille=120, police=TITRE, couleur=BLANC)
        soulignement(s, x, Inches(4.75))
        texte(s, x, Inches(4.95), Inches(5), Inches(0.5),
              [[(petit, {}), ("   PASS", {"couleur": VERT, "police": TITRE})]], taille=22, police=LEGER, couleur=BLANC)
    notes(s, f"""
Une commande, db/check.py, rejoue {F['controles_bdd']} contrôles et rend PASS ou FAIL :
nombres de lignes attendus, aucune ligne DVF perdue, contours géographiques valides,
repères connus (la Tour Eiffel tombe bien dans le 7e arrondissement), cohérence PostgreSQL ↔ MongoDB,
absence de données personnelles d'agence, et médianes Spark = recalcul SQL.
Les {F['tests_app']} tests de l'application vérifient qu'elle démarre et affiche la carte aux {F['echelles']} échelles,
et qu'un clic tombe sur la bonne zone.
Les chiffres de ce deck sont eux-mêmes extraits de la base par un script, pas recopiés à la main.
""")


def s09_cloud(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fond(s, BLANC)
    entete(s, 9, "Plateforme cloud", "Spark passe sur OVHcloud Data Platform")
    colonnes = [
        ("AUJOURD'HUI", "Spark local", "1 machine", ENCRE),
        ("OVHCLOUD DATA PLATFORM", "Spark distribué", "1 driver + N exécuteurs", BLEU),
        ("RÉSULTAT", "Mêmes indicateurs", "même application", ENCRE),
    ]
    gap = Inches(0.9)
    w = (LARGEUR - 2 * gap) / 3
    for i, (etiquette, gros, petit, couleur) in enumerate(colonnes):
        x = MARGE + i * (w + gap)
        rect(s, x, Inches(2.7), w, Inches(0.09), remplissage=BLEU if i == 1 else FILET)
        texte(s, x, Inches(3.0), w, Inches(0.4), etiquette, taille=16, couleur=ORANGE)
        texte(s, x, Inches(3.45), w, Inches(1.0), gros, taille=36, police=TITRE, couleur=couleur)
        texte(s, x, Inches(4.35), w, Inches(0.5), petit, taille=20, police=LEGER, couleur=GRIS)
        if i < 2:
            texte(s, x + w, Inches(3.4), gap, Inches(0.9), "→", taille=40, police=LEGER, couleur=ORANGE,
                  align=PP_ALIGN.CENTER)
    trait(s, MARGE, Inches(5.4), L - MARGE, Inches(5.4))
    texte(s, MARGE, Inches(5.6), LARGEUR, Inches(0.5),
          [[("Mode serverless : ", {"police": TITRE, "couleur": BLEU}), ("facturé à l'exécution", {})]],
          taille=22, police=LEGER, couleur=ENCRE)
    notes(s, """
Le sujet impose de répartir le calcul sur un cluster de machines (Hadoop / Spark) : on le fera sur OVHcloud Data Platform.
Ce que la plateforme fournit (doc officielle OVHcloud) :
- le Data Processing Engine exécute un script PySpark comme une « action » : 1 driver qui coordonne,
  et un nombre d'exécuteurs réglable qui portent la partie distribuée du calcul ;
- la puissance se règle par job en DPU (1 DPU ≈ 1 vCPU + 4 Go de RAM) ;
- les données sont déposées via les Connectors et stockées en tables Iceberg (Lakehouse Manager) ;
- le résultat peut être écrit dans une table PostgreSQL connectée.
Notre job tourne déjà en PySpark : on le porte tel quel, la table d'indicateurs et l'application ne changent pas.
Coût maîtrisé : facturation à l'usage ; en mode serverless, un job ne consomme que pendant son exécution
(un notebook allumé ou le mode always-up consomment en continu, on les évite).
Contrôle prévu : la même vérification qu'aujourd'hui, médiane Spark = recalcul SQL sur toutes les zones.
""")


def s10_feuille_de_route(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fond(s, BLANC)
    entete(s, 10, "Feuille de route", "Quatre paliers jusqu'au rendu du 7 février")
    paliers = [
        ("23/11 – 13/12", "Socio-éco", "Revenus, DPE, risques"),
        ("14/12 – 10/01", "Analyse de texte", "Sentiment des annonces"),
        ("11/01 – 31/01", "Spark sur OVHcloud", f"{F['sources_visees']} sources au total"),
        ("01/02 – 07/02", "Rendu", "Documentation"),
    ]
    y = Inches(3.5)
    trait(s, MARGE, y, L - MARGE, y, couleur=ENCRE, epaisseur=1.5)
    texte(s, MARGE, y - Inches(0.75), Inches(3), Inches(0.4),
          [[("▼ ", {"taille": 12}), ("Aujourd'hui · 20/11", {})]], taille=16, couleur=ORANGE)
    w = LARGEUR / 4
    for i, (dates, titre, detail) in enumerate(paliers):
        x = MARGE + i * w
        rect(s, x, y - Inches(0.1), Inches(0.2), Inches(0.2), remplissage=ORANGE if i == 3 else BLEU)
        texte(s, x, y + Inches(0.4), w - Inches(0.3), Inches(0.4), dates, taille=16, couleur=BLEU)
        texte(s, x, y + Inches(0.9), w - Inches(0.3), Inches(1.0), titre, taille=28, police=TITRE)
        texte(s, x, y + Inches(1.6), w - Inches(0.3), Inches(1.0), detail, taille=19, police=LEGER, couleur=GRIS)
    notes(s, f"""
Nous sommes au début du premier palier. Chaque palier ajoute une brique sur le socle existant, sans rien
reconstruire : même clé (code INSEE), mêmes bases, même mécanisme de contrôles PASS/FAIL.
1. 23/11 – 13/12 : {F['sources_palier1']} sources socio-économiques et risques (revenus INSEE Filosofi, population, DPE ADEME,
   retrait-gonflement des argiles), affichées comme nouveaux indicateurs sur la carte.
2. 14/12 – 10/01 : analyse de sentiment sur le texte des annonces (et d'avis si la source est retenue),
   agrégée par commune ; méthode et modèle documentés comme l'exige le sujet.
3. 11/01 – 31/01 : job Spark sur OVHcloud Data Platform (slide précédente), {F['sources_restantes']} dernières sources
   pour atteindre {F['sources_visees']}, page tableau avec indicateurs croisés et export.
4. 01/02 – 07/02 : gel des fonctionnalités, documentation (schéma, méthodologie de nettoyage, IA), répétition.
Merci — questions ?
""")


def main():
    prs = Presentation()
    prs.slide_width, prs.slide_height = L, H
    for f in (s01_titre, s02_etapes, s03_sources, s04_bases, s05_nettoyage, s06_spark, s07_demo,
              s08_controles, s09_cloud, s10_feuille_de_route):
        f(prs)
    prs.save(SORTIE)
    print(f"-> {SORTIE.name} ({len(prs.slides)} slides)")


if __name__ == "__main__":
    main()
