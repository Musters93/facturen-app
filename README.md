# Facturen Project
V1.0
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
