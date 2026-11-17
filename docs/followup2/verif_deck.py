"""
Follow-up 2 — contrôle PASS/FAIL du deck, sans relecture humaine.

- chaque nombre visible ET dans les notes existe dans faits.json (hors dates et constantes de méthode) ;
- au plus 30 mots de contenu par slide (navigation exclue : rubrique, pied, index 01-04 ; dates exclues),
  100 pour les slides de fond marquées « dense » (architecture et fiches domaines, demandé par Nicolas le 2026-11-17) ;
- notes speaker non vides ; aucune forme à coins arrondis ; entre 8 et 16 slides ;
- aucune forme ne dépasse de la slide.

Usage : docs/followup2/.venv/Scripts/python docs/followup2/verif_deck.py
"""

import json
import re
import sys
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

ICI = Path(__file__).resolve().parent
DECK = ICI / "Homepedia_Follow-up_2.pptx"
FAITS = json.loads((ICI / "faits.json").read_text(encoding="utf-8"))

MOTS_MAX = 30
MOTS_MAX_DENSE = 100
# Nombres légitimes qui ne sont pas des faits de la base : numéros de slide, constantes de méthode
# (bornes 200-30 000 €/m² du job Spark, horizon de 15 ans cité par le sujet), port de l'app, identifiants.
CONSTANTES = {200, 30000, 15, 901, 2026, 2027, 8501} | set(range(1, 17))
MOIS = r"(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)"
DATE = re.compile(r"\b\d{1,2}/\d{1,2}\b")
NOMBRE = re.compile(r"\d+(?:[  ]\d{3})*(?:,\d+)?")  # milliers : espace fine insécable, cf. n()
MOT = re.compile(r"[A-Za-zÀ-ÿ0-9]+(?:['’][A-Za-zÀ-ÿ]+)?")

echecs = []


def controle(ok, message):
    print(("PASS " if ok else "FAIL ") + message)
    if not ok:
        echecs.append(message)


def nombres(texte):
    texte = DATE.sub(" ", texte)                                              # 23/11
    texte = re.sub(rf"\b\d{{1,2}}\s+{MOIS}(\s+\d{{4}})?", " ", texte)         # 7 février 2027
    texte = re.sub(r"T-DAT-901|DVF\s?2022|\b\d+(e|er|ème)\b", " ", texte)     # identifiants, 6e arrondissement
    for m in NOMBRE.finditer(texte):
        brut = m.group()
        yield brut, float(re.sub(r"[  ]", "", brut).replace(",", "."))


def textes(slide, chrome=True):
    """Textes de la slide, un par forme ; chrome=False exclut la navigation."""
    return [sh.text_frame.text for sh in slide.shapes
            if sh.has_text_frame and (chrome or not sh.name.startswith("chrome"))]


def main():
    prs = Presentation(DECK)
    # Valeur absolue : une variation « −7,3 % » est lue 7,3 (le signe est typographique, pas dans le nombre)
    valeurs = {abs(float(v)) for v in FAITS.values()} | {float(c) for c in CONSTANTES}
    controle(8 <= len(prs.slides) <= 16, f"nombre de slides : {len(prs.slides)} (attendu 8-16)")
    for i, slide in enumerate(prs.slides, 1):
        note = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""
        mots = len(MOT.findall(DATE.sub(" ", "\n".join(textes(slide, chrome=False)))))
        limite = MOTS_MAX_DENSE if slide.name == "dense" else MOTS_MAX
        controle(mots <= limite, f"slide {i} : {mots} mots de contenu (max {limite})")
        controle(len(note.strip()) > 80, f"slide {i} : notes speaker présentes ({len(note.strip())} car.)")
        inconnus = [b for t in textes(slide) + [note] for b, v in nombres(t) if v not in valeurs]
        controle(not inconnus, f"slide {i} : nombres traçables dans faits.json" +
                 (f" — inconnus : {inconnus}" if inconnus else ""))
        arrondis = [sh.name for sh in slide.shapes if sh.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE
                    and "ROUND" in str(sh.auto_shape_type).upper()]
        controle(not arrondis, f"slide {i} : aucune forme à coins arrondis" + (f" — {arrondis}" if arrondis else ""))
        hors = [sh.name for sh in slide.shapes if sh.left < 0 or sh.top < 0
                or sh.left + sh.width > prs.slide_width or sh.top + sh.height > prs.slide_height]
        controle(not hors, f"slide {i} : aucune forme hors cadre" + (f" — {hors}" if hors else ""))
    # Le déroulé de démo cite des prix en clair : ils doivent être ceux de la base
    demo = (ICI / "demo.md").read_text(encoding="utf-8")
    prix = [int(p.replace(" ", "")) for p in re.findall(r"(\d{1,3}(?: \d{3})*) €/m²", demo)]
    faux = [p for p in prix if p not in FAITS.values()]
    controle(prix and not faux, f"demo.md : {len(prix)} prix cités, tous dans faits.json" + (f" — inconnus : {faux}" if faux else ""))
    print(f"\n{'PASS' if not echecs else 'FAIL'} — {len(echecs)} échec(s)")
    sys.exit(1 if echecs else 0)


if __name__ == "__main__":
    main()
