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

def limpiar_texto_programa(texto_raw):
    # Eliminar duraciones tipo '23 min', '12 min'
    texto = re.sub(r'\b\d{1,3}\s*min\b', '', texto_raw, flags=re.I)
    # Eliminar palabras/botones residuales del reproductor
    texto = re.sub(r'(Agendar|Google Calendar|Descargar|\.ics|18\+|13\+|TODOS)', '', texto, flags=re.I)
    # Normalizar espacios
    return re.sub(r'\s+', ' ', texto).strip()

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

    # 3. Scroll progresivo
    for _ in range(3):
        page.evaluate("window.scrollBy(0, 800)")
        page.wait_for_timeout(1000)

    html_content = page.content()
    browser.close()

# 4. Procesamiento
soup = BeautifulSoup(html_content, "html.parser")

bloques = soup.find_all("article")
if not bloques:
    bloques = soup.find_all(["div", "tr", "li"], class_=re.compile(r'item|card|program|schedule|show|event', re.I))

tz_local = zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")
indice_dia = datetime.now(tz_local).weekday()

programas_raw = []

for b in bloques:
    texto_art = b.get_text(" ", strip=True)
    
    # Filtrar contenedores masivos con múltiples horarios (evita la 1ª fila basura)
    matches_hora = re.findall(r'\b\d{1,2}:\d{2}\b', texto_art)
    if len(matches_hora) > 2 or not matches_hora:
        continue
        
    hora_ini = matches_hora[0]
    if len(hora_ini) == 4:
        hora_ini = "0" + hora_ini

    # Tomar TODO el texto restándole solo la hora de inicio
    texto_sin_hora = re.sub(r'^\d{1,2}:\d{2}\s*', '', texto_art)
    
    # Limpiar duraciones y caracteres sobrantes
    programa_completo = limpiar_texto_programa(texto_sin_hora)

    if not programa_completo or len(programa_completo) < 2:
        continue

    # Evitar duplicados inmediatos
    if programas_raw and programas_raw[-1]["inicio"] == hora_ini and programas_raw[-1]["programa"] == programa_completo:
        continue

    programas_raw.append({
        "inicio": hora_ini,
        "programa": programa_completo
    })

# 5. Formatear lista final
filas_epg = [
    ["Dia", "Inicio", "Fin", "Programa", "Descripcion"]
]

for i in range(len(programas_raw)):
    p_curr = programas_raw[i]
    
    # Control de paso a la medianoche
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

    # Descripcion queda vacia ("")
    filas_epg.append([dia_nombre, p_curr["inicio"], fin, p_curr["programa"], ""])

# 6. Volcar a Google Sheets
sheet.clear()
sheet.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se actualizaron {len(filas_epg)-1} registros. Todo el texto va en 'Programa' y 'Descripcion' queda vacía.")
