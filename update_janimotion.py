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
NOMBRE_PESTANA = "JANI"

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

dias_semana_esp = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

# 2. Scraping Web navegando por pestañas de días
url = "https://janimotion.com/schedule"
programas_totales = []

tz_local = zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")
fecha_base = datetime.now(tz_local)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        timezone_id="America/Argentina/Buenos_Aires",
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    
    # Cambiado a domcontentloaded para evitar time out por peticiones residuales
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # Identificar botones de los días
    botones_dias = page.query_selector_all("button, [role='tab'], div.cursor-pointer, a")
    tabs_validos = []
    for btn in botones_dias:
        txt = btn.inner_text().strip()
        if re.search(r'(Hoy|Lunes|Martes|Miércoles|Jueves|Viernes|Sábado|Domingo|\d{1,2}\s+de\s+\w+)', txt, re.I):
            tabs_validos.append(btn)

    if not tabs_validos:
        tabs_validos = page.query_selector_all(".flex.gap-4 button, header button, div.flex > div")

    cant_dias = max(1, len(tabs_validos))
    
    for idx in range(cant_dias):
        fecha_dia = fecha_base + timedelta(days=idx)
        nombre_dia = dias_semana_esp[fecha_dia.weekday()]

        if idx < len(tabs_validos):
            try:
                tabs_validos[idx].click()
                page.wait_for_timeout(2000)
            except Exception:
                pass

        page.evaluate("window.scrollBy(0, 800)")
        page.wait_for_timeout(500)

        html_content = page.content()
        soup = BeautifulSoup(html_content, "html.parser")

        bloques = soup.find_all("article")
        if not bloques:
            bloques = soup.find_all("div", class_=re.compile(r'card|item|program|show|event|schedule', re.I))

        for b in bloques:
            texto_raw = b.get_text("\n", strip=True)
            lineas = [l.strip() for l in texto_raw.split("\n") if l.strip()]

            if not lineas:
                continue

            # 1. Determinar Hora de Inicio
            hora_str = None
            lineas_sin_hora = []

            for l in lineas:
                match_h = re.search(r'\b\d{1,2}:\d{2}\b', l)
                if match_h and not hora_str:
                    hora_str = match_h.group(0).zfill(5)
                elif re.search(r'^AHORA$', l, re.I) and not hora_str:
                    hora_str = "AHORA"
                elif not re.search(r'^\d{1,2}:\d{2}$|^AHORA$|^\+\d{1,2}$|^(Agendar|Google Calendar|Descargar|\.ics)$', l, re.I):
                    lineas_sin_hora.append(l)

            if not hora_str or not lineas_sin_hora:
                continue

            # 2. Determinar Título
            elem_titulo = b.find(["h1", "h2", "h3", "h4", "h5", "strong", "b"])
            if elem_titulo and elem_titulo.get_text(strip=True):
                titulo = elem_titulo.get_text(strip=True)
            else:
                titulo = lineas_sin_hora[0]

            # 3. Filtrar y Desduplicar la Descripción
            partes_desc = []
            for l in lineas_sin_hora:
                if l.lower() == titulo.lower():
                    continue
                if l not in partes_desc:
                    partes_desc.append(l)

            descripcion_final = " ".join(partes_desc).strip()

            programas_totales.append({
                "dia": nombre_dia,
                "inicio": hora_str,
                "programa": titulo,
                "descripcion": descripcion_final
            })

    browser.close()

# 3. Post-procesamiento
programas_procesados = []

for i in range(len(programas_totales)):
    p_curr = programas_totales[i]
    
    if p_curr["inicio"] == "AHORA":
        if i > 0 and programas_totales[i-1]["dia"] == p_curr["dia"] and programas_totales[i-1]["inicio"] != "AHORA":
            p_curr["inicio"] = programas_totales[i-1]["inicio"]
        elif i < len(programas_totales) - 1 and programas_totales[i+1]["inicio"] != "AHORA":
            p_curr["inicio"] = programas_totales[i+1]["inicio"]
        else:
            p_curr["inicio"] = "00:00"

    if i < len(programas_totales) - 1:
        fin_str = programas_totales[i+1]["inicio"]
        if fin_str == "AHORA":
            fin_str = p_curr["inicio"]
    else:
        fin_str = "00:00"

    if programas_procesados:
        p_prev = programas_procesados[-1]
        if p_prev["dia"] == p_curr["dia"] and p_prev["inicio"] == p_curr["inicio"] and p_prev["programa"] == p_curr["programa"]:
            continue

    programas_procesados.append({
        "dia": p_curr["dia"],
        "inicio": p_curr["inicio"],
        "fin": fin_str,
        "programa": p_curr["programa"],
        "descripcion": p_curr["descripcion"]
    })

# 4. Volcar a Google Sheets
filas_epg = [
    ["Dia", "Inicio", "Fin", "Programa", "Descripcion"]
]

for p in programas_procesados:
    filas_epg.append([p["dia"], p["inicio"], p["fin"], p["programa"], p["descripcion"]])

sheet.clear()
sheet.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se actualizaron {len(filas_epg)-1} registros sin texto duplicado.")
