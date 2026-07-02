"""
Startbase-Magazin-Scraper  ("Neuste Beitraege")  -  mit lokaler KI (Ollama)
===========================================================================

Was dieses Programm macht (in einfachen Worten):

1. Es oeffnet die Startbase-Seite "Neuste Beitraege" mit einem echten Browser
   (Playwright) und sammelt die Links zu den neuesten Beitraegen.
2. Es merkt sich, welche Beitraege es schon kennt, und verarbeitet nur die neuen.
3. Pro neuem Beitrag liest es NUR die Ueberschrift und die kurze Zusammenfassung
   aus (beides liefert Startbase frei zugaenglich mit).
4. Diese zwei Texte gibt es an ein KI-Modell, das LOKAL auf deinem Mac laeuft
   (Ollama). Das Modell zieht daraus drei Dinge heraus:
       - den Firmennamen,
       - einen klaren deutschen Satz, was die Firma macht,
       - ob die Firma fuer GovTech / oeffentlichen Sektor relevant ist.
5. Nur die relevanten Firmen werden mit Name + Beschreibung in einer lokalen
   SQLite-Datenbank gespeichert. Der Artikeltext selbst wird nicht gespeichert.
"""

import json
import sqlite3
import time
import datetime
import urllib.request

from playwright.sync_api import sync_playwright


# ===========================================================================
# EINSTELLUNGEN  -  hier kannst du gefahrlos Dinge anpassen
# ===========================================================================

FEED_URL = "https://www.startbase.de/feed-view/"
DB_PATH = "startups.db"

# Browserfenster sichtbar (True) oder unsichtbar (False)? Unsichtbar ist stabil.
SHOW_BROWSER = False

# Nur Firmen speichern, die die KI als relevant einstuft?
#   True  = nur relevante Firmen
#   False = ALLE erkannten Firmen speichern (zum Gegenpruefen)
ONLY_RELEVANT = True

# Lokales KI-Modell (Ollama). Laeuft auf deinem Mac, kostenlos und offline.
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1:8b"

# Hoeflichkeitspause zwischen den Beitraegen (Sekunden).
DELAY_SECONDS = 2


