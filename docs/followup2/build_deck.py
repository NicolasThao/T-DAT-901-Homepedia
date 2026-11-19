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


def pct(x):
    """Variation signée au format français : −7,3 % (espace insécable avant %)."""
    return f"{x:+.1f}\u00a0%".replace("-", "−").replace(".", ",")


PERIODE = f"{F['annee_debut']}-{F['annee_fin']}"
# Palette divergente de l'app (app/carte.py DIVERGENTE), baisse -> hausse
DIVERGENTE = [RGBColor.from_string(c) for c in ("104281", "2A78D6", "86B6EF", "D2D0C8", "EF9A95", "E34948", "A3201F")]


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
        ("BIG DATA", "Pipeline Spark"),
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
- Collecte : DVF {PERIODE} (ventes réelles, DGFiP, publiées par Etalab), référentiel géographique geo.api.gouv.fr, {F['annonces']} annonces Orpi.
- Bases : PostgreSQL/PostGIS pour le tabulaire et le spatial, MongoDB pour le texte des annonces.
- Big data : un pipeline Spark en {F['etapes_pipeline']} étapes (bronze → argent → or, puis contrôles) calcule {F['indicateurs_marche']} indicateurs
  de prix, recontrôlés en SQL ; il est prêt pour OVHcloud Data Platform (slide 10).
- Visualisation : application Streamlit, carte région → département → commune.
La suite : d'abord le déploiement de ce pipeline sur OVHcloud Data Platform, puis l'analyse de texte,
puis les nouvelles sources, qui s'ajoutent alors comme de simples jobs.
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
    # Feuille de route : les 4 sources socio-éco et les 5 dernières arrivent au même palier (11/01 – 31/01)
    for i, (nom, fond_case, encre) in enumerate(cases):
        ligne, col = divmod(i, 4)
        x, y = MARGE + col * (cw + gap), Inches(2.5) + ligne * (ch + gap)
        rect(s, x, y, cw, ch, remplissage=fond_case)
        texte(s, x + Inches(0.25), y, cw - Inches(0.5), ch, nom, taille=24, police=TITRE, couleur=encre,
              ancre=MSO_ANCHOR.MIDDLE)
    # 8e case : les sources restantes, sans cases vides
    x, y = MARGE + 3 * (cw + gap), Inches(2.5) + ch + gap
    rect(s, x, y, cw, ch, remplissage=BLEU_PALE)
    texte(s, x + Inches(0.25), y, cw - Inches(0.5), ch,
          f"+{F['sources_restantes']} sources", taille=28, couleur=ENCRE,
          police=TITRE, ancre=MSO_ANCHOR.MIDDLE)
    y_leg = Inches(5.55)
    for j, (style, libelle) in enumerate([((BLEU, None), "chargées en base"), ((BLEU_PALE, None), "d'ici le 31/01")]):
        x = MARGE + j * Inches(3.0)
        rect(s, x, y_leg + Inches(0.06), Inches(0.22), Inches(0.22), remplissage=style[0], contour=style[1])
        texte(s, x + Inches(0.35), y_leg, Inches(2.6), Inches(0.4), libelle, taille=16, couleur=GRIS)
    notes(s, f"""
Le sujet demande au moins une douzaine de sources, dont une textuelle.
En place et chargées en base :
1. DVF {PERIODE} (Demandes de Valeurs Foncières, DGFiP, version géolocalisée d'Etalab) : {n(F['dvf_lignes_csv'])} lignes,
   toutes les ventes immobilières de {F['annees_dvf']} années complètes.
2. Référentiel géographique geo.api.gouv.fr : {F['regions']} régions, {F['departements']} départements, {n(F['communes'])} communes et leurs contours.
3. Annonces Orpi : {F['annonces']} annonces de vente collectées par scraping (robots.txt respecté, 1 requête par seconde),
   avec la description en texte libre — c'est notre source textuelle.
D'ici le 31/01, une fois les pipelines déployés automatiquement sur la plateforme cloud (priorité du premier palier),
{F['sources_palier1']} sources socio-économiques en open data, reliées par le code INSEE de la commune : revenus (INSEE Filosofi),
population, diagnostics énergétiques (ADEME), risque retrait-gonflement des argiles (Géorisques — répond à la
question du sujet sur le risque climatique à 15 ans) ;
et {F['sources_restantes']} de plus pour atteindre {F['sources_visees']} : établissements scolaires, gares, chômage localisé (INSEE),
Base Adresse Nationale, et une source d'avis textuels.
Chaque nouvelle source = un job ajouté au pipeline, pas un chantier à part.
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
  {n(F['dvf_mutations'])} ventes DVF ({PERIODE}), et les champs structurés des annonces (prix, surface, DPE, position).
  Index B-tree sur les clés de jointure, index spatiaux GiST sur les géométries.
- MongoDB : l'annonce brute telle que scrapée, dont la description. Structure variable, index plein texte
  (ex. « balcon » renvoie {F['annonces_texte_balcon']} annonces), et un champ réservé au résultat de l'analyse de sentiment.
Le pivot entre toutes les sources est le code INSEE de la commune (5 caractères, pas le code postal,
qui peut couvrir plusieurs communes). Chaque annonce existe des deux côtés avec le même identifiant, sans doublon de contenu.
Le schéma complet est documenté dans docs/schema_bdd.md.
""")


