/**
 * Web App unique pour Sporting Villette : reçoit les matchs ajoutés/mis à jour par le
 * scraper FFHB (action "add_match"), et remplace maintenant aussi les 2 scénarios Make.com
 * des formulaires club (action "add_score" pour le score en direct, "add_photo" pour la
 * photo de fin de match, uploadée sur Google Drive à la place de Dropbox).
 *
 * Les formulaires (form-score-club-2-, form-score-club-photo-only) sont des pages HTML
 * publiques : ils postent en multipart/form-data (pas de JSON) et utilisent un secret
 * DIFFÉRENT de celui du scraper (FORM_SHARED_SECRET, moins sensible) pour que sa fuite
 * éventuelle dans ce code JS public ne compromette pas SHARED_SECRET (utilisé par le
 * scraper côté GitHub Actions, jamais exposé).
 *
 * DÉPLOIEMENT :
 * 1) Ouvrir le Google Sheet "Com matchs réseaux" > Extensions > Apps Script.
 * 2) Coller ce fichier (remplace le contenu par défaut de Code.gs).
 * 3) Remplacer SHARED_SECRET et FORM_SHARED_SECRET ci-dessous par deux valeurs
 *    secrètes distinctes de ton choix.
 * 4) Créer un dossier Google Drive "Photos matchs" (sur le compte associatif), ouvrir
 *    son ID dans l'URL (drive.google.com/drive/folders/<ID>) et le coller dans
 *    PHOTOS_FOLDER_ID ci-dessous.
 * 5) Déployer > Nouveau déploiement > Type "Application Web".
 *    - Exécuter en tant que : Moi
 *    - Qui a accès : Tout le monde
 * 6) Copier l'URL de déploiement (se termine par /exec).
 * 7) Dans le repo GitHub sv-planning-entrainements, Settings > Secrets and variables >
 *    Actions, créer :
 *    - SHEET_WEBAPP_URL = l'URL copiée à l'étape 6
 *    - SHEET_WEBAPP_SECRET = la même valeur que SHARED_SECRET ci-dessous
 * 8) Dans form-score-club-2-/index.html et form-score-club-photo-only/index.html,
 *    mettre à jour CONFIG.webhookUrl (même URL qu'à l'étape 6) et CONFIG.webhookSecret
 *    (même valeur que FORM_SHARED_SECRET ci-dessous).
 *
 * À chaque modification de ce code après un déploiement existant, utiliser
 * Déployer > Gérer les déploiements > éditer (icône crayon) > Nouvelle version,
 * plutôt que de créer un nouveau déploiement (sinon l'URL change).
 */

const SHEET_NAME = 'Matchs';
const SHARED_SECRET = 'CHANGE_MOI'; // remplacer avant déploiement — scraper uniquement
const FORM_SHARED_SECRET = 'CHANGE_MOI_AUSSI'; // remplacer avant déploiement — formulaires publics uniquement
const PHOTOS_FOLDER_ID = 'CHANGE_MOI_FOLDER_ID'; // ID du dossier Drive "Photos matchs"
const PROGRESS_CACHE_KEY = 'scrape_progress';
const PROGRESS_CACHE_TTL = 21600; // 6h (max autorisé par CacheService)

// Ordre exact des colonnes du Sheet (A -> AD). Ne pas réordonner sans adapter le Sheet.
const COLUMNS = [
  'Code Gesthand', 'Catégorie', 'Genre', 'Index', 'Championnat', 'Poule', 'Journée',
  'Eq1', 'Eq1X', 'Date', 'Heure', 'Eq2', 'Eq2X', 'Gymnase', 'Ville',
  'Eq1Score', 'Eq2Score', 'WinLose',
  'Story Insta', 'Get Story', 'Story avant match', 'Publier Story', 'Lien Story',
  'PhotoEq', 'Story résultat',
  'INSTA_Cat', 'INSTA_date', 'INSTA_Eq1', 'INSTA_Eq2', 'Insta_Ville',
];

const JOURS_FR = ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam'];

