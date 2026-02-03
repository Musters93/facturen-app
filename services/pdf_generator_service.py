# pdf_generator.py

import os
import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageTemplate, Frame
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# PDF directory
pdf_dir = "facturen_pdfs"
os.makedirs(pdf_dir, exist_ok=True)

# Constantes
bedrijf_naam = "Piet Damen Teeltadvies en -verkoop"
banktekst = (
    "Graag binnen 14 dagen de betaling voldoen op rekening NL49RABO0156625946 "
    "t.n.v. P.J.M. Damen onder vermelding van het factuurnummer."
)

footer = {
    "naam": "Piet Damen",
    "adres": "Oostheullaan 1",
    "postcode_plaats": "2675 KR Honselersdijk",
    "telefoon": "0651332914",
    "email": "info.pietdamen@gmail.com",
    "kvk": "84008407",
    "btw_id": "NL003911777B36",
    "iban": "NL49RABO0156625946"
}

def genereer_pdf(factuur: dict, klant: dict, regels: list,  suffix: str = "") -> str:
    """
    Genereert PDF van een factuur
    factuur: dict met factuurgegevens
    klant: dict met klantgegevens
    regels: lijst van factuurregels
    return: path naar de PDF
    """
    from reportlab.lib.units import mm  # lokaal importeren

    factuurnummer = factuur["factuurnummer"]
    safe_klantnaam = klant['klantnaam'].replace(" ", "")
    factuurdatum = datetime.datetime.fromisoformat(factuur["factuurdatum"])
    jaar_dir = str(factuurdatum.year)
    kwartaal_dir = f"Q{((factuurdatum.month - 1) // 3) + 1}"
    target_dir = os.path.join(pdf_dir, jaar_dir, kwartaal_dir)
    os.makedirs(target_dir, exist_ok=True)
    pdf_path = os.path.join(target_dir, f"{factuurnummer}_PietDamen_{safe_klantnaam}{suffix}.pdf")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="BedrijfGroen", fontName="Helvetica-Bold", fontSize=16, textColor=colors.green))
    styles.add(ParagraphStyle(name="CenterBold", fontName="Helvetica-Bold", fontSize=10, alignment=1))

    story = []

    # Header
    story.append(Paragraph(bedrijf_naam, styles["BedrijfGroen"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"{klant['klantnaam']}<br/>{klant['adres']}<br/>{klant['postcode_plaats']}", styles["Normal"]))
    story.append(Spacer(1, 12))
    if klant["btw_verlegd"]:
        story.append(Paragraph(f"<b>BTW verlegd</b><br/>BTW-nummer: {klant['btw_nummer']}", styles["Normal"]))
        story.append(Spacer(1, 12))
    story.append(Paragraph("<b>Factuur</b>", styles["Heading2"]))
    story.append(Paragraph(f"Factuurnummer: {factuurnummer}<br/>Datum: {factuurdatum.strftime('%d-%m-%Y')}", styles["Normal"]))
    story.append(Spacer(1, 12))

    # Tabel
    table_data = [["Omschrijving", "Aantal uur", "Uurtarief (€)", "Totaal (€)"]]
    for r in regels:
        table_data.append([r["omschrijving"], f"{r['aantal_uren']:.2f}", f"€ {r['uurprijs']:.2f}", f"€ {r['totaal']:.2f}"])

    row_idx = len(table_data)
    totaal_excl = factuur["totaal_excl"]
    btw_bedrag = factuur["btw_bedrag"]
    totaal_incl = factuur["totaal_incl"]

    if klant["btw_verlegd"]:
        table_data.append(["Totaal", "", "", Paragraph(f"<b>€ {totaal_incl:.2f}</b>", styles["CenterBold"])])
        table_style = TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('SPAN', (0,row_idx), (2,row_idx)),
            ('LINEBELOW', (0,row_idx), (-1,row_idx), 2, colors.black),
            ('ALIGN', (1,1), (2,-2), 'CENTER'),
            ('ALIGN', (0,1), (0,-1), 'LEFT'),
            ('ALIGN', (3,1), (3,-1), 'CENTER')
        ])
    else:
        table_data += [
            ["Totaalbedrag exclusief btw", "", "", f"€ {totaal_excl:.2f}"],
            ["21% btw", "", "", f"€ {btw_bedrag:.2f}"],
            ["Totaal inclusief btw", "", "", Paragraph(f"<b>€ {totaal_incl:.2f}</b>", styles["CenterBold"])]
        ]
        table_style = TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('SPAN', (0,row_idx), (2,row_idx)),
            ('LINEBELOW', (0,row_idx), (-1,row_idx), 1.5, colors.black),
            ('SPAN', (0,row_idx+1), (2,row_idx+1)),
            ('LINEBELOW', (0,row_idx+1), (-1,row_idx+1), 1.5, colors.black),
            ('SPAN', (0,row_idx+2), (2,row_idx+2)),
            ('LINEBELOW', (0,row_idx+2), (-1,row_idx+2), 2, colors.black),
            ('ALIGN', (1,1), (2,-4), 'CENTER'),
            ('ALIGN', (0,1), (0,-1), 'LEFT'),
            ('ALIGN', (3,1), (3,-1), 'CENTER')
        ])

    table = Table(table_data, colWidths=[80*mm, 30*mm, 30*mm, 30*mm], hAlign='LEFT')
    table.setStyle(table_style)
    story.append(table)
    story.append(Spacer(1, 24))
    story.append(Paragraph(banktekst, styles["Normal"]))

    # Footer
    def draw_footer(canvas, doc):
        footer_data = [
            [footer['naam'], f"Telefoon: {footer['telefoon']}", f"KvK: {footer['kvk']}"],
            [footer['adres'], f"E-mail: {footer['email']}", f"BTW Id: {footer['btw_id']}"],
            [footer['postcode_plaats'], "", f"IBAN: {footer['iban']}"]
        ]
        footer_table = Table(footer_data, colWidths=[60*mm, 60*mm, 60*mm])
        footer_table.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('TOPPADDING', (0,0), (-1,-1), 2),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2)
        ]))
        w, h = footer_table.wrap(doc.width, doc.bottomMargin)
        footer_table.drawOn(canvas, doc.leftMargin, 12)

    frame = Frame(20*mm, 35*mm, A4[0]-40*mm, A4[1]-80*mm, id='normal')
    doc = SimpleDocTemplate(pdf_path, pagesize=A4)
    doc.addPageTemplates([PageTemplate(id='footer', frames=[frame], onPage=draw_footer)])
    doc.build(story)

    return pdf_path
