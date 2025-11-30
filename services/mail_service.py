# mailing.py
import os
import smtplib
from email.message import EmailMessage

bedrijf_naam = "Piet Damen Teeltadvies en -verkoop"
banktekst = (
    "Graag binnen 14 dagen de betaling voldoen op rekening NL49RABO0156625946 "
    "t.n.v. P.J.M. Damen onder vermelding van het factuurnummer."
)

def prepare_email_data(factuurnummer: str, klant: dict) -> dict:
    """
    Bereidt de e-mailinformatie voor een factuur.
    Return: dict met 'emails' en 'email_body'
    """
    emails_raw = klant.get("email", "")
    email_lijst = [e.strip() for e in emails_raw.split(";") if "@" in e] if emails_raw else []
    email_body = f"""Beste {klant['klantnaam']},

In de bijlage vindt u de factuur {factuurnummer}.

{banktekst}

Met vriendelijke groet,
{bedrijf_naam}
"""
    return {"emails": email_lijst, "email_body": email_body}


def send_email(factuurnummer: str, pdf_path: str, ontvangers: list, email_body: str) -> dict:
    """
    Verstuur een PDF factuur via e-mail.
    Return: dict met status en eventueel foutmelding
    """
    if not ontvangers:
        return {"status": "error", "message": "Geen geldig e-mailadres gevonden."}

    gmail_user = os.environ.get("GMAIL_USER")
    gmail_pass = os.environ.get("GMAIL_APP_PASS")
    if not gmail_user or not gmail_pass:
        return {"status": "error", "message": "Gmail credentials niet ingesteld."}

    subject = f"Factuur {factuurnummer} - {bedrijf_naam}"
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(gmail_user, gmail_pass)
            msg = EmailMessage()
            msg['Subject'] = subject
            msg['From'] = gmail_user
            msg['To'] = ", ".join(ontvangers)
            msg.set_content(email_body)
            with open(pdf_path, 'rb') as f:
                file_data = f.read()
                file_name = os.path.basename(pdf_path)
            msg.add_attachment(file_data, maintype='application', subtype='pdf', filename=file_name)
            smtp.send_message(msg)
    except Exception as e:
        return {"status": "error", "message": str(e)}

    return {"status": "success"}
