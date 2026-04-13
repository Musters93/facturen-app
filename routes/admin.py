from fastapi import APIRouter, Request, Body, Form, Query
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from database import get_db
from services.pdf_generator_service import genereer_pdf
from services.mail_service import prepare_email_data
import os
import glob
import csv
import re

templates = Jinja2Templates(directory="templates")
router = APIRouter()

# ==========================================
# ADMIN OVERZICHT
# ==========================================
@router.get("/")
def admin(
    request: Request,
    table: str = "klanten",
    search: str = "",
    jaar: str = "",
    kwartaal: str = ""
):
    with get_db() as conn:
        cur = conn.cursor()
        selected_table = table
        search_query = search.strip()

        # Jaren ophalen
        cur.execute("SELECT DISTINCT strftime('%Y', factuurdatum) AS jaar FROM facturen ORDER BY jaar")
        jaren_rows = cur.fetchall()
        jaren = [r["jaar"] for r in jaren_rows]

        # Factuurnummers op basis van jaar
        factuurnummers_jaar = None
        if jaar:
            cur.execute("SELECT factuurnummer FROM facturen WHERE strftime('%Y', factuurdatum) = ?", (jaar,))
            factuurnummers_jaar = [r["factuurnummer"] for r in cur.fetchall()]

        # ==========================
        # KLANTEN
        # ==========================
        query_klanten = "SELECT * FROM klanten"
        conditions_klanten = []
        params_klanten = []

        if selected_table == "klanten":
            if search_query:
                like = f"%{search_query}%"
                conditions_klanten.append("(klantnaam LIKE ? OR adres LIKE ? OR email LIKE ?)")
                params_klanten.extend([like, like, like])

            if jaar:
                conditions_klanten.append("""
                    klant_id IN (
                        SELECT klantId FROM facturen
                        WHERE strftime('%Y', factuurdatum) = ?
                    )
                """)
                params_klanten.append(jaar)

        if conditions_klanten:
            query_klanten += " WHERE " + " AND ".join(conditions_klanten)

        cur.execute(query_klanten, params_klanten)
        klanten = cur.fetchall()

        # ==========================
        # FACTUREN
        # ==========================
        query_facturen = """
            SELECT f.*, k.klantnaam, k.btw_verlegd
            FROM facturen f
            JOIN klanten k ON f.klantId = k.klant_id
            WHERE 1=1
        """
        conditions_facturen = []
        params_facturen = []

        if jaar:
            conditions_facturen.append("strftime('%Y', f.factuurdatum) = ?")
            params_facturen.append(jaar)

        if search_query:
            like = f"%{search_query}%"
            conditions_facturen.append("(f.factuurnummer LIKE ? OR k.klantnaam LIKE ? OR f.factuurdatum LIKE ?)")
            params_facturen.extend([like, like, like])

        if selected_table == "facturen":
            if conditions_facturen:
                query_facturen += " AND " + " AND ".join(conditions_facturen)
            query_facturen += " ORDER BY f.factuurdatum DESC"
            cur.execute(query_facturen, params_facturen)
            facturen = cur.fetchall()
        else:
            cur.execute("""
                SELECT f.*, k.klantnaam, k.btw_verlegd
                FROM facturen f
                JOIN klanten k ON f.klantId = k.klant_id
                ORDER BY f.factuurdatum DESC
            """)
            facturen = cur.fetchall()

        # ==========================
        # FACTUURREGELS
        # ==========================
        query_regels = "SELECT * FROM factuurregels"
        conditions_regels = []
        params_regels = []

        if selected_table == "factuurregels":
            if search_query:
                like = f"%{search_query}%"
                conditions_regels.append("(omschrijving LIKE ? OR factuur_id LIKE ?)")
                params_regels.extend([like, like])

            if jaar and factuurnummers_jaar:
                placeholders = ",".join("?" * len(factuurnummers_jaar))
                conditions_regels.append(f"factuur_id IN ({placeholders})")
                params_regels.extend(factuurnummers_jaar)

        if conditions_regels:
            query_regels += " WHERE " + " AND ".join(conditions_regels)

        query_regels += " ORDER BY id DESC"
        cur.execute(query_regels, params_regels)
        factuurregels = cur.fetchall()

        # ==========================
        # TOTALEN PER KWARTAAL
        # ==========================
        totalen_query = """
            SELECT f.kwartaal, 
                   SUM(CASE WHEN k.btw_verlegd=0 THEN f.totaal_excl ELSE 0 END) AS binnenland,
                   SUM(CASE WHEN k.btw_verlegd=0 THEN f.btw ELSE 0 END) AS btw,
                   SUM(CASE WHEN k.btw_verlegd=1 THEN f.totaal_excl ELSE 0 END) AS buitenland
            FROM facturen f
            JOIN klanten k ON f.klantId = k.klant_id
            WHERE 1=1
        """
        total_params = []
        if jaar:
            totalen_query += " AND strftime('%Y', f.factuurdatum) = ?"
            total_params.append(jaar)
        totalen_query += " GROUP BY f.kwartaal"

        cur.execute(totalen_query, total_params)
        rows = cur.fetchall()
        totalen = {
            r["kwartaal"]: {
                "binnenland": r["binnenland"] or 0,
                "btw": r["btw"] or 0,
                "buitenland": r["buitenland"] or 0
            } for r in rows
        }

    return templates.TemplateResponse("admin/overview.html", {
        "request": request,
        "klanten": klanten,
        "facturen": facturen,
        "factuurregels": factuurregels,
        "totalen": totalen,
        "selected_table": selected_table,
        "search_query": search_query,
        "selected_jaar": jaar,
        "selected_kwartaal": kwartaal,
        "jaren": jaren,
    })

