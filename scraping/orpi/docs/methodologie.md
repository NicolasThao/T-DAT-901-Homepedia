# Méthodologie de sourcing — Annonces Orpi

Source complémentaire au Follow-up 1 (KaDo + DVF). Documente la collecte d'un échantillon d'annonces de vente immobilière pour le projet Homepedia, réutilisable telle quelle dans le rapport final.

---

## 1. Source

**Orpi** (`www.orpi.com`) — réseau coopératif de ~1 250 agences immobilières en France, l'un des plus gros réseaux du pays. Sitemap officiel des annonces de vente : `sitemap-biens-a-vendre-1.xml` (45 000+ URLs), un deuxième fichier `-2.xml` et un sitemap dédié aux locations (`sitemap-biens-a-louer.xml`) existent mais n'ont pas été utilisés dans cette itération (cf. Limites).

### Pourquoi Orpi et pas un autre site

Neuf sites d'annonces immobilières ont été évalués avant de retenir Orpi (pap.fr, SeLoger, leboncoin.fr, Century21, Laforêt, Guy Hoquet, avendrealouer.fr, ParuVendu, Stéphane Plaza Immobilier) :

| Site | Raison d'exclusion |
|---|---|
| pap.fr | `robots.txt` bloque nommément `python-requests` sur tout le site |
| SeLoger | `robots.txt` bloque `/list.htm` (recherche) et `/*/detail.htm` (fiches annonces) |
| leboncoin.fr | `robots.txt` : interdiction explicite d'accès automatisé + blocage nommé de `ClaudeBot`/`anthropic-ai` |
| Century21, Guy Hoquet | `robots.txt` bloque les endpoints de recherche/transaction |
| avendrealouer.fr | Mur anti-bot actif (DataDome) dès la requête du `robots.txt` — non contourné |

**Orpi** : le `robots.txt` autorise explicitement les pages `/annonce-vente-*` (absentes de la liste des `Disallow`), publie un sitemap officiel dédié aux annonces, et ne bloque nommément aucun outil de scraping.

---

## 2. Conformité `robots.txt` et éthique de collecte

- Aucune page visitée n'appartient aux chemins listés dans `Disallow` du `robots.txt` d'Orpi.
- **User-Agent honnête et identifiable** : `T-DAT-901-Epitech-bootstrap (usage pedagogique, contact: projet Homepedia Epitech)` — pas d'usurpation de navigateur.
- **Rate limit conservateur** : 1 requête/seconde + jitter aléatoire (0-0.3s), sans parallélisme.
- **Pas de retry agressif** : un échec (page morte, erreur réseau) est loggé et non re-tenté en boucle.
- **Arrêt automatique** prévu après 10 échecs consécutifs (signal probable de blocage) — non déclenché en pratique.
- **Volume raisonné** : 500 annonces sur un total de 45 000+ dans le sitemap (~1,1 %), collectées en une seule passe, pas de collecte répétée/continue à ce stade.
- Usage strictement académique et non commercial (projet Epitech T-DAT-901).

Résultat : **aucun blocage rencontré** (0 erreur 403/429/CAPTCHA) sur les 515 pages visitées.

---

## 3. Méthode de collecte

1. **Découverte des URLs** — parsing du sitemap officiel (`sitemap-biens-a-vendre-1.xml`, 45 000 URLs).
2. **Échantillonnage aléatoire** — tirage sans stratification forcée (`random.sample`, graine fixée à 42 pour reproductibilité), avec une marge de collecte de ×1,2 pour compenser le taux de pages mortes/redirigées observé en reconnaissance (~7 %).
3. **Extraction** — chaque page annonce Orpi embarque un bloc **JSON structuré complet** dans l'attribut HTML `data-estate="{...}"` (63 à 85 champs selon le type de bien : prix, surfaces, DPE/GES, coordonnées GPS, description, informations agence). Extraction directe de ce JSON plutôt qu'un parsing par classes CSS (non documentées, utilitaires génériques type Tailwind) — nettement plus fiable et complet.
4. **Nettoyage** — déduplication sur l'identifiant Orpi, conversion DPE/GES (indice numérique 1-7 → lettre A-G), calcul du prix au m², détection des annonces hors périmètre France.
5. **Vérification de cohérence** — comparaison croisée code postal / code département, recoupement avec le texte de l'annonce pour valider le mapping DPE (`DPE C` dans le texte ↔ `consumptionIndex: 3` dans le JSON, confirmé sur plusieurs exemples).

Scripts : `scraping/orpi/explore.py` (reconnaissance), `parser.py` (extraction), `collecte.py` (pipeline), `nettoyage.py` (structuration).

