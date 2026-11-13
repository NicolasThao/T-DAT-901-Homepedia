# Fiche — Le web scraping, expliqué avec la collecte Orpi

> Pour qui : étudiant·es qui débutent en data. Chaque notion est illustrée par le code réel du dossier `scraping/orpi/`.
> Méthodologie complète et chiffres : `scraping/orpi/docs/methodologie.md`.

---

## 1. De quoi parle-t-on ?

| Terme | Définition | Dans Homepedia |
|---|---|---|
| **Web scraping** | Extraire automatiquement des données d'une page web pour les structurer (tableau, JSON) | Extraire prix, surface, DPE, GPS... d'une annonce Orpi |
| **Crawling** | Parcourir des pages en suivant les liens pour les *découvrir* | Pas nécessaire ici : le sitemap donne directement la liste des URL |
| **Robot / bot** | Programme qui visite des pages sans humain derrière | `collecte.py` |
| **API** | Point d'accès prévu pour les machines, avec un format stable (souvent JSON) | À préférer quand elle existe (ex. `geo.api.gouv.fr` pour les communes) — le scraping est le plan B |
| **Donnée structurée / semi-structurée / non structurée** | Tableau à colonnes fixes / JSON à champs variables / texte libre | Prix (structuré), JSON `data-estate` (semi-structuré), description de l'annonce (non structuré) |

**Règle d'or : API d'abord, fichier open data ensuite, scraping en dernier.** Le scraping est fragile (le site change, la collecte casse) et soulève des questions de droit.

---

## 2. Le pipeline en 5 étapes

```
 sitemap XML ──► échantillon d'URL ──► requête HTTP ──► parsing HTML ──► JSONL brut ──► nettoyage ──► CSV propre ──► PostgreSQL / MongoDB
 (découverte)    (random, seed 42)    (1 req/s)       (JSON embarqué)   (1 ligne/annonce)  (pandas)
```

| Étape | Script | Idée clé |
|---|---|---|
| 1. Reconnaissance | `explore.py` | Regarder *ce que contient vraiment* une page avant d'écrire le parseur |
| 2. Extraction | `parser.py` | Transformer une page HTML en un dictionnaire à plat |
| 3. Collecte | `collecte.py` | Visiter les pages poliment, sauvegarder au fil de l'eau |
| 4. Nettoyage | `nettoyage.py` | Types, codes, doublons, valeurs hors domaine, rapport qualité |
| 5. Stockage | `db/load_postgres.py` | Relier l'annonce au référentiel (code INSEE de la commune) |

---

## 3. Avoir le droit de collecter : `robots.txt` et politesse

### `robots.txt`
Fichier public à la racine d'un site (`https://www.orpi.com/robots.txt`) qui dit aux robots ce qu'ils peuvent visiter. Protocole appelé **Robots Exclusion Protocol**.

```
User-agent: *          ← la règle s'applique à tous les robots
Disallow: /recherche   ← chemin interdit
Allow: /annonce-...    ← chemin autorisé
Sitemap: https://...   ← où trouver la liste des pages
```

Ce n'est pas une barrière technique, c'est une **règle de conduite** : la respecter est ce qui distingue une collecte éthique d'une collecte abusive. Nous avons évalué 9 sites et exclu ceux dont le `robots.txt` interdisait l'accès (pap.fr bloque nommément `python-requests`, leboncoin interdit tout accès automatisé).

### Le code de la politesse (`collecte.py`)

```python
USER_AGENT = "T-DAT-901-Epitech-bootstrap (usage pedagogique, contact: projet Homepedia Epitech)"
RATE_LIMIT_S = 1.0
JITTER_S = 0.3
MAX_CONSECUTIVE_ERREURS = 10
```

| Notion | Ce que ça veut dire | Pourquoi |
|---|---|---|
| **User-Agent** | En-tête HTTP qui dit « qui » fait la requête | On s'annonce honnêtement comme robot étudiant ; se faire passer pour un navigateur (*spoofing*) serait tromper le site |
| **Rate limiting** | Limiter le nombre de requêtes par seconde | 1 requête/s : on ne surcharge pas le serveur |
| **Jitter** | Petit délai aléatoire ajouté à chaque attente | Évite un rythme parfaitement régulier |
| **Pas de parallélisme** | Une requête à la fois | Même raison que le rate limit |
| **Disjoncteur** (*circuit breaker*) | Arrêt après 10 échecs consécutifs | Si le site nous bloque, on s'arrête au lieu d'insister |
| **Pas de retry agressif** | Un échec est noté, pas re-tenté en boucle | Re-tenter en boucle = marteler le serveur |

