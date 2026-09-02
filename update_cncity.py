import os
import json
import re
from datetime import datetime
import zoneinfo
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

# 1. Conexión con Google Sheets
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

# Abre o crea la pestaña CNCITY
try:
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet("CNCITY")
except Exception:
    sheet = client.open_by_key(SPREADSHEET_ID).add_worksheet(title="CNCITY", rows=1000, cols=10)

dias_mapa = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

def extraer_programa_y_descripcion(texto_raw):
    texto = re.sub(r'(Agendar|Google Calendar|Descargar|\.ics|18\+|13\+|TODOS)', '', texto_raw, flags=re.I).strip()
    if "—" in texto:
        partes = texto.split("—", 1)
        return partes[0].strip(), partes[1].strip()
    match_ep = re.search(r'^(.*?(?:Ep\.|Episode|Cap\.|Capítulo)\s*\d+)(.*)$', texto, re.I)
    if match_ep:
        return match_ep.group(1).strip(), match_ep.group(2).strip()
    partes = re.split(r'(?<=[a-z0-9])\s+(?=[A-Z0-9])', texto, maxsplit=1)
    if len(partes) == 2:
        return partes[0].strip(), partes[1].strip()
    return texto[:35].strip(), texto.strip()

url = "https://cncity.live/"

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

    # 1. Abrir sección Grilla
    try:
        grilla_btn = page.get_by_text("GRILLA", exact=False).first
        if grilla_btn.is_visible():
            grilla_btn.click()
            page.wait_for_timeout(2000)
    except Exception as e:
        print("Aviso al ingresar a Grilla:", e)

    # 2. Seleccionar franja horaria Argentina
    try:
        arg_btn = page.get_by_text("ARGENTINA", exact=False).first
        if arg_btn.is_visible():
            arg_btn.click()
            page.wait_for_timeout(2000)
    except Exception as e:
        print("Aviso al seleccionar Argentina:", e)

    # 3. Scroll progresivo para desplegar todo lo cargado dinámicamente
    for _ in range(3):
        page.evaluate("window.scrollBy(0, 800)")
        page.wait_for_timeout(1000)

    html_content = page.content()
    browser.close()

# 4. Procesamiento de los datos reales del DOM
soup = BeautifulSoup(html_content, "html.parser")

bloques = soup.find_all("article")
if not bloques:
    bloques = soup.find_all(["div", "tr", "li"], class_=re.compile(r'item|card|program|schedule|show|event', re.I))

# Determinamos el día inicial según la hora local de Argentina
tz_local = zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")
indice_dia = datetime.now(tz_local).weekday()

programas_raw = []

for b in bloques:
    texto_art = b.get_text(" ", strip=True)
    
    hora_match = re.search(r'\b\d{1,2}:\d{2}\b', texto_art)
    if not hora_match:
        continue
        
    hora_ini = hora_match.group(0)
    if len(hora_ini) == 4:
        hora_ini = "0" + hora_ini

    titulo_tag = b.find(["h2", "h3", "h4", "h5", "strong", "b"])
    if titulo_tag:
        titulo = titulo_tag.get_text(strip=True)
        titulo = re.sub(r'^\d{1,2}:\d{2}\s*', '', titulo).strip()
        desc = texto_art.replace(titulo, "", 1)
        desc = re.sub(r'\b\d{1,2}:\d{2}\b', '', desc)
        desc = re.sub(r'(Agendar|Google Calendar|Descargar|\.ics|18\+|13\+|TODOS)', '', desc, flags=re.I).strip()
    else:
        texto_sin_hora = re.sub(r'^\d{1,2}:\d{2}\s*', '', texto_art)
        titulo, desc = extraer_programa_y_descripcion(texto_sin_hora)

    if not titulo:
        titulo = "Programa"

    if programas_raw and programas_raw[-1]["inicio"] == hora_ini and programas_raw[-1]["titulo"] == titulo:
        continue

    programas_raw.append({
        "inicio": hora_ini,
        "titulo": titulo,
        "descripcion": desc
    })

# 5. Formatear lista final con cálculo automático de día y hora fin
filas_epg = [
    ["Dia", "Inicio", "Fin", "Programa", "Descripcion"]
]

for i in range(len(programas_raw)):
    p_curr = programas_raw[i]
    
    # Si la hora pasa de noche (>=20:00) a madrugada (<06:00), avanzamos el día automáticamente
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

    filas_epg.append([dia_nombre, p_curr["inicio"], fin, p_curr["titulo"], p_curr["descripcion"]])

# 6. Volcar a Google Sheets
sheet.clear()
sheet.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se cargaron {len(filas_epg)-1} programas reales en la pestaña CNCITY.")
