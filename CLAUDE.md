# Contexte du projet — sv-planning-entrainements

Ce repo héberge des outils web pour **Sporting Villette** (club de handball,
Villette d'Anthon, Isère) et ses ententes partenaires. Tout est construit
comme une **application HTML statique unique** (`index.html`), sans backend,
hébergée sur **GitHub Pages**. Elle lit ses données en direct depuis un
Google Sheet publié en CSV, et génère plusieurs documents (plannings
d'entraînement, "Team Book") entièrement côté navigateur. Elle affiche aussi
le calendrier/résultats FFHB du club, scrapés côté CI (voir section dédiée
plus bas) — le seul morceau du projet qui n'est pas 100% client-side.

Ce fichier a été rédigé pour transférer le contexte d'un travail fait avec
Claude (claude.ai) vers Claude Code, qui reprend la suite du développement.

## Hébergement

- Repo : `sportingvillette-beep/sv-planning-entrainements` (public)
- GitHub Pages activé : Settings → Pages → branche `main` / `(root)`
- URL publique : `https://sportingvillette-beep.github.io/sv-planning-entrainements/`
- **Important** : l'app fait des `fetch()` vers Google Sheets. Ces requêtes
  échouent si le fichier est ouvert en local (`file://...`) à cause de
  restrictions CORS/navigateur — il faut toujours tester via l'URL GitHub
  Pages ci-dessus, jamais en double-cliquant sur le fichier téléchargé.

## Source de données

- Google Sheet (édition) : `https://docs.google.com/spreadsheets/d/1viw-QLYXpA4jNV_bHhfCsBtJ8ueaC0ujXfqtPPpIAq0/edit?usp=sharing`
- Export CSV publié (utilisé par l'app, `Fichier > Partager > Publier sur le
  web > CSV`) :
  `https://docs.google.com/spreadsheets/d/e/2PACX-1vT3RqA-z8ANNaXXsYMgh4ynk8LV4EjOnkAqyThzFQ4TcxIUofmVlWg20wyfw-ZmeDettPCjkCgank_3/pub?output=csv`
- Onglet source : `Synthèse`
- **Bug ouvert / à investiguer** : le lien CSV répond correctement en
  `curl`/fetch serveur, mais un utilisateur a récemment eu une erreur
  `Failed to fetch` côté navigateur. Ce lien `pub?output=csv` fait une
  redirection 302 vers un hôte `doc-XX-XX-sheets.googleusercontent.com` —
  suspect principal : absence d'en-tête `Access-Control-Allow-Origin` sur la
  réponse finale après redirection dans certains cas (comportement Google
  possiblement inconsistant). À vérifier avant de conclure — pourrait aussi
  être un simple problème de test en `file://` (voir point ci-dessus) ou de
  cache GitHub Pages pas encore à jour.

### Colonnes du CSV (une ligne = une équipe)

```
Section, Indice équipe, Categorie, Années de naissance, Prix_Licence, Genre,
E1.Lieu, E1.Jour, E1. Debut, E1.Fin,   (jusqu'à E4 — 4 créneaux d'entraînement max)
E2.Lieu, E2.Jour, E2. Debut, E2.Fin,
E3.Lieu, E3.Jour, E3. Debut, E3.Fin,
E4.Lieu, E4.Jour, E4. Debut, E4.Fin,
Entraineur1, Entraineur2, Entraineur3, Entraineur4,
P1.Niveau, P1.Lien, P1.Poule,   (Phase 1 de championnat — P1.Lien pointe vers une page de poule FFHB)
P2.Niveau, P2.Lien, P2.Poule    (Phase 2, souvent vide en début de saison)
```

- `Lieu` est au format `"Ville - Gymnase"` (ex. `"Genas - Halle des Sports"`),
  toujours séparé par ` - `.
- `Jour` est en français, une valeur parmi `Lundi..Samedi` (pas de dimanche
  actuellement dans la logique — si un jour Dimanche apparaît dans les
  données, il sera silencieusement ignoré par les vues planning : à corriger
  si besoin en étendant le tableau `DAYS`).
- `P1.Lien` / `P2.Lien` sont des URLs vers des pages de poule sur
  `ffhandball.fr`, ex. :
  `https://www.ffhandball.fr/competitions/saison-2026-2027-22/regional/m18-ans-feminin-excellence-aura-30507/poule-190314/`
  — ces liens sont la base de la prochaine fonctionnalité (scraper FFHB, voir
  plus bas).

### 4 ententes/sections (valeurs exactes de la colonne `Section`)

```
Sporting Villette
Entente Villette Genas
Entente Lyon Est Handball (F)
Entente Est Lyonnais (G)
```

Couleurs associées (utilisées comme code couleur dans les vues) :
```js
{
  'Sporting Villette': '#0b5e8f',
  'Entente Villette Genas': '#2f7d4f',
  'Entente Lyon Est Handball (F)': '#a8452f',
  'Entente Est Lyonnais (G)': '#8a5aab',
}
```

### Villes (code couleur additionnel utilisé dans les vues "par équipe")

```js
{
  "Villette d'Anthon": '#c0392b',
  'Meyzieu': '#5dade2',
  'Genas': '#1a3a6b',
  'Saint-Priest': '#d4ac0d',
  'Janneyrias': '#2e7d32',
  'Vaulx-En-Velin': '#e67e22',
  'Corbas': '#16a085',
}
```

## Architecture de `index.html`

Fichier unique, pas de build, pas de dépendance externe (pas de CDN, pas de
librairie JS tierce). Structure interne :

1. **UI** (thème sombre) : boutons d'action, zone de résultat, statut.
2. **Logique de données** (fonctions `parseCSV`, `buildRecords`,
   `mergeRecords`, `finalLabel`) : parse le CSV en enregistrements par équipe,
   fusionne les lignes qui ont un horaire strictement identique (ex. deux
   équipes qui s'entraînent ensemble), calcule un libellé d'équipe.
3. **4 fonctions de rendu**, chacune retourne une chaîne HTML complète avec
   son propre `<style>` inline :
   - `renderEquipeComplet(merged)` — planning classique, jours en colonnes,
     équipes en lignes, avec légende et CSS en classes (usage : consultation
     libre / export).
   - `renderEquipeMinimal(merged)` — même contenu mais **sans classes CSS ni
     propriétés `display`/`padding`/`margin` en style inline** ; seulement
     `<br>`, `<b>`, `<i>` et `color`/`background-color`. Nécessaire car
     l'éditeur du site du club (SportsRégions) filtre agressivement le CSS
     collé — voir leçon ci-dessous.
   - `renderParGymnase(records)` — grille horaire (créneaux de 15 min) par
     gymnase, pour repérer les chevauchements. Amplitude horaire calculée
     dynamiquement par gymnase (pas de plage fixe). Fond jaune = chevauchement
     intégral (équipes regroupées, horaire identique) ; fond rouge = vrai
     conflit (chevauchement partiel, horaires différents).
   - `renderTeamBook(records, sectionName)` — génère une page de garde +
     une page par équipe (infos licence, entraînements, entraîneurs,
     niveau/poule championnat), format custom **100mm × 132mm** (calibré
     empiriquement pour tenir sur un "écran" de lecture mobile sans trop de
     vide, avec marge de sécurité pour le pire cas — 4 créneaux + 4
     entraîneurs + noms de gymnase longs qui retournent à la ligne).
4. **Génération PDF** : pas de librairie JS (voir leçon `html2pdf.js`
   ci-dessous). Utilise `window.print()` avec une règle CSS
   `@media print` qui masque tout sauf `#result-content`, plus une règle
   `@page` par vue pour forcer le bon format/orientation. L'utilisateur
   choisit "Enregistrer en PDF" dans la boîte de dialogue d'impression du
   navigateur.

## Leçons apprises (à ne pas refaire)

- **`file://` casse les `fetch()`** vers Google Sheets → toujours tester via
  l'URL GitHub Pages, jamais en local.
- **Google Drive n'exécute pas le HTML/JS** — un fichier `.html` déposé dans
  Drive ne fonctionne pas comme une page web, juste comme un fichier stocké.
- **`html2pdf.js` (rasterisation canvas) est peu fiable** : testé et
  abandonné — bug de pagination (doublait le nombre de pages à cause d'un
  mauvais calcul d'échelle canvas→PDF) et texte rendu en image (flou, non
  sélectionnable). Le rendu natif du navigateur (`window.print()` +
  `@media print` + `@page`) donne un résultat vectoriel fiable et est la
  méthode à privilégier pour tout futur export PDF.
- **Éditeurs CMS tiers (SportsRégions) filtrent le CSS** collé dans leurs
  champs de texte enrichi : ils ne gardent souvent que `color` et
  `background-color`, suppriment `display`, `font-weight`, `padding`,
  `margin`, `border`. D'où l'existence de `renderEquipeMinimal`, qui
  n'utilise que des balises HTML structurelles (`<br>`, `<b>`, `<i>`) plutôt
  que du CSS pour la mise en forme.
- **`@page { size: ... }` en CSS n'est respecté par un outil d'impression
  automatisé que si on force l'option correspondante** (ex. Playwright
  nécessite `prefer_css_page_size: true`) — sinon le format par défaut
  (souvent Letter portrait) prend le dessus silencieusement.
- **La zone d'aperçu de l'app a `max-height` + `overflow:auto`** — override
  impératif en `@media print` (`max-height:none; overflow:visible;`) sinon
  l'impression tronque le contenu à la hauteur visible à l'écran.

## Scraper FFHB (calendrier / résultats / classements)

Implémenté comme prévu ci-dessus dans la version précédente de ce fichier :
**pas de scraping côté navigateur** (CORS + Playwright indisponible dans un
onglet), mais un scraping côté CI (GitHub Actions) qui commite des fichiers
statiques que `index.html` lit en `fetch()` same-origin, exactement comme il
lit déjà le Google Sheet.

### Fichiers

- `scraper/scrape_ffhb.py` — briques de scraping réutilisables (Playwright +
  BeautifulSoup) : parcours des journées d'une poule FFHB, extraction
  calendrier/scores/classement, extraction gymnase/ville sur la page de
  détail d'un match. Utilisable aussi en CLI interactif en local
  (`python scrape_ffhb.py`) indépendamment du club — mono-poule/mono-équipe.
- `scraper/scrape_ffhb_club.py` — orchestrateur multi-équipes club. Deux
  modes :
  - **Interactif local** (`python scrape_ffhb_club.py`, sans argument) :
    menu 1/2, comme avant.
  - **CLI non interactif** (utilisé par le workflow) :
    `sync-mapping --mapping-dir scraper` puis
    `scrape --mapping-dir scraper --outdir data --teams <ids ou vide>`.
- `scraper/team_mapping.csv` — **versionné**, rapprochement nom d'équipe du
  sheet (`Section`+`Indice équipe`+`Categorie`+phase) ↔ nom d'équipe affiché
  sur ffhandball.fr. Colonne `id` = clé stable (slug) utilisée pour cibler
  une équipe depuis l'UI ou le `workflow_dispatch`.
- `data/calendrier_club.csv`, `data/classements_club.csv` — sorties
  consolidées, une ligne par match/par classement avec colonnes
  `section/indice/categorie/phase` en tête. Lues par `index.html`.
- `data/last_update.json` — `{ derniere_maj, mode, equipes_rafraichies,
  erreurs }`, affiché dans l'UI.
- `.github/workflows/scrape-ffhb.yml` — cron dimanche soir +
  `workflow_dispatch` (input `teams`, IDs séparés par virgules, vide = tout).

### Piège important : le "club porteur" d'une entente

Une entente de clubs (ex. `Entente Lyon Est Handball (F)`) fait jouer chaque
équipe sous licence d'un seul club membre ("club porteur"), pas sous le nom
de l'entente. La ligue liste souvent ce club porteur (ex. `ST PRIEST
HANDBALL`, `AS LYON CALUIRE`) plutôt que le nom de l'entente sur
ffhandball.fr — le rapprochement automatique (fuzzy matching sur mots-clés)
échoue ou se trompe silencieusement sur ces cas, surtout en tout début de
saison. C'est pour ça que `team_mapping.csv` **n'est jamais régénéré en
entier automatiquement** : `sync-mapping` n'ajoute que les lignes vraiment
nouvelles (nouvelle équipe/phase apparue dans le sheet) et ne touche jamais
aux lignes déjà présentes, même si leur score de confiance était bas. Une
correction manuelle dans ce fichier (commit direct) est donc définitive tant
qu'elle n'est pas explicitement changée à la main.

### Fusion sélective (`--teams`)

Un run CI (manuel ou cron) ne réécrit dans `data/*.csv` que les lignes des
équipes effectivement rafraîchies ce run-là (`_merge_by_key` dans
`scrape_ffhb_club.py`, clé = `section+indice+categorie+phase`) — les autres
équipes gardent leurs données du run précédent. Indispensable pour que le
rafraîchissement manuel ciblé (cases à cocher dans l'UI) ne fasse pas
disparaître les données des équipes non sélectionnées.

### Cron et fuseau horaire

GitHub Actions n'évalue les triggers `schedule:` que sur la **branche par
défaut** (`main`) — le cron ne tournera qu'une fois ce workflow mergé, pas
sur une branche de feature. Le cron est en UTC sans awareness du changement
d'heure française ; `30 20 * * 0` (dimanche 20h30 UTC) tombe vers 21h30 CET
(hiver) ou 22h30 CEST (été) — accepté comme compromis "dimanche soir" plutôt
que de gérer deux cron saisonniers.

### Rafraîchissement manuel depuis l'UI

Le site restant 100% statique, le bouton "Lancer un rafraîchissement" appelle
directement l'API GitHub (`POST
/repos/{repo}/actions/workflows/scrape-ffhb.yml/dispatches`) depuis le
navigateur, avec un jeton **fine-grained PAT stocké en `localStorage`**
(jamais commité, jamais envoyé ailleurs qu'à `api.github.com`). Chaque
admin doit créer son propre jeton une fois par appareil (scope minimal :
`Actions: Read and write` sur ce repo uniquement). Confirmé fonctionnel :
l'API GitHub répond bien en CORS à un `fetch()` cross-origin authentifié par
`Authorization: Bearer <token>` (testé avec un faux jeton → 401 propre, pas
d'erreur CORS bloquante).

### Barre de progression du rafraîchissement (équipe par équipe)

L'API GitHub Actions ne donne pas de vrai pourcentage, et streamer les logs
d'un job en cours n'est pas fiable. On utilise donc le Web App Apps Script
comme relais : `scrape_ffhb_club.py` (`post_progress`) pousse à chaque étape
un petit JSON dans `CacheService` (action `progress` de `Code.gs` — pas le
Sheet, purement éphémère, 6h de TTL). Le site sonde ça via
`doGet(?action=progress)` toutes les 3s (`PROGRESS_WEBAPP_URL`, hardcodée
dans `index.html` — l'URL n'est pas sensible en elle-même, seules les
actions d'écriture sont protégées par le secret partagé).

Chaque équipe a **2 phases séquentielles**, chacune pesant pour moitié du
créneau de l'équipe dans la barre :
- `phase: "journees"` (callback `on_journee` de `scrape_poule_journees`) —
  parcours intégral des journées de la poule, toujours fait en entier
  (impossible de savoir sans les visiter si un score est apparu).
- `phase: "details"` (callback `on_match` de `enrich_salle`) —
  gymnase/ville par match, qui **saute** les matchs déjà joués et connus
  (cache). Sans cette 2e phase distincte, la barre semblerait geler sur les
  équipes ayant beaucoup de nouveaux matchs à détailler, puisque la phase
  "journees" seule atteint 100% de son propre décompte bien avant que
  l'équipe entière soit terminée.

Un `started_at` (posé une fois par run) est comparé côté client au moment
du déclenchement pour ignorer une progression laissée par un run précédent
(sinon un `done:true` périmé stopperait le sondage immédiatement). Filet de
sécurité : arrêt du sondage après 15 min.

## Synchronisation vers la sheet "Matchs" (remplace le copier-coller manuel)

Historique : Julien copiait manuellement le résultat d'un ancêtre du scraper
dans le Google Sheet "Matchs" (`Com matchs réseaux`, celui que lisent
`form-score-club*` — voir plus bas). Le scraper FFHB **écrit maintenant
directement** dans cette sheet à chaque run (upsert par match), sans
supprimer la possibilité d'ajouter des matchs à la main (amicaux/tournois
absents de la FFHB) — les deux modes de saisie coexistent.

### Écriture via un Web App Apps Script (pas d'API Google côté scraper)

`apps-script/Code.gs` est un Web App unique lié à la sheet "Matchs" : le
scraper (GitHub Actions) lui POST un JSON par match (`action: "add_match"`),
protégé par un secret partagé (`SHARED_SECRET` dans le script =
`SHEET_WEBAPP_SECRET` côté GitHub). Choix déjà fait pour remplacer
Make.com sur les formulaires score/photo — même Web App, même point
d'entrée unique pour toute écriture dans la sheet, à étendre plus tard.
**Ce script doit être collé à la main dans l'éditeur Apps Script de la
sheet et déployé par Julien** (Claude Code n'a pas d'accès à son compte
Google) — voir les instructions en tête de `Code.gs`.

Côté Python (`scrape_ffhb_club.py`) : `SHEET_WEBAPP_URL` /
`SHEET_WEBAPP_SECRET` sont lues en variables d'environnement
(`post_match_to_sheet`) — **no-op silencieux si absentes**, donc sûr de
merger/tester avant que le Web App soit réellement déployé.

### Mapping des colonnes (voir `build_match_payload` dans scrape_ffhb_club.py)

- `Code Gesthand` = l'ID FFHB (`rencontre-XXXXXXX`, extrait du lien scrapé)
  pour les matchs venant du scraper. Les matchs ajoutés à la main gardent le
  format historique de Julien (date + indice, ex. `1309E` — **pas** un vrai
  code Gesthand malgré le nom de la colonne, un identifiant qu'il invente
  lui-même).
- `Eq1`/`Eq2` : le côté qui est nous reçoit le nom de section du club (propre,
  ex. `Entente Villette Genas`) + `Eq1X`/`Eq2X` = notre `indice` (A/B/C...,
  vide si l'équipe est seule dans sa catégorie — cf discussion avec Julien).
  Le côté adverse reçoit le nom FFHB brut (souvent un peu bruité, ex. `M18F
  EXC - ENTENTE LYON EST HANDBALL - 1`) ; `split_trailing_index()` tente d'en
  extraire un indice en suffixe (` - 1`, ` 2`...) quand il y en a un.
- `Date`/`Heure` ne sont écrites **que si FFHB a confirmé la date** (présence
  de l'heure dans le texte scrapé) — jamais une date approximative/plage.
- `Eq1Score`/`Eq2Score`/`WinLose` : seulement si FFHB affiche un score.
  `WinLose` est calculé du point de vue du club (Victoire/Défaite/Match Nul),
  pas juste "qui a gagné dans l'absolu".
- `Story*`/`PhotoEq` (pilotage de publication, hérité du flux Make
  actuellement manuel) : **jamais touchées** par le scraper, ni à la
  création ni à la mise à jour — en dehors de son périmètre.
- `INSTA_Cat`/`INSTA_date`/`INSTA_Eq1`/`INSTA_Eq2`/`Insta_Ville` : remplies
  **uniquement à la création** de la ligne (aide pour un futur Canva Bulk
  Create), jamais réécrites ensuite.

### Écosystème plus large (contexte, pas construit ici)

Le club a 3 autres repos (`form-score-club`, `form-score-club-2-`,
`form-score-club-photo-only`) qui lisent/écrivent cette même sheet "Matchs"
via des scénarios Make.com (score en direct pendant le match, photo de fin
de match archivée sur Dropbox). `form-score-club/Claude.md` décrit un plan
plus large (bascule vers Supabase, dashboard, PWA) resté au stade de la
session 1/6. Objectif à terme évoqué avec Julien : remplacer aussi ces
scénarios Make par le même Web App Apps Script (pas fait dans cette
itération — seule l'écriture des matchs scrapés est en place).
