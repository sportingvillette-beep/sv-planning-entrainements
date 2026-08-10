# scrape_ffhb_club.py
# Scrape le calendrier/classement de toutes les equipes du club listees dans le Google Sheet.
#
# Usage interactif (local, comme avant) :
#   python scrape_ffhb_club.py
#
# Usage CI (non interactif, utilise par le workflow GitHub Actions) :
#   python scrape_ffhb_club.py sync-mapping --mapping-dir scraper
#   python scrape_ffhb_club.py scrape --mapping-dir scraper --outdir data [--teams id1,id2]
#
# team_mapping.csv est le rapprochement approximatif nom sheet <-> nom FFHB. Il est
# versionne dans le repo et NE DOIT PAS etre ecrase aveuglement a chaque run : une fois
# une ligne corrigee a la main (cas "club porteur" d'une entente, cf CLAUDE.md), elle doit
# etre preservee. sync-mapping n'ajoute que les lignes nouvelles (nouvelles equipes/phases
# apparues dans le sheet), sans toucher aux lignes existantes.
import argparse
import datetime
import json
import os
import re
import sys
from difflib import SequenceMatcher

import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from scrape_ffhb import (
    clean_text,
    slugify,
    parse_table_by_heading,
    scrape_poule_journees,
    normalize_poule_base_url,
    enrich_salle,
    save_if,
)

SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vT3RqA-z8ANNaXXsYMgh4ynk8LV4EjOnkAqyThzFQ4TcxIUofmVlWg20wyfw-ZmeDettPCjkCgank_3"
    "/pub?output=csv"
)

STOPWORDS = {"entente", "handball", "hb", "club", "association", "asc", "as", "sporting"}

def team_keywords(section: str) -> list:
    section = re.sub(r"\(.*?\)", " ", section)
    tokens = re.findall(r"[A-Za-zÀ-ÿ0-9]+", section.upper())
    return [t for t in tokens if t.lower() not in STOPWORDS and len(t) > 1]