```python
time.sleep(RATE_LIMIT_S + random.uniform(0, JITTER_S))
```

### Protections anti-bot
Certains sites ajoutent des barrières : **CAPTCHA**, services comme **DataDome** ou Cloudflare, blocage d'adresse IP. **On ne les contourne pas** : c'est le signal clair que le site ne veut pas de robots (avendrealouer.fr a été écarté pour cette raison).

### Données personnelles (RGPD)
Principe de **minimisation** : ne garder que ce qui est utile. Le téléphone et l'e-mail des agences sont collectés dans le brut mais **ne sont pas chargés en base** (`db/postgres/schema.sql`, table `agence`).

---

## 4. HTTP en 2 minutes

| Élément | Exemple |
|---|---|
| **Requête GET** | `requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)` |
| **Timeout** | 15 s max d'attente, sinon erreur réseau (le script ne reste pas bloqué) |
| **Code 200** | OK |
| **Codes 301 / 302** | Redirection — l'annonce a souvent été retirée. `collecte.py` compare `resp.url != url` pour la détecter |
| **Code 404** | Page inexistante |
| **Code 403** | Accès interdit (souvent : on a été bloqué) |
| **Code 429** | *Too Many Requests* : on va trop vite |

Résultat de notre collecte : 515 pages visitées, 500 annonces valides, 15 pages mortes ou redirigées, **0 erreur 403/429**.

---

## 5. Découvrir les pages : le sitemap

Un **sitemap** est un fichier XML que le site publie pour les moteurs de recherche : la liste de ses pages.

```python
SITEMAP_URL = "https://www.orpi.com/sitemap-biens-a-vendre-1.xml"

def charger_urls_sitemap(sitemap_url):
    resp = requests.get(sitemap_url, headers={"User-Agent": USER_AGENT}, timeout=15)
    soup = BeautifulSoup(resp.content, "xml")
    return [loc.text.strip() for loc in soup.find_all("loc")]   # chaque <loc> = une URL
```

45 000+ URL récupérées en une seule requête, sans crawler le site.

---

## 6. Extraire les données : parsing HTML

### Méthode classique : sélecteurs CSS
Le HTML est un arbre (le **DOM**). On cible un élément par balise, classe ou id avec **BeautifulSoup** : `soup.select_one("span.price")`.
**Problème** : sur Orpi, les classes sont des utilitaires génériques (style Tailwind : `text-lg font-bold`...), qui ne disent rien du contenu et changent à chaque refonte → parseur **fragile**.

### Méthode retenue : le JSON embarqué
En inspectant une page (étape de **reconnaissance**, `explore.py`), on a trouvé que le site met toutes les données de l'annonce dans un attribut HTML, pour que son propre JavaScript affiche la carte :

```html
<div data-component="estate-poi-map" data-estate="{&quot;id&quot;:1492067,&quot;price&quot;:137000, ...}">
```

C'est un **attribut `data-*`** qui contient du JSON, avec les guillemets encodés en **entités HTML** (`&quot;`). Extraction (`parser.py`) :

```python
def extract_estate_json(page_html):
    marker = 'data-estate="'
    start = page_html.find(marker)
    ...
    decoded = htmlmod.unescape(raw)   # &quot; -> "
    return json.loads(decoded)        # texte JSON -> dictionnaire Python
```

**63 à 85 champs** par annonce (prix, surfaces, DPE/GES, GPS, description, agence, avis clients, texte sur la commune) — bien plus que ce qu'on aurait obtenu en lisant le texte affiché.

> Leçon réutilisable : avant d'écrire des sélecteurs CSS, chercher du **JSON déjà présent** dans la page (attributs `data-*`, balises `<script type="application/ld+json">`, `__NEXT_DATA__`...). On parle de données d'**hydratation**.

### Aplatir (*flatten*)
Le JSON est imbriqué (`estate["agency"]["reputation"]`). `parse_listing()` le transforme en un dictionnaire **à plat** (une clé = une future colonne), en protégeant les accès :

```python
agency = estate.get("agency") or {}      # .get() : pas de plantage si la clé manque
reputation = agency.get("reputation") or {}
```

---

## 7. Sauvegarder au fil de l'eau : JSONL

**JSONL** (*JSON Lines*) = un objet JSON par ligne.

