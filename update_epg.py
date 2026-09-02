import os
import json
import time
from datetime import datetime
import zoneinfo
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# 1. Autenticación
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

gcp_key = os.environ.get("GCP_SA_KEY")
if not gcp_key:
    raise ValueError("No se encontró GCP_SA_KEY en los Secrets de GitHub.")

credentials_info = json.loads(gcp_key)
credentials = Credentials.from_service_account_info(credentials_info, scopes=SCOPES)
client = gspread.authorize(credentials)

SPREADSHEET_ID = "1JKs0R5aFs4uWMBFDAuVtf2-hDDYd87ZkibTqFV600Rs"

def abrir_sheet_con_reintento(spreadsheet_id, nombre_pestana=None, max_intentos=5):
    for intento in range(1, max_intentos + 1):
        try:
            doc = client.open_by_key(spreadsheet_id)
            if nombre_pestana:
                try:
                    return doc.worksheet(nombre_pestana)
                except Exception:
                    return doc.add_worksheet(title=nombre_pestana, rows=1000, cols=10)
            return doc.sheet1
        except gspread.exceptions.APIError as e:
            code = getattr(e.response, "status_code", None)
            if code in [500, 502, 503, 504] and intento < max_intentos:
                espera = intento * 5
                print(f"Aviso: Google API respondió con error {code}. Reintentando en {espera}s (Intento {intento}/{max_intentos})...")
                time.sleep(espera)
            else:
                raise e

sheet = abrir_sheet_con_reintento(SPREADSHEET_ID)

dias_mapa = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

# 2. Scraping Web
url = "https://japanmotion.site/"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        timezone_id="America/Argentina/Buenos_Aires",
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    page.goto(url, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(3000)

    for _ in range(3):
        page.evaluate("window.scrollBy(0, 800)")
        page.wait_for_timeout(1000)

    html_content = page.content()
    browser.close()

# 3. Extracción y Limpieza
soup = BeautifulSoup(html_content, "html.parser")
bloques = soup.find_all("article")
if not bloques:
    bloques = soup.find_all(["div", "tr", "li"])

tz_local = zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")
indice_dia = datetime.now(tz_local).weekday()

programas_raw = []

for b in bloques:
    texto_art = b.get_text(" ", strip=True)
    import re
    matches_hora = re.findall(r'\b\d{1,2}:\d{2}\b', texto_art)
    if not matches_hora:
        continue
        
    hora_ini = matches_hora[0]
    if len(hora_ini) == 4:
        hora_ini = "0" + hora_ini

    texto_sin_hora = re.sub(r'^\d{1,2}:\d{2}\s*', '', texto_art)
    programa_limpio = re.sub(r'\s+', ' ', texto_sin_hora).strip()

    if not programa_limpio or len(programa_limpio) < 2:
        continue

    if programas_raw and programas_raw[-1]["inicio"] == hora_ini and programas_raw[-1]["programa"] == programa_limpio:
        continue

    programas_raw.append({
        "inicio": hora_ini,
        "programa": programa_limpio
    })

# 4. Formatear grilla EPG
filas_epg = [
    ["Dia", "Inicio", "Fin", "Programa", "Descripcion"]
]

for i in range(len(programas_raw)):
    p_curr = programas_raw[i]
    
    if i > 0:
        hora_prev = programas_raw[i-1]["inicio"]
        hora_curr = p_curr["inicio"]
        if hora_prev >= "20:00" and hora_curr < "06:00":
            indice_dia = (indice_dia + 1) % 7

    dia_nombre = dias_mapa[indice_dia]

    if i < len(programas_raw) - 1:
        fin = programas_raw[i+1]["inicio"]
    else:
        fin = programas_raw[0]["inicio"]

    filas_epg.append([dia_nombre, p_curr["inicio"], fin, p_curr["programa"], ""])

sheet.clear()
sheet.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se actualizaron {len(filas_epg)-1} registros en Japan Motion.")
