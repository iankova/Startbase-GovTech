#!/bin/bash
# Taeglicher Lauf: erst der Scraper (fuellt die Datenbank),
# dann der Sync (schreibt ins Google Sheet). Alles wird in log.txt protokolliert.

cd /Users/polinaiankova/startbase

echo "=== Lauf $(date '+%Y-%m-%d %H:%M:%S') ===" >> log.txt
venv/bin/python startbase_scraper.py >> log.txt 2>&1
venv/bin/python sync_to_sheets.py >> log.txt 2>&1