# ==========================================
# REGEN PDF
# ==========================================
@router.get("/regen_pdf/{factuurnummer}")
def regen_pdf(factuurnummer: str, request: Request):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM facturen WHERE factuurnummer = ?", (factuurnummer,))
        factuur = cur.fetchone()
        if not factuur:
            return {"error": "Factuur niet gevonden"}

        cur.execute("SELECT * FROM klanten WHERE klant_id = ?", (factuur["klantId"],))
        klant = cur.fetchone()

        # factuurregels zijn opgeslagen met factuurnummer in kolom factuur_id
        cur.execute("SELECT * FROM factuurregels WHERE factuur_id = ?", (factuurnummer,))
        regels_db = cur.fetchall()

    factuur_data = {
        "factuurnummer": factuur["factuurnummer"],
        "factuurdatum": factuur["factuurdatum"],
        "totaal_excl": factuur["totaal_excl"],
        "btw_bedrag": factuur["btw"],
        "totaal_incl": factuur["totaal_incl"],
    }

    regels = [{"omschrijving": r["omschrijving"], "aantal_uren": r["aantal_uren"],
               "uurprijs": r["uurprijs"], "totaal": r["totaal"]} for r in regels_db]

    pdf_path = genereer_pdf(factuur=factuur_data, klant=klant, regels=regels, suffix="_regenerated")
    email_data = prepare_email_data(factuurnummer, dict(klant))

    return templates.TemplateResponse("facturen/sendmail.html", {
        "request": request,
        "factuurnummer": factuurnummer,
        "pdf_bestandsnaam": os.path.relpath(pdf_path, "facturen_pdfs"),
        "emails": email_data["emails"],
        "email_body": email_data["email_body"]
    })

# ==========================================
# DELETE FACTUUR + REGELS
# ==========================================
@router.post("/facturen/delete")
def delete_factuur(
    request: Request,
    factuurnummer: str = Form(...),
    return_to: str = Form("/admin?table=facturen")
):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM factuurregels WHERE factuur_id = ?", (factuurnummer,))
        cur.execute("DELETE FROM facturen WHERE factuurnummer = ?", (factuurnummer,))
        conn.commit()

    # Verwijder bijhorende PDFs (origineel en regenerated varianten)
    for path in glob.glob(os.path.join("facturen_pdfs", "**", f"{factuurnummer}_*.pdf"), recursive=True):
        try:
            os.remove(path)
        except OSError:
            pass

    return RedirectResponse(url=return_to, status_code=303)

