/**
 * Web App unique pour Sporting Villette : reçoit les matchs ajoutés/mis à jour par le
 * scraper FFHB (action "add_match"). Remplace Make.com pour cette partie du flux.
 * Les actions score/photo (ex-scénarios Make) pourront être ajoutées ici plus tard,
 * une fois validées séparément (pas dans cette première version).
 *
 * DÉPLOIEMENT :
 * 1) Ouvrir le Google Sheet "Com matchs réseaux" > Extensions > Apps Script.
 * 2) Coller ce fichier (remplace le contenu par défaut de Code.gs).
 * 3) Remplacer SHARED_SECRET ci-dessous par une valeur secrète de ton choix.
 * 4) Déployer > Nouveau déploiement > Type "Application Web".
 *    - Exécuter en tant que : Moi
 *    - Qui a accès : Tout le monde
 * 5) Copier l'URL de déploiement (se termine par /exec).
 * 6) Dans le repo GitHub, Settings > Secrets and variables > Actions, créer :
 *    - SHEET_WEBAPP_URL = l'URL copiée à l'étape 5
 *    - SHEET_WEBAPP_SECRET = la même valeur que SHARED_SECRET ci-dessous
 *
 * À chaque modification de ce code après un déploiement existant, utiliser
 * Déployer > Gérer les déploiements > éditer (icône crayon) > Nouvelle version,
 * plutôt que de créer un nouveau déploiement (sinon l'URL change).
 */

const SHEET_NAME = 'Matchs';
const SHARED_SECRET = 'CHANGE_MOI'; // remplacer avant déploiement

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
    const body = JSON.parse(e.postData.contents);
    if (body.secret !== SHARED_SECRET) {
      return jsonResponse({ ok: false, error: 'secret invalide' });
    }
    if (body.action === 'add_match') {
      return jsonResponse(upsertMatch(body.match));
    }
    return jsonResponse({ ok: false, error: 'action inconnue: ' + body.action });
  } catch (err) {
    return jsonResponse({ ok: false, error: String(err) });
  }
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
