"""
Charge KaDo.csv (7,2 M lignes) dans le schéma en étoile kado.* de PostgreSQL.

Rejouable : le schéma est recréé à l'identique (IF NOT EXISTS) et les tables sont
vidées puis rechargées dans une seule transaction — un échec laisse l'état précédent.

Usage : python db/load_kado.py
"""

import time

from config import DB_DIR, postgres

KADO_CSV = DB_DIR.parent / "bootstrap" / "data" / "KaDo.csv"

STAGING = """
CREATE TEMP TABLE kado_brut (
    ticket_id   bigint,
    mois_vente  smallint,
    prix_net    numeric,
    famille     text,
    univers     text,
    maille      text,
    libelle     text,
    cli_id      bigint
) ON COMMIT DROP
"""

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre"]

REMPLISSAGE = """
INSERT INTO kado.dim_client (cli_id)
SELECT DISTINCT cli_id FROM kado_brut;

-- DISTINCT sur les 4 colonnes : si un libellé avait deux catégories différentes,
-- la contrainte UNIQUE (libelle) ferait échouer le chargement au lieu d'en choisir une.
INSERT INTO kado.dim_produit (libelle, famille, univers, maille)
SELECT DISTINCT libelle, famille, univers, maille FROM kado_brut;

INSERT INTO kado.fait_vente (ticket_id, cli_id, produit_id, mois_vente, prix_net)
SELECT b.ticket_id, b.cli_id, p.produit_id, b.mois_vente, b.prix_net
FROM kado_brut b JOIN kado.dim_produit p USING (libelle);
"""


def main():
    t0 = time.time()
    with postgres() as conn, conn.cursor() as cur:
        cur.execute((DB_DIR / "postgres" / "kado.sql").read_text(encoding="utf-8"))
        cur.execute("TRUNCATE kado.fait_vente, kado.dim_client, kado.dim_produit, kado.dim_temps "
                    "RESTART IDENTITY")

        cur.executemany(
            "INSERT INTO kado.dim_temps (mois_vente, nom_mois, trimestre) VALUES (%s, %s, %s)",
            [(m, MOIS[m - 1], (m - 1) // 3 + 1) for m in range(1, 13)],
        )

        cur.execute(STAGING)
        with KADO_CSV.open("rb") as f, cur.copy("COPY kado_brut FROM STDIN WITH (FORMAT csv, HEADER true)") as copy:
            while chunk := f.read(1 << 20):
                copy.write(chunk)
        print(f"KaDo : {cur.execute('SELECT count(*) FROM kado_brut').fetchone()[0]} lignes copiées "
              f"({time.time() - t0:.0f} s)")

        cur.execute(REMPLISSAGE)
        for table in ["dim_client", "dim_produit", "dim_temps", "fait_vente"]:
            n = cur.execute(f"SELECT count(*) FROM kado.{table}").fetchone()[0]
            print(f"kado.{table} : {n} lignes")

    with postgres() as conn:
        conn.autocommit = True
        conn.execute("VACUUM ANALYZE kado.fait_vente")
    print(f"KaDo chargé en {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
