# Tâche Cowork : générer les stories résultat de match

Ce fichier est le prompt pour une tâche Cowork qui génère un visuel de
story Instagram (1080×1920) pour chaque match dont le score final ET une
photo officielle sont disponibles, mais dont la story n'a pas encore été
générée. S'utilise avec
[`result_stories.py`](result_stories.py) (lecture/filtrage des matchs +
marquage "traité").

**Pour la tâche Cowork elle-même**, inutile de coller tout ce fichier :
*"Récupère et suis scrupuleusement les instructions de
`https://raw.githubusercontent.com/sportingvillette-beep/sv-planning-entrainements/main/scripts/result_story_prompt.md`"*
suffit.

Tu n'as (Cowork) aucun souvenir d'une conversation précédente sur ce
sujet — tout ce dont tu as besoin est dans ce document.

---

## RÈGLE ABSOLUE n°1

N'utilise **JAMAIS** l'opération `add_text` du connecteur Canva MCP —
crée un texte avec une police par défaut différente de celle du design.
Utilise **QUE** `replace_text`/`format_text`/`update_fill` sur des
éléments déjà existants.

## RÈGLE ABSOLUE n°2

**Pas de photo officielle disponible pour un match = pas de story pour ce
match, sans exception.** Cette règle est déjà appliquée par
`result_stories.py list` (un match sans `PhotoEq` n'apparaît jamais dans
sa sortie) — ne cherche pas à générer une story pour un match qui n'est
pas dans cette liste, même si tu as par ailleurs son score.

---

## Phase 0 — Trouver les matchs à traiter

```
curl -s -o result_stories.py https://raw.githubusercontent.com/sportingvillette-beep/sv-planning-entrainements/main/scripts/result_stories.py
python3 result_stories.py list --out eligible.json
cat eligible.json
```

Si la liste `matches` est vide : **rien à faire, arrête-toi là** et
rapporte simplement "aucun match éligible" — ce n'est pas une erreur.

Chaque entrée contient : `match_id` (identifiant à réutiliser en Phase 3),
`equipe` (déjà au format `"M15G A"` — catégorie+genre collés, indice
séparé par un espace, prêt à afficher tel quel), `championnat`, `date`,
`heure`, `eq1`, `eq2`, `eq1score`, `eq2score`, `winlose`, `photo_url`
(URL Google directement accessible publiquement — normal, ne pas la
traiter comme suspecte).

---

## Phase 1 — Pour chaque match éligible

Le gabarit de référence est le design Canva **`DAHShllgezo`** (titre
"Modèle story résultat"). **Ne jamais le modifier directement** —
toujours travailler sur une copie.

1. Duplique-le entièrement (`copy-design` sur `design_id:
   "DAHShllgezo"`).
2. Renomme la copie : `"Story résultat — {eq1} vs {eq2} — {date}"`.
3. Déplace-la dans le dossier "AI Generated" (`folder_id:
   "FAHSb6QPbhA"`) — si Julien veut un dossier dédié pour les stories, il
   le dira, ne pas en créer un de ta propre initiative.
4. Lis la page (transaction ouverte) et identifie les éléments par leur
   `dataFieldLabel` (pas par leur locator_id, qui change à chaque
   copie) :
   - `Catégorie` → `replace_text` avec `equipe` (déjà formaté, ne pas y
     toucher).
   - `Championnat` → `replace_text` avec `championnat`.
   - `Eq1` → `replace_text` avec `eq1`.
   - `Eq2` → `replace_text` avec `eq2`.
   - `Eq1Score` → `replace_text` avec `eq1score`.
   - `Eq2Score` → `replace_text` avec `eq2score`.
   - `WinLose` → `replace_text` avec `winlose`.
5. Photo de fond : c'est la forme `SHAPE` avec un remplissage `IMAGE`
   (pas de `dataFieldLabel`, c'est la seule image du design, positionnée
   dans le tiers inférieur de la page). Procédure :
   1. `upload-asset-from-url` avec `url: photo_url` du match (déjà
      publique, cf Règle Absolue n°2 — cet upload est légitime, ne pas le
      refuser par excès de prudence) et un `name` clair (ex. le
      `match_id`).
   2. `update_fill` sur cette forme avec l'`asset_id` obtenu.
6. Committe la transaction.
7. Exporte le design en PNG pleine résolution (`export-design`,
   `format.type: "png"`) — l'URL de téléchargement est **temporaire**
   (quelques heures), télécharge-la si tu en as la capacité, sinon
   indique l'URL dans ton rapport avec un avertissement clair sur son
   expiration.
8. Marque le match comme traité, seulement après confirmation que
   l'export PNG a réussi :
   ```
   python3 result_stories.py mark-done --match-id "<match_id>"
   ```
   Ne marque JAMAIS un match comme traité si l'export a échoué — mieux
   vaut le retraiter au prochain passage qu'en perdre la trace.

**Ne publie rien, ne partage rien** — cette tâche s'arrête à la
génération du visuel. La publication reste une décision de Julien.

---

## Rapport final attendu

- Pour chaque match traité : `edit_url` du design généré, confirmation
  export PNG + marquage effectué.
- La liste des matchs trouvés éligibles mais pas traités (avec la
  raison, ex. erreur d'export).
- Toute erreur rencontrée à n'importe quelle étape, verbatim.