# ===========================================================================
# DATENBANK
# ===========================================================================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_articles (
            url          TEXT PRIMARY KEY,
            processed_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            name             TEXT PRIMARY KEY,
            description      TEXT,
            source_article   TEXT,
            matched_keyword  TEXT,
            first_seen       TEXT
        )
    """)
    conn.commit()
    return conn


def article_already_seen(conn, url):
    cur = conn.execute("SELECT 1 FROM seen_articles WHERE url = ?", (url,))
    return cur.fetchone() is not None


def mark_article_seen(conn, url):
    conn.execute(
        "INSERT OR IGNORE INTO seen_articles (url, processed_at) VALUES (?, ?)",
        (url, datetime.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def save_company(conn, name, description, source_article, category):
    conn.execute(
        """INSERT OR IGNORE INTO companies
           (name, description, source_article, matched_keyword, first_seen)
           VALUES (?, ?, ?, ?, ?)""",
        (name, description, source_article, category,
         datetime.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


# ===========================================================================
# LOKALE KI (OLLAMA)
# ===========================================================================

def ollama_available():
    """Prueft, ob Ollama laeuft und das Modell vorhanden ist."""
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        names = [m.get("name", "") for m in data.get("models", [])]
        return True, names
    except Exception as e:
        return False, str(e)


def analyze_with_ollama(title, summary):
    """Laesst das lokale Modell Firmenname, Beschreibung und Relevanz bestimmen.
    Gibt ein dict zurueck - oder None, wenn etwas schiefging."""
    prompt = (
        "Du erhaeltst Ueberschrift und Zusammenfassung eines Nachrichtenartikels "
        "ueber ein Startup.\n\n"
        "Ueberschrift: " + (title or "") + "\n"
        "Zusammenfassung: " + (summary or "") + "\n\n"
        "Aufgabe: Bestimme das wichtigste im Artikel vorgestellte Unternehmen.\n"
        "Antworte AUSSCHLIESSLICH mit einem JSON-Objekt mit genau diesen Feldern:\n"
        '  "firma": der Name des Unternehmens (nur der Name, keine Zusaetze),\n'
        '  "beschreibung": ein einziger klarer deutscher Satz, was das Unternehmen macht,\n'
        '  "relevant": true oder false,\n'
        '  "kategorie": ein kurzes Schlagwort zur Relevanz oder "".\n\n'
        "Setze relevant auf true, wenn das Unternehmen Bezug hat zu: GovTech, "
        "oeffentlicher Verwaltung oder Behoerden, digitaler Souveraenitaet, Cloud, "
        "Kuenstlicher Intelligenz (KI), Cybersecurity, oeffentlicher Vergabe oder "
        "Regulierung. Andernfalls false.\n"
        "Wenn kein einzelnes klares Unternehmen erkennbar ist (z. B. bei "
        'Wochenrueckblicken), setze firma auf "" und relevant auf false.'
    )

    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return json.loads(data["response"])
    except Exception as e:
        print("   (KI-Analyse fehlgeschlagen:", e, ")")
        return None


# ===========================================================================
# BROWSER-HILFSFUNKTIONEN
# ===========================================================================

def maybe_accept_cookies(page):
    for label in ["Akzeptieren", "Alle akzeptieren", "Zustimmen",
                  "Accept", "Einverstanden", "Alle Cookies akzeptieren"]:
        try:
            page.get_by_role("button", name=label).click(timeout=1500)
            return
        except Exception:
            pass


def collect_article_links(page):
    """Sammelt von 'Neuste Beitraege' die Links zu einzelnen Beitraegen."""
    page.goto(FEED_URL, wait_until="domcontentloaded", timeout=60000)
    maybe_accept_cookies(page)
    try:
        page.wait_for_selector("a[href*='/news/']", timeout=30000)
    except Exception:
        pass
    time.sleep(2)

    hrefs = page.eval_on_selector_all(
        "a[href*='/news/']",
        "elements => elements.map(e => e.href)",
    )
    clean = []
    for url in hrefs:
        url = url.split("#")[0].split("?")[0].rstrip("/")
        if "/news/" in url and url not in clean:
            clean.append(url)
    return clean


def get_article_info(page, article_url):
    """Liest Ueberschrift und Zusammenfassung eines Beitrags aus."""
    page.goto(article_url, wait_until="domcontentloaded", timeout=60000)
    maybe_accept_cookies(page)

    title = page.get_attribute('meta[property="og:title"]', "content") or page.title()
    title = title.split("|")[0].strip()

    summary = page.get_attribute('meta[name="description"]', "content") or ""
    if not summary:
        summary = page.get_attribute('meta[property="og:description"]', "content") or ""

    return title, summary.strip()


# ===========================================================================
# HAUPTPROGRAMM
# ===========================================================================

def main():
    print("Start:", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))

    ok, info = ollama_available()
    if not ok:
        print("\nFEHLER: Ollama ist nicht erreichbar (" + str(info) + ").")
        print("Bitte starte Ollama (Mac-App oeffnen oder 'ollama serve') und versuche es erneut.")
        return
    if OLLAMA_MODEL not in info:
        print(f"\nHinweis: Modell '{OLLAMA_MODEL}' nicht gefunden. Verfuegbar: {info}")
        print(f"Hole es mit:  ollama pull {OLLAMA_MODEL}")
        return

    conn = init_db()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not SHOW_BROWSER)
        context = browser.new_context(
            locale="de-DE",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        article_urls = collect_article_links(page)
        print(f"{len(article_urls)} Beitraege im Feed gefunden.")

        new_articles = [u for u in article_urls if not article_already_seen(conn, u)]
        print(f"{len(new_articles)} davon sind neu.\n")

        saved = 0
        for article_url in new_articles:
            title, summary = get_article_info(page, article_url)
            time.sleep(DELAY_SECONDS)
            print("Beitrag:", title)

            result = analyze_with_ollama(title, summary)
            if result is None:
                # Analyse fehlgeschlagen -> NICHT als gesehen markieren,
                # damit es beim naechsten Lauf erneut versucht wird.
                continue

            mark_article_seen(conn, article_url)

            firma = (result.get("firma") or "").strip()
            if not firma:
                print("   keine einzelne Firma erkannt - uebersprungen.")
                continue

            relevant = bool(result.get("relevant"))
            kategorie = (result.get("kategorie") or "").strip()
            beschreibung = (result.get("beschreibung") or "").strip()

            if ONLY_RELEVANT and not relevant:
                print(f"   nicht relevant - uebersprungen: {firma}")
                continue

            save_company(conn, firma, beschreibung, article_url, kategorie)
            saved += 1
            print(f"   gespeichert: {firma}  [{kategorie or 'relevant'}]")

        browser.close()

    print(f"\nFertig. {saved} Unternehmen neu gespeichert. Datenbank: {DB_PATH}")
    conn.close()


if __name__ == "__main__":
    main()
