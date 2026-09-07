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

dias_mapa = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

def convertir_horario_peru_a_art(hora_str_peru, sumadd=2):
    """
    Convierte cadenas como '7:00 am', '1:30 pm', '11:30 pm' o '07:00'
    de Hora de Perú (UTC-5) a Hora de Argentina (UTC-3), sumando 2 horas.
    Retorna (hora_formateada_HH:MM, cruzo_dia_bool)
    """
    s = hora_str_peru.strip().lower()
    
    # Extraer horas y minutos
    match = re.search(r'(\d{1,2}):(\d{2})\s*(am|pm)?', s)
    if not match:
        return None, False

    h = int(match.group(1))
    m = int(match.group(2))
    ampm = match.group(3)

    if ampm:
        if ampm == 'pm' and h < 12:
            h += 12
        elif ampm == 'am' and h == 12:
            h = 0

    # Sumar 2 horas (Perú a Argentina)
    dt_peru = datetime(2026, 1, 1, h, m)
    dt_art = dt_peru + timedelta(hours=sumadd)

    cruzo_dia = dt_art.day > 1
    return dt_art.strftime("%H:%M"), cruzo_dia


# 2. Scraping Web navegando por las 3 pestañas
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
    page.wait_for_timeout(4000)

    # Identificar los botones de pestañas (Lunes a Viernes, Sábado, Domingo)
    botones = page.query_selector_all("button, [role='tab'], .vc_tta-tab, .elementor-tab-title, a")
    
    tabs_encontradas = []
    for b in botones:
        txt = b.inner_text().strip()
        if re.search(r'(Lunes|Viernes|Sábado|Sabado|Domingo)', txt, re.I):
            tabs_encontradas.append((txt, b))

    # Si hay pestañas interactivas, las recorremos; de lo contrario procesamos el HTML cargado
    if tabs_encontradas:
        for txt_tab, btn_elem in tabs_encontradas:
            try:
                btn_elem.click()
                page.wait_for_timeout(1500)
            except Exception:
                pass

            html_content = page.content()
            soup = BeautifulSoup(html_content, "html.parser")
            
            # Mapear qué días representa la pestaña
            dias_bloque = []
            if "sabado" in txt_tab.lower() or "sábado" in txt_tab.lower():
                dias_bloque = ["Sábado"]
            elif "domingo" in txt_tab.lower():
                dias_bloque = ["Domingo"]
            else:
                dias_bloque = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]

            # Extraer filas de tablas
            filas_tabla = soup.find_all("tr")
            for tr in filas_tabla:
                tds = tr.find_all(["td", "th"])
                if len(tds) >= 2:
                    col_hora = tds[0].get_text(strip=True)
                    col_prog = tds[1].get_text(strip=True)
                    col_clas = tds[2].get_text(strip=True) if len(tds) > 2 else ""

                    if re.search(r'\d{1,2}:\d{2}', col_hora) and col_prog.lower() != "programa":
                        for dia_nombre in dias_bloque:
                            programas_totales.append({
                                "dia": dia_nombre,
                                "hora_raw": col_hora,
                                "programa": col_prog,
                                "clasificacion": col_clas
                            })
    else:
        # Extraer directo si toda la programación está renderizada en una sola tabla/vista
        html_content = page.content()
        soup = BeautifulSoup(html_content, "html.parser")
        filas_tabla = soup.find_all("tr")
        for tr in filas_tabla:
            tds = tr.find_all(["td", "th"])
            if len(tds) >= 2:
                col_hora = tds[0].get_text(strip=True)
                col_prog = tds[1].get_text(strip=True)
                col_clas = tds[2].get_text(strip=True) if len(tds) > 2 else ""

                if re.search(r'\d{1,2}:\d{2}', col_hora) and col_prog.lower() != "programa":
                    for dia_nombre in ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]:
                        programas_totales.append({
                            "dia": dia_nombre,
                            "hora_raw": col_hora,
                            "programa": col_prog,
                            "clasificacion": col_clas
                        })

    browser.close()

# 3. Procesar horarios, conversión a Argentina (+2h) y ajuste de rangos
filas_epg = [
    ["Dia", "Inicio", "Fin", "Programa", "Descripcion"]
]

for p in programas_totales:
    col_hora = p["hora_raw"]
    
    # Manejar rangos tipo "7:00 – 7:30 am" o horas únicas "7:00 am"
    partes = re.split(r'[–\-–]', col_hora)
    
    hora_ini_peru = partes[0].strip()
    hora_fin_peru = partes[1].strip() if len(partes) > 1 else ""

    # Asegurar sufijo am/pm en el inicio si solo está en el fin
    if hora_fin_peru and re.search(r'(am|pm)', hora_fin_peru, re.I) and not re.search(r'(am|pm)', hora_ini_peru, re.I):
        sufijo = re.search(r'(am|pm)', hora_fin_peru, re.I).group(0)
        hora_ini_peru += f" {sufijo}"

    ini_art, _ = convertir_horario_peru_a_art(hora_ini_peru, sumadd=2)
    fin_art, _ = convertir_horario_peru_a_art(hora_fin_peru, sumadd=2) if hora_fin_peru else (None, False)

    if not ini_art:
        continue

    desc = f"Clasificación: {p['clasificacion']}" if p['clasificacion'] else ""

    filas_epg.append([
        p["dia"],
        ini_art,
        fin_art if fin_art else "",
        p["programa"],
        desc
    ])

# Completar horas de Fin vacías con la hora de inicio del siguiente programa
for i in range(1, len(filas_epg) - 1):
    if not filas_epg[i][2]:  # Fin vacío
        if filas_epg[i][0] == filas_epg[i+1][0]:
            filas_epg[i][2] = filas_epg[i+1][1]
        else:
            filas_epg[i][2] = "00:00"

if len(filas_epg) > 1 and not filas_epg[-1][2]:
    filas_epg[-1][2] = "00:00"

# 4. Volcar a Google Sheets
sheet.clear()
sheet.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se actualizaron {len(filas_epg)-1} registros para Doble C convertidos a Hora de Argentina.")
