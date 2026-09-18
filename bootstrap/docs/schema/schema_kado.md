# Modélisation en étoile — KaDo

Source : `bootstrap/data/KaDo.csv` (données brutes de tickets de caisse, 7 colonnes descriptives + 1 mesure).
Exploration : `bootstrap/scripts/explore_kado.py` (profilage exécuté via PySpark sur le fichier complet, résultats ci-dessous).

## Constats sur les données (avant modélisation)

| Constat | Valeur | Impact sur le schéma |
|---|---|---|
| Volume | 7 245 522 lignes, 0 valeur nulle sur les 8 colonnes | Grain = 1 ligne = 1 article vendu dans un ticket |
| Tickets distincts | 2 734 841 | `TICKET_ID` = dimension dégénérée (aucun attribut propre en dehors de ce qui est déjà dans les autres dimensions) |
| Clients distincts | 853 514 | Chaque `TICKET_ID` n'est associé qu'à **un seul** `CLI_ID` (vérifié : 0 ticket multi-client) |
| Hiérarchie produit | 9 `FAMILLE`, 105 `UNIVERS`, 34 `MAILLE`, 1484 `LIBELLE` | Chaque `UNIVERS` appartient à **exactement une** `FAMILLE` (hiérarchie propre FAMILLE→UNIVERS). En revanche **30 des 34 `MAILLE`** apparaissent sous plusieurs `UNIVERS` différents → `MAILLE` n'est **pas** un sous-niveau de `UNIVERS`, c'est un attribut transverse de classification produit. Chaque `LIBELLE` a toujours la même combinaison (FAMILLE, UNIVERS, MAILLE) → pas d'ambiguïté sur le produit lui-même. |
| Temporalité | `MOIS_VENTE` ∈ [1, 12], pas de colonne année | Le dataset ne couvre a priori qu'une seule année (ou l'année n'est pas trackée) — **à confirmer** : si les tickets couvrent en réalité plusieurs années, `MOIS_VENTE` seul ne suffit pas à les distinguer (risque de mélanger des mois de calendrier différents). Décision retenue pour ce bootstrap : dimension `Dim_Temps` au grain mois calendaire (1-12), à étendre avec une année si une source complémentaire l'apporte. |

## Schéma retenu

```
                     ┌──────────────┐
                     │  Dim_Client  │
                     │──────────────│
                     │ cli_id (PK)  │
                     └──────┬───────┘
                            │
┌───────────────┐    ┌──────▼────────────┐    ┌───────────────┐
│  Dim_Temps    │    │   Fait_Ventes     │    │  Dim_Produit  │
│───────────────│    │───────────────────│    │───────────────│
│ mois_vente(PK)├────┤ ticket_id (DD)    ├────┤ produit_id(PK)│
└───────────────┘    │ mois_vente (FK)   │    │ libelle       │
                     │ cli_id (FK)       │    │ famille       │
                     │ produit_id (FK)   │    │ univers       │
                     │ prix_net (mesure) │    │ maille        │
                     └───────────────────┘    └───────────────┘
```

(DD = dimension dégénérée : conservée directement dans la table de faits, sans table dédiée, car sans attribut propre.)

### Fait_Ventes

Grain : **1 ligne = 1 article vendu dans un ticket**.

| Colonne | Type | Rôle |
|---|---|---|
| `ticket_id` | int | Dimension dégénérée — identifie le panier d'achat |
| `cli_id` | int (FK → Dim_Client) | Client ayant réalisé l'achat |
| `mois_vente` | int (FK → Dim_Temps) | Mois de la vente |
| `produit_id` | int (FK → Dim_Produit) | Produit vendu (surrogate key générée depuis `LIBELLE`, absent des données sources) |
| `prix_net` | double (mesure) | Prix net de la ligne |

### Dim_Client

| Colonne | Type |
|---|---|
| `cli_id` (PK) | int |

Aucun attribut démographique disponible dans KaDo — dimension minimale pour l'instant, à enrichir si une source client complémentaire est intégrée dans le projet Homepedia complet.

### Dim_Produit

| Colonne | Type |
|---|---|
| `produit_id` (PK) | int (surrogate key sur `LIBELLE`) |
| `libelle` | string |
| `famille` | string |
| `univers` | string |
| `maille` | string |

`famille`, `univers`, `maille` sont conservés comme **attributs plats** de la dimension (pas de snowflake), car `MAILLE` ne descend pas hiérarchiquement de `UNIVERS` (cf. constats ci-dessus). Filtrer/regrouper par `FAMILLE > UNIVERS` est fiable ; regrouper par `MAILLE` doit être traité indépendamment de `UNIVERS`.

### Dim_Temps

| Colonne | Type |
|---|---|
| `mois_vente` (PK) | int (1-12) |

## Requêtes types permises par ce schéma

- Chiffre d'affaires par mois, par famille, par client
- Top produits par univers ou par maille (indépendamment)
- Panier moyen par ticket (`SUM(prix_net) GROUP BY ticket_id`)
- Fréquence d'achat par client (`COUNT(DISTINCT ticket_id) GROUP BY cli_id`)
