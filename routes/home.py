
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from database import get_db  # jouw helper module voor DB connectie

templates = Jinja2Templates(directory="templates")
router = APIRouter()  # router gebruiken in plaats van app

@router.get("/")
def index(request: Request):
    welkom_bericht = "Welkom bij de Factuur App! Je kunt hier klanten en facturen beheren."

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT klantnaam FROM klanten ORDER BY klantnaam")
        klanten = [r["klantnaam"] for r in cur.fetchall()]

    return templates.TemplateResponse("home/index.html", {
        "request": request,
        "klanten": klanten,
        "welkom_bericht": welkom_bericht
    })