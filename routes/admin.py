from fastapi import APIRouter, Request, Body, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from database import get_db
from services.pdf_generator_service import genereer_pdf
from services.mail_service import prepare_email_data
import os

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
                    klantId IN (
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
                conditions_regels.append("(omschrijving LIKE ? OR factuurnummer LIKE ?)")
                params_regels.extend([like, like])

            if jaar and factuurnummers_jaar:
                placeholders = ",".join("?" * len(factuurnummers_jaar))
                conditions_regels.append(f"factuurnummer IN ({placeholders})")
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

        cur.execute("SELECT * FROM klanten WHERE klant_id = ?", (factuur["klant_id"],))
        klant = cur.fetchone()

        cur.execute("SELECT * FROM factuurregels WHERE factuurnummer = ?", (factuurnummer,))
        regels_db = cur.fetchall()

    regels = [{"omschrijving": r["omschrijving"], "aantal_uren": r["aantal_uren"],
               "uurprijs": r["uurprijs"], "totaal": r["totaal"]} for r in regels_db]

    pdf_path = genereer_pdf(factuur=factuur, klant=klant, regels=regels, suffix="_regenerated")
    email_data = prepare_email_data(factuurnummer, dict(klant))

    return templates.TemplateResponse("facturen/sendmail.html", {
        "request": request,
        "factuurnummer": factuurnummer,
        "pdf_bestandsnaam": os.path.basename(pdf_path),
        "emails": email_data["emails"],
        "email_body": email_data["email_body"]
    })

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