# scrape_ffhb.py
import io, os, re, sys
from typing import List, Optional

import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

def clean_text(x: str) -> str:
    return re.sub(r"\s+", " ", x or "").strip()

def slugify(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_") or "equipe"

def parse_table_by_heading(soup: BeautifulSoup, heading_keywords: List[str]) -> Optional[pd.DataFrame]:
    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        txt = clean_text(h.get_text(" "))
        if any(k.lower() in txt.lower() for k in heading_keywords):
            limit = h.find_next(re.compile(r"^h[1-6]$"))
            table = None
            for el in h.find_all_next():
                if limit is not None and el is limit:
                    break
                if el.name == "table":
                    table = el
                    break
                if el.name == "div" and re.search("table", el.get("role") or "", re.I):
                    table = el
                    break
            if table:
                if table.name == "table":
                    try:
                        df = pd.read_html(io.StringIO(str(table)))[0]
                        return df
                    except Exception:
                        pass
                # Structure ARIA role=table
                rows = []
                header = []
                head_row = table.find(["div", "tr"], attrs={"role": re.compile("row", re.I)})
                if head_row:
                    cells = head_row.find_all(["div", "th", "td"], attrs={"role": re.compile("(columnheader|cell|gridcell)", re.I)})
                    header = [clean_text(c.get_text(" ")) for c in cells]
                for r in table.find_all(["div", "tr"], attrs={"role": re.compile("row", re.I)}):
                    cells = r.find_all(["div", "td", "th"], attrs={"role": re.compile("(cell|gridcell)", re.I)})
                    if not cells:
                        continue
                    rows.append([clean_text(c.get_text(" ")) for c in cells])
                if rows:
                    df = pd.DataFrame(rows, columns=header if header and len(header) == len(rows[0]) else None)
                    return df
    return None

def extract_matches(soup: BeautifulSoup, journee_num: int) -> pd.DataFrame:
    # Date/plage affichée en tête de journée (utilisée en repli quand un match n'a pas encore de date fixée)
    header_date = ""
    date_range_re = re.compile(r"\d{1,2}\s+\S+\s+\d{4}\s+au\s+\d{1,2}\s+\S+\s+\d{4}", re.I)
    for el in soup.find_all(class_=re.compile(r"styles_title", re.I)):
        txt = clean_text(el.get_text(" "))
        if date_range_re.search(txt):
            header_date = txt
            break

    rows = []
    cards = soup.find_all("a", class_=re.compile(r"rencontre", re.I))
    for card in cards:
        date_el = card.find(class_=re.compile(r"block_date", re.I))
        own_date = clean_text(date_el.get_text(" ")) if date_el else ""
        # Une carte sans sa propre date n'a pas de date confirmée, même si un match
        # précédent dans la liste en affiche une (ce n'est pas un partage de créneau).
        date_val = own_date or header_date

        team_names = card.find_all(class_=re.compile(r"teamName", re.I))
        scores = card.find_all(class_=re.compile(r"score", re.I))
        domicile = clean_text(team_names[0].get_text(" ")) if len(team_names) > 0 else ""
        exterieur = clean_text(team_names[1].get_text(" ")) if len(team_names) > 1 else ""
        score_dom = clean_text(scores[0].get_text(" ")) if len(scores) > 0 else ""
        score_ext = clean_text(scores[1].get_text(" ")) if len(scores) > 1 else ""
        joue = score_dom.isdigit() and score_ext.isdigit()
        score = f"{score_dom} - {score_ext}" if joue else ""
        date_connue = bool(own_date)
        href = card.get("href", "")
        lien = f"https://www.ffhandball.fr{href}" if href.startswith("/") else href
        rows.append({
            "journée": journee_num,
            "date/heure": date_val,
            "date_confirmee": date_connue,
            "domicile": domicile,
            "extérieur": exterieur,
            "score": score,
            "lien": lien,
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame()

def extract_salle(soup: BeautifulSoup) -> dict:
    address_div = soup.find("div", class_=re.compile(r"style_address", re.I))
    if not address_div:
        return {"gymnase": "", "ville": "", "adresse_complete": ""}
    spans = address_div.find_all("span")
    texts = [clean_text(s.get_text(" ")) for s in spans]
    gymnase = texts[0] if len(texts) > 0 else ""
    rue = texts[1] if len(texts) > 1 else ""
    ville = texts[2] if len(texts) > 2 else ""
    adresse_complete = ", ".join(t for t in [gymnase, rue, ville] if t)
    return {"gymnase": gymnase, "ville": ville, "adresse_complete": adresse_complete}

def save_if(df: Optional[pd.DataFrame], path: str, label: str):
    if df is not None and not df.empty:
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"✔ {label} -> {path}")
    else:
        print(f"⚠ {label} non trouvé automatiquement.")

def get_num_journees(page) -> int:
    nums = page.evaluate(r"""
        () => Array.from(document.querySelectorAll('button'))
            .map(b => b.textContent.trim())
            .filter(t => /^J\d{1,2}$/.test(t))
            .map(t => parseInt(t.slice(1), 10))
    """)
    return max(nums) if nums else 1

def load_salle_cache(outdir: str, team_filter: str) -> dict:
    # Réutilise le CSV équipe d'un run précédent : un match déjà noté (score connu)
    # n'a pas besoin d'être re-scrapé, sa salle ne changera plus.
    path = os.path.join(outdir, f"calendrier_{slugify(team_filter)}.csv")
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

def normalize_poule_base_url(url: str) -> str:
    return re.sub(r"/journee-\d+/?$", "", url.rstrip("/")) + "/"

def resolve_poule_base_url(page, base_url: str) -> str:
    """Certains liens (compétition à poule unique) ne contiennent pas /poule-XXXXX/.
    La page par défaut affiche quand même la poule, mais /journee-N/ ne fonctionne
    pas sans ce segment (404). On le retrouve via un lien interne (ex. Classement)."""
    if re.search(r"/poule-\d+/", base_url):
        return base_url
    try:
        page.goto(base_url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_selector('a[href*="/poule-"]', timeout=15000)
        href = page.evaluate(
            "() => { const a = document.querySelector('a[href*=\"/poule-\"]'); return a ? a.getAttribute('href') : null; }"
        )
    except Exception:
        return base_url
    m = re.search(r"/poule-\d+/", href or "")
    if not m:
        return base_url
    resolved = base_url.rstrip("/") + m.group(0)
    print(f"  URL de poule résolue -> {resolved}")
    return resolved

def scrape_poule_journees(page, base_url: str):
    """Parcourt toutes les journées d'une poule. Retourne (calendrier_df, classement_df, num_journees)."""
    base_url = resolve_poule_base_url(page, base_url)
    page.goto(base_url, wait_until="domcontentloaded", timeout=90000)
    try:
        page.wait_for_selector("table", timeout=30000)
    except Exception:
        pass
    num_journees = get_num_journees(page)
    print(f"{num_journees} journée(s) détectée(s).")

    all_rows = []
    classement = None
    for j in range(1, num_journees + 1):
        j_url = f"{base_url}journee-{j}/"
        print(f"  Journée {j}/{num_journees}...")
        page.goto(j_url, wait_until="domcontentloaded", timeout=90000)
        try:
            page.wait_for_selector('a[class*="rencontre"], table', timeout=20000)
        except Exception:
            pass
        html = page.content()
        soup = BeautifulSoup(html, "lxml")

        df = extract_matches(soup, journee_num=j)
        if not df.empty:
            all_rows.append(df)

        if classement is None:
            classement = parse_table_by_heading(soup, ["Classement", "Classement général", "Tableau"])
            if classement is not None and not classement.empty:
                rename_map = {
                    "Pts": "Points", "J": "Joués", "G": "Gagnés", "N": "Nuls", "P": "Perdus",
                    "Diff": "Différence", "But+": "Buts+", "But-": "Buts-", "N°": "Rang", "Équipe": "Équipe",
                }
                classement = classement.rename(columns={k: v for k, v in rename_map.items() if k in classement.columns})

    calendrier = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    return calendrier, classement, num_journees

def enrich_salle(page, team_df: pd.DataFrame, salle_cache: dict) -> pd.DataFrame:
    """Ajoute gymnase/ville/adresse_complete à team_df, en réutilisant salle_cache pour les matchs déjà joués."""
    gymnases, villes, adresses = [], [], []
    for i, row in team_df.iterrows():
        lien = row["lien"]
        score_connu = bool(str(row.get("score", "") or "").strip())
        cached = salle_cache.get(lien) if (score_connu and lien) else None
        if cached:
            print(f"  Match {i + 1}/{len(team_df)} déjà joué et connu ({row['domicile']} - {row['extérieur']}) -> cache")
            salle = cached
        elif lien:
            print(f"  Détail match {i + 1}/{len(team_df)} ({row['domicile']} - {row['extérieur']})...")
            try:
                page.goto(lien, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_selector('div[class*="style_address"], h3', timeout=10000)
            except Exception:
                pass
            salle = extract_salle(BeautifulSoup(page.content(), "lxml"))
        else:
            salle = {"gymnase": "", "ville": "", "adresse_complete": ""}
        gymnases.append(salle["gymnase"])
        villes.append(salle["ville"])
        adresses.append(salle["adresse_complete"])
    team_df = team_df.copy()
    team_df["gymnase"] = gymnases
    team_df["ville"] = villes
    team_df["adresse_complete"] = adresses
    ordered_cols = [c for c in team_df.columns if c not in ("lien", "adresse_complete")] + ["lien", "adresse_complete"]
    return team_df[ordered_cols]

def fetch_poule(url: str, outdir: str, team_filter: Optional[str]):
    print(f"\n=== Traitement de la poule ===\n{url}\n")
    base_url = normalize_poule_base_url(url)

    team_df = pd.DataFrame()
    salle_cache = load_salle_cache(outdir, team_filter) if team_filter else {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        calendrier, classement, _ = scrape_poule_journees(page, base_url)

        if team_filter and not calendrier.empty:
            mask = (
                calendrier["domicile"].str.contains(team_filter, case=False, na=False, regex=False)
                | calendrier["extérieur"].str.contains(team_filter, case=False, na=False, regex=False)
            )
            team_df = calendrier[mask].reset_index(drop=True)
            team_df = enrich_salle(page, team_df, salle_cache)

        browser.close()

    save_if(calendrier, os.path.join(outdir, "calendrier_complet.csv"), "Calendrier complet (toutes journées)")
    save_if(classement, os.path.join(outdir, "classement.csv"), "Classement")

    if team_filter:
        fname = f"calendrier_{slugify(team_filter)}.csv"
        save_if(team_df, os.path.join(outdir, fname), f"Calendrier filtré ({team_filter})")

def main():
    print("Bonjour 👋")
    print("Collez l'URL de la poule FFHB (ex: https://www.ffhandball.fr/competitions/.../poule-XXXXX/)")
    print("Toutes les journées de la poule seront parcourues automatiquement.")
    print("Vous pourrez entrer plusieurs poules, une par ligne. Laissez vide pour terminer.\n")
    urls = []
    while True:
        try:
            u = input("URL de poule (ou Entrée pour finir) : ").strip()
        except EOFError:
            break
        if not u:
            break
        urls.append(u)
    if not urls:
        print("Aucune URL fournie, arrêt.")
        sys.exit(0)

    try:
        team = input("Nom de l'équipe à filtrer (laisser vide pour ne pas filtrer) : ").strip()
    except EOFError:
        team = ""

    outdir = os.path.join(os.path.dirname(__file__), "export")
    os.makedirs(outdir, exist_ok=True)

    for u in urls:
        try:
            fetch_poule(u, outdir, team or None)
        except Exception as e:
            print(f"❌ Erreur sur {u}: {e}")

    print("\nTerminé. Les fichiers sont dans le dossier 'export/'.")

if __name__ == "__main__":
    main()