# ==========================================
# DELETE FACTUURREGEL
# ==========================================
@router.post("/factuurregels/delete")
def delete_factuurregel(
    request: Request,
    regel_id: int = Form(...),
    return_to: str = Form("/admin?table=factuurregels")
):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT factuur_id FROM factuurregels WHERE id = ?", (regel_id,))
        row = cur.fetchone()
        factuur_id = row["factuur_id"] if row else None
        cur.execute("DELETE FROM factuurregels WHERE id = ?", (regel_id,))

        if factuur_id:
            cur.execute("SELECT SUM(totaal) AS totaal_excl FROM factuurregels WHERE factuur_id = ?", (factuur_id,))
            totaal_excl = cur.fetchone()["totaal_excl"] or 0
            cur.execute("""
                SELECT f.klantId, k.btw_verlegd
                FROM facturen f
                JOIN klanten k ON f.klantId = k.klant_id
                WHERE f.factuurnummer = ?
            """, (factuur_id,))
            klant_row = cur.fetchone()
            if klant_row:
                btw_bedrag = 0 if klant_row["btw_verlegd"] else round(totaal_excl * 0.21, 2)
                totaal_incl = totaal_excl + btw_bedrag
                cur.execute("""
                    UPDATE facturen
                    SET totaal_excl = ?, btw = ?, totaal_incl = ?
                    WHERE factuurnummer = ?
                """, (totaal_excl, btw_bedrag, totaal_incl, factuur_id))
        conn.commit()

    return RedirectResponse(url=return_to, status_code=303)

# ==========================================
# INLINE EDITING ENDPOINT
# ==========================================
@router.post("/update_cell")
async def update_cell(data: dict = Body(...)):
    editable_columns = {
        "klanten": {"klantnaam", "adres", "postcode_plaats", "email", "btw_verlegd", "btw_nummer"},
        "facturen": {"factuurdatum", "totaal_excl", "btw_bedrag", "totaal_incl", "isBetaald"},
        "factuurregels": {"omschrijving", "aantal_uren", "uurprijs", "totaal"}
    }

    pk_columns = {
        "klanten": "klant_id",
        "facturen": "factuurnummer",
        "factuurregels": "id"
    }

    table = data.get("table")
    field = data.get("field")
    row_id = data.get("id")
    value = data.get("value")

    if table not in editable_columns or field not in editable_columns[table]:
        return {"success": False, "error": "Invalid table or field"}

    pk = pk_columns[table]

    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(f"UPDATE {table} SET {field} = ? WHERE {pk} = ?", (value, row_id))
            conn.commit()
    except Exception as e:
        return {"success": False, "error": str(e)}

    return {"success": True}

# ==========================================
# QUERY CONSOLE
# ==========================================
@router.get("/query")
def query_console(request: Request, table: str = "", q: str = ""):
    results, columns, error, tables = [], [], "", []

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [r["name"] for r in cur.fetchall()]

        if q.strip():
            try:
                sql = q.strip()
                sql_upper = sql.upper()
                blocked = ["DROP", "ALTER", "ATTACH", "DETACH", "VACUUM", "PRAGMA"]
                for b in blocked:
                    if b in sql_upper:
                        raise Exception(f"Query bevat een verboden statement: {b}")

                if ";" in sql and not sql.strip().endswith(";"):
                    raise Exception("Meerdere SQL statements zijn niet toegestaan.")

                if not any(sql_upper.startswith(a) for a in ["SELECT", "UPDATE", "DELETE"]):
                    raise Exception("Query moet beginnen met SELECT, UPDATE of DELETE.")

                cur.execute(sql)
                if sql_upper.startswith("SELECT"):
                    rows = cur.fetchall()
                    results = [dict(r) for r in rows]
                    columns = list(results[0].keys()) if results else []

                conn.commit()

            except Exception as e:
                error = str(e)

    return templates.TemplateResponse("admin/SQL_console.html", {
        "request": request,
        "tables": tables,
        "selected_table": table,
        "query": q,
        "results": results,
        "columns": columns,
        "error": error,
    })

# Admin - klantenbeheer
@router.get("/klanten/nieuw")
def admin_klanten(request: Request):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM klanten")
        klanten = cur.fetchall()
    return templates.TemplateResponse("admin/nieuwe_klant.html", {
        "request": request,
        "klanten": klanten
    })

@router.post("/klanten/nieuw")
def maak_klant_admin(
    request: Request,
    new_klantnaam: str = Form(...),
    adres: str = Form(...),
    postcode_plaats: str = Form(...),
    btw_verlegd: int = Form(...),
    btw_nummer: str = Form(""),
    email: str = Form(...)
):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO klanten (klantnaam, adres, postcode_plaats, btw_verlegd, btw_nummer, email)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (new_klantnaam, adres, postcode_plaats, bool(btw_verlegd), btw_nummer, email))
        conn.commit()
    return RedirectResponse(url="/admin", status_code=303)


