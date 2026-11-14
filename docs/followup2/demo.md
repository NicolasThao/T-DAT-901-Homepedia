# Follow-up 2 — déroulé de la démo live (2026-11-20)

Chiffres de ce déroulé : `faits.json` (extraits de la base par `faits.py`, jamais recopiés).

## 1. Le matin même (J-0, ~5 min)

| # | Action | Attendu |
|---|---|---|
| 1 | Lancer Docker Desktop | icône baleine stable |
| 2 | `docker compose -p candidata stop` | Candidata arrêté (il publie aussi le port 5433) |
| 3 | `docker compose -f db/docker-compose.yml --env-file db/.env up -d --wait` | `homepedia-postgres-1` et `homepedia-mongo-1` *Healthy* |
| 4 | `.venv\Scripts\python db\check.py` | `PASS — 47/47 contrôles OK` |
| 5 | `.venv\Scripts\streamlit run app\main.py` | navigateur sur `http://localhost:8501` |
| 6 | Cliquer une fois France → Île-de-France → Paris, puis revenir à France | met les cartes en cache : la démo devant le jury est instantanée |
| 7 | Vérifier la connexion internet | le fond de carte (Esri) vient d'internet ; sans réseau, les zones colorées s'affichent quand même sur fond gris |
| 8 | Ouvrir le deck, onglet app prêt à côté (Alt+Tab) | — |

## 2. Le parcours (slide 7, ~2 min)

| Clic | Écran | Phrase |
|---|---|---|
| — | France par région, « Tous » | « Le prix médian au m² de chaque région, calculé par Spark sur les ventes réelles de 2022. L'Île-de-France est à 5 000 €/m². » |
| 1 | Clic sur l'Île-de-France → ses départements | « On descend d'une échelle. Paris : 10 760 €/m². » |
| 2 | Clic sur Paris → les 20 arrondissements | « Jusqu'à la commune — ici l'arrondissement, parce que DVF code Paris par arrondissement. » |
| 3 | Bouton « Appartement » | « Filtre par type de bien : appartements du 6e, 14 928 €/m². » |
| — | Tableau à droite, tri sur le prix, « Exporter en CSV » | « Le tableau reprend exactement les chiffres de la carte, il se trie et s'exporte. » |
| — | Zone grisée (dans un département rural) + légende sous la carte | « Moins de 30 ventes : on n'affiche pas de prix plutôt qu'un chiffre non significatif. Les limites de la donnée sont écrites sous la carte. » |
| — | Bouton « France » | retour, Alt+Tab vers le deck, slide 8 |

## 3. Plan B

| Problème | Réponse |
|---|---|
| Docker ne démarre pas / port 5433 occupé | `docker ps` : arrêter le conteneur qui tient 5433 ; sinon passer au plan B captures |
| App lente au premier clic | normal sans cache : faire l'étape 6 du J-0 |
| Rien ne marche | captures du parcours : `captures/1_france_app.png`, `2_ile_de_france_app.png`, `3_paris_app.png` (même parcours, mêmes chiffres) |

## 4. Répétition

| Date | Qui | Parcours complet | Durée | Remarque |
|---|---|---|---|---|
| 2026-11-14 | automatique (`captures.py`, Chrome headless) | France → Île-de-France → Paris : OK | 19 s (cache chaud, 3 temps d'attente de 3 s inclus) | clics placés par coordonnées géographiques, pas par pixel |
| *à faire* | Nicolas | deck + démo à voix haute | | |
