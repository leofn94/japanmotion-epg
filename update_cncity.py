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

# Abre o crea la pestaña de CNCity en el Spreadsheet
try:
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet("CNCITY")
except Exception:
    # Si no existe la pestaña 'CNCITY', la crea automáticamente
    sheet = client.open_by_key(SPREADSHEET_ID).add_worksheet(title="CNCITY", rows=1000, cols=10)

dias_mapa = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

filas_epg = [
    ["Dia", "Inicio", "Fin", "Programa", "Descripcion"]
]

url = "https://cncity.live/"

# 2. Extracción interactiva con Playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        timezone_id="America/Argentina/Buenos_Aires",
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    # 1. Hacer clic en la sección 'Grilla'
    try:
        grilla_btn = page.locator("text=/grilla/i").first
        if grilla_btn.is_visible():
            grilla_btn.click()
            page.wait_for_timeout(2000)
    except Exception as e:
        print("Aviso al buscar sección Grilla:", e)

    # 2. Seleccionar la opción de 'Argentina'
    try:
        arg_btn = page.locator("text=/argentina/i").first
        if arg_btn.is_visible():
            arg_btn.click()
            page.wait_for_timeout(2000)
    except Exception as e:
        print("Aviso al seleccionar Argentina:", e)

    # 3. Recorrer los días disponibles
    # Buscamos botones o solapas de días
    pestañas_dias = page.query_selector_all("button, a, [role='tab']")
    
    # Filtrar solo pestañas correspondientes a días o fechas
    dias_validos = []
    for elem in pestañas_dias:
        txt = elem.inner_text().strip()
        if any(d.lower() in txt.lower() for d in ["lunes", "martes", "miércoles", "miercoles", "jueves", "viernes", "sábado", "sabado", "domingo", "hoy"]):
            dias_validos.append(elem)

    if not dias_validos:
        dias_validos = [None]

    tz_local = zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")
    dia_base_idx = datetime.now(tz_local).weekday()

    programas_todos = []

    for idx, btn_dia in enumerate(dias_validos):
        dia_efectivo_base = dias_mapa[(dia_base_idx + idx) % 7]

        if btn_dia:
            try:
                btn_dia.click()
                page.wait_for_timeout(1500)
            except Exception:
                pass

        # Scroll suave para forzar la carga de la grilla del día
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)

        html_content = page.content()
        soup = BeautifulSoup(html_content, "html.parser")

        # Buscar contenedores de ítems de programación
        bloques = soup.find_all(["article", "tr", "li", "div"], class_=re.compile(r'item|card|program|schedule|show|event', re.I))

        programas_dia = []
        paso_medianoche = False

        for b in bloques:
            texto = b.get_text(" ", strip=True)
            
            # Buscar formato horario HH:MM
            hora_match = re.search(r'\b\d{1,2}:\d{2}\b', texto)
            if not hora_match:
                continue

            hora_ini = hora_match.group(0)
            if len(hora_ini) == 4:
                hora_ini = "0" + hora_ini

            # Transición tras la medianoche
            if len(programas_dia) > 0:
                hora_prev = programas_dia[-1]["inicio"]
                if hora_prev >= "20:00" and hora_ini < "06:00":
                    paso_medianoche = True

            dia_efectivo = dias_mapa[(dias_mapa.index(dia_efectivo_base) + 1) % 7] if paso_medianoche else dia_efectivo_base

            # Extraer Título y Descripción
            titulo_tag = b.find(["h2", "h3", "h4", "h5", "strong", "b", "span"], class_=re.compile(r'title|nombre|programa', re.I))
            if titulo_tag:
                titulo = titulo_tag.get_text(strip=True)
                desc = texto.replace(titulo, "", 1)
            else:
                texto_limpio = re.sub(r'^\d{1,2}:\d{2}\s*', '', texto)
                partes = texto_limpio.split("—", 1) if "—" in texto_limpio else [texto_limpio[:30], texto_limpio]
                titulo = partes[0].strip()
                desc = partes[1].strip() if len(partes) > 1 else texto_limpio.strip()

            titulo = re.sub(r'^\d{1,2}:\d{2}\s*', '', titulo).strip()
            desc = re.sub(r'\b\d{1,2}:\d{2}\b', '', desc).strip()

            # Evitar duplicados inmediatos
            if programas_dia and programas_dia[-1]["inicio"] == hora_ini and programas_dia[-1]["titulo"] == titulo:
                continue

            programas_dia.append({
                "dia": dia_efectivo,
                "inicio": hora_ini,
                "titulo": titulo if titulo else "Programa",
                "descripcion": desc
            })

        programas_todos.extend(programas_dia)

    browser.close()

# 3. Asignación de Horario de Fin
for i in range(len(programas_todos)):
    p_curr = programas_todos[i]
    if i < len(programas_todos) - 1:
        fin = programas_todos[i+1]["inicio"]
    else:
        fin = programas_todos[0]["inicio"]

    fila = [p_curr["dia"], p_curr["inicio"], fin, p_curr["titulo"], p_curr["descripcion"]]
    if fila not in filas_epg:
        filas_epg.append(fila)

# 4. Volcado a Google Sheets en la pestaña CNCITY
sheet.clear()
sheet.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se actualizaron {len(filas_epg)-1} registros para CN City.")