```python
with output_path.open("a", encoding="utf-8") as f:          # "a" = append (ajout)
    f.write(json.dumps(row, ensure_ascii=False) + "\n")
    f.flush()                                                 # écrit tout de suite sur le disque
```

| Avantage | Pourquoi |
|---|---|
| **Écriture incrémentale** | Si le script plante à l'annonce 300, les 299 premières sont sauvées |
| **Append-only** | On ne réécrit jamais le fichier entier |
| **Lisible ligne par ligne** | Pas besoin de charger tout le fichier en mémoire |
| **Garde le brut** | On pourra re-nettoyer autrement sans re-scraper le site |

Séparer **brut** (`listings_raw.jsonl`) et **propre** (`listings_clean.csv`), c'est le principe des couches *raw → clean* (bronze → silver dans le vocabulaire *medallion*).

---

## 8. Échantillonner

```python
def echantillon_aleatoire(urls, n, seed):
    rng = random.Random(seed)                          # graine fixe
    n_tire = min(int(n * MARGE_SUR_ECHANTILLONNAGE), len(urls))
    return rng.sample(urls, n_tire)                    # tirage sans remise
```

| Notion | Explication |
|---|---|
| **Échantillon aléatoire simple** | Chaque annonce a la même chance d'être tirée |
| **Graine (*seed*)** | `seed=42` : relancer le script tire exactement les mêmes URL → **reproductibilité** |
| **Marge ×1,2** | On tire 600 URL pour en obtenir 500 valides (certaines pages sont mortes) |
| **Représentativité** | Vérifiée : 48,6 % de maisons dans l'échantillon contre 49,2 % dans le sitemap complet |
| **Stratification** | Tirer un quota par département garantirait la couverture géographique — non fait, c'est une limite connue |

---

## 9. Nettoyer (`nettoyage.py`)

| Problème | Traitement |
|---|---|
| **Doublons** | `drop_duplicates(subset="id")` sur l'identifiant Orpi |
| **Codes à décoder** | DPE/GES stockés en indice 1-7 → lettre A-G (`DPE_LETTRES`), mapping vérifié en recoupant avec le texte de l'annonce (« DPE C » ↔ indice 3) |
| **Valeurs hors domaine** | 2 annonces à l'île Maurice → marquées `departement_valide_france = False` |
| **Zéro qui veut dire « absent »** | Prix à 0 d'un programme neuf → `prix_indisponible = True` au lieu d'un faux prix |
| **Format** | Code postal complété sur 5 caractères (`zfill(5)`) : « 6130 » → « 06130 » |
| **Valeurs manquantes attendues** | Pas de surface habitable pour un terrain : ce n'est pas une erreur, le rapport qualité le distingue |

Un **rapport de qualité** (complétude par champ, répartition, cas limites) est imprimé à chaque nettoyage : on ne *suppose* pas que les données sont propres, on le *mesure*.

---

## 10. Relier aux autres sources

Une donnée scrapée n'a de valeur que si on peut la **joindre** aux autres sources. Clé commune de Homepedia : le **code INSEE** de la commune, pas le code postal (un code postal couvre souvent plusieurs communes).
`db/load_postgres.py` résout le code INSEE de chaque annonce (nom + code postal, puis position GPS dans le contour de la commune) : 498/500 résolues, les 2 restantes sont les annonces de l'île Maurice.

---

## 11. Pièges courants

| Piège | Parade |
|---|---|
| Scraper sans lire `robots.txt` | Toujours le lire en premier |
| Se faire passer pour un navigateur | User-Agent honnête |
| Parser des classes CSS instables | Chercher le JSON embarqué ou une API |
| Tout garder en mémoire et écrire à la fin | Écriture incrémentale (JSONL + `flush`) |
| Re-scraper à chaque essai de nettoyage | Garder le brut, re-nettoyer depuis le fichier |
| Comparer prix affiché et prix vendu | Orpi = prix **demandé**, DVF = prix **payé** : ce n'est pas la même chose |
| Oublier que la page vit | Une annonce est une photo à un instant T (collecte du 2026-09-21) |

---

## 12. Glossaire express

`robots.txt` · `Disallow` · sitemap · User-Agent · rate limit · jitter · disjoncteur · CAPTCHA · anti-bot · HTTP GET · code de statut · timeout · redirection · DOM · BeautifulSoup · sélecteur CSS · attribut `data-*` · entité HTML · JSON embarqué / hydratation · aplatissement · JSONL · append-only · brut / propre · seed · échantillonnage aléatoire / stratifié · représentativité · minimisation RGPD · code INSEE · géocodage inverse.
