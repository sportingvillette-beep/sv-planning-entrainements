# Contexte du projet — sv-planning-entrainements

Ce repo héberge des outils web pour **Sporting Villette** (club de handball,
Villette d'Anthon, Isère) et ses ententes partenaires. Tout est construit
comme une **application HTML statique unique** (`index.html`), sans backend,
hébergée sur **GitHub Pages**. Elle lit ses données en direct depuis un
Google Sheet publié en CSV, et génère plusieurs documents (plannings
d'entraînement, "Team Book") entièrement côté navigateur.

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

## Prochaine fonctionnalité demandée : "scraper FFHB"

Julien veut ajouter un outil qui va chercher des informations sur les pages
de poule FFHB (liens déjà présents dans les colonnes `P1.Lien` / `P2.Lien`
du Google Sheet, un lien par équipe et par phase). **Le besoin exact n'a pas
encore été détaillé avec Claude (claude.ai)** — à clarifier avec Julien avant
de coder : veut-il un classement, un calendrier de matchs, des résultats,
une synthèse par équipe/entente, une fréquence de mise à jour (à la demande,
ou automatisée) ? Le format de sortie doit sans doute suivre la même logique
que le reste de l'app (bouton dans `index.html`, génération côté client) —
mais le scraping d'un site tiers depuis le navigateur du client posera
probablement un problème de CORS similaire à celui déjà rencontré avec
Google Sheets (voire pire, ffhandball.fr n'étant pas conçu pour être
consommé en cross-origin). Une fonction serverless / proxy (GitHub Actions
planifiée + commit d'un JSON de résultats dans le repo, par exemple) est
probablement une meilleure architecture qu'un fetch direct depuis le
navigateur — à évaluer avec Julien selon la fraîcheur des données souhaitée.
