"""
import_old_facturen.py
---------------------
Scans old PDF invoices from the 2025 folder, extracts invoice data via PDF text
parsing, copies each PDF to facturen_pdfs/2025/Q{N}/, and inserts the data into
staging tables (facturen_history / factuurregels_history) for review before merging.

Usage (from project root):
    poetry run python3 scripts/import_old_facturen.py

After reviewing in the SQL Console (/admin/query), merge with:
    INSERT INTO facturen SELECT * FROM facturen_history
        WHERE factuurnummer NOT IN (SELECT factuurnummer FROM facturen);
    INSERT INTO factuurregels SELECT * FROM factuurregels_history
        WHERE factuur_id NOT IN (SELECT DISTINCT factuur_id FROM factuurregels);
"""

import os
import re
import shutil
import sqlite3
import glob
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    sys.exit("pdfplumber is niet geinstalleerd. Voer uit: poetry add pdfplumber")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
SOURCE_DIR = Path("/Users/joy/Library/Mobile Documents/com~apple~CloudDocs/Documents/Koen/Piet ZZP/2025")
PDF_DEST_DIR = PROJECT_DIR / "facturen_pdfs" / "2025"
DB_PATH = PROJECT_DIR / "facturen.db"

MONTH_TO_QUARTER = {1: "Q1", 2: "Q1", 3: "Q1",
                    4: "Q2", 5: "Q2", 6: "Q2",
                    7: "Q3", 8: "Q3", 9: "Q3",
                    10: "Q4", 11: "Q4", 12: "Q4"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def nl_float(value: str) -> float:
    """Convert Dutch-formatted number to float.
    Handles '1.234,56', '1 .089,00' (pdfplumber space artefact) -> 1234.56 / 1089.0
    """
    v = value.strip().replace(" ", "").replace(".", "").replace(",", ".")
    return float(v)


def parse_pdf(pdf_path: Path) -> dict | None:
    """
    Extract invoice data from a PDF file.
    Returns a dict with keys: factuurnummer, factuurdatum, klantnaam,
    totaal_excl, btw, totaal_incl, kwartaal, regels (list of dicts)
    Returns None if parsing fails.
    """
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as e:
        print(f"  [!] Kan PDF niet lezen: {e}")
        return None

    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # --- Factuurnummer ---
    fnr_match = re.search(r'Factuurnummer\s+(\d{9})', text)
    if not fnr_match:
        print(f"  [!] Geen factuurnummer gevonden in {pdf_path.name}")
        return None
    factuurnummer = fnr_match.group(1)

    # --- Factuurdatum (DD/MM/YYYY) ---
    datum_match = re.search(r'Factuurdatum\s+(\d{2}/\d{2}/\d{4})', text)
    if not datum_match:
        print(f"  [!] Geen factuurdatum gevonden in {pdf_path.name}")
        return None
    dd, mm, yyyy = datum_match.group(1).split("/")
    factuurdatum = f"{yyyy}-{mm}-{dd}"
    kwartaal = MONTH_TO_QUARTER[int(mm)]

    # --- Klantnaam: line immediately after "Teeltadvies en -verkoop" ---
    klantnaam = ""
    for i, line in enumerate(lines):
        if line == "Teeltadvies en -verkoop":
            if i + 1 < len(lines):
                klantnaam = lines[i + 1]
            break

    # --- BTW verlegd? ---
    btw_verlegd = bool(re.search(r'BTW\s+verlegd', text, re.IGNORECASE))

    # --- Totaal incl. btw ([\d\s.,]+ handles pdfplumber space artefact "1 .089,00") ---
    if btw_verlegd:
        # Format: "Totaal € 700,00"  (no BTW line)
        totaal_match = re.search(
            r'Totaal\s+[€\u20ac]\s+([\d\s.,]+)', text, re.IGNORECASE
        )
        if not totaal_match:
            print(f"  [!] Geen totaalbedrag gevonden in {pdf_path.name}")
            return None
        totaal_incl = nl_float(totaal_match.group(1))
        btw = 0.0
    else:
        totaal_incl_match = re.search(
            r'Totaal\s+inclusief\s+btw\s+[€\u20ac]\s+([\d\s.,]+)', text, re.IGNORECASE
        )
        if not totaal_incl_match:
            print(f"  [!] Geen 'Totaal inclusief btw' gevonden in {pdf_path.name}")
            return None
        totaal_incl = nl_float(totaal_incl_match.group(1))
        btw_match = re.search(r'21%\s*btw\s+[€\u20ac]\s+([\d\s.,]+)', text, re.IGNORECASE)
        btw = nl_float(btw_match.group(1)) if btw_match else 0.0

    totaal_excl = round(totaal_incl - btw, 2)

    # --- Factuurregels ---
    # Pattern: "Omschrijving text  N  €  H  €  T,TT"
    # Example: "Advisering teelt week 1 t/m 5 3 € 50 € 150,00"
    regels = []
    regel_pattern = re.compile(
        r'^(.+?)\s+(\d+(?:,\d+)?)\s+€\s+(\d+(?:,\d+)?)\s+€\s+([\d.]+,\d{2})$'
    )
    for line in lines:
        m = regel_pattern.match(line)
        if m:
            omschrijving = m.group(1).strip()
            # Skip header row
            if omschrijving.lower() in ("omschrijving", "omschrijving aantal uur uurtarief totaal"):
                continue
            regels.append({
                "omschrijving": omschrijving,
                "aantal_uren": nl_float(m.group(2)),
                "uurprijs": nl_float(m.group(3)),
                "totaal": nl_float(m.group(4)),
            })

    return {
        "factuurnummer": factuurnummer,
        "factuurdatum": factuurdatum,
        "klantnaam": klantnaam,
        "totaal_excl": totaal_excl,
        "btw": btw,
        "totaal_incl": totaal_incl,
        "kwartaal": kwartaal,
        "regels": regels,
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def create_staging_tables(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS facturen_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            factuurnummer TEXT NOT NULL UNIQUE,
            klantnaam   TEXT NOT NULL,
            klantId     INTEGER,
            factuurdatum TEXT NOT NULL,
            totaal_excl REAL NOT NULL,
            btw         REAL NOT NULL,
            totaal_incl REAL NOT NULL,
            isBetaald   BOOLEAN NOT NULL DEFAULT 0,
            kwartaal    TEXT NOT NULL,
            mailSent    BOOLEAN NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS factuurregels_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            factuur_id  TEXT NOT NULL,
            omschrijving TEXT NOT NULL,
            aantal_uren REAL NOT NULL,
            uurprijs    REAL NOT NULL,
            totaal      REAL NOT NULL,
            weeknummers TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.commit()


def find_klant_id(conn: sqlite3.Connection, klantnaam: str) -> int | None:
    """Try to match klantnaam to an existing klant_id via exact or partial match."""
    cur = conn.cursor()
    # Exact match
    cur.execute("SELECT klant_id FROM klanten WHERE klantnaam = ?", (klantnaam,))
    row = cur.fetchone()
    if row:
        return row[0]
    # Partial match: check if any word from klantnaam appears in DB klantnamen
    words = [w for w in re.split(r'\s+', klantnaam) if len(w) > 3]
    for word in words:
        cur.execute("SELECT klant_id, klantnaam FROM klanten WHERE klantnaam LIKE ?", (f"%{word}%",))
        row = cur.fetchone()
        if row:
            return row[0]
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    pdf_files = sorted(SOURCE_DIR.glob("Factuur *.pdf"))
    if not pdf_files:
        print(f"Geen PDFs gevonden in {SOURCE_DIR}")
        return

    print(f"Gevonden: {len(pdf_files)} PDFs in {SOURCE_DIR}\n")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    create_staging_tables(conn)

    stats = {"inserted": 0, "skipped": 0, "failed": 0, "copied": 0}

    for pdf_path in pdf_files:
        print(f"Verwerken: {pdf_path.name}")

        data = parse_pdf(pdf_path)
        if not data:
            stats["failed"] += 1
            continue

        fnr = data["factuurnummer"]
        print(f"  Factuurnummer : {fnr}")
        print(f"  Factuurdatum  : {data['factuurdatum']}  ({data['kwartaal']})")
        print(f"  Klant         : {data['klantnaam']}")
        print(f"  Totaal incl.  : € {data['totaal_incl']:.2f}  (btw: € {data['btw']:.2f})")
        print(f"  Regels        : {len(data['regels'])}")

        # --- Copy PDF ---
        dest_dir = PDF_DEST_DIR / data["kwartaal"]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / pdf_path.name
        if not dest_path.exists():
            shutil.copy2(str(pdf_path), str(dest_path))
            print(f"  Gekopieerd naar: facturen_pdfs/2025/{data['kwartaal']}/")
            stats["copied"] += 1
        else:
            print(f"  PDF al aanwezig, overgeslagen.")

        # --- Insert into history DB ---
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM facturen_history WHERE factuurnummer = ?", (fnr,))
        if cur.fetchone():
            print(f"  Al in history-tabel, overgeslagen.")
            stats["skipped"] += 1
            print()
            continue

        klant_id = find_klant_id(conn, data["klantnaam"])
        if klant_id:
            print(f"  Klant gevonden in DB: klantId={klant_id}")
        else:
            print(f"  Klant NIET gevonden in DB - klantId=NULL (handmatig invullen na merge)")

        cur.execute("""
            INSERT INTO facturen_history
                (factuurnummer, klantnaam, klantId, factuurdatum,
                 totaal_excl, btw, totaal_incl, isBetaald, kwartaal, mailSent)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 0)
        """, (fnr, data["klantnaam"], klant_id, data["factuurdatum"],
              data["totaal_excl"], data["btw"], data["totaal_incl"], data["kwartaal"]))

        for regel in data["regels"]:
            cur.execute("""
                INSERT INTO factuurregels_history
                    (factuur_id, omschrijving, aantal_uren, uurprijs, totaal, weeknummers)
                VALUES (?, ?, ?, ?, ?, '')
            """, (fnr, regel["omschrijving"], regel["aantal_uren"],
                  regel["uurprijs"], regel["totaal"]))

        conn.commit()
        stats["inserted"] += 1
        print()

    conn.close()

    print("=" * 60)
    print(f"Klaar!")
    print(f"  Ingevoegd in history : {stats['inserted']}")
    print(f"  Al aanwezig (skip)   : {stats['skipped']}")
    print(f"  PDFs gekopieerd      : {stats['copied']}")
    print(f"  Mislukt              : {stats['failed']}")
    print()
    print("Valideer de history-tabellen via /admin/query met:")
    print("  SELECT * FROM facturen_history ORDER BY factuurdatum;")
    print("  SELECT * FROM factuurregels_history LIMIT 50;")
    print()
    print("Merge naar productie (na validatie):")
    print("""  INSERT INTO facturen
      SELECT id, factuurnummer, klantnaam, klantId, factuurdatum,
             totaal_excl, btw, totaal_incl, isBetaald, kwartaal, mailSent
      FROM facturen_history
      WHERE factuurnummer NOT IN (SELECT factuurnummer FROM facturen);

  INSERT INTO factuurregels
      SELECT id, factuur_id, omschrijving, aantal_uren, uurprijs, totaal, weeknummers
      FROM factuurregels_history
      WHERE factuur_id NOT IN (SELECT DISTINCT factuur_id FROM factuurregels);""")


if __name__ == "__main__":
    main()
