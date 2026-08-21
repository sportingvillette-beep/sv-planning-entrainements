"""Crée et publie sur SportsRégions (admin.sportsregions.fr/actualite) la news hebdomadaire
"résultats du week-end" — bloc 2 (tableau de synthèse des résultats) + bloc 3 (un bloc par
match avec photo et/ou commentaire remonté par les participants, SANS IA, texte repris tel
quel) du plan de Julien (2026-08-20). Intro IA et bloc actus à venir restent à construire
(même philosophie "pas à pas" que le reste du chantier SportsRégions).

Le contenu (`renderWeekendResultsTable` + `renderWeekendTeamBlocks`, index.html) est régénéré
via page.evaluate sur le site GitHub Pages en direct, comme le reste de l'automatisation
SportsRégions — voir push_sportsregions_fiches.py pour le principe général. La seule donnée qui
ne peut PAS venir du site (fetch HTTP) est l'instantané de classement d'avant le week-end
(data/classements_history/*.csv, committé dans ce repo) : lu directement depuis le disque local
(le script tourne dans le même checkout que ces fichiers, que ce soit en CI ou en local) et
passé en paramètre à la fonction JS plutôt que refetché. Le bloc 3 lit la sheet "Matchs"
publiée en CSV (MATCHS_SHEET_CSV_URL, même source que scripts/result_stories.py) pour
PhotoEq/Commentaire — données saisies par les coachs via form-score-club-2-.

Usage :
    python push_weekend_news.py --dry-run                    # génère et affiche le tableau, ne touche rien
    python push_weekend_news.py --dry-run --saturday 2026-09-12
    python push_weekend_news.py                                 # crée + remplit la news (reste Hors ligne, brouillon)
    python push_weekend_news.py --publish                       # crée + remplit + PUBLIE (En ligne, visible publiquement)
    python push_weekend_news.py --saturday 2026-09-12          # cible un week-end précis (test)
    python push_weekend_news.py --headed                       # navigateur visible

Ne publie JAMAIS automatiquement (--publish explicite requis) : créer/remplir une news reste
une action réversible (brouillon "Hors ligne"), la publier ne l'est pas (visible publiquement).
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, Page

from sportsregions_pipeline import admin_bridge, ensure_logged_in, get_credentials, login

SITE_URL = "https://sportingvillette-beep.github.io/sv-planning-entrainements/"
HISTORY_DIR = Path(__file__).resolve().parent.parent / "data" / "classements_history"

GENERATE_JS = """
    async ([saturdayISO, sundayISO, historyText]) => {
      const [calText, mapText, clText, matchsText] = await Promise.all([
        fetchText(CALENDRIER_CLUB_URL),
        fetchText(TEAM_MAPPING_URL),
        fetchText(CLASSEMENTS_CLUB_URL),
        fetchText(MATCHS_SHEET_CSV_URL),
      ]);
      const calendrierRows = parseCSV(calText);
      const mappingRows = parseCSV(mapText).filter(r => (r['equipe_ffhb_proposee'] || '').trim() !== '');
      const classementsRows = parseCSV(clText);
      const start = new Date(saturdayISO), end = new Date(sundayISO);
      end.setHours(23, 59, 59, 999);

      const played = calendrierRows.filter(r => {
        const d = parseFrenchDate(r['date/heure']);
        return d && d >= start && d <= end && (r['score'] || '').trim() !== '';
      });
      const resultsTable = renderWeekendResultsTable(played, mappingRows, classementsRows, historyText || '');

      // Sheet Matchs : Date au format DD/MM/YYYY (pas le même format que calendrier_club.csv,
      // colonne séparée de Heure) — parsing dédié, pas de fonction existante réutilisable ici.
      function parseSheetDate(dateStr) {
        const m = (dateStr || '').match(/^(\\d{1,2})\\/(\\d{1,2})\\/(\\d{4})$/);
        if (!m) return null;
        return new Date(parseInt(m[3], 10), parseInt(m[2], 10) - 1, parseInt(m[1], 10));
      }
      const matchsRows = parseCSV(matchsText).filter(r => {
        const d = parseSheetDate(r['Date']);
        if (!d || d < start || d > end) return false;
        const scoreFinal = (r['Eq1Score'] || '').trim() && (r['Eq2Score'] || '').trim() && (r['WinLose'] || '').trim();
        if (!scoreFinal) return false;
        return (r['PhotoEq'] || '').trim() !== '' || (r['Commentaire'] || '').trim() !== '';
      });
      const teamBlocks = renderWeekendTeamBlocks(matchsRows);

      return {
        count: played.length,
        teamBlocksCount: matchsRows.length,
        html: resultsTable + (teamBlocks ? '\\n<p>&nbsp;</p>\\n' + teamBlocks : ''),
      };
    }