def s06_nettoyage(prs):
    """Chaîne de nettoyage : 3 volumes (lignes -> ventes -> ventes retenues), puis les 4 traitements dans l'ordre."""
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s._element.cSld.set("name", "dense")
    fond(s, BLEU)
    entete(s, 6, "Nettoyage", "Du fichier brut aux prix : rien n'est supprimé", sombre=True)

    # 1. Les trois volumes, reliés par ce qui les sépare
    volumes = [(n(F["dvf_lignes_csv"]), f"lignes DVF {PERIODE}"),
               (n(F["dvf_mutations"]), "ventes distinctes"),
               (n(F["ventes_retenues"]), "ventes utilisées pour les prix")]
    passages = ["regroupées", "filtrées"]
    w, y = Inches(3.0), Inches(2.25)
    gap = (LARGEUR - 3 * w) / 2
    for i, (gros, petit) in enumerate(volumes):
        x = MARGE + i * (w + gap)
        texte(s, x, y, w, Inches(0.9), gros, taille=48, police=TITRE, couleur=BLANC)
        texte(s, x, y + Inches(0.9), w, Inches(0.4), petit, taille=16, police=LEGER, couleur=BLANC)
        if i < 2:
            texte(s, x + w, y - Inches(0.05), gap, Inches(0.35), passages[i], taille=14, couleur=VERT,
                  align=PP_ALIGN.CENTER)
            texte(s, x + w, y + Inches(0.2), gap, Inches(0.6), "→", taille=36, police=LEGER, couleur=VERT,
                  align=PP_ALIGN.CENTER)

    # 2. Les quatre traitements, dans l'ordre où ils s'appliquent
    etapes = [
        ("Regrouper", "Une vente répétée sur plusieurs lignes devient une seule ligne, son prix compté une fois"),
        ("Standardiser", "Code INSEE (commune du logement), dates au format ISO, position GPS"),
        ("Marquer", f"{n(F['dvf_hors_marche'])} ventes hors marché, {n(F['dvf_douteuses'])} prix au m² douteux"),
        ("Filtrer", "Vente de marché d'une maison ou d'un appartement, entre 200 et 30 000 €/m²"),
    ]
    y2 = Inches(4.05)
    trait(s, MARGE, y2, L - MARGE, y2, couleur=BLEU_CLAIR, epaisseur=1.0)
    g2 = Inches(0.35)
    w2 = (LARGEUR - 3 * g2) / 4
    for i, (verbe, detail) in enumerate(etapes):
        x = MARGE + i * (w2 + g2)
        texte(s, x, y2 + Inches(0.25), w2, Inches(0.45),
              [[(f"{i + 1}  ", {"couleur": ORANGE}), (verbe, {})]], taille=24, police=TITRE, couleur=BLANC)
        texte(s, x, y2 + Inches(0.8), w2, Inches(1.5), detail, taille=15, police=LEGER, couleur=BLANC,
              interligne=1.1)
    notes(s, f"""
Le sujet demande une description précise de la méthode de nettoyage : la voici, de la donnée brute aux prix affichés.
C'est, pour le domaine prix, le passage de la couche bronze à la couche argent présenté sur la slide précédente.
Trois volumes : {n(F['dvf_lignes_csv'])} lignes dans les fichiers DVF {PERIODE} → {n(F['dvf_mutations'])} ventes distinctes
→ {n(F['ventes_retenues'])} ventes utilisées pour calculer les prix. Entre les deux derniers, rien n'est supprimé de la base :
les ventes non retenues restent stockées, simplement exclues du calcul.
1. Regrouper. DVF a une ligne par lot, par parcelle et par nature de culture : une même vente apparaît sur plusieurs
   lignes, avec le prix total répété. Compter les lignes compterait plusieurs fois la même vente. On regroupe par
   identifiant de vente (fourni par Etalab). Un logement répété sur plusieurs natures de culture (sol, jardin…)
   n'est compté qu'une fois. Contrôle automatique, année par année : la somme des lignes regroupées redonne
   exactement le total du fichier.
2. Standardiser. Chaque vente est rattachée à sa commune par le code INSEE sur 5 caractères (la clé commune à
   toutes nos sources) ; si une vente porte sur plusieurs communes, on prend celle du logement. Dates au format ISO,
   arrondissements de Paris, Lyon et Marseille, position GPS de la vente. {F['dvf_codes_inconnus']} codes de communes
   absents du référentiel actuel sont conservés et comptés, pas jetés.
3. Marquer, jamais supprimer. {n(F['dvf_hors_marche'])} ventes hors marché (échanges, adjudications, expropriations :
   leur prix n'est pas un prix de marché) et {n(F['dvf_douteuses'])} ventes au prix au m² douteux (plusieurs logements
   à des adresses différentes vendus en un seul prix). Chaque marque est une colonne de la base : on peut toujours
   revenir en arrière.
4. Filtrer pour le calcul des prix. On ne garde que les ventes de marché d'un seul logement (maison ou appartement),
   avec un prix entre 200 et {n(30000)} €/m² (garde-fou contre les erreurs de saisie).
L'app affiche ces limites en clair sous la carte. Méthodologie complète : docs/schema_bdd.md.
""")


