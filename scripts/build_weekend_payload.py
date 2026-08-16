#!/usr/bin/env python3
"""Construit le payload JSON des matchs du prochain week-end, regroupés par
page du post Instagram "planning des matchs" (Canva).

Source de données : `data/calendrier_club.csv` (un match par ligne) et
`scraper/team_mapping.csv` (identifie quel côté domicile/extérieur est
"nous"), lus en local par défaut ou via URL (--calendrier / --team-mapping
acceptent indifféremment un chemin local ou une URL http(s), ex. les URLs
GitHub Pages publiques du repo) pour un run sans accès au filesystem local
(ex. depuis une session planifiée type Cowork) :
    --calendrier https://sportingvillette-beep.github.io/sv-planning-entrainements/data/calendrier_club.csv
    --team-mapping https://sportingvillette-beep.github.io/sv-planning-entrainements/scraper/team_mapping.csv

Réutilise la même logique de nettoyage de nom d'adversaire et de parsing de
date que `index.html` (stripCategoryPrefix / splitTrailingIndex /
parseFrenchDate en JS) — voir CLAUDE.md section "Source de données" et
`cleanOpponentLabel` dans index.html. Toute modification de cette logique
doit être répercutée des deux côtés.

Usage :
    python scripts/build_weekend_payload.py \
        --calendrier data/calendrier_club.csv \
        --team-mapping scraper/team_mapping.csv \
        [--today 2026-08-11] [--out -]

Sortie (stdout par défaut) : JSON avec `weekend_label`, `saturday`,
`sunday`, `pages` (une clé par page du gabarit Canva, liste de lignes
{equipe, jour, recevant, visiteur, lieu}) et `domicile` (matchs à Villette
d'Anthon, toutes catégories, {equipe, jour, recevant, visiteur}). Une page
sans aucun match n'apparaît pas dans `pages` (le gabarit Canva ne doit pas
l'inclure cette semaine-là).
"""

import argparse
import csv
import io
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

MONTHS_FR = {
    "janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "décembre": 12,
}
MONTH_ABBR_FR = {
    1: "JAN", 2: "FÉV", 3: "MARS", 4: "AVR", 5: "MAI", 6: "JUIN",
    7: "JUIL", 8: "AOÛT", 9: "SEPT", 10: "OCT", 11: "NOV", 12: "DÉC",
}
WEEKDAY_ABBR_FR = {5: "Sam", 6: "Dim"}  # Python weekday(): Monday=0..Sunday=6

# Regroupement des catégories en pages du gabarit Canva (ordre = ordre des
# pages 3 à 9 du design DAHSb3SEpJ4). Catégories volontairement absentes
# (pas de championnat) : M5, Loisirs, Handfit.
PAGE_ORDER = ["M7_M9", "M11", "M13", "M15", "M16_M17", "M18", "Seniors"]
CATEGORIE_TO_PAGE = {
    "M7": "M7_M9", "M9": "M7_M9",
    "M11": "M11",
    "M13": "M13",
    "M15": "M15",
    "M16": "M16_M17", "M17": "M16_M17",
    "M18": "M18",
    "Seniors": "Seniors",
}
CATEGORIE_SORT_ORDER = {"M7": 0, "M9": 1, "M11": 2, "M13": 3, "M15": 4, "M16": 5, "M17": 6, "M18": 7, "Seniors": 8}
GENRE_SORT_ORDER = {"F": 0, "G": 1, "": 2}

DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})(?:\s+à\s+(\d{1,2})[hH](\d{2}))?")
STRIP_PREFIX_RE = re.compile(r"^[A-Za-zÀ-ÿ]*\d[A-Za-zÀ-ÿ0-9]*\s+[A-ZÀ-Ÿ0-9]+\s*-\s*(.+)$")
TRAILING_INDEX_RE = re.compile(r"^(.*\S)[\s-]+([A-Za-z]|\d{1,2})$")
GENRE_SUFFIX_RE = re.compile(r"\s*\([FG]\)\s*$")


