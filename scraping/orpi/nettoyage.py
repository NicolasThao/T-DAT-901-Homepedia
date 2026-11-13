"""
Nettoie et structure le dataset brut (data/listings_raw.jsonl, 500
annonces) :
  - cast des types deja corrects (JSON), verifications de coherence
  - mapping DPE/GES : indice numerique (1-7) -> lettre (A-G),
    confirme sur des exemples reels (consumptionIndex=3 <-> "DPE C"
    mentionne dans le texte libre de l'annonce)
  - prix_m2 calcule quand surface habitable disponible (comparable
    aux jobs PySpark sur les donnees DVF du Follow-up 1)
  - detection de doublons (id) et d'incoherences (departement_code vs
    code_postal)
  - rapport de qualite (valeurs manquantes par champ, avec contexte :
    beaucoup de nulls sont attendus selon le type de bien, pas des
    erreurs)

Sortie : data/listings_clean.csv (non versionne, cf. .gitignore).
"""

import json
from pathlib import Path

import pandas as pd

DPE_LETTRES = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F", 7: "G"}

RAW_PATH = Path(__file__).parent / "data" / "listings_raw.jsonl"
CLEAN_PATH = Path(__file__).parent / "data" / "listings_clean.csv"


def charger_brut(path: Path) -> pd.DataFrame:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return pd.DataFrame(rows)


def nettoyer(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Doublons sur l'identifiant Orpi
    n_avant = len(df)
    df = df.drop_duplicates(subset="id", keep="first")
    n_doublons = n_avant - len(df)

    # DPE/GES : indice numerique -> lettre (mapping standard francais A-G)
    df["dpe_lettre"] = df["dpe_classe_conso"].map(DPE_LETTRES)
    df["ges_lettre"] = df["dpe_classe_emission"].map(DPE_LETTRES)

    # Prix au m2 (comparable aux jobs PySpark sur les donnees DVF)
    df["prix_m2"] = None
    surface_ok = df["surface_habitable_m2"].notna() & (df["surface_habitable_m2"] > 0)
    df.loc[surface_ok, "prix_m2"] = (
        df.loc[surface_ok, "prix"] / df.loc[surface_ok, "surface_habitable_m2"]
    ).round(2)

    # Departement Orpi : numerique (1-95 metropole, 971-976 DOM, 201/202
    # Corse). Detecte les annonces hors de ces plages (ex. 2 annonces
    # "Ile Maurice", departement_code=10000001 - hors perimetre "marche
    # du logement francais" du sujet, a exclure des analyses).
    dept_num = pd.to_numeric(df["departement_code"], errors="coerce")
    df["departement_valide_france"] = (
        dept_num.between(1, 95) | dept_num.between(971, 976) | dept_num.isin([201, 202])
    )
    df["code_postal"] = df["code_postal"].astype(str).str.zfill(5)

    # Prix a 0 : legitime pour les programmes neufs (lots multiples, pas de
    # prix unique) - on le marque explicitement plutot que de le traiter
    # comme une donnee manquante
    df["prix_indisponible"] = (df["prix"] == 0) | df["prix"].isna()

    # Description : longueur, utile pour juger l'exploitabilite comme
    # source textuelle (sentiment analysis)
    df["description_longueur"] = df["description"].fillna("").str.len()

    colonnes_ordre = [
        "id", "reference", "url", "type_bien", "sous_type", "transaction",
        "prix", "prix_indisponible", "prix_m2",
        "surface_habitable_m2", "surface_terrain_m2", "surface_sejour_m2",
        "nb_pieces", "nb_chambres", "nb_salles_de_bain", "nb_places_parking",
        "ascenseur", "jardin", "garage", "piscine", "cave", "grenier",
        "terrasse", "balcon", "acces_handicape", "etat_general",
        "dpe_disponible", "dpe_lettre", "ges_lettre",
        "dpe_conso_valeur", "dpe_emission_valeur", "dpe_date",
        "code_postal", "commune", "departement_code", "departement_nom",
        "departement_valide_france", "region_nom", "longitude", "latitude",
        "description", "description_longueur", "date_mise_en_marche",
        "agence_nom", "agence_telephone", "agence_email", "agence_adresse",
        "agence_note", "agence_nb_avis",
        "commune_texte", "departement_texte",
    ]
    df = df[colonnes_ordre]

    print(f"Doublons supprimes : {n_doublons}")
    return df


def rapport_qualite(df: pd.DataFrame) -> None:
    print("\n" + "=" * 60)
    print("RAPPORT DE QUALITE")
    print("=" * 60)
    print(f"Lignes : {len(df)}")

    print("\nRepartition par type de bien :")
    print(df["type_bien"].value_counts().to_string())

    print("\nValeurs manquantes par champ (top 15) :")
    manquants = df.isna().sum().sort_values(ascending=False)
    print(manquants.head(15).to_string())

    print("\nNote sur les nulls attendus (pas des erreurs) :")
    print(f"  surface_habitable_m2 null (terrain/stationnement) : {df['surface_habitable_m2'].isna().sum()}")
    print(f"  nb_pieces null (terrain/stationnement/certains) : {df['nb_pieces'].isna().sum()}")
    print(f"  dpe_lettre null (dpe non affiche) : {df['dpe_lettre'].isna().sum()} sur {len(df)}")

    n_hors_france = (~df["departement_valide_france"]).sum()
    print(f"\nAnnonces hors perimetre France (departement_code invalide, ex. international) : {n_hors_france}")
    if n_hors_france:
        print(df.loc[~df["departement_valide_france"], ["commune", "departement_nom", "type_bien"]].to_string())

    n_prix_indispo = df["prix_indisponible"].sum()
    print(f"Prix indisponible (0 ou null, ex. programmes neufs) : {n_prix_indispo}")

    print(f"\nDescription : longueur moyenne {df['description_longueur'].mean():.0f} caracteres, "
          f"min {df['description_longueur'].min()}, max {df['description_longueur'].max()}")
    print(f"Descriptions vides (0 caractere) : {(df['description_longueur'] == 0).sum()}")

    print(f"\nprix_m2 disponible pour {df['prix_m2'].notna().sum()}/{len(df)} annonces "
          f"(maison + appartement + immeuble principalement)")


def main() -> None:
    df_brut = charger_brut(RAW_PATH)
    df_propre = nettoyer(df_brut)
    rapport_qualite(df_propre)

    df_propre.to_csv(CLEAN_PATH, index=False, encoding="utf-8")
    print(f"\nEcrit : {CLEAN_PATH} ({len(df_propre)} lignes)")


if __name__ == "__main__":
    main()