def s07_application(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fond(s, BLANC)
    entete(s, 7, "Application", "Trois pages pour deux questions métier")
    pages = [
        ("EN PLACE", "Carte", "Prix, évolution, puis autres indicateurs", True),
        ("À VENIR", "Fiche territoire", "Une zone, tous ses chiffres", False),
        ("À VENIR", "Comparateur", "Scoring franchises, écarts d'inégalités", False),
    ]
    gap = Inches(0.6)
    w = (LARGEUR - 2 * gap) / 3
    for i, (etat, titre, detail, fait) in enumerate(pages):
        x = MARGE + i * (w + gap)
        rect(s, x, Inches(2.7), w, Inches(0.09), remplissage=BLEU if fait else FILET)
        texte(s, x, Inches(3.0), w, Inches(0.4), etat, taille=16, couleur=VERT if fait else ORANGE,
              police=TITRE if fait else CORPS)
        texte(s, x, Inches(3.45), w, Inches(0.9), titre, taille=40, police=TITRE, couleur=BLEU if fait else ENCRE)
        texte(s, x, Inches(4.4), w - Inches(0.2), Inches(1.0), detail, taille=20, police=LEGER, couleur=GRIS)
    notes(s, f"""
Le sujet ne vise pas les particuliers mais les professionnels : agences, collectivités, analystes.
On a choisi deux de ses questions métier comme fil rouge (ADR-042) :
- « Où ouvrir les 10 prochaines franchises de mon entreprise ? » → un scoring multi-critères dont l'utilisateur règle les poids
  (prix, revenus, population, dynamisme des ventes, risque argiles…) ;
- « Comment réduire les inégalités dans mon département ? » → des indicateurs d'écart entre communes d'un même département.
L'application cible a trois pages :
1. Carte (en place) : prix médian et évolution aujourd'hui, puis chaque nouvel indicateur devient une couche au choix.
2. Fiche territoire : une commune, un département ou une région, tous ses indicateurs et leur évolution sur une page.
3. Comparateur et scoring : plusieurs zones côte à côte, classement pondérable pour les franchises, écarts pour les inégalités.
Le volet texte alimente la carte et les fiches : caractéristiques extraites des annonces (« travaux », « rénovation »)
et sentiment calculé sur une source d'avis.
Sur chaque page, comme le demande le sujet : commune, département et région, tableau triable, filtrable et exportable,
indicateurs croisés.
""")


def capture_recadree(nom="1_france", boite=(230, 60, 1420, 1170)):
    """Carte sans les contrôles Leaflet (zoom, échelle, attribution, citée sous l'image)."""
    src, dst = ICI / "captures" / f"{nom}_carte.png", ICI / "captures" / f"{nom}_carte_recadree.png"
    Image.open(src).crop(boite).save(dst)
    return dst


def s08_demo(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fond(s, BLANC)
    entete(s, 8, "Démo", f"De la France à l'arrondissement en {F['clics_demo']} clics")
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
1. France par région, toutes ventes de {F['annee_fin']} (année affichée par défaut) : l'Île-de-France ressort à {n(F['prix_france_idf'])} €/m².
2. Clic sur l'Île-de-France → ses départements. Paris : {n(F['prix_paris'])} €/m².
3. Clic sur Paris → les arrondissements. Appartements du 6e : {n(F['prix_paris_6e_appart'])} €/m² (filtre Appartement).
4. Le tableau à droite reprend exactement les chiffres de la carte, se trie et s'exporte en CSV. Il ajoute les
   indicateurs du pipeline : quartiles, écart D9/D1 (dispersion), prix médian d'un bien, surface médiane.
   Sous la carte : d'où viennent les chiffres (pipeline, lot, date de calcul).
5. Zones grisées : moins de {F['seuil_ventes']} ventes — on préfère ne rien afficher qu'un prix non significatif.
6. Bouton « Évolution » : on enchaîne sur la slide suivante.
Si la démo ne répond pas : captures du parcours dans docs/followup2/captures/.
À dire à l'oral pendant la démo (pas de slide dédiée) :
- Les prix affichés sont calculés par Spark : {n(F['ventes_retenues'])} ventes de marché d'un seul logement → {n(F['indicateurs_lignes'])} indicateurs
  (médianes par commune, département, région, type de bien et année). Pourquoi la médiane : une vente aberrante ne la déplace pas.
- Chaque indicateur Spark (médiane, quartiles, déciles, valeur et surface) est recalculé en SQL : {F['ecarts_spark_sql']} écart sur toutes les zones.
- Une commande rejoue {F['controles_bdd']} contrôles sur les bases (aucune ligne perdue, repères connus, cohérence PostgreSQL ↔ MongoDB)
  et {F['tests_app']} tests vérifient l'application ; les chiffres de ce deck sont extraits de la base par un script.
""")


def s09_evolution(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fond(s, BLANC)
    entete(s, 9, "Évolution", f"Paris : {pct(F['variation_paris_pct'])} entre {F['annee_debut']} et {F['annee_fin']}")
    pic = image(s, capture_recadree("5_evolution_paris"), MARGE, Inches(2.0), Inches(6.2), Inches(4.65))
    texte(s, MARGE, pic.top + pic.height + Inches(0.08), pic.width, Inches(0.25), "Fond de carte © Esri",
          taille=10, couleur=GRIS).name = "chrome attribution"
    x = MARGE + Inches(6.9)
    texte(s, x, Inches(2.2), Inches(4.8), Inches(0.4), "VARIATION DU PRIX MÉDIAN", taille=14, couleur=GRIS)
    for i, c in enumerate(DIVERGENTE):
        rect(s, x + i * Inches(0.5), Inches(2.65), Inches(0.5), Inches(0.3), remplissage=c)
    texte(s, x, Inches(3.05), Inches(4.0), Inches(0.4), [[("baisse", {}), ("  →  ", {"couleur": GRIS}), ("hausse", {})]],
          taille=16, police=LEGER, couleur=ENCRE)
    texte(s, x, Inches(3.9), Inches(1.4), Inches(1.2), str(F["arrondissements_en_baisse"]), taille=72, police=TITRE,
          couleur=BLEU)
    texte(s, x + Inches(1.4), Inches(4.2), Inches(3.4), Inches(0.8),
          [f"arrondissements sur {F['arrondissements_compares']}", "en baisse"], taille=20, police=LEGER, couleur=ENCRE)
    soulignement(s, x, Inches(5.55))
    texte(s, x, Inches(5.75), Inches(4.8), Inches(0.5),
          [[("Île-de-France  ", {"couleur": GRIS}), (pct(F["variation_idf_pct"]), {"couleur": ENCRE, "police": TITRE, "taille": 24})]],
          taille=16, police=LEGER)
    notes(s, f"""
Le sujet demande l'évolution des prix : on a chargé {F['annees_dvf']} années complètes de DVF ({PERIODE}),
avec les mêmes règles de nettoyage pour chaque année, contrôlées année par année.
Dans l'app, le bouton « Évolution » compare deux années au choix, aux {F['echelles']} échelles.
- Paris : prix médian au m² {pct(F['variation_paris_pct'])} entre {F['annee_debut']} et {F['annee_fin']} ;
  {F['arrondissements_en_baisse']} arrondissements sur {F['arrondissements_compares']} sont en baisse.
- Île-de-France : {pct(F['variation_idf_pct'])}. En France, {F['departements_en_baisse']} départements sur {F['departements_compares']}
  et {F['regions_en_baisse']} régions sur {F['regions_comparees']} sont en baisse sur la période.
Palette divergente : bleu = baisse, rouge = hausse, gris = stable (entre −2 et +2 %).
Une zone n'est colorée que si elle a au moins {F['seuil_ventes']} ventes chacune des deux années :
une variation calculée sur quelques ventes ne veut rien dire.
On compare des médianes, jamais des moyennes.
Plan B : captures/4_evolution_france_app.png et 5_evolution_paris_app.png.
""")


def s10_cloud(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fond(s, BLANC)
    entete(s, 10, "Plateforme cloud", "Pipeline prix prêt pour OVHcloud")
    colonnes = [
        ("FAIT", f"{F['etapes_pipeline']} étapes Spark", "bronze → argent → or", ENCRE),
        ("VÉRIFIÉ", f"{F['controles_pipeline']} contrôles PASS", "en local, même code", BLEU),
        ("PROCHAINE ÉTAPE", "Déploiement", "workflow planifié", ENCRE),
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
          [[("Ensuite : ", {"police": TITRE, "couleur": BLEU}), ("une source = une étape", {})]],
          taille=22, police=LEGER, couleur=ENCRE)
    notes(s, """
Le sujet impose de répartir le calcul sur un cluster de machines (Hadoop / Spark) : on le fait sur OVHcloud Data Platform.
Où on en est : le pipeline du domaine prix est écrit et vérifié ; il reste à le déployer sur la plateforme (palier 1).
- {F['etapes_pipeline']} étapes Spark, un fichier chacune : bronze → argent (les {n(F['dvf_lignes_csv'])} lignes DVF deviennent {n(F['dvf_mutations'])} ventes),
  argent → or ({n(F['indicateurs_lignes'])} indicateurs), puis {F['controles_pipeline']} contrôles PASS/FAIL ; un contrôle en échec arrête tout.
- Même code en local et sur la plateforme (forme d'une « action PySpark » : 1 driver + N exécuteurs réglables en DPU,
  1 DPU = 1 vCPU + 4 Go). Testé sur deux versions de Spark (3.4, celle des exemples de la doc, et 4.0) : mêmes résultats.
- Vérifié contre l'existant : la couche argent Spark est identique, vente par vente, à la base actuelle ({F['ecarts_parite']} écart),
  et chaque indicateur est recalculé en SQL ({F['ecarts_spark_sql']} écart).
- Données : un bucket avec un dossier par couche ; l'or est rapatrié dans la base de l'app seulement si tous les
  contrôles sont PASS. L'app ne dépend donc pas du cloud pour fonctionner.
- Coût : facturé au DPU-heure (quelques centimes), en mode serverless seulement pendant l'exécution, soit quelques dizaines de centimes
  par exécution complète (estimation) ; un notebook allumé ou le mode always-up consomment en continu, on les évite.
Prochaine étape : créer les ressources sur la plateforme, lancer le workflow, le planifier. Ensuite, intégrer une
nouvelle source ou un nouveau calcul revient à ajouter une étape, déployée et contrôlée de la même façon.
Ce qu'on appelle un pipeline : une chaîne de traitements automatisée, de la source jusqu'à la table lue par l'app
(ingestion → nettoyage → calcul Spark → contrôles PASS/FAIL), déclenchée sans intervention (planning ou nouvelle
livraison), rejouable, et qui s'arrête en alerte si un contrôle échoue. Aujourd'hui nos chaînes existent et sont
contrôlées, mais se lancent encore à la main : les automatiser sur la plateforme est l'objet de ce palier.
Organisation de l'équipe : un seul projet Data Platform, partagé à 4 (chacun invité comme membre de l'équipe),
qui porte les données, les pipelines et l'app ; il est facturé au compte qui l'héberge. Chacun peut garder son propre
projet comme bac à sable (tester un notebook, un job, un modèle) ; le code passe par un dépôt Git commun.
L'organisation en domaines et couches a été présentée en slide 5 ; les slides suivantes donnent une fiche par domaine.
""")


# Couleurs des couches (repères seulement : petites barres d'en-tête)
COUCHES = [("BRONZE", "donnée brute, telle que reçue", RGBColor.from_string("B0703C")),
           ("ARGENT", "nettoyée, standardisée, code INSEE", RGBColor.from_string("8A93A6")),
           ("OR", "indicateurs lus par l'app", RGBColor.from_string("C99A12"))]


def s05_architecture(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s._element.cSld.set("name", "dense")
    fond(s, BLANC)
    entete(s, 5, "Architecture des données", "Trois domaines traversent trois couches")
    x_lib, w_lib, gap = MARGE, Inches(1.9), Inches(0.6)
    w = (LARGEUR - w_lib - 2 * gap) / 3
    xs = [x_lib + w_lib + i * (w + gap) for i in range(3)]
    y_tete = Inches(2.15)
    for i, (nom, role, couleur) in enumerate(COUCHES):
        rect(s, xs[i], y_tete, w, Inches(0.09), remplissage=couleur)
        texte(s, xs[i], y_tete + Inches(0.2), w, Inches(0.35), nom, taille=20, police=TITRE, couleur=couleur)
        texte(s, xs[i], y_tete + Inches(0.55), w, Inches(0.3), role, taille=13, couleur=GRIS)
        if i < 2:
            texte(s, xs[i] + w, y_tete + Inches(0.15), gap, Inches(0.4), "→", taille=20, police=LEGER,
                  couleur=ORANGE, align=PP_ALIGN.CENTER)
    domaines = [
        ("Prix", ["Fichiers DVF Etalab", "Une ligne par vente, qualité marquée", "Indicateurs par zone, type, année"]),
        ("Texte", ["Annonces et avis bruts", "Textes rattachés à la commune", "Thèmes et sentiment par commune"]),
        ("Socio-éco", ["Fichiers INSEE, ADEME, Géorisques", "Standardisés sur le code INSEE", "Taux d'effort, écarts, score"]),
    ]
    y, h = Inches(3.15), Inches(0.82)
    for r, (domaine, cellules) in enumerate(domaines):
        yr = y + r * h
        trait(s, MARGE, yr, L - MARGE, yr, couleur=BLEU if r == 0 else FILET, epaisseur=1.5 if r == 0 else 1.0)
        texte(s, x_lib, yr, w_lib, h, domaine, taille=24, police=TITRE, couleur=ENCRE, ancre=MSO_ANCHOR.MIDDLE)
        for i, cellule in enumerate(cellules):
            texte(s, xs[i], yr, w - Inches(0.1), h, cellule, taille=16, police=LEGER, couleur=ENCRE,
                  ancre=MSO_ANCHOR.MIDDLE)
    trait(s, MARGE, y + 3 * h, L - MARGE, y + 3 * h)
    texte(s, MARGE, Inches(6.0), LARGEUR, Inches(0.45),
          [[("Pipeline : ", {"police": TITRE, "couleur": BLEU}),
            ("le passage automatisé d'une couche à la suivante, contrôlé à chaque étape", {})]],
          taille=20, police=LEGER, couleur=ENCRE)
    notes(s, f"""
On organise les données en domaines, et chaque domaine traverse les mêmes trois couches (architecture dite « médaillon »).
- Un domaine regroupe les données qui répondent à un même besoin : le marché immobilier (prix), le texte (annonces, avis),
  le contexte socio-économique et les risques. Chacun a sa fiche dans les slides suivantes.
- Bronze : la donnée brute, conservée telle que reçue, avec sa source et sa date d'ingestion. On peut tout recalculer à partir d'elle.
- Argent : la donnée nettoyée et standardisée. Clé commune = code INSEE de la commune ; lignes douteuses marquées,
  jamais supprimées ; une ligne par vente pour DVF.
- Or : les indicateurs prêts à l'emploi, par zone (commune, département, région) et par période. C'est la seule couche que lit l'app.
- Un pipeline fait passer un domaine d'une couche à la suivante, automatiquement, et s'arrête si un contrôle échoue.
Aujourd'hui, en local, ces couches existent déjà sans en porter le nom : fichiers téléchargés (bronze),
tables nettoyées PostgreSQL comme les ventes DVF et les annonces (argent), table d'indicateurs calculée par Spark (or).
Sur OVHcloud Data Platform : un bucket (stockage objet) avec un dossier par couche, bronze/, argent/ (Parquet), or/ ;
l'or est rapatrié dans la base de l'app après contrôles. Les conventions reprennent celles documentées par notre collègue
(colonnes de traçabilité _source, _date_ingestion, _batch_id ; lignes douteuses marquées, jamais supprimées).
Intérêt : une nouvelle source n'entre que par sa couche bronze ; le reste de la chaîne et l'app ne changent pas.
""")


def fiche_pipeline(prs, numero, rubrique_libelle, titre, lignes, indicateurs, dans_app, contenu_notes):
    """Fiche d'un domaine de données : Objectif / Entrée / Traitement / Indicateurs (grille) / Dans l'app.

    `indicateurs` : liste de (libellé, en_place). Slide marquée « dense » : verif_deck.py y autorise plus de mots
    (slides de fond, demandé par Nicolas le 2026-11-17)."""
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s._element.cSld.set("name", "dense")
    fond(s, BLANC)
    entete(s, numero, rubrique_libelle, titre)
    x_lib, x_val = MARGE, MARGE + Inches(2.1)
    l_val = L - MARGE - x_val
    h_ligne, h_item, cols = Inches(0.6), Inches(0.42), 3
    y = Inches(2.15)

    def filet(y, premier=False):
        trait(s, MARGE, y, L - MARGE, y, couleur=BLEU if premier else FILET, epaisseur=1.5 if premier else 1.0)

    def ligne_texte(y, libelle, valeur):
        texte(s, x_lib, y + Inches(0.2), Inches(2.3), Inches(0.3), libelle, taille=14, couleur=ORANGE)
        texte(s, x_val, y + Inches(0.08), l_val, Inches(0.45), valeur, taille=18, police=LEGER, couleur=ENCRE,
              ancre=MSO_ANCHOR.MIDDLE)

    for i, (libelle, valeur) in enumerate(lignes):
        filet(y, premier=(i == 0))
        ligne_texte(y, libelle, valeur)
        y += h_ligne

    # Indicateurs : grille de 3 colonnes, carré plein = en place, carré vide = à ajouter
    filet(y)
    texte(s, x_lib, y + Inches(0.2), Inches(2.3), Inches(0.3), "INDICATEURS", taille=14, couleur=ORANGE)
    if any(fait for _, fait in indicateurs):
        for j, (plein, libelle) in enumerate([(True, "existe, lancé à la main"), (False, "à ajouter")]):
            yl = y + Inches(0.6) + j * Inches(0.3)
            rect(s, x_lib, yl + Inches(0.06), Inches(0.13), Inches(0.13),
                 remplissage=BLEU if plein else None, contour=None if plein else BLEU, epaisseur=1.0)
            texte(s, x_lib + Inches(0.25), yl, Inches(2.0), Inches(0.3), libelle, taille=12, couleur=GRIS)
    w_col = l_val / cols
    for k, (libelle, fait) in enumerate(indicateurs):
        rang, col = divmod(k, cols)
        xi, yi = x_val + col * w_col, y + Inches(0.17) + rang * h_item
        rect(s, xi, yi + Inches(0.09), Inches(0.14), Inches(0.14),
             remplissage=BLEU if fait else None, contour=None if fait else BLEU, epaisseur=1.0)
        texte(s, xi + Inches(0.28), yi, w_col - Inches(0.35), Inches(0.35), libelle, taille=16, police=LEGER,
              couleur=ENCRE)
    rangs = -(-len(indicateurs) // cols)
    y += max(Inches(1.25) if any(f for _, f in indicateurs) else 0, rangs * h_item + Inches(0.3))

    filet(y)
    ligne_texte(y, "DANS L'APP", dans_app)
    filet(y + h_ligne)
    notes(s, contenu_notes)


def s11_domaine_prix(prs):
    fiche_pipeline(
        prs, 11, "Domaine prix  ·  23/11 – 13/12", "Domaine 1 : le marché immobilier local",
        [("OBJECTIF", "Niveau, dynamisme, dispersion et coût d'implantation de chaque marché"),
         ("ENTRÉE", f"DVF Etalab {PERIODE} (logements, locaux, terrains), référentiel géo"),
         ("TRAITEMENT", "Regroupement par vente, filtres, agrégats Spark par zone, type et année")],
        [("Prix au m², évolution", True), ("Volume de ventes", True), ("Quartiles, écart D9/D1", True),
         ("Prix d'un bien, surface", True), ("Prix du T1 au T5+", False), ("Part neuf / maisons", False),
         ("Locaux commerciaux au m²", False), ("Terrains à bâtir", False), ("Densité des ventes (GPS)", False)],
        "Sélecteur d'indicateur, carte de chaleur, tableau croisé exportable",
        f"""
Premier domaine porté sur la plateforme. Son pipeline (bronze → argent → or → contrôles) est écrit et vérifié en local ;
il se lance encore à la main et sera déployé et planifié sur OVHcloud au palier 1.
Il produit déjà {F['indicateurs_marche']} indicateurs (carrés pleins) : médiane, quartiles, déciles 1 et 9, prix médian d'un bien,
surface médiane, avec le nombre de ventes ; ils apparaissent dans le tableau de l'app. Les autres (carrés vides) suivent,
tous tirés des données DVF déjà en base : aucune nouvelle source à intégrer.
- Entrée : DVF géolocalisées d'Etalab ({PERIODE}, {n(F['dvf_lignes_csv'])} lignes → {n(F['dvf_mutations'])} ventes), qui ne contiennent
  pas que des logements : en {F['annee_fin']}, {n(F['dvf_locaux_fin'])} ventes de locaux commerciaux ou industriels et
  {n(F['dvf_terrains_fin'])} ventes de terrains sans bâti. Plus le référentiel geo.api.gouv.fr (communes, contours).
- Traitement : regroupement des lignes par vente, marquage des ventes douteuses et hors marché, puis agrégats Spark
  par commune, département et région, par type de bien et par année. Chaque indicateur a son contrôle SQL, comme la médiane aujourd'hui.
Indicateurs, et ce qu'ils apportent :
- Prix médian au m² et évolution (en place) : le niveau des prix.
- Volume de ventes et son évolution (en place) : le dynamisme du marché, utile pour les franchises.
- Quartiles et écart entre les 10 % les plus chers et les 10 % les moins chers (D9/D1) : la dispersion des prix
  à l'intérieur d'une zone, première mesure d'inégalité (en place).
- Prix médian d'un bien et surface médiane (en place) : le budget réel d'un acheteur, pas seulement le prix au m².
- Prix par taille, du T1 au T5 et plus : le marché des petites surfaces et celui des familles.
- Part du neuf (VEFA) et part des maisons : construction et type de tissu urbain.
- Locaux commerciaux au m² : le coût d'implantation, directement utile pour les franchises
  (demande d'ajouter la surface des locaux au chargement, aujourd'hui seule celle des logements est retenue).
- Terrains à bâtir : le potentiel de construction.
- Densité des ventes : presque toutes les ventes ont une position GPS, d'où une carte de chaleur, type de carte cité par le sujet.
Dans l'app : chaque indicateur devient un choix de la carte, avec le même tableau croisé, triable et exportable.
""")


def s12_domaine_texte(prs):
    fiche_pipeline(
        prs, 12, "Domaine texte  ·  14/12 – 10/01", "Domaine 2 : analyse de texte",
        [("OBJECTIF", "Qualifier l'état des logements et la perception des quartiers"),
         ("ENTRÉE", f"{F['annonces']} annonces Orpi (MongoDB) · une source d'avis d'habitants"),
         ("TRAITEMENT", "Caractéristiques des annonces, sentiment des avis, agrégés par commune")],
        [("Annonces à rénover", False), ("Thèmes les plus cités", False), ("Sentiment moyen", False)],
        "Nouvelles couches de la carte, fiche territoire avec thèmes et extraits",
        f"""
Le sujet exige une source textuelle traitée, pas une liste de commentaires (l'exemple des « rats » dans les avis).
- Objectif : décrire l'état des logements et la perception des quartiers, commune par commune.
- Entrée : les {F['annonces']} annonces Orpi déjà en base (description en texte libre, dans MongoDB), puis une source d'avis
  réels, choisie en vérifiant ses conditions d'utilisation comme pour Orpi.
- Traitement (ADR-042, deux branches) :
  1. caractéristiques extraites des annonces : « travaux », « rénovation », « balcon »… (la recherche plein texte
     trouve déjà {F['annonces_texte_balcon']} annonces avec « balcon ») ;
  2. sentiment calculé sur les avis, avec un modèle de langue français pré-entraîné, choisi et documenté comme le demande le sujet.
  Les descriptions d'annonces ne servent pas au sentiment : c'est du texte publicitaire, positif par construction.
  Résultat par document dans MongoDB, agrégats par commune dans PostgreSQL (même clé INSEE).
Indicateurs :
- Part d'annonces à rénover : où se concentrent les logements à remettre en état (lien avec les passoires du DPE).
- Thèmes les plus cités : ce qui revient dans les annonces et les avis d'une commune.
- Sentiment moyen : la perception d'un quartier par ses habitants.
- Dans l'app : couches de la carte, et la fiche territoire (thèmes les plus cités, extraits).
""")


def s13_domaine_socio(prs):
    fiche_pipeline(
        prs, 13, "Domaine socio-éco  ·  11/01 – 31/01", "Domaine 3 : socio-éco et risques",
        [("OBJECTIF", "Répondre aux deux questions métier : franchises et inégalités"),
         ("ENTRÉE", f"Revenus, population, DPE, argiles, +{F['sources_restantes']} sources open data · prix du domaine 1"),
         ("TRAITEMENT", "Une ingestion par source, jointure INSEE, écarts, score pondéré")],
        [("Taux d'effort", False), ("Écart de revenus D9/D1", False), ("Passoires thermiques", False),
         ("Exposition aux argiles", False), ("Population, chômage", False), ("Score franchises pondéré", False)],
        "Couches de la carte, comparateur de zones, classement du scoring",
        f"""
Le domaine qui sert directement les deux questions métier (slide 7).
Ce n'est pas un pipeline unique : chaque source a sa propre ingestion (bronze → argent), avec son format et son
rythme de mise à jour, puis un calcul commun produit les indicateurs (argent → or). Ajouter une source = ajouter une ingestion.
- Objectif : « Où ouvrir les 10 prochaines franchises ? » et « Comment réduire les inégalités dans mon département ? ».
- Entrée : {F['sources_palier1']} sources open data (revenus INSEE Filosofi, population INSEE, diagnostics énergétiques ADEME,
  risque retrait-gonflement des argiles Géorisques) et {F['sources_restantes']} autres pour atteindre {F['sources_visees']} : établissements scolaires,
  gares, chômage localisé, Base Adresse Nationale, source d'avis. Plus les indicateurs de prix du domaine 1.
- Traitement : standardisation sur le code INSEE (communes fusionnées comprises), jointure avec les prix,
  écarts entre communes d'un même département, score normalisé dont l'utilisateur règle les poids.
Indicateurs :
- Taux d'effort : prix médian d'un bien rapporté au revenu médian, en années de revenu. Croise les domaines 1 et 3.
- Écart de revenus D9/D1 (Filosofi) : les inégalités de revenus dans la commune.
- Passoires thermiques : part de logements classés F ou G au DPE.
- Exposition aux argiles : risque pour le bâti, la question climat du sujet.
- Population, croissance et chômage : la demande locale.
- Score franchises : somme pondérée de critères normalisés (population, revenu, dynamisme des ventes, prix des locaux
  commerciaux…), poids réglés par l'utilisateur.
- Dans l'app : chaque indicateur devient une couche de la carte ; le comparateur met des zones côte à côte ;
  le scoring classe les zones selon les poids choisis ; tableau croisé, filtrable et exportable aux {F['echelles']} échelles.
""")


def s14_feuille_de_route(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fond(s, BLANC)
    entete(s, 14, "Feuille de route", "Quatre paliers jusqu'au rendu du 7 février")
    paliers = [
        ("23/11 – 13/12", "Spark sur OVHcloud", "Pipelines déployés automatiquement"),
        ("14/12 – 10/01", "Analyse de texte", "Annonces et avis"),
        ("11/01 – 31/01", "Socio-éco", f"Revenus, DPE, risques · {F['sources_visees']} sources"),
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
Nous sommes au début du premier palier, déjà entamé : le pipeline du domaine prix est écrit et vérifié en local. Chaque palier ajoute une brique sur le socle existant, sans rien
reconstruire : même clé (code INSEE), mêmes bases, même mécanisme de contrôles PASS/FAIL.
1. 23/11 – 13/12 : priorité à la plateforme. Spark sur OVHcloud Data Platform (slide 10) et déploiement
   automatisé des pipelines de données : ingestion, nettoyage, calcul, contrôles. C'est l'investissement qui rend
   les paliers suivants rapides — une nouvelle donnée ou un nouveau calcul devient un job de plus.
   Organisation en domaines et couches bronze / argent / or (slide 5) ; le domaine prix (slide 11), dont le pipeline
   est prêt (slide 10), est le premier déployé : création des ressources, workflow planifié, puis les autres domaines.
2. 14/12 – 10/01 : analyse de texte (domaine texte, slide 12). Caractéristiques extraites des annonces (« travaux », « rénovation »…) et
   sentiment calculé sur une source d'avis, agrégés par commune ; méthode et modèle documentés comme l'exige le sujet.
3. 11/01 – 31/01 : {F['sources_palier1']} sources socio-économiques et risques (revenus INSEE Filosofi, population, DPE ADEME,
   retrait-gonflement des argiles) et {F['sources_restantes']} autres pour atteindre {F['sources_visees']}, intégrées par les pipelines du
   palier 1 (domaine socio-éco, slide 13) ; pages Fiche territoire et Comparateur (slide 7).
4. 01/02 – 07/02 : gel des fonctionnalités, documentation (schéma, méthodologie de nettoyage, IA), répétition.
Merci — questions ?
""")


def main():
    prs = Presentation()
    prs.slide_width, prs.slide_height = L, H
    for f in (s01_titre, s02_etapes, s03_sources, s04_bases, s05_architecture, s06_nettoyage, s07_application,
              s08_demo, s09_evolution, s10_cloud, s11_domaine_prix, s12_domaine_texte, s13_domaine_socio,
              s14_feuille_de_route):
        f(prs)
    prs.save(SORTIE)
    print(f"-> {SORTIE.name} ({len(prs.slides)} slides)")


if __name__ == "__main__":
    main()