def parse_french_dates(raw: str):
    """Toutes les dates trouvées dans une chaîne (1 pour une date confirmée,
    2 pour une plage "X au Y" non confirmée). Renvoie une liste de
    (date, heure_str_ou_None)."""
    if not raw:
        return []
    out = []
    for d, mo, y, h, mi in DATE_RE.findall(raw):
        month = MONTHS_FR.get(mo.lower())
        if month is None:
            continue
        out.append((date(int(y), month, int(d)), f"{int(h):02d}:{mi}" if h else None))
    return out


def strip_category_prefix(name: str) -> str:
    m = STRIP_PREFIX_RE.match(name)
    return m.group(1).strip() if m else name


def split_trailing_index(name: str):
    name = (name or "").strip()
    m = TRAILING_INDEX_RE.match(name)
    if m and len(m.group(1)) > 3:
        return m.group(1).rstrip(" -").strip(), m.group(2)
    return name, ""


def clean_opponent_label(raw: str) -> str:
    stripped = strip_category_prefix((raw or "").strip())
    base, idx = split_trailing_index(stripped)
    return f"{base} - {idx}" if idx else base


def pretty_section(section: str) -> str:
    """Nom de club affichable : retire le suffixe genre '(F)'/'(G)' du nom
    de section (ex. 'Entente Lyon Est Handball (F)' -> 'Entente Lyon Est
    Handball')."""
    return GENRE_SUFFIX_RE.sub("", section or "").strip()


def next_saturday(today: date) -> date:
    """Samedi du prochain week-end à venir (si `today` est déjà samedi ou
    dimanche, renvoie le samedi de CE week-end)."""
    wd = today.weekday()  # Monday=0 .. Sunday=6
    if wd == 5:
        return today
    if wd == 6:
        return today - timedelta(days=1)
    return today + timedelta(days=(5 - wd))


def weekend_label(saturday: date, sunday: date) -> str:
    if saturday.month == sunday.month:
        return f"{saturday.day} & {sunday.day} {MONTH_ABBR_FR[saturday.month]}."
    return f"{saturday.day} {MONTH_ABBR_FR[saturday.month]}. & {sunday.day} {MONTH_ABBR_FR[sunday.month]}."


def equipe_label(categorie: str, genre: str, indice: str) -> str:
    parts = [categorie]
    if genre:
        parts.append(genre)
    if indice:
        parts.append(indice)
    return " ".join(parts)


def _read_csv(source: str) -> list:
    if source.startswith("http://") or source.startswith("https://"):
        with urllib.request.urlopen(source, timeout=30) as resp:
            raw = resp.read().decode("utf-8-sig")
    else:
        with open(source, "r", encoding="utf-8-sig") as f:
            raw = f.read()
    return list(csv.DictReader(io.StringIO(raw)))


def load_team_mapping(source: str) -> dict:
    """Index (section, indice, categorie, phase) -> ligne team_mapping."""
    rows = _read_csv(source)
    index = {}
    for r in rows:
        key = (r.get("section", ""), r.get("indice", ""), r.get("categorie", ""), r.get("phase", ""))
        index[key] = r
    return index


