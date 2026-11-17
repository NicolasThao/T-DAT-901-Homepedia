"""Lectures PostgreSQL de l'app (lecture seule : l'app ne lit que la base, jamais les CSV)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "db"))
from config import postgres  # noqa: E402

TYPES_BIEN = ("Tous", "Appartement", "Maison")

# Zones affichées à chaque échelle. Paris, Lyon, Marseille : on affiche les arrondissements
# (DVF est codé par arrondissement) et pas la commune parente qui les recouvre.
ZONES = {
    "region": """
        SELECT code_region, nom, ST_AsGeoJSON(contour_carte, 5) FROM region
        WHERE %(parent)s::text IS NULL""",
    "departement": """
        SELECT code_departement, nom, ST_AsGeoJSON(contour_carte, 5) FROM departement
        WHERE code_region = %(parent)s""",
    "commune": """
        SELECT c.code_insee, c.nom, ST_AsGeoJSON(c.contour_carte, 5) FROM commune c
        WHERE c.code_departement = %(parent)s
          AND NOT EXISTS (SELECT 1 FROM commune a WHERE a.code_commune_parent = c.code_insee)""",
}


def periodes():
    with postgres() as conn:
        return [p for (p,) in conn.execute(
            "SELECT DISTINCT periode FROM indicateurs_prix ORDER BY periode DESC")]


def zones(niveau, parent, type_local, periode):
    """Zones d'une échelle (enfants de `parent`, ou toute la France pour les régions), avec leur indicateur.

    Renvoie une liste de dicts : code, nom, geometrie (GeoJSON), prix_m2_median, nb_ventes
    (None / 0 si aucune vente retenue dans la zone).
    """
    sql = f"""
        SELECT z.code, z.nom, z.geom, i.prix_m2_median, coalesce(i.nb_ventes, 0)
        FROM ({ZONES[niveau]}) AS z(code, nom, geom)
        LEFT JOIN indicateurs_prix i ON i.niveau_geo = %(niveau)s AND i.code_geo = z.code
             AND i.type_local = %(type_local)s AND i.periode = %(periode)s
        ORDER BY z.nom"""
    params = {"parent": parent, "niveau": niveau, "type_local": type_local, "periode": periode}
    with postgres() as conn:
        return [
            {"code": code, "nom": nom, "geometrie": json.loads(geom),
             "prix_m2_median": prix, "nb_ventes": nb}
            for code, nom, geom, prix, nb in conn.execute(sql, params)
        ]


def zones_series(niveau, parent, type_local):
    """Zones d'une échelle avec la série complète de leurs prix (toutes les années).

    Renvoie une liste de dicts : code, nom, geometrie, serie = [(periode, prix_m2_median, nb_ventes)].
    Ne dépend pas des années choisies : un seul passage en base (et en cache) par échelle et type de bien.
    """
    sql = f"""
        SELECT z.code, z.nom, z.geom, s.periodes, s.prix, s.ventes
        FROM ({ZONES[niveau]}) AS z(code, nom, geom)
        LEFT JOIN LATERAL (
            SELECT array_agg(periode ORDER BY periode) AS periodes,
                   array_agg(prix_m2_median ORDER BY periode) AS prix,
                   array_agg(nb_ventes ORDER BY periode) AS ventes
            FROM indicateurs_prix
            WHERE niveau_geo = %(niveau)s AND code_geo = z.code AND type_local = %(type_local)s) AS s ON true
        ORDER BY z.nom"""
    zones = []
    with postgres() as conn:
        for code, nom, geom, periodes, prix, ventes in conn.execute(
                sql, {"parent": parent, "niveau": niveau, "type_local": type_local}):
            zones.append({"code": code, "nom": nom, "geometrie": json.loads(geom),
                          "serie": list(zip(periodes or [], prix or [], ventes or []))})
    return zones


def zones_evolution(zones, debut, fin):
    """Ajoute à chaque zone de `zones_series` le prix et les ventes des années `debut` et `fin`
    (None / 0 si aucune vente retenue cette année-là). Renvoie de nouveaux dicts (le cache reste intact)."""
    resultat = []
    for z in zones:
        par_annee = {p: (px, n) for p, px, n in z["serie"]}
        (pd_, vd), (pf, vf) = par_annee.get(debut, (None, 0)), par_annee.get(fin, (None, 0))
        resultat.append({**z, "prix_debut": pd_, "ventes_debut": vd, "prix_fin": pf, "ventes_fin": vf})
    return resultat


def zone_au_point(niveau, parent, lat, lon):
    """Code de la zone affichée (même échelle, même parent) qui contient le point cliqué, ou None."""
    sql = f"""
        SELECT z.code FROM ({ZONES[niveau]}) AS z(code, nom, geom)
        JOIN {'commune' if niveau == 'commune' else niveau} t
          ON t.{'code_insee' if niveau == 'commune' else 'code_' + niveau} = z.code
        WHERE ST_Contains(t.contour_carte, ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326))
        LIMIT 1"""
    with postgres() as conn:
        ligne = conn.execute(sql, {"parent": parent, "lat": lat, "lon": lon}).fetchone()
    return ligne[0] if ligne else None


def nom_zone(niveau, code):
    table, colonne = {"region": ("region", "code_region"),
                      "departement": ("departement", "code_departement")}[niveau]
    with postgres() as conn:
        return conn.execute(f"SELECT nom FROM {table} WHERE {colonne} = %s", (code,)).fetchone()[0]


def ventes_non_localisees(periode):
    """Ventes qui passeraient le filtre du job Spark mais dont la commune DVF n'est plus au
    référentiel (communes fusionnées depuis) : absentes de la carte, on les compte."""
    with postgres() as conn:
        return conn.execute("""
            SELECT count(*) FROM mutation_dvf
            WHERE code_insee IS NULL AND date_mutation >= make_date(%s, 1, 1)
              AND date_mutation < make_date(%s + 1, 1, 1)
              AND NOT hors_marche AND NOT prix_m2_douteux AND nb_logements = 1
              AND type_local IN ('Maison', 'Appartement') AND prix_m2 BETWEEN 200 AND 30000""",
            (periode, periode)).fetchone()[0]
