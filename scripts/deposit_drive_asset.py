#!/usr/bin/env python3
"""Dépose un fichier (PNG de post ou story Canva) dans le dossier Drive
dédié correspondant, via l'action `add_asset` du même Web App Apps Script
que le formulaire score/photo (voir CLAUDE.md, apps-script/Code.gs).

Le fichier est encodé en base64 côté client, comme la photo de fin de
match (`add_photo`) — Apps Script ne reçoit pas de vrai Blob multipart
pour une requête postée par un client externe, voir la docstring
d'`addPhoto` dans Code.gs. Mêmes URL/secret publics que ceux déjà
embarqués en clair dans result_stories.py (FORM_SHARED_SECRET, moins
sensible que SHARED_SECRET par conception — sa présence ici n'est pas une
nouvelle exposition).

Usage :
    python scripts/deposit_drive_asset.py \
        --kind weekend_post --subfolder "17 & 18 JAN." --file 01-couverture.png

    python scripts/deposit_drive_asset.py \
        --kind result_story --subfolder rencontre-2654273 --file story.png

`--kind` détermine le dossier racine Drive : `weekend_post` -> "Temp
posts Instagram", `result_story` -> "Temp stories Instagram". `--subfolder`
regroupe les fichiers d'un même run (le weekend_label pour le post hebdo,
le match_id pour une story résultat) dans un sous-dossier dédié.

Affiche le JSON de réponse ({"ok": true, "url": "...", "fileId": "..."})
sur stdout et sort en code 1 si `ok` est faux.
"""

import argparse
import base64
import json
import mimetypes
import sys
import urllib.request
import urllib.parse

# Mêmes valeurs que CONFIG.webhookUrl / CONFIG.webhookSecret dans
# form-score-club-2-/index.html et FORM_SHARED_SECRET dans result_stories.py (public, voir
# docstring ci-dessus).
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzA8_vH6hAwZl3aBOxEtL4sKqxi10mhY6Tw0dDRLU-SHszHHui4GXSR04GX8VV15oQC/exec"
FORM_SHARED_SECRET = "wpFt6IaS4QDZCodB"


def deposit(kind: str, subfolder: str, file_path: str) -> dict:
    with open(file_path, "rb") as f:
        content = f.read()

    file_type = mimetypes.guess_type(file_path)[0] or "image/png"
    file_name = file_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]

    data = urllib.parse.urlencode({
        "action": "add_asset",
        "secret": FORM_SHARED_SECRET,
        "kind": kind,
        "subfolder": subfolder,
        "file_name": file_name,
        "file_type": file_type,
        "file_base64": base64.b64encode(content).decode("ascii"),
    }).encode("utf-8")

    req = urllib.request.Request(WEBHOOK_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", required=True, choices=["weekend_post", "result_story"])
    ap.add_argument("--subfolder", required=True, help="Regroupe les fichiers d'un même run (weekend_label ou match_id)")
    ap.add_argument("--file", required=True, help="Chemin local du fichier à déposer")
    args = ap.parse_args()

    result = deposit(args.kind, args.subfolder, args.file)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