def match_team_name(section: str, candidates: list):
    keywords = team_keywords(section)
    if not keywords or not candidates:
        return None, 0.0, []
    scored = []
    for cand in candidates:
        cand_up = cand.upper()
        # \b sur mot entier : "EST" ne doit pas matcher dans "OUEST"
        hits = sum(1 for k in keywords if re.search(rf"\b{re.escape(k)}\b", cand_up))
        coverage = hits / len(keywords)
        sim = SequenceMatcher(None, " ".join(keywords), cand_up).ratio()
        score = 0.7 * coverage + 0.3 * sim
        scored.append((cand, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    best_name, best_score = scored[0]
    return best_name, best_score, scored

def team_row_id(section: str, indice: str, categorie: str, phase: str) -> str:
    return slugify(f"{section}_{indice}_{categorie}_{phase}")

def load_sheet_teams() -> pd.DataFrame:
    df = pd.read_csv(SHEET_CSV_URL, encoding="utf-8")
    df.columns = [c.strip() for c in df.columns]
    rows = []
    for _, r in df.iterrows():
        section = clean_text(str(r.get("Section", "") or ""))
        if not section:
            continue
        indice = clean_text(str(r.get("Indice équipe", "") or "")) if pd.notna(r.get("Indice équipe")) else ""
        categorie = clean_text(str(r.get("Categorie", "") or ""))
        for phase, lien_col, niveau_col, poule_col in [
            ("P1", "P1.Lien", "P1.Niveau", "P1.Poule"),
            ("P2", "P2.Lien", "P2.Niveau", "P2.Poule"),
        ]:
            lien = str(r.get(lien_col, "") or "").strip()
            if not lien or lien.lower() == "nan" or not lien.startswith("http"):
                continue
            rows.append({
                "id": team_row_id(section, indice, categorie, phase),
                "section": section,
                "indice": indice,
                "categorie": categorie,
                "phase": phase,
                "niveau": clean_text(str(r.get(niveau_col, "") or "")),
                "poule_num": clean_text(str(r.get(poule_col, "") or "")),
                "lien": lien,
            })
    return pd.DataFrame(rows)

def get_poule_candidates(page, base_url: str) -> list:
    try:
        page.goto(base_url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_selector("table", timeout=20000)
    except Exception:
        pass
    soup = BeautifulSoup(page.content(), "lxml")
    classement = parse_table_by_heading(soup, ["Classement", "Classement général", "Tableau"])
    if classement is None or classement.empty:
        return []
    club_col = next(
        (c for c in classement.columns if "club" in str(c).lower() or "équipe" in str(c).lower()),
        classement.columns[1] if len(classement.columns) > 1 else classement.columns[0],
    )
    return [clean_text(str(v)) for v in classement[club_col].tolist()]

def resolve_new_teams(teams: pd.DataFrame) -> list:
    """Rapproche (fuzzy matching) chaque ligne de `teams` avec les équipes de sa poule."""
    if teams.empty:
        return []
    results = []
    candidates_by_poule = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for _, t in teams.iterrows():
            base_url = normalize_poule_base_url(t["lien"])
            if base_url not in candidates_by_poule:
                print(f"Lecture du classement -> {base_url}")
                candidates_by_poule[base_url] = get_poule_candidates(page, base_url)
            candidates = candidates_by_poule[base_url]

            best_name, best_score, scored = match_team_name(t["section"], candidates)
            top2_gap = (scored[0][1] - scored[1][1]) if len(scored) > 1 else 1.0
            a_verifier = (best_score < 0.5) or (top2_gap < 0.1)

            label = " ".join(x for x in [t["section"], t["indice"], t["categorie"], f"({t['phase']})"] if x)
            flag = " ⚠ A VERIFIER" if a_verifier else ""
            print(f"  {label} -> {best_name}  [confiance {best_score:.2f}]{flag}")

            results.append({
                "id": t["id"],
                "section": t["section"],
                "indice": t["indice"],
                "categorie": t["categorie"],
                "phase": t["phase"],
                "niveau": t["niveau"],
                "poule_url": base_url,
                "equipe_ffhb_proposee": best_name or "",
                "confiance": round(best_score, 2),
                "a_verifier": a_verifier,
                "candidats_poule": " | ".join(candidates),
            })
        browser.close()
    return results

def build_mapping(outdir: str):
    """Régénère team_mapping.csv en entier (usage local/manuel — écrase les corrections)."""
    teams = load_sheet_teams()
    print(f"{len(teams)} entrées équipe x phase avec lien trouvées dans le Google Sheet.\n")
    if teams.empty:
        print("Aucune équipe avec lien à traiter.")
        return

    results = resolve_new_teams(teams)
    mapping_df = pd.DataFrame(results)
    path = os.path.join(outdir, "team_mapping.csv")
    mapping_df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"\n✔ Mapping proposé -> {path}")
    n_verif = int(mapping_df["a_verifier"].sum())
    print(f"{n_verif} ligne(s) à vérifier manuellement (colonne 'a_verifier').")
    print("Corrigez au besoin la colonne 'equipe_ffhb_proposee' avant de lancer l'option 2.")

def sync_mapping(mapping_dir: str) -> int:
    """Ajoute au team_mapping.csv existant les lignes nouvelles du sheet, SANS toucher
    aux lignes déjà présentes (préserve les corrections manuelles). Retourne le nombre
    de lignes ajoutées."""
    mapping_path = os.path.join(mapping_dir, "team_mapping.csv")
    existing = pd.read_csv(mapping_path, encoding="utf-8-sig") if os.path.exists(mapping_path) else pd.DataFrame()
    existing_ids = set(existing["id"]) if not existing.empty and "id" in existing.columns else set()

    teams = load_sheet_teams()
    new_teams = teams[~teams["id"].isin(existing_ids)]
    print(f"{len(teams)} entrées équipe x phase dans le sheet, {len(new_teams)} nouvelle(s) à rapprocher.")

    new_rows = resolve_new_teams(new_teams)
    if new_rows:
        new_df = pd.DataFrame(new_rows)
        updated = pd.concat([existing, new_df], ignore_index=True) if not existing.empty else new_df
    else:
        updated = existing

    os.makedirs(mapping_dir, exist_ok=True)
    updated.to_csv(mapping_path, index=False, encoding="utf-8-sig")
    print(f"✔ team_mapping.csv à jour -> {mapping_path} ({len(new_rows)} ligne(s) ajoutée(s))")
    return len(new_rows)

def load_club_salle_cache(outdir: str) -> dict:
    path = os.path.join(outdir, "calendrier_club.csv")
    if not os.path.exists(path):
        return {}
    try:
        prev = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return {}
    cache = {}
    for _, row in prev.iterrows():
        score = str(row.get("score", "") or "").strip()
        gymnase = str(row.get("gymnase", "") or "").strip()
        lien = str(row.get("lien", "") or "").strip()
        if lien and score and gymnase:
            cache[lien] = {
                "gymnase": gymnase,
                "ville": str(row.get("ville", "") or ""),
                "adresse_complete": str(row.get("adresse_complete", "") or ""),
            }
    return cache

def scrape_one_mapping_row(page, poule_cache: dict, salle_cache: dict, t: dict):
    """Scrape la poule d'une ligne de mapping (avec cache par poule) et retourne
    (lignes_calendrier_ou_None, ligne_classement_ou_None) pour cette équipe."""
    base_url = t["poule_url"]
    label = " ".join(str(x) for x in [t["section"], t["indice"], t["categorie"], f"({t['phase']})"] if str(x) and str(x) != "nan")
    print(f"\n=== {label} -> {t['equipe_ffhb_proposee']} ===\n{base_url}")

    if base_url not in poule_cache:
        calendrier, classement, _ = scrape_poule_journees(page, base_url)
        poule_cache[base_url] = (calendrier, classement)
    calendrier, classement = poule_cache[base_url]

    team_name = t["equipe_ffhb_proposee"]
    team_calendrier = None
    if calendrier is not None and not calendrier.empty:
        mask = (
            calendrier["domicile"].str.contains(team_name, case=False, na=False, regex=False)
            | calendrier["extérieur"].str.contains(team_name, case=False, na=False, regex=False)
        )
        team_df = calendrier[mask].reset_index(drop=True)
        if not team_df.empty:
            team_df = enrich_salle(page, team_df, salle_cache)
            team_df.insert(0, "phase", t["phase"])
            team_df.insert(0, "categorie", t["categorie"])
            team_df.insert(0, "indice", t["indice"])
            team_df.insert(0, "section", t["section"])
            team_calendrier = team_df
        else:
            print("  ⚠ Aucun match trouvé pour ce nom d'équipe dans la poule (mapping probablement faux).")

    team_classement = None
    if classement is not None and not classement.empty:
        cl = classement.copy()
        cl.insert(0, "phase", t["phase"])
        cl.insert(0, "categorie", t["categorie"])
        cl.insert(0, "indice", t["indice"])
        cl.insert(0, "section", t["section"])
        team_classement = cl

    return team_calendrier, team_classement

def run_club_scrape(outdir: str):
    """Scrape complet, usage local/interactif. Écrase entièrement les fichiers de sortie."""
    mapping_path = os.path.join(outdir, "team_mapping.csv")
    if not os.path.exists(mapping_path):
        print("⚠ Aucun team_mapping.csv trouvé. Lancez d'abord l'option 1 (génération du mapping).")
        return
    mapping = pd.read_csv(mapping_path, encoding="utf-8-sig")
    mapping["equipe_ffhb_proposee"] = mapping["equipe_ffhb_proposee"].fillna("").astype(str).str.strip()
    mapping = mapping[mapping["equipe_ffhb_proposee"] != ""]
    if mapping.empty:
        print("⚠ Aucune équipe avec un nom FFHB validé dans team_mapping.csv.")
        return

    salle_cache = load_club_salle_cache(outdir)
    poule_cache = {}
    calendrier_rows = []
    classement_rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for _, t in mapping.iterrows():
            cal, cls = scrape_one_mapping_row(page, poule_cache, salle_cache, t)
            if cal is not None:
                calendrier_rows.append(cal)
            if cls is not None:
                classement_rows.append(cls)
        browser.close()

    calendrier_club = pd.concat(calendrier_rows, ignore_index=True) if calendrier_rows else pd.DataFrame()
    classements_club = pd.concat(classement_rows, ignore_index=True) if classement_rows else pd.DataFrame()

    save_if(calendrier_club, os.path.join(outdir, "calendrier_club.csv"), "Calendrier club (toutes équipes)")
    save_if(classements_club, os.path.join(outdir, "classements_club.csv"), "Classements club (toutes équipes)")

def _merge_by_key(prev: pd.DataFrame, new: pd.DataFrame, key_cols: list) -> pd.DataFrame:
    """Remplace dans `prev` les lignes des équipes présentes dans `new` (par key_cols),
    garde le reste de `prev` intact, ajoute les lignes de `new`."""
    if prev is None or prev.empty:
        return new
    if new is None or new.empty:
        return prev
    new_keys = set(tuple(x) for x in new[key_cols].itertuples(index=False, name=None))
    keep_mask = ~prev[key_cols].apply(lambda r: tuple(r) in new_keys, axis=1)
    return pd.concat([prev[keep_mask], new], ignore_index=True)

def run_club_scrape_ci(mapping_dir: str, outdir: str, teams_filter: str):
    """Scrape non interactif pour CI. Ne remplace que les équipes concernées dans les
    fichiers de sortie (les autres équipes gardent leurs données du run précédent) et
    écrit data/last_update.json avec le statut du run."""
    mapping_path = os.path.join(mapping_dir, "team_mapping.csv")
    if not os.path.exists(mapping_path):
        print("⚠ Aucun team_mapping.csv trouvé — lancez d'abord sync-mapping.")
        sys.exit(1)

    mapping = pd.read_csv(mapping_path, encoding="utf-8-sig")
    mapping["equipe_ffhb_proposee"] = mapping["equipe_ffhb_proposee"].fillna("").astype(str).str.strip()
    mapping = mapping[mapping["equipe_ffhb_proposee"] != ""]

    ids_filter = [s.strip() for s in teams_filter.split(",") if s.strip()] if teams_filter else []
    if ids_filter:
        mapping = mapping[mapping["id"].isin(ids_filter)]
    if mapping.empty:
        print("⚠ Aucune équipe à traiter (mapping vide ou filtre sans correspondance).")
        sys.exit(1)

    os.makedirs(outdir, exist_ok=True)
    calendrier_path = os.path.join(outdir, "calendrier_club.csv")
    classements_path = os.path.join(outdir, "classements_club.csv")
    prev_calendrier = pd.read_csv(calendrier_path, encoding="utf-8-sig") if os.path.exists(calendrier_path) else pd.DataFrame()
    prev_classements = pd.read_csv(classements_path, encoding="utf-8-sig") if os.path.exists(classements_path) else pd.DataFrame()

    salle_cache = load_club_salle_cache(outdir)
    poule_cache = {}
    calendrier_rows = []
    classement_rows = []
    refreshed_ids = []
    erreurs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for _, t in mapping.iterrows():
            try:
                cal, cls = scrape_one_mapping_row(page, poule_cache, salle_cache, t)
                if cal is not None:
                    calendrier_rows.append(cal)
                if cls is not None:
                    classement_rows.append(cls)
                refreshed_ids.append(t["id"])
            except Exception as e:
                print(f"  ❌ Erreur sur {t['id']}: {e}")
                erreurs.append(t["id"])
        browser.close()

    new_calendrier = pd.concat(calendrier_rows, ignore_index=True) if calendrier_rows else pd.DataFrame()
    new_classements = pd.concat(classement_rows, ignore_index=True) if classement_rows else pd.DataFrame()

    key_cols = ["section", "indice", "categorie", "phase"]
    final_calendrier = _merge_by_key(prev_calendrier, new_calendrier, key_cols)
    final_classements = _merge_by_key(prev_classements, new_classements, key_cols)

    save_if(final_calendrier, calendrier_path, "Calendrier club")
    save_if(final_classements, classements_path, "Classements club")

    status = {
        "derniere_maj": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mode": "partiel" if ids_filter else "complet",
        "equipes_rafraichies": refreshed_ids,
        "erreurs": erreurs,
    }
    with open(os.path.join(outdir, "last_update.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    print(f"\n✔ last_update.json -> {len(refreshed_ids)} équipe(s) rafraîchie(s), {len(erreurs)} erreur(s).")
    if erreurs:
        sys.exit(1)

def main():
    if len(sys.argv) > 1:
        parser = argparse.ArgumentParser(description="Scraper FFHB club (mode CI non interactif)")
        sub = parser.add_subparsers(dest="command", required=True)

        p_sync = sub.add_parser("sync-mapping", help="Ajoute les nouvelles équipes du sheet à team_mapping.csv")
        p_sync.add_argument("--mapping-dir", default="scraper")

        p_scrape = sub.add_parser("scrape", help="Scrape le calendrier/classement des équipes du mapping")
        p_scrape.add_argument("--mapping-dir", default="scraper")
        p_scrape.add_argument("--outdir", default="data")
        p_scrape.add_argument("--teams", default="", help="IDs séparés par des virgules (vide = toutes)")

        args = parser.parse_args()
        if args.command == "sync-mapping":
            sync_mapping(args.mapping_dir)
        elif args.command == "scrape":
            run_club_scrape_ci(args.mapping_dir, args.outdir, args.teams)
        return

    print("Bonjour 👋 — Scraper FFHB club")
    print("1) Générer/mettre à jour le mapping équipes (team_mapping.csv)")
    print("2) Lancer le scraping complet du club (à partir du mapping validé)")
    try:
        choice = input("Choix (1/2) : ").strip()
    except EOFError:
        choice = ""

    outdir = os.path.join(os.path.dirname(__file__), "export")
    os.makedirs(outdir, exist_ok=True)

    if choice == "1":
        build_mapping(outdir)
    elif choice == "2":
        run_club_scrape(outdir)
    else:
        print("Choix invalide (1 ou 2 attendu).")

if __name__ == "__main__":
    main()