"""

MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def last_weekend_saturday(today: datetime.date) -> datetime.date:
    """Samedi le plus récent (aujourd'hui inclus si on est déjà sam/dim) — même logique que
    lastWeekendRange() côté JS (index.html), portée en Python."""
    weekday = today.weekday()  # Monday=0 ... Sunday=6
    if weekday == 5:
        return today
    if weekday == 6:
        return today - datetime.timedelta(days=1)
    return today - datetime.timedelta(days=weekday + 2)


def find_history_snapshot(before_date: datetime.date, max_days_back: int = 7) -> str:
    """Dernier instantané data/classements_history/*.csv strictement antérieur à `before_date`
    (normalement le vendredi qui précède le week-end) — remonte jusqu'à `max_days_back` jours
    si un run de scraping a manqué. Chaîne vide si rien trouvé (évolution alors omise, pas
    fausse — voir renderWeekendResultsTable)."""
    for delta in range(1, max_days_back + 1):
        d = before_date - datetime.timedelta(days=delta)
        p = HISTORY_DIR / f"{d.isoformat()}.csv"
        if p.exists():
            return p.read_text(encoding="utf-8")
    return ""


def default_title() -> str:
    return "Résultats du week-end"


def default_chapo(saturday: datetime.date, sunday: datetime.date) -> str:
    mois = MOIS_FR[sunday.month - 1]
    if saturday.month == sunday.month:
        return f"Week-end du {saturday.day}-{sunday.day} {mois}"
    return f"Week-end du {saturday.day} {MOIS_FR[saturday.month - 1]} au {sunday.day} {mois}"


def generate_results_table(page: Page, site_url: str, saturday: datetime.date, sunday: datetime.date) -> dict:
    page.goto(site_url)
    page.wait_for_load_state("networkidle")
    history_text = find_history_snapshot(saturday)
    saturday_iso = saturday.isoformat()
    sunday_iso = sunday.isoformat()
    return page.evaluate(GENERATE_JS, [saturday_iso, sunday_iso, history_text])


def create_news(page: Page, title: str) -> str:
    """Crée une news vierge (popup 'Ajouter une news') et renvoie son id (extrait de l'URL de
    la page d'édition qui suit, .../actualite/edit/<id>)."""
    page.goto(admin_bridge("/actualite"))
    page.wait_for_load_state("networkidle")
    ensure_logged_in(page)
    page.click("text=Ajouter une news")
    page.wait_for_selector(".modal input[name=titre]", state="visible")
    page.fill(".modal input[name=titre]", title)
    page.click(".modal button:has-text('Enregistrer')")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    m = re.search(r"/actualite/edit/(\d+)", page.url)
    if not m:
        raise RuntimeError(f"Impossible de retrouver l'id de la news créée dans l'URL : {page.url}")
    return m.group(1)


def fill_news_content(page: Page, news_id: str, *, chapo: str, corps_html: str, ai_generated: bool = True) -> None:
    page.goto(admin_bridge(f"/actualite/edit/{news_id}"))
    page.wait_for_load_state("networkidle")
    ensure_logged_in(page)
    page.wait_for_selector("#textarea_chapo", state="attached")
    page.fill("#textarea_chapo", chapo)
    page.wait_for_function("window.CKEDITOR && window.CKEDITOR.instances['ckeditor_corps']")
    page.wait_for_timeout(500)
    page.evaluate(
        "([html]) => window.CKEDITOR.instances['ckeditor_corps'].setData(html)",
        [corps_html],
    )
    if ai_generated:
        page.check("#checkbox_contenu_ia")
    page.click("button:has-text('Enregistrer'), input[value='Enregistrer']")
    page.wait_for_load_state("networkidle")


def publish_news(page: Page, news_id: str) -> None:
    page.goto(admin_bridge(f"/actualite/edit/{news_id}"))
    page.wait_for_load_state("networkidle")
    ensure_logged_in(page)
    page.click("text=En ligne")
    page.wait_for_timeout(1500)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Génère et affiche le tableau, ne crée/publie aucune news (pas de login)")
    ap.add_argument("--saturday", help="Date du samedi ciblé (YYYY-MM-DD) — défaut : dernier week-end écoulé")
    ap.add_argument("--site", default=SITE_URL, help="URL du site à charger (défaut : GitHub Pages en prod)")
    ap.add_argument("--headed", action="store_true", help="Navigateur visible")
    ap.add_argument(
        "--publish", action="store_true",
        help="Bascule la news en 'En ligne' après création (publication publique réelle). "
             "Par défaut la news est créée et remplie mais reste 'Hors ligne' (brouillon) — "
             "publier une news est une action visible publiquement, jamais automatique sans "
             "ce flag explicite.",
    )
    args = ap.parse_args()

    if args.saturday:
        saturday = datetime.date.fromisoformat(args.saturday)
    else:
        saturday = last_weekend_saturday(datetime.date.today())
    sunday = saturday + datetime.timedelta(days=1)

    if not args.dry_run and not get_credentials():
        print(
            "!!! Identifiants SportsRégions absents : variables d'environnement "
            "SPORTSREGIONS_USERNAME / SPORTSREGIONS_PASSWORD non définies.",
            file=sys.stderr,
        )
        sys.exit(1)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        context = browser.new_context()
        page = context.new_page()

        if not args.dry_run:
            login(page)

        result = generate_results_table(page, args.site, saturday, sunday)
        print(f">>> {result['count']} résultat(s) trouvé(s) pour le week-end du {saturday}.", file=sys.stderr)
        print(f">>> {result['teamBlocksCount']} bloc(s) équipe (photo/commentaire) inclus.", file=sys.stderr)

        if args.dry_run:
            print(result["html"])
            browser.close()
            return

        title = default_title()
        chapo = default_chapo(saturday, sunday)
        news_id = create_news(page, title)
        print(f">>> News créée (id {news_id}).", file=sys.stderr)
        fill_news_content(page, news_id, chapo=chapo, corps_html=result["html"])
        print(">>> Contenu enregistré (Hors ligne).", file=sys.stderr)
        if args.publish:
            publish_news(page, news_id)
            print(">>> News publiée (En ligne).", file=sys.stderr)
        else:
            print(">>> Reste en brouillon (Hors ligne) — relancer avec --publish pour la mettre en ligne.", file=sys.stderr)

        browser.close()


if __name__ == "__main__":
    main()
