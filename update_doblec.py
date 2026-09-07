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

dias_lista = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

def parsear_hora_peru(hora_str, es_hora_fin=False, ampm_fin=None):
    s = hora_str.strip().lower()
    match = re.search(r'(\d{1,2}):(\d{2})\s*(am|pm)?', s)
    if not match:
        return None

    h = int(match.group(1))
    m = int(match.group(2))
    ampm = match.group(3)

    if not ampm and ampm_fin:
        if not es_hora_fin:
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

def convertir_peru_a_art_con_dias(h, m, dia_base_idx):
    """
    Suma 2 horas (Perú UTC-5 a Argentina UTC-3) y ajusta el día de la semana
    si cruza la medianoche (00:00).
    """
    dt_peru = datetime(2026, 1, 1, h, m)
    dt_art = dt_peru + timedelta(hours=2)

    offset_dias = 0
    if dt_art.day > 1:
        offset_dias = 1

    nuevo_dia_idx = (dia_base_idx + offset_dias) % 7
    return dt_art.strftime("%H:%M"), dias_lista[nuevo_dia_idx]


# 2. Scraping Web aislando el HTML de cada pestaña individualmente
url = "https://doblec.com.pe/programacion/"
programas_por_pestana = {
    "lun_vie": [],
    "sabado": [],
    "domingo": []
}

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

    # Forzar clic en cada pestaña para aislar el contenedor que se vuelve visible/activo
    tabs_config = [
        ("lun_vie", r'Lunes|Viernes'),
        ("sabado", r'Sábado|Sabado'),
        ("domingo", r'Domingo')
    ]

    for clave, regex_tab in tabs_config:
        try:
            # Buscar el botón correspondiente y hacer click
            btn = page.locator(f"button:has-text('{clave}'), a:has-text('{clave}'), div:has-text('{clave}')").first
            elementos = page.query_selector_all("button, [role='tab'], .elementor-tab-title, a, div")
            for el in elementos:
                txt = el.inner_text().strip()
                if re.search(regex_tab, txt, re.I) and len(txt) < 30:
                    el.click()
                    page.wait_for_timeout(1000)
                    break
        except Exception:
            pass

        # Extraer solo las tablas asociadas a contenedores visibles o específicos
        html_content = page.content()
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Buscar paneles de pestañas activos
        paneles = soup.find_all(["div", "section"], class_=re.compile(r'active|show|elementor-tab-content', re.I))
        contenedor_target = None
        
        for pan in paneles:
            # Validar que no sea un contenedor oculto si tiene style="display: none"
            style = pan.get("style", "")
            if "display: none" not in style and "display:none" not in style:
                contenedor_target = pan
                break

        if not contenedor_target:
            contenedor_target = soup

        filas_tabla = contenedor_target.find_all("tr")
        for tr in filas_tabla:
            tds = tr.find_all(["td", "th"])
            if len(tds) >= 2:
                col_hora = tds[0].get_text(strip=True)
                col_prog = tds[1].get_text(strip=True)
                col_clas = tds[2].get_text(strip=True) if len(tds) > 2 else ""

                if re.search(r'\d{1,2}:\d{2}', col_hora) and col_prog.lower() != "programa":
                    # Evitar duplicados consecutivos exactos dentro de la misma pestaña
                    item = {"hora_raw": col_hora, "programa": col_prog, "clasificacion": col_clas}
                    if not programas_por_pestana[clave] or programas_por_pestana[clave][-1]["hora_raw"] != col_hora:
                        programas_por_pestana[clave].append(item)

    browser.close()

# 3. Mapear y Replicar Lunes a Viernes + Sábado + Domingo individualmente
filas_epg = [
    ["Dia", "Inicio", "Fin", "Programa", "Descripcion"]
]

# Construir la semana completa
grilla_semanal = [
    ("Lunes", 0, programas_por_pestana["lun_vie"]),
    ("Martes", 1, programas_por_pestana["lun_vie"]),
    ("Miércoles", 2, programas_por_pestana["lun_vie"]),
    ("Jueves", 3, programas_por_pestana["lun_vie"]),
    ("Viernes", 4, programas_por_pestana["lun_vie"]),
    ("Sábado", 5, programas_por_pestana["sabado"]),
    ("Domingo", 6, programas_por_pestana["domingo"])
]

for dia_nombre, dia_idx, lista_progs in grilla_semanal:
    for i in range(len(lista_progs)):
        p = lista_progs[i]
        col_hora = p["hora_raw"]
        partes = re.split(r'[–\-–]', col_hora)
        
        hora_ini_raw = partes[0].strip()
        hora_fin_raw = partes[1].strip() if len(partes) > 1 else ""

        match_ampm_fin = re.search(r'(am|pm)', hora_fin_raw, re.I)
        ampm_fin = match_ampm_fin.group(0).lower() if match_ampm_fin else None

        res_ini = parsear_hora_peru(hora_ini_raw, es_hora_fin=False, ampm_fin=ampm_fin)
        res_fin = parsear_hora_peru(hora_fin_raw, es_hora_fin=True, ampm_fin=ampm_fin) if hora_fin_raw else None

        if not res_ini:
            continue

        # Convertir hora e identificar si se mueve de día por el huso horario
        ini_art, dia_real = convertir_peru_a_art_con_dias(res_ini[0], res_ini[1], dia_idx)
        fin_art, _ = convertir_peru_a_art_con_dias(res_fin[0], res_fin[1], dia_idx) if res_fin else ("", None)

        desc = f"Clasificación: {p['clasificacion']}" if p['clasificacion'] else ""

        filas_epg.append([
            dia_real,
            ini_art,
            fin_art,
            p["programa"],
            desc
        ])

# Completar horas de Fin vacías dentro del mismo día
for i in range(1, len(filas_epg) - 1):
    if not filas_epg[i][2]:
        if filas_epg[i][0] == filas_epg[i+1][0]:
            filas_epg[i][2] = filas_epg[i+1][1]
        else:
            filas_epg[i][2] = "00:00"

if len(filas_epg) > 1 and not filas_epg[-1][2]:
    filas_epg[-1][2] = "00:00"

# 4. Volcar en Google Sheets
sheet.clear()
sheet.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se actualizaron {len(filas_epg)-1} registros asignando días de la semana reales y convirtiendo a hora de Argentina.")