function doPost(e) {
  try {
    // Les formulaires club (score/photo) postent en multipart/form-data (nécessaire pour
    // envoyer un fichier) : les champs arrivent dans e.parameter, pas e.postData.contents.
    // Le scraper (GitHub Actions) continue de poster du JSON classique.
    const isMultipart = e.postData && String(e.postData.type || '').indexOf('multipart/form-data') === 0;

    if (isMultipart) {
      const p = e.parameter;
      if (p.secret !== FORM_SHARED_SECRET) {
        return jsonResponse({ ok: false, error: 'secret invalide' });
      }
      if (p.action === 'add_score') return jsonResponse(updateScore(p));
      if (p.action === 'add_photo') return jsonResponse(addPhoto(p));
      return jsonResponse({ ok: false, error: 'action inconnue: ' + p.action });
    }

    const body = JSON.parse(e.postData.contents);
    if (body.secret !== SHARED_SECRET) {
      return jsonResponse({ ok: false, error: 'secret invalide' });
    }
    if (body.action === 'add_match') {
      return jsonResponse(upsertMatch(body.match));
    }
    if (body.action === 'progress') {
      // Suivi d'avancement d'un run de scraping — stockage éphémère (CacheService,
      // pas le Sheet), lu par le site via doGet pour afficher une barre de progression.
      CacheService.getScriptCache().put(PROGRESS_CACHE_KEY, JSON.stringify(body.progress), PROGRESS_CACHE_TTL);
      return jsonResponse({ ok: true });
    }
    return jsonResponse({ ok: false, error: 'action inconnue: ' + body.action });
  } catch (err) {
    return jsonResponse({ ok: false, error: String(err) });
  }
}

// Lecture de la progression (pas d'authentification requise — donnée non sensible,
// juste des noms d'équipes déjà publics et un numéro de journée).
function doGet(e) {
  if (e.parameter.action === 'progress') {
    const raw = CacheService.getScriptCache().get(PROGRESS_CACHE_KEY);
    return jsonResponse(raw ? JSON.parse(raw) : null);
  }
  return jsonResponse({ ok: false, error: 'action inconnue' });
}

function getSheet() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
  if (!sheet) throw new Error('Feuille "' + SHEET_NAME + '" introuvable');
  return sheet;
}

// Colonne A = Code Gesthand. Recherche linéaire (volume de matchs d'un club : pas un
// problème de perf tant qu'on reste sous quelques milliers de lignes).
function findRowByCode(sheet, code) {
  const data = sheet.getRange(1, 1, sheet.getLastRow(), 1).getValues();
  for (let i = 1; i < data.length; i++) {
    if (String(data[i][0]).trim() === String(code).trim()) return i + 1; // numéro de ligne 1-indexé
  }
  return null;
}

function colIndex(name) {
  const idx = COLUMNS.indexOf(name);
  if (idx === -1) throw new Error('Colonne inconnue: ' + name);
  return idx;
}

/**
 * Ajoute ou met à jour un match par Code Gesthand (= ID FFHB pour les matchs scrapés).
 * Ne touche jamais aux colonnes de suivi de publication (Story*, PhotoEq) sur une ligne
 * existante — seulement les champs sourcés FFHB. Les colonnes INSTA_* ne sont remplies
 * qu'à la création (aide manuelle pour Canva), jamais réécrites ensuite.
 */
function upsertMatch(m) {
  if (!m || !m.code) return { ok: false, error: 'match.code manquant' };
  const sheet = getSheet();
  const rowNumber = findRowByCode(sheet, m.code);

  const values = {
    'Code Gesthand': m.code,
    'Catégorie': m.categorie || '',
    'Genre': m.genre || '',
    'Index': m.index || '',
    'Championnat': m.championnat || '',
    'Poule': m.poule || '',
    'Journée': m.journee || '',
    'Eq1': m.eq1 || '',
    'Eq1X': m.eq1x || '',
    'Eq2': m.eq2 || '',
    'Eq2X': m.eq2x || '',
    'Gymnase': m.gymnase || '',
    'Ville': m.ville || '',
  };
  // Date/Heure : n'écrase que si le scraper envoie une date confirmée (sinon on garde
  // ce qui était déjà là, potentiellement une date confirmée entre-temps par un autre run).
  if (m.date) values['Date'] = m.date;
  if (m.heure) values['Heure'] = m.heure;
  // Score/WinLose : n'écrase que si FFHB a publié un score (source de vérité, voir CLAUDE.md).
  if (m.eq1score !== undefined && m.eq1score !== '') values['Eq1Score'] = m.eq1score;
  if (m.eq2score !== undefined && m.eq2score !== '') values['Eq2Score'] = m.eq2score;
  if (m.winlose) values['WinLose'] = m.winlose;

  if (rowNumber) {
    const rowRange = sheet.getRange(rowNumber, 1, 1, COLUMNS.length);
    const current = rowRange.getValues()[0];
    Object.keys(values).forEach(col => {
      current[colIndex(col)] = values[col];
    });
    rowRange.setValues([current]);
    return { ok: true, action: 'updated', row: rowNumber };
  }

  const newRow = COLUMNS.map(col => (Object.prototype.hasOwnProperty.call(values, col) ? values[col] : ''));
  newRow[colIndex('INSTA_Cat')] = [m.categorie, m.genre].filter(Boolean).join(' ');
  newRow[colIndex('INSTA_date')] = formatInstaDate(m.date, m.heure);
  newRow[colIndex('INSTA_Eq1')] = m.eq1 || '';
  newRow[colIndex('INSTA_Eq2')] = m.eq2 || '';
  newRow[colIndex('Insta_Ville')] = m.ville || '';

  sheet.appendRow(newRow);
  return { ok: true, action: 'inserted' };
}

