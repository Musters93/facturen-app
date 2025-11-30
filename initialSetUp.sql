
CREATE TABLE sqlite_sequence(name,seq);
CREATE TABLE footer (
    naam TEXT,
    adres TEXT,
    postcode_plaats TEXT,
    telefoon TEXT,
    email TEXT,
    kvk TEXT,
    btw_id TEXT,
    iban TEXT
);
CREATE TABLE bedrijf_footer (
    id INTEGER PRIMARY KEY,
    naam TEXT,
    adres TEXT,
    postcode_plaats TEXT,
    telefoon TEXT,
    email TEXT,
    kvk TEXT,
    btw_id TEXT,
    iban TEXT
);
CREATE TABLE IF NOT EXISTS "klanten" (
    klant_id INTEGER PRIMARY KEY AUTOINCREMENT,
    klantnaam TEXT NOT NULL UNIQUE,
    adres TEXT NOT NULL,
    postcode_plaats TEXT NOT NULL,
    btw_verlegd BOOLEAN NOT NULL,
    btw_nummer TEXT NOT NULL,
    email TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS "facturen" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    factuurnummer TEXT NOT NULL UNIQUE,
    klantnaam TEXT NOT NULL,
    klantId INTEGER NOT NULL,
    factuurdatum TEXT NOT NULL,
    totaal_excl REAL NOT NULL,
    btw REAL NOT NULL,
    totaal_incl REAL NOT NULL,
    isBetaald BOOLEAN NOT NULL,
    kwartaal TEXT NOT NULL,
    mailSent BOOLEAN NOT NULL DEFAULT 0,
    FOREIGN KEY (klantId) REFERENCES "klanten"(klant_id)
);
CREATE TABLE IF NOT EXISTS "factuurregels" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    factuur_id INTEGER NOT NULL,
    omschrijving TEXT NOT NULL,
    aantal_uren REAL NOT NULL,
    uurprijs REAL NOT NULL,
    totaal REAL NOT NULL,
    weeknummers TEXT NOT NULL,
    FOREIGN KEY (factuur_id) REFERENCES "facturen"(id)
);
sqlite> 