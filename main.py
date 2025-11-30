import sqlite3
import datetime
import os
from fastapi import HTTPException
from fastapi import FastAPI, Request, Form
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pdf_generator import genereer_pdf 
from mailing import prepare_email_data, send_email
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Body


# ==========================================
# VARIABELEN
# ==========================================
uurprijs_default = 50
pdf_dir = "facturen_pdfs"
os.makedirs(pdf_dir, exist_ok=True)

# ==========================================
# FASTAPI INIT
# ==========================================
app = FastAPI()
app.mount("/facturen_pdfs", StaticFiles(directory=pdf_dir), name="facturen_pdfs")
templates = Jinja2Templates(directory="templates")


# ==========================================
# DATABASE HELPER
# ==========================================
def get_db():
    conn = sqlite3.connect("facturen.db")
    conn.row_factory = sqlite3.Row
    return conn


# ==========================================
# ROUTE: INDEX
# ==========================================
@app.get("/")
def index(request: Request):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT klantnaam FROM klanten ORDER BY klantnaam")
    klanten = [r["klantnaam"] for r in cur.fetchall()]
    conn.close()
    return templates.TemplateResponse("index.html", {"request": request, "klanten": klanten})


# ==========================================
# NIEUWE KLANT
# ==========================================
@app.post("/maak_klant")
def maak_klant(
    request: Request,
    new_klantnaam: str = Form(...),
    adres: str = Form(...),
    postcode_plaats: str = Form(...),
    btw_verlegd: int = Form(...),
    btw_nummer: str = Form(""),
    email: str = Form(...)
):
    conn = get_db()
    cur = conn.cursor()

    klant_id = int(datetime.datetime.now().timestamp())
    cur.execute("""
        INSERT INTO klanten (klant_id, klantnaam, adres, postcode_plaats, btw_verlegd, btw_nummer, email)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (klant_id, new_klantnaam, adres, postcode_plaats, bool(btw_verlegd), btw_nummer, email))

    conn.commit()
    conn.close()

    return {"status": "success", "message": f"Klant {new_klantnaam} toegevoegd."}


# ==========================================
# MAAK FACTUUR
# ==========================================
@app.post("/maak_factuur")
def maak_factuur(
    request: Request,
    klantnaam: str = Form(...),
    omschrijving: str = Form(...),
    uren: float = Form(...)
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM klanten WHERE klantnaam = ?", (klantnaam,))
    row = cur.fetchone()

    if row:
        klant = row
        klant_id = klant["klant_id"]
    else:
        klant_id = int(datetime.datetime.now().timestamp())
        cur.execute("""
            INSERT INTO klanten (klant_id, klantnaam, adres, postcode_plaats, btw_verlegd, btw_nummer, email)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (klant_id, klantnaam, "", "", False, "", ""))
        conn.commit()
        cur.execute("SELECT * FROM klanten WHERE klant_id = ?", (klant_id,))
        klant = cur.fetchone()

    # Factuurnummer
    cur.execute("SELECT factuurnummer FROM facturen ORDER BY factuurnummer DESC LIMIT 1")
    row = cur.fetchone()
    factuurnummer = str(int(row["factuurnummer"]) + 1) if row else "202500042"
    factuurdatum = datetime.datetime.now()

    totaal = uren * uurprijs_default
    regels = [(factuurnummer, omschrijving, uren, uurprijs_default, totaal, "")]

    for r in regels:
        cur.execute("""
            INSERT INTO factuurregels (factuurnummer, omschrijving, aantal_uren, uurprijs, totaal, weeknummers)
            VALUES (?, ?, ?, ?, ?, ?)
        """, r)
    conn.commit()

    totaal_excl = sum(r[4] for r in regels)
    btw_bedrag = 0 if klant["btw_verlegd"] else round(totaal_excl * 0.21, 2)
    totaal_incl = totaal_excl + btw_bedrag
    maand = factuurdatum.month
    kwartaal = f"Q{((maand-1)//3)+1}"

    cur.execute("""
        INSERT INTO facturen (factuurnummer, klant_id, factuurdatum, totaal_excl, btw_bedrag, totaal_incl, isBetaald, kwartaal)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (factuurnummer, klant_id, factuurdatum.isoformat(), totaal_excl, btw_bedrag, totaal_incl, False, kwartaal))
    conn.commit()

    pdf_path = genereer_pdf(
        factuur={
            "factuurnummer": factuurnummer,
            "factuurdatum": factuurdatum.isoformat(),
            "totaal_excl": totaal_excl,
            "btw_bedrag": btw_bedrag,
            "totaal_incl": totaal_incl
        },
        klant=klant,
        regels=[{
            "omschrijving": r[1],
            "aantal_uren": r[2],
            "uurprijs": r[3],
            "totaal": r[4]
        } for r in regels]
)


    klant_dict = dict(klant)
    email_data = prepare_email_data(factuurnummer, klant_dict)

    return templates.TemplateResponse("result.html", {
        "request": request,
        "factuurnummer": factuurnummer,
        "pdf_bestandsnaam": os.path.basename(pdf_path),
        "emails": email_data["emails"],
        "email_body": email_data["email_body"]
    })


# ==========================================
# MAIL
# ==========================================
@app.post("/verzend_mail")
def verzend_mail(
    request: Request,
    factuurnummer: str = Form(...),
    ontvangers: str = Form(...),
    email_body: str = Form(...),
    pdf_bestandsnaam: str = Form(...)
):
    pdf_path = os.path.join(pdf_dir, pdf_bestandsnaam)
    ontvangers_lijst = [e.strip() for e in ontvangers.split(",") if "@" in e]

    result = send_email(factuurnummer, pdf_path, ontvangers_lijst, email_body)
    print("STATUS:", result["status"], "ERROR:", result.get("message", ""))

    return templates.TemplateResponse("result.html", {
        "request": request,
        "factuurnummer": factuurnummer,
        "pdf_bestandsnaam": os.path.basename(pdf_path),
        "emails": ontvangers_lijst,
        "email_body": email_body,
        "status": result["status"],
        "error_message": result.get("message", "")
    })


# ==========================================
# INLINE EDITING ENDPOINT (NOTION STYLE)
# ==========================================
@app.post("/admin/update_cell")
async def update_cell(data: dict = Body(...)):
    """
    Verwacht JSON:
    {
        "table": "klanten",
        "pk": "klant_id",
        "id": "1234567890",
        "field": "klantnaam",
        "value": "Nieuwe naam"
    }
    """

    # Whitelists
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

    if table not in editable_columns:
        return {"success": False, "error": "Invalid table"}

    if field not in editable_columns[table]:
        return {"success": False, "error": "Field not editable"}

    pk = pk_columns[table]

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            f"UPDATE {table} SET {field} = ? WHERE {pk} = ?",
            (value, row_id)
        )
        conn.commit()

    except Exception as e:
        return {"success": False, "error": str(e)}

    finally:
        conn.close()

    return {"success": True}


# ==========================================
# ADMIN MODULE
# ==========================================
@app.get("/admin")
def admin(
    request: Request,
    table: str = "klanten",
    search: str = "",
    jaar: str = "",
    kwartaal: str = ""
):
    conn = get_db()
    cur = conn.cursor()

    selected_table = table
    search_query = search.strip()

    cur.execute("SELECT DISTINCT strftime('%Y', factuurdatum) AS jaar FROM facturen ORDER BY jaar")
    jaren_rows = cur.fetchall()
    jaren = [r["jaar"] for r in jaren_rows]

    # ------------------------------------------------------
    # Bouw lijst met factuurnummers op basis van JAAR filter
    # ------------------------------------------------------
    factuurnummers_jaar = None
    if jaar:
        cur.execute("""
            SELECT factuurnummer
            FROM facturen
            WHERE strftime('%Y', factuurdatum) = ?
        """, (jaar,))
        factuurnummers_jaar = [row["factuurnummer"] for row in cur.fetchall()]

    # ======================================================
    # KLANTEN
    # ======================================================
    query_klanten = "SELECT * FROM klanten"
    conditions_klanten = []
    params_klanten = []

    if selected_table == "klanten":

        if search_query:
            like = f"%{search_query}%"
            conditions_klanten.append(
                "(klantnaam LIKE ? OR adres LIKE ? OR email LIKE ?)"
            )
            params_klanten.extend([like, like, like])

        if jaar:
            conditions_klanten.append("""
                klant_id IN (
                    SELECT klant_id 
                    FROM facturen
                    WHERE strftime('%Y', factuurdatum) = ?
                )
            """)
            params_klanten.append(jaar)

    if conditions_klanten:
        query_klanten += " WHERE " + " AND ".join(conditions_klanten)

    cur.execute(query_klanten, params_klanten)
    klanten = cur.fetchall()

    # ======================================================
    # FACTUREN
    # ======================================================
    query_facturen = """
        SELECT f.*, k.klantnaam, k.btw_verlegd
        FROM facturen f
        JOIN klanten k ON f.klant_id = k.klant_id
        WHERE 1=1
    """
    conditions_facturen = []
    params_facturen = []

    if jaar:
        conditions_facturen.append("strftime('%Y', f.factuurdatum) = ?")
        params_facturen.append(jaar)

    if search_query:
        like = f"%{search_query}%"
        conditions_facturen.append(
            "(f.factuurnummer LIKE ? OR k.klantnaam LIKE ? OR f.factuurdatum LIKE ?)"
        )
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
            JOIN klanten k ON f.klant_id = k.klant_id
            ORDER BY f.factuurdatum DESC
        """)
        facturen = cur.fetchall()

    # ======================================================
    # FACTUURREGELS
    # ======================================================
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

    # -----------------------
    # TOTALEN PER KWARTAAL 
    # -----------------------
    totalen_query = """
        SELECT f.kwartaal, 
               SUM(CASE WHEN k.btw_verlegd=0 THEN f.totaal_excl ELSE 0 END) AS binnenland,
               SUM(CASE WHEN k.btw_verlegd=0 THEN f.btw_bedrag ELSE 0 END) AS btw,
               SUM(CASE WHEN k.btw_verlegd=1 THEN f.totaal_excl ELSE 0 END) AS buitenland
        FROM facturen f
        JOIN klanten k ON f.klant_id = k.klant_id
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
        }
        for r in rows
    }

    conn.close()

    return templates.TemplateResponse("admin.html", {
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
@app.get("/regen_pdf/{factuurnummer}")
def regen_pdf(factuurnummer: str, request: Request):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM facturen WHERE factuurnummer = ?", (factuurnummer,))
    factuur = cur.fetchone()
    if not factuur:
        return {"error": "Factuur niet gevonden"}

    cur.execute("SELECT * FROM klanten WHERE klant_id = ?", (factuur["klant_id"],))
    klant = cur.fetchone()

    cur.execute("SELECT * FROM factuurregels WHERE factuurnummer = ?", (factuurnummer,))
    regels_db = cur.fetchall()

    regels = [{
        "omschrijving": r["omschrijving"],
        "aantal_uren": r["aantal_uren"],
        "uurprijs": r["uurprijs"],
        "totaal": r["totaal"]
    } for r in regels_db]

    pdf_path = genereer_pdf(
        factuur=factuur,
        klant=klant,
        regels=regels,
        suffix="_regenerated"
    )

    klant_dict = dict(klant)
    email_data = prepare_email_data(factuurnummer, klant_dict)

    return templates.TemplateResponse("result.html", {
        "request": request,
        "factuurnummer": factuurnummer,
        "pdf_bestandsnaam": os.path.basename(pdf_path),
        "emails": email_data["emails"],
        "email_body": email_data["email_body"]
    })



# ==========================================
# Admin console - Query Editor
# ==========================================

@app.get("/admin/query")
def query_console(request: Request, table: str = "", q: str = ""):
    """
    Eigen SQL-console. Toelaatbaar: SELECT, UPDATE, DELETE.
    Niet-toegestaan: DROP, ALTER, PRAGMA, ATTACH, meerdere statements.
    """
    conn = get_db()
    cur = conn.cursor()

    # Alle tabellen tonen
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
    """)
    tables = [r["name"] for r in cur.fetchall()]

    results = []
    columns = []
    error = ""

    if q.strip():
        try:
            sql = q.strip()
            sql_upper = sql.upper()

            # 1) Forbidden keywords (veiligheidsfilter)
            blocked = ["DROP", "ALTER", "ATTACH", "DETACH", "VACUUM", "PRAGMA"]
            if any(b in sql_upper for b in blocked):
                raise Exception(f"Query bevat een verboden statement: {b}")

            # 2) Geen meerdere statements zoals "UPDATE ...; DELETE ..."
            if ";" in sql and not sql.strip().endswith(";"):
                raise Exception("Meerdere SQL statements zijn niet toegestaan.")

            # 3) Query moet beginnen met SELECT, UPDATE, DELETE
            allowed = ["SELECT", "UPDATE", "DELETE"]
            if not any(sql_upper.startswith(a) for a in allowed):
                raise Exception("Query moet beginnen met SELECT, UPDATE of DELETE.")

            # Uitvoeren
            cur.execute(sql)

            # Resultaat ophalen (alleen bij SELECT)
            if sql_upper.startswith("SELECT"):
                rows = cur.fetchall()
                results = [dict(r) for r in rows]
                columns = list(results[0].keys()) if results else []

            conn.commit()

        except Exception as e:
            error = str(e)

    conn.close()

    return templates.TemplateResponse("query.html", {
        "request": request,
        "tables": tables,
        "selected_table": table,
        "query": q,
        "results": results,
        "columns": columns,
        "error": error,
    })