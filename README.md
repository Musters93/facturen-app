# Facturen Project
V1.1

## App lokaal draaien

### Vereisten
- Python 3.9 of hoger
- Poetry

### Installatie
```bash
poetry install
```

### Database (eenmalig, alleen als je een lege database wil)
Als `facturen.db` nog niet bestaat of je wilt een schone start:
```bash
sqlite3 facturen.db < initialSetUp.sql
```

### Starten
```bash
poetry run uvicorn main:app --reload
```

Open daarna de app in je browser op:
```
http://127.0.0.1:8000
```

---

## Betalingen controleren

Via `/admin/betalingen` kun je aan het einde van elk kwartaal (of wanneer je wil) controleren welke facturen betaald zijn.

### Stappenplan nieuw kwartaal

**Stap 1 — CSV downloaden bij Rabobank**
- Log in op Rabo Bankieren Online
- Ga naar je zakelijke rekening → Downloaden/Exporteren
- Kies periode: begin tot einde van het kwartaal (of langer als je meerdere kwartalen wil checken)
- Exportformaat: **CSV** (kommagescheiden / puntkommagescheiden)
- Sla het bestand op in de map `transacties/` in dit project
- De bestandsnaam blijft zoals Rabobank hem geeft (bijv. `CSV_A_NL49RABO...EUR_20260101_20260331.csv`)

> De app pakt altijd het **alfabetisch laatste** bestand in `transacties/`. Oudere bestanden kun je laten staan of archiveren — ze worden niet meer gebruikt zolang er een nieuwer bestand aanwezig is.

**Stap 2 — Betalingen verwerken**
1. Start de app: `poetry run uvicorn main:app --reload`
2. Ga naar **Admin → Betalingen Controleren**
3. Gebruik het **jaarfilter** om alleen het relevante jaar te tonen (bijv. 2026)
4. De app matcht automatisch transacties aan facturen en zet `isBetaald = 1` voor elke match

**Stap 3 — Controleer de resultaten**

De pagina toont drie situaties:

| Status | Betekenis |
|--------|-----------|
| ✓ Match | Bedrag klopt exact — factuur automatisch als betaald gemarkeerd |
| ~ Afwijking | Factuur(en) gevonden maar bedrag wijkt af — handmatig controleren |
| ? Pre-app | Factuurnummer niet in DB (bijv. oudere factuur of fout referentienummer) |

**Stap 4 — Handmatig corrigeren**
- Facturen die als **afwijking** of **? pre-app** staan maar wél betaald zijn: markeer ze handmatig via **Admin → Admin Overzicht → Facturen** (klik op de cel `isBetaald` om te bewerken), of voeg een comment toe via de SQL Console.
- Deroose Plants betaalt soms meerdere facturen in één batchtransactie met een reeks-referentie (bijv. `REF.: 202500003 - 202500007`). De app filtert automatisch op klantnaam zodat alleen Deroose-facturen in die reeks worden meegeteld.

**Stap 5 — Openstaande facturen**
- Onderaan de pagina staat de tabel **DB-facturen nog niet betaald**
- Filter op klant (bijv. Deroose Plants N.V.) om per klant het openstaande bedrag te zien
- Het totaal onderaan de tabel past zich aan op de actieve filters

### Hoe de matching werkt
- **Enkel nummer** in omschrijving: `202500004` → directe opzoeking
- **Reeks**: `REF.: 202500003 - 202500007` → alle facturen van díe klant binnen het nummerbereik worden opgeteld
- **Vrije tekst**: `15073/  15374  202400033` → alle 9-cijferige nummers worden eruit gepikt
- **Hernummerde facturen** (bijv. fout factuurnummer in PDF): de app vindt ze terug via de `comment`-kolom

---

## Oude facturen importeren (eenmalig)

Facturen die vóór de app zijn aangemaakt (als PDF in de `2025/`-map op iCloud) kunnen worden geïmporteerd via het script `scripts/import_old_facturen.py`.

### Werkwijze
1. Zorg dat de PDF-bestanden beschikbaar zijn op:
   ```
   /Users/joy/Library/Mobile Documents/com~apple~CloudDocs/Documents/Koen/Piet ZZP/2025/
   ```
2. Voer het script uit vanuit de projectroot:
   ```bash
   poetry run python3 scripts/import_old_facturen.py
   ```
3. Het script doet het volgende:
   - Leest de factuurdatum, klantnaam en bedragen uit elke PDF
   - Kopieert de PDF naar `facturen_pdfs/2025/Q1/`, `Q2/`, `Q3/` of `Q4/` op basis van de factuurdatum
   - Zet de gegevens in **staging-tabellen** (`facturen_history` en `factuurregels_history`) — de productietabellen worden nog niet aangepast
4. Valideer de geïmporteerde data via **Admin → SQL Console**:
   ```sql
   SELECT * FROM facturen_history ORDER BY factuurdatum;
   SELECT * FROM factuurregels_history LIMIT 50;
   ```
5. Als alles klopt, merge je naar productie met de volgende twee queries (ook via SQL Console):
   ```sql
   INSERT INTO facturen
       SELECT id, factuurnummer, klantnaam, klantId, factuurdatum,
              totaal_excl, btw, totaal_incl, isBetaald, kwartaal, mailSent
       FROM facturen_history
       WHERE factuurnummer NOT IN (SELECT factuurnummer FROM facturen);

   INSERT INTO factuurregels
       SELECT id, factuur_id, omschrijving, aantal_uren, uurprijs, totaal, weeknummers
       FROM factuurregels_history
       WHERE factuur_id NOT IN (SELECT DISTINCT factuur_id FROM factuurregels);
   ```

### Nieuw jaar (bijv. 2026)
Pas in `scripts/import_old_facturen.py` de variabele `SOURCE_DIR` aan naar de juiste iCloud-map, en `PDF_DEST_DIR` naar `facturen_pdfs/2026`. De rest van het script werkt hetzelfde.
