"""
Export-Hilfe
=============
Liest die gespeicherten Unternehmen aus startups.db und schreibt sie in
eine CSV-Datei (unternehmen.csv), die du mit Excel oder Numbers oeffnen kannst.

Aufruf im Terminal:
    python export_csv.py
"""

import sqlite3
import csv

DB_PATH = "startups.db"
CSV_PATH = "unternehmen.csv"

conn = sqlite3.connect(DB_PATH)
rows = conn.execute(
    "SELECT name, description, source_article, matched_keyword, first_seen "
    "FROM companies ORDER BY first_seen DESC"
).fetchall()
conn.close()

with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f, delimiter=";")  # Semikolon = deutsch-freundlich fuer Excel
    writer.writerow(["Firmenname", "Kurzbeschreibung", "Quell-Artikel",
                     "Treffer-Stichwort", "Zuerst gesehen"])
    writer.writerows(rows)

print(f"{len(rows)} Unternehmen exportiert nach {CSV_PATH}")
