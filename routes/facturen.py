import os
import datetime
from fastapi import APIRouter, Request, Form
from fastapi.templating import Jinja2Templates
from database import get_db
from services.pdf_generator_service import genereer_pdf
from services.mail_service import prepare_email_data, send_email

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# PDF directory
pdf_dir = "facturen_pdfs"
os.makedirs(pdf_dir, exist_ok=True)

# Default uurprijs
uurprijs_default = 50

# ==========================================
# NIEUWE FACTUUR - FORMULIER
# ==========================================
@router.get("/nieuw")
def nieuw_factuur_form(request: Request):
    # database connectie
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT klantnaam FROM klanten ORDER BY klantnaam ASC")
        klanten = [row["klantnaam"] for row in cur.fetchall()]

    return templates.TemplateResponse("facturen/facturen.html", {
        "request": request,
        "klanten": klanten
    })


# ==========================================
# NIEUWE FACTUUR - VERWERKING
# ==========================================
@router.post("/nieuw")
def maak_factuur(
    request: Request,
    klantnaam: str = Form(...),
    omschrijving: str = Form(...),
    uren: float = Form(...)
):
    with get_db() as conn:
        cur = conn.cursor()

        # Controleer of klant bestaat
        cur.execute("SELECT * FROM klanten WHERE klantnaam = ?", (klantnaam,))
        row = cur.fetchone()

        if row:
            klant = row
            klant_id = klant["klant_id"]
        else:
            # Nieuwe klant aanmaken
            klant_id = int(datetime.datetime.now().timestamp())
            cur.execute("""
                INSERT INTO klanten (klant_id, klantnaam, adres, postcode_plaats, btw_verlegd, btw_nummer, email)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (klant_id, klantnaam, "", "", False, "", ""))
            conn.commit()
            cur.execute("SELECT * FROM klanten WHERE klant_id = ?", (klant_id,))
            klant = cur.fetchone()

        # Factuurnummer bepalen
        cur.execute("SELECT factuurnummer FROM facturen ORDER BY factuurnummer DESC LIMIT 1")
        row = cur.fetchone()
        factuurnummer = str(int(row["factuurnummer"]) + 1) if row else "202500042"
        factuurdatum = datetime.datetime.now()

        totaal = uren * uurprijs_default
        regels = [(factuurnummer, omschrijving, uren, uurprijs_default, totaal, "")]

        # Voeg factuurregels toe
        for r in regels:
            cur.execute("""
                INSERT INTO factuurregels (factuurnummer, omschrijving, aantal_uren, uurprijs, totaal, weeknummers)
                VALUES (?, ?, ?, ?, ?, ?)
            """, r)
        conn.commit()

        # Factuurberekening
        totaal_excl = sum(r[4] for r in regels)
        btw_bedrag = 0 if klant["btw_verlegd"] else round(totaal_excl * 0.21, 2)
        totaal_incl = totaal_excl + btw_bedrag
        maand = factuurdatum.month
        kwartaal = f"Q{((maand-1)//3)+1}"

        # Voeg factuur toe
        cur.execute("""
            INSERT INTO facturen (factuurnummer, klant_id, factuurdatum, totaal_excl, btw_bedrag, totaal_incl, isBetaald, kwartaal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (factuurnummer, klant_id, factuurdatum.isoformat(), totaal_excl, btw_bedrag, totaal_incl, False, kwartaal))
        conn.commit()

    # Genereer PDF
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

    return templates.TemplateResponse("facturen/sendmail.html", {
        "request": request,
        "factuurnummer": factuurnummer,
        "pdf_bestandsnaam": os.path.basename(pdf_path),
        "emails": email_data["emails"],
        "email_body": email_data["email_body"]
    })


# ==========================================
# MAIL VERZENDEN
# ==========================================
@router.post("/sendMail")
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

    return templates.TemplateResponse("facturen/sendmail.html", {
        "request": request,
        "factuurnummer": factuurnummer,
        "pdf_bestandsnaam": os.path.basename(pdf_path),
        "emails": ontvangers_lijst,
        "email_body": email_body,
        "status": result["status"],
        "error_message": result.get("message", "")
    })