/**
 * Formulaire score en direct (remplace le scénario Make "Formulaire nouveau score",
 * route "sans photo" — la route "avec photo_finale" était du code mort, non reproduite).
 * Écrase toujours Eq1Score/Eq2Score/WinLose : contrairement au scraper, ici c'est une
 * saisie humaine explicite, donc source de vérité la plus récente.
 */
function updateScore(p) {
  if (!p.match_id) return { ok: false, error: 'match_id manquant' };
  const sheet = getSheet();
  const rowNumber = findRowByCode(sheet, p.match_id);
  if (!rowNumber) return { ok: false, error: 'match introuvable: ' + p.match_id };

  const rowRange = sheet.getRange(rowNumber, 1, 1, COLUMNS.length);
  const current = rowRange.getValues()[0];
  if (p.score_dom !== undefined && p.score_dom !== '') current[colIndex('Eq1Score')] = p.score_dom;
  if (p.score_ext !== undefined && p.score_ext !== '') current[colIndex('Eq2Score')] = p.score_ext;
  if (p.winlose) current[colIndex('WinLose')] = p.winlose;
  rowRange.setValues([current]);
  return { ok: true, action: 'score_updated', row: rowNumber };
}

/**
 * Formulaire photo de fin de match (remplace les 2 scénarios Make qui uploadaient sur
 * Dropbox sans jamais écrire dans la sheet). Ici on upload sur Drive (dossier dédié par
 * match) et on écrit le lien dans PhotoEq — un envoi ultérieur pour le même match
 * remplace le lien précédent (un seul "photo résultat" attendu par match, cf CLAUDE.md).
 */
function addPhoto(p) {
  if (!p.match_id) return { ok: false, error: 'match_id manquant' };
  if (!p.photo || typeof p.photo.getBytes !== 'function') return { ok: false, error: 'photo manquante' };
  const sheet = getSheet();
  const rowNumber = findRowByCode(sheet, p.match_id);
  if (!rowNumber) return { ok: false, error: 'match introuvable: ' + p.match_id };

  const parentFolder = DriveApp.getFolderById(PHOTOS_FOLDER_ID);
  const matchFolder = getOrCreateSubfolder(parentFolder, p.match_id);
  const file = matchFolder.createFile(p.photo);
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  const url = 'https://lh3.googleusercontent.com/d/' + file.getId();

  const rowRange = sheet.getRange(rowNumber, 1, 1, COLUMNS.length);
  const current = rowRange.getValues()[0];
  current[colIndex('PhotoEq')] = url;
  rowRange.setValues([current]);
  return { ok: true, action: 'photo_added', url: url, row: rowNumber };
}

function getOrCreateSubfolder(parent, name) {
  const safeName = String(name).trim();
  const existing = parent.getFoldersByName(safeName);
  if (existing.hasNext()) return existing.next();
  return parent.createFolder(safeName);
}

function formatInstaDate(dateStr, heureStr) {
  if (!dateStr) return '';
  const parts = String(dateStr).split('/'); // DD/MM/YYYY
  if (parts.length !== 3) return '';
  const d = new Date(parseInt(parts[2], 10), parseInt(parts[1], 10) - 1, parseInt(parts[0], 10));
  const jour = JOURS_FR[d.getDay()];
  return heureStr ? `${jour} ${heureStr}` : jour;
}

function jsonResponse(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
