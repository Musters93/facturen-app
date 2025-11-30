import sqlite3
import datetime
import os
from fastapi import HTTPException
from fastapi import FastAPI, Request, Form
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from services.pdf_generator_service import genereer_pdf 
from services.mail_service import prepare_email_data, send_email
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Body
from routes.home import router as home_router  # <-- hier
from routes.admin import router as admin_router    # jouw admin module
from routes.facturen import router as facturen_router    # jouw admin module
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
app.include_router(home_router)          
app.include_router(admin_router, prefix="/admin")  
app.include_router(facturen_router, prefix="/facturen")