def build_payload(calendrier_source: str, team_mapping_source: str, today: date) -> dict:
    calendrier_rows = _read_csv(calendrier_source)
    team_index = load_team_mapping(team_mapping_source)

    saturday = next_saturday(today)
    sunday = saturday + timedelta(days=1)
    target_dates = {saturday, sunday}

    pages = {p: [] for p in PAGE_ORDER}
    domicile = []
    warnings = []

    for row in calendrier_rows:
        section = row.get("section", "")
        indice = row.get("indice", "")
        categorie = row.get("categorie", "")
        phase = row.get("phase", "")
        if not section or categorie not in CATEGORIE_TO_PAGE:
            continue  # catégorie hors périmètre (M5/Loisirs/Handfit) ou ligne vide

        parsed = parse_french_dates(row.get("date/heure", ""))
        match_dates = [d for d, _ in parsed]
        if not any(d in target_dates for d in match_dates):
            continue  # pas ce week-end-là

        confirmee = row.get("date_confirmee", "").strip().lower() == "true"
        match_date = next((d for d in match_dates if d in target_dates), None)
        heure = next((h for d, h in parsed if d == match_date and h), None) if confirmee else None

        if confirmee and match_date and heure:
            jour = f"{WEEKDAY_ABBR_FR.get(match_date.weekday(), '')} {heure}"
        else:
            jour = "Sam ou Dim"

        team = team_index.get((section, indice, categorie, phase))
        if team is None:
            warnings.append(f"Pas de team_mapping trouvé pour {section} / {indice} / {categorie} / {phase}")
            continue
        genre = team.get("genre", "")
        our_name = (team.get("equipe_ffhb_proposee", "") or "").strip()

        domicile_raw = (row.get("domicile", "") or "").strip()
        exterieur_raw = (row.get("extérieur", "") or "").strip()
        club_name = pretty_section(section)

        if our_name and our_name.casefold() == domicile_raw.casefold():
            recevant, visiteur, us_home = club_name, clean_opponent_label(exterieur_raw), True
        elif our_name and our_name.casefold() == exterieur_raw.casefold():
            recevant, visiteur, us_home = clean_opponent_label(domicile_raw), club_name, False
        else:
            warnings.append(
                f"Impossible de déterminer notre côté (dom={domicile_raw!r} ext={exterieur_raw!r} "
                f"attendu={our_name!r}) pour {section}/{indice}/{categorie} — ligne ignorée"
            )
            continue

        ville = (row.get("ville", "") or "").strip()
        lieu = ville if (confirmee and ville) else "Lieu à confirmer"

        entry = {
            "equipe": equipe_label(categorie, genre, indice),
            "jour": jour,
            "recevant": recevant,
            "visiteur": visiteur,
            "lieu": lieu,
            "_sort": (CATEGORIE_SORT_ORDER.get(categorie, 99), GENRE_SORT_ORDER.get(genre, 9), indice),
        }
        pages[CATEGORIE_TO_PAGE[categorie]].append(entry)

        if confirmee and "villette d'anthon" in ville.casefold():
            domicile.append({k: entry[k] for k in ("equipe", "jour", "recevant", "visiteur", "_sort")})

    for p in pages:
        pages[p].sort(key=lambda e: e["_sort"])
        for e in pages[p]:
            del e["_sort"]
    domicile.sort(key=lambda e: e["_sort"])
    for e in domicile:
        del e["_sort"]

    pages_non_vides = {p: rows for p, rows in pages.items() if rows}

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "weekend_label": weekend_label(saturday, sunday),
        "saturday": saturday.isoformat(),
        "sunday": sunday.isoformat(),
        "pages": pages_non_vides,
        "domicile": domicile,
        "warnings": warnings,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calendrier", default="data/calendrier_club.csv", help="Chemin ou URL du CSV calendrier")
    ap.add_argument("--team-mapping", default="scraper/team_mapping.csv", help="Chemin ou URL du CSV team_mapping")
    ap.add_argument("--today", help="Date de référence AAAA-MM-JJ (défaut : aujourd'hui) — pour tester un autre jour que le run réel")
    ap.add_argument("--out", default="-", help="Fichier de sortie JSON ('-' = stdout)")
    args = ap.parse_args()

    today = date.fromisoformat(args.today) if args.today else date.today()
    payload = build_payload(args.calendrier, args.team_mapping, today)

    out_text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out == "-":
        print(out_text)
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out_text)

    if payload["warnings"]:
        print(f"\n{len(payload['warnings'])} avertissement(s) :", file=sys.stderr)
        for w in payload["warnings"]:
            print(f"  - {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