# ==========================================
# BETALINGEN CONTROLEREN
# ==========================================

def _parse_bedrag(value: str) -> float:
    """Convert Dutch-formatted number string to float (e.g. '2.148,96' -> 2148.96)."""
    v = value.strip().replace(".", "").replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return 0.0


def _extract_factuurnummers(omschrijving: str):
    """
    Extract invoice number(s) from an Omschrijving field.
    Returns (nummers, is_range, range_start, range_end).
      - Single/multiple: (['202500004', ...], False, None, None)
      - Range REF.:      ([], True, '202500003', '202500007')
    """
    range_match = re.search(r'REF\.\s*:\s*(\d{9})\s*-\s*(\d{9})', omschrijving)
    if range_match:
        return [], True, range_match.group(1), range_match.group(2)

    found = re.findall(r'\b(\d{9})\b', omschrijving)
    seen = []
    for n in found:
        if n not in seen:
            seen.append(n)
    return seen, False, None, None


# Generic business words that appear in multiple customer names and should not be used for matching
_NAME_STOPWORDS = {"plants", "plant", "group", "young", "holding", "services", "company"}

def _names_match(db_name: str, csv_name: str) -> bool:
    """Fuzzy match between DB klantnaam and CSV Naam tegenpartij.
    Uses distinctive words only (excludes generic business words like 'plants', 'group')
    so e.g. 'DEROOSE PLANTS NV' won't falsely match 'Van der Voort Young Plants'.
    """
    db_lower = db_name.lower()
    csv_lower = csv_name.lower()
    words = [w for w in re.split(r'\W+', csv_lower) if len(w) > 3 and w not in _NAME_STOPWORDS]
    return bool(words) and any(w in db_lower for w in words)


