import os
import json
import time
import re
from datetime import datetime, timedelta
import zoneinfo
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# 1. Autenticación con Google Sheets
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
NOMBRE_PESTANA = "DOBLE_C"

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

sheet = abrir_sheet_con_reintento(SPREADSHEET_ID, NOMBRE_PESTANA)

def parsear_hora_peru(hora_str, es_hora_fin=False, ampm_fin=None):
    """
    Parsea cadenas como '11:00', '11:30 am', '12:00 pm', '02:30 am' en Hora de Perú.
    Maneja la ambigüedad de mediodía/medianoche correctamente.
    """
    s = hora_str.strip().lower()
    match = re.search(r'(\d{1,2}):(\d{2})\s*(am|pm)?', s)
    if not match:
        return None

    h = int(match.group(1))
    m = int(match.group(2))
    ampm = match.group(3)

    # Si la hora inicial no especifica am/pm, inferir del sufijo fin
    if not ampm and ampm_fin:
        if not es_hora_fin:
            # Ej: 11:00 - 12:00 pm -> 11:00 es AM
            if h == 11 and ampm_fin == 'pm':
                ampm = 'am'
            elif h == 11 and ampm_fin == 'am':
                ampm = 'pm'
            else:
                ampm = ampm_fin

    if ampm:
        if ampm == 'pm' and h < 12:
            h += 12
        elif ampm == 'am' and h == 12:
            h = 0

    return h, m

def convertir_peru_a_art(h, m):
    """Suma 2 horas (Perú UTC-5 a Argentina UTC-3)"""
    dt_peru = datetime(2026, 1, 1, h, m)
    dt_art = dt_peru + timedelta(hours=2)
    return dt_art.strftime("%H:%M")


# 2. Scraping Web distinguiendo las 3 pestañas dinámicas
url = "https://doblec.com.pe/programacion/"
programas_totales = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        timezone_id="America/Lima",
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    html_content = page.content()
    soup = BeautifulSoup(html_content, "html.parser")

    # Identificar contenedores o pestañas de Elementor
    tab_containers = soup.find_all(["div", "section"], class_=re.compile(r'elementor-tab-content|vc_tta-panel|tab-pane|tab-content', re.I))

    # Definir mapeo de bloques si existen paneles separados
    if len(tab_containers) >= 3:
        bloques_mapa = [
            ("Weekdays", tab_containers[0]),
            ("Sábado", tab_containers[1]),
            ("Domingo", tab_containers[2])
        ]
    else:
        # Si no los encuentra por contenedor, hacer clic interactivo y extraer selector activo
        bloques_mapa = []
        botones = page.query_selector_all(".elementor-tab-title, .vc_tta-tab, button, [role='tab']")
        
        for b in botones:
            txt = b.inner_text().strip()
            if re.search(r'Lunes|Viernes', txt, re.I):
                b.click()
                page.wait_for_timeout(1000)
                s = BeautifulSoup(page.content(), "html.parser")
                bloques_mapa.append(("Weekdays", s))
            elif re.search(r'Sábado|Sabado', txt, re.I):
                b.click()
                page.wait_for_timeout(1000)
                s = BeautifulSoup(page.content(), "html.parser")
                bloques_mapa.append(("Sábado", s))
            elif re.search(r'Domingo', txt, re.I):
                b.click()
                page.wait_for_timeout(1000)
                s = BeautifulSoup(page.content(), "html.parser")
                bloques_mapa.append(("Domingo", s))

    # Recorrer cada pestaña con su DOM específico
    for etiqueta_dia, contenedor in bloques_mapa:
        filas_tabla = contenedor.find_all("tr")
        
        for tr in filas_tabla:
            tds = tr.find_all(["td", "th"])
            if len(tds) >= 2:
                col_hora = tds[0].get_text(strip=True)
                col_prog = tds[1].get_text(strip=True)
                col_clas = tds[2].get_text(strip=True) if len(tds) > 2 else ""

                if re.search(r'\d{1,2}:\d{2}', col_hora) and col_prog.lower() != "programa":
                    programas_totales.append({
                        "dia": etiqueta_dia,
                        "hora_raw": col_hora,
                        "programa": col_prog,
                        "clasificacion": col_clas
                    })

    browser.close()

# 3. Procesamiento y Conversión de Horarios
filas_epg = [
    ["Dia", "Inicio", "Fin", "Programa", "Descripcion"]
]

for p in programas_totales:
    col_hora = p["hora_raw"]
    partes = re.split(r'[–\-–]', col_hora)
    
    hora_ini_raw = partes[0].strip()
    hora_fin_raw = partes[1].strip() if len(partes) > 1 else ""

    # Extraer am/pm del fin si existe
    match_ampm_fin = re.search(r'(am|pm)', hora_fin_raw, re.I)
    ampm_fin = match_ampm_fin.group(0).lower() if match_ampm_fin else None

    # Parsea Perú
    res_ini = parsear_hora_peru(hora_ini_raw, es_hora_fin=False, ampm_fin=ampm_fin)
    res_fin = parsear_hora_peru(hora_fin_raw, es_hora_fin=True, ampm_fin=ampm_fin) if hora_fin_raw else None

    if not res_ini:
        continue

    # Convertir a Hora Argentina (+2h)
    ini_art = convertir_peru_a_art(res_ini[0], res_ini[1])
    fin_art = convertir_peru_a_art(res_fin[0], res_fin[1]) if res_fin else ""

    desc = f"Clasificación: {p['clasificacion']}" if p['clasificacion'] else ""

    filas_epg.append([
        p["dia"],
        ini_art,
        fin_art,
        p["programa"],
        desc
    ])

# Completar horas de Fin vacías con la hora del programa posterior en la misma pestaña
for i in range(1, len(filas_epg) - 1):
    if not filas_epg[i][2]:
        if filas_epg[i][0] == filas_epg[i+1][0]:
            filas_epg[i][2] = filas_epg[i+1][1]
        else:
            filas_epg[i][2] = "00:00"

if len(filas_epg) > 1 and not filas_epg[-1][2]:
    filas_epg[-1][2] = "00:00"

# 4. Volcar a Google Sheets
sheet.clear()
sheet.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se actualizaron {len(filas_epg)-1} registros separando adecuadamente Weekdays, Sábado y Domingo.")
