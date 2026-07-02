"""
Google-Sheets-Sync
===================
Schreibt die in startups.db gespeicherten Unternehmen in ein Google Sheet.
Bei jedem Lauf wird das Tabellenblatt geleert und mit der kompletten,
aktuellen Liste neu befuellt - das Sheet ist also immer ein 1:1-Abbild
der Datenbank.

Voraussetzungen (einmalig, siehe Anleitung):
  - "service_account.json"  : die Schluesseldatei aus der Google Cloud Console
  - "sheet_url.txt"         : eine Textdatei mit der Adresse deines Google Sheets
  - das Sheet wurde fuer die Service-Account-E-Mail freigegeben (Bearbeiter)

Aufruf:
    python sync_to_sheets.py
"""

import os
import sqlite3

import gspread


# ---- EINSTELLUNGEN ----
DB_PATH = "startups.db"
CREDENTIALS_FILE = "service_account.json"
SHEET_URL_FILE = "sheet_url.txt"

HEADERS = ["Firmenname", "Kurzbeschreibung", "Quell-Beitrag",
           "Treffer-Stichwort", "Zuerst gesehen"]


def main():
    # 1) Pruefen, ob die noetigen Dateien da sind - mit freundlicher Erklaerung.
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"FEHLT: '{CREDENTIALS_FILE}' nicht gefunden. Bitte die Schluesseldatei "
              f"aus der Google Cloud Console in diesen Ordner legen und so benennen.")
        return

    if not os.path.exists(SHEET_URL_FILE):
        print(f"FEHLT: '{SHEET_URL_FILE}' nicht gefunden. Bitte anlegen, z. B. mit:\n"
              f'   echo "DEINE_GOOGLE_SHEET_URL" > {SHEET_URL_FILE}')
        return

    with open(SHEET_URL_FILE) as f:
        sheet_url = f.read().strip()
    if not sheet_url.startswith("http"):
        print(f"Die Datei '{SHEET_URL_FILE}' enthaelt keine gueltige Adresse.")
        return

    # 2) Daten aus der lokalen Datenbank lesen.
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT name, description, source_article, matched_keyword, first_seen "
        "FROM companies ORDER BY first_seen DESC"
    ).fetchall()
    conn.close()

    # Leere Felder (None) zu leerem Text machen, damit Google nicht stolpert.
    data = [HEADERS]
    for r in rows:
        data.append([(value if value is not None else "") for value in r])

    # 3) Mit Google verbinden und das Sheet oeffnen.
    try:
        gc = gspread.service_account(filename=CREDENTIALS_FILE)
        sh = gc.open_by_url(sheet_url)
        ws = sh.sheet1
    except gspread.exceptions.SpreadsheetNotFound:
        print("Das Sheet wurde nicht gefunden. Hast du es fuer die Service-Account-"
              "E-Mail (aus service_account.json, Feld 'client_email') freigegeben?")
        return
    except Exception as e:
        print("Verbindung zu Google fehlgeschlagen:", e)
        return

    # 4) Tabellenblatt leeren und komplett neu schreiben.
    ws.clear()
    ws.update(data, "A1")

    print(f"{len(rows)} Unternehmen ins Google Sheet geschrieben.")


if __name__ == "__main__":
    main()