---

## 4. Volume et résultat

- **500 annonces de vente** collectées (sur 515 pages testées : 500 valides, 15 mortes/redirigées ≈ 2,9 %).
- Répartition par type conforme à celle du sitemap complet, ce qui valide la représentativité de l'échantillon aléatoire :

| Type | Échantillon (500) | Sitemap complet (45 000) |
|---|---|---|
| Maison | 48,6 % | 49,2 % |
| Appartement | 38,0 % | 38,6 % |
| Terrain | 9,8 % | 8,8 % |
| Immeuble | 2,6 % | 1,9 % |
| Stationnement | 0,8 % | 1,1 % |
| Programme neuf | 0,2 % | 0,4 % |

---

## 5. Champs extraits

| Champ | Description | Couverture |
|---|---|---|
| `type_bien`, `sous_type`, `transaction` | Type de bien, sous-type, nature de la transaction | 500/500 |
| `prix` | Prix affiché (€) | 499/500 (1 programme neuf sans prix fixe) |
| `surface_habitable_m2`, `surface_terrain_m2`, `surface_sejour_m2` | Surfaces (habitable, terrain, séjour) | 435/500 pour la surface habitable |
| `prix_m2` | Calculé, comparable aux jobs PySpark sur les données DVF | 435/500 |
| `nb_pieces`, `nb_chambres`, `nb_salles_de_bain`, `nb_places_parking` | Composition du bien | Variable selon le type |
| Équipements (`ascenseur`, `jardin`, `garage`, `piscine`, `cave`, `grenier`, `terrasse`, `balcon`, `acces_handicape`) | Booléens | 500/500 |
| `dpe_lettre`, `ges_lettre`, valeurs numériques, date | Performance énergétique | 380/500 (76 %) — DPE non toujours affiché |
| `code_postal`, `commune`, `departement_code`, `departement_nom`, `region_nom` | Localisation administrative | 500/500 |
| `longitude`, `latitude` | Géolocalisation précise | 500/500 — exploitable pour cartographie |
| `description` | Texte libre rédigé par l'agent (« avis de l'agent ») | 500/500, moyenne 983 caractères |
| `commune_texte`, `departement_texte` | Texte descriptif de la commune/département (démographie, commerces...) | Quasi systématique |
| `agence_nom`, `agence_telephone`, `agence_email`, `agence_adresse`, `agence_note`, `agence_nb_avis` | Agence en charge de l'annonce, réputation | 500/500 |

**Trois sources textuelles distinctes** dans ce seul dataset : la description de l'annonce, le texte descriptif de la commune/du département, et (dans le JSON brut, non repris dans le CSV structuré) des extraits d'avis clients de l'agence — exploitables pour l'exigence de sentiment analysis du sujet.

---

## 6. Limites connues

- **Échantillon, pas exhaustif** : 500 annonces sur 45 000+ disponibles dans un seul fichier sitemap. Représentatif par type (cf. tableau ci-dessus), mais pas garanti représentatif géographiquement (pas de stratification par département).
- **2 annonces hors périmètre France** détectées (Île Maurice) et flagées via `departement_valide_france` — à exclure des analyses sur le marché français.
- **DPE incomplet** : 24 % des annonces n'affichent pas de DPE (dépend de si le vendeur/l'agence l'a renseigné).
- **Ventes uniquement** : les locations (`sitemap-biens-a-louer.xml`) n'ont pas été collectées dans cette itération — décision du plan, alignée avec le périmètre DVF déjà traité.
- **Un seul fichier sitemap sur deux** utilisé (`-1.xml`, pas `-2.xml`) — le volume total disponible est donc encore plus grand que les 45 000 URLs mentionnées.
- **Photo à un instant T** (collecte du 2026-09-21) : les annonces vendues/retirées depuis ne sont plus valides ; pas de mécanisme de mise à jour continue à ce stade.
- **Prix affichés, pas transactionnels** : contrairement au DVF (prix réellement payés), les prix Orpi sont des prix demandés — utile en complément mais pas directement comparable sans le signaler.

---

## 7. Usage prévu dans Homepedia

- **Complément aux données DVF** : le DVF donne les transactions passées, Orpi donne l'offre actuelle (prix demandés, biens disponibles) — comparaison prix demandé / prix de marché historique par zone.
- **Source textuelle pour sentiment/qualité** : descriptions d'annonces + textes communaux/départementaux + avis clients d'agences.
- **Cartographie** : coordonnées GPS précises pour des visualisations bubble/heat map, en complément des données communales agrégées du DVF.