@router.get("/betalingen")
def betalingen(
    request: Request,
    search: str = "",
    jaar: list[str] = Query(default=[]),
    klant: str = "",
):
    # --- Find latest CSV in transacties/ ---
    csv_dir = "transacties"
    csv_files = sorted(glob.glob(os.path.join(csv_dir, "*.csv")))
    if not csv_files:
        return templates.TemplateResponse("admin/betalingen.html", {
            "request": request,
            "error": "Geen CSV-bestanden gevonden in de map 'transacties'.",
        })
    csv_path = csv_files[-1]
    csv_name = os.path.basename(csv_path)

    # --- Parse CSV ---
    transacties_met_factuur = []
    with open(csv_path, encoding="latin-1", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            bedrag_raw = row.get("Bedrag", "0").strip()
            bedrag = _parse_bedrag(bedrag_raw)
            if bedrag <= 0:
                continue  # only incoming payments

            omschrijving = row.get("Omschrijving-1", "").strip()
            nummers, is_range, range_start, range_end = _extract_factuurnummers(omschrijving)
            if not nummers and not is_range:
                continue  # skip non-invoice transactions

            transacties_met_factuur.append({
                "datum": row.get("Datum", "").strip(),
                "naam": row.get("Naam tegenpartij", "").strip(),
                "bedrag": bedrag,
                "factuurnummers": nummers,
                "is_range": is_range,
                "range_start": range_start,
                "range_end": range_end,
                "range_label": "",
                "omschrijving": omschrijving,
            })

    # --- Look up invoices in DB and build results ---
    resultaten = []
    betaald_factuurnummers = []

    with get_db() as conn:
        cur = conn.cursor()

        for trx in transacties_met_factuur:
            gevonden = []
            niet_in_db = []

            if trx["is_range"]:
                # Range: find all facturen in the number range that belong to this customer
                cur.execute(
                    """SELECT factuurnummer, klantnaam, totaal_incl, comment
                       FROM facturen
                       WHERE factuurnummer >= ? AND factuurnummer <= ?""",
                    (trx["range_start"], trx["range_end"])
                )
                all_in_range = [dict(r) for r in cur.fetchall()]
                gevonden = [f for f in all_in_range if _names_match(f["klantnaam"], trx["naam"])]
                # Surface the matched numbers for display
                trx["factuurnummers"] = [f["factuurnummer"] for f in gevonden]
                trx["range_label"] = f"{trx['range_start']} t/m {trx['range_end']}"
            else:
                for fnr in trx["factuurnummers"]:
                    # Direct lookup by factuurnummer
                    cur.execute(
                        "SELECT factuurnummer, klantnaam, totaal_incl, comment FROM facturen WHERE factuurnummer = ?",
                        (fnr,)
                    )
                    row = cur.fetchone()
                    if not row:
                        # Fallback: old number may have been remapped — check comment
                        cur.execute(
                            "SELECT factuurnummer, klantnaam, totaal_incl, comment FROM facturen WHERE comment LIKE ?",
                            (f"%{fnr}%",)
                        )
                        row = cur.fetchone()
                    if row:
                        gevonden.append(dict(row))
                    else:
                        niet_in_db.append(fnr)

            som_db = round(sum(f["totaal_incl"] for f in gevonden), 2)
            afwijking = round(trx["bedrag"] - som_db, 2)

            if gevonden and abs(afwijking) < 0.02:
                status = "match"
                for f in gevonden:
                    betaald_factuurnummers.append(f["factuurnummer"])
            elif gevonden:
                status = "afwijking"
            else:
                status = "niet_in_db"

            resultaten.append({
                **trx,
                "gevonden": gevonden,
                "niet_in_db": niet_in_db,
                "som_db": som_db,
                "afwijking": afwijking,
                "status": status,
            })

        # --- Auto-update isBetaald for matched invoices (only if not already paid) ---
        for fnr in betaald_factuurnummers:
            cur.execute("UPDATE facturen SET isBetaald = 1 WHERE factuurnummer = ? AND isBetaald = 0", (fnr,))
        conn.commit()

        # --- Unpaid DB invoices (sorted by factuurnummer) ---
        cur.execute("""
            SELECT f.factuurnummer, k.klantnaam, f.factuurdatum, f.totaal_incl, f.comment
            FROM facturen f
            JOIN klanten k ON f.klantId = k.klant_id
            WHERE f.isBetaald = 0
            ORDER BY f.factuurnummer
        """)
        onbetaald = [dict(r) for r in cur.fetchall()]

    # --- Collect available years + klanten for filters (before filtering) ---
    alle_jaren = set()
    for r in resultaten:
        for fnr in r["factuurnummers"]:
            if len(fnr) >= 4 and fnr[:4].isdigit():
                alle_jaren.add(fnr[:4])
    for r in onbetaald:
        fnr = r["factuurnummer"]
        if len(fnr) >= 4 and fnr[:4].isdigit():
            alle_jaren.add(fnr[:4])
    available_years = sorted(alle_jaren)
    available_klanten = sorted({r["klantnaam"] for r in onbetaald})

    # --- Apply year filter ---
    if jaar:
        resultaten = [
            r for r in resultaten
            if any(fnr[:4] in jaar for fnr in r["factuurnummers"] if len(fnr) >= 4)
        ]
        onbetaald = [
            r for r in onbetaald
            if r["factuurnummer"][:4] in jaar
        ]

    # --- Apply klant filter (onbetaald only) ---
    klant = klant.strip()
    if klant:
        onbetaald = [r for r in onbetaald if r["klantnaam"] == klant]

    # --- Apply factuurnummer search filter ---
    search = search.strip()
    if search:
        resultaten = [
            r for r in resultaten
            if search in " ".join(r["factuurnummers"])
        ]
        onbetaald = [
            r for r in onbetaald
            if search in r["factuurnummer"]
        ]

    # --- Totaal onbetaald (after all filters) ---
    totaal_onbetaald = round(sum(r["totaal_incl"] for r in onbetaald), 2)

    # --- Summary counts ---
    n_match = sum(1 for r in resultaten if r["status"] == "match")
    n_afwijking = sum(1 for r in resultaten if r["status"] == "afwijking")
    n_niet_in_db = sum(1 for r in resultaten if r["status"] == "niet_in_db")

    return templates.TemplateResponse("admin/betalingen.html", {
        "request": request,
        "csv_name": csv_name,
        "resultaten": resultaten,
        "onbetaald": onbetaald,
        "totaal_onbetaald": totaal_onbetaald,
        "n_match": n_match,
        "n_afwijking": n_afwijking,
        "n_niet_in_db": n_niet_in_db,
        "n_onbetaald": len(onbetaald),
        "n_nieuw_betaald": len(betaald_factuurnummers),
        "search": search,
        "available_years": available_years,
        "selected_years": jaar,
        "available_klanten": available_klanten,
        "selected_klant": klant,
    })
