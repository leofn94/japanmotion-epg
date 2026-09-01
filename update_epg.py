import os
import json
import re
from datetime import datetime, timedelta
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
sheet = client.open_by_key(SPREADSHEET_ID).sheet1

dias_mapa = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

def obtener_dia_semana_actual():
    d_num = datetime.now().weekday()
    return dias_mapa[d_num]

def siguiente_dia(dia_actual_nombre):
    dia_clean = dia_actual_nombre.strip()
    if dia_clean in dias_mapa:
        idx = (dias_mapa.index(dia_clean) + 1) % 7
        return dias_mapa[idx]
    return dia_actual_nombre

filas_epg = [
    ["Dia", "Inicio", "Fin", "Programa", "Descripcion"]
]

url = "https://www.japanmotion.com/horarios"

# 2. Extracción con Playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        timezone_id="America/Argentina/Buenos_Aires",
        viewport={"width": 1280, "height": 800}
    )
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    
    # Esperamos a que cargue la grilla
    page.wait_for_selector("article", timeout=20000)

    # Capturar los botones de las pestañas superiores
    pestañas = page.query_selector_all("button, [role='tab'], .nav-tabs a, div[class*='tab']")
    
    # Filtrar solo botones válidos que contengan texto de fechas o días
    pestañas_validas = []
    for btn in pestañas:
        txt = btn.inner_text().strip()
        if txt and len(txt) < 30 and ("agosto" in txt.lower() or "septiembre" in txt.lower() or "hoy" in txt.lower() or any(d.lower() in txt.lower() for d in dias_mapa)):
            pestañas_validas.append(btn)

    if not pestañas_validas:
        pestañas_validas = [None]

    dia_base_index = datetime.now().weekday()

    for idx, btn in enumerate(pestañas_validas):
        # Determinar el nombre del día
        dia_efectivo_base = dias_mapa[(dia_base_index + idx) % 7]

        if btn:
            try:
                btn.click()
                page.wait_for_timeout(1000)
            except Exception:
                pass

        html_content = page.content()
        soup = BeautifulSoup(html_content, "html.parser")
        articulos = soup.find_all("article")

        programas_dia = []
        paso_medianoche = False

        for art in articulos:
            # Extraer Hora de Inicio
            texto_art = art.get_text(" ", strip=True)
            hora_match = re.search(r'\b\d{1,2}:\d{2}\b', texto_art)
            if not hora_match:
                continue
                
            hora_ini = hora_match.group(0)
            if len(hora_ini) == 4:
                hora_ini = "0" + hora_ini

            # Control de paso a la medianoche (00:00)
            if len(programas_dia) > 0:
                hora_prev = programas_dia[-1]["inicio"]
                if hora_prev >= "23:00" and hora_ini < "06:00":
                    paso_medianoche = True

            dia_efectivo = siguiente_dia(dia_efectivo_base) if paso_medianoche else dia_efectivo_base

            # Extraer Título explícito (buscando etiquetas fuertes o encabezados)
            titulo_elem = art.find(["h2", "h3", "h4", "h5", "strong", "b"])
            if titulo_elem:
                titulo = titulo_elem.get_text(strip=True)
            else:
                # Si no hay etiqueta de título, extraemos hasta el primer punto o guión
                partes = re.split(r'—|\.', texto_art, maxsplit=1)
                titulo = partes[0].strip() if partes else "Programa"

            # Limpieza del Título
            titulo = re.sub(r'^\d{1,2}:\d{2}\s*', '', titulo)
            titulo = re.sub(r'(Google Calendar|Agendar|Descargar|\.ics|18\+|13\+|TODOS)', '', titulo, flags=re.I).strip()

            # Extraer Descripción limpia quitando el título y la hora
            descripcion = texto_art
            if titulo and titulo in descripcion:
                descripcion = descripcion.replace(titulo, "", 1)
            
            descripcion = re.sub(r'\b\d{1,2}:\d{2}\b', '', descripcion)
            descripcion = re.sub(r'(Agendar|Google Calendar|Descargar|\.ics|18\+|13\+|TODOS)', '', descripcion, flags=re.I).strip()

            programas_dia.append({
                "dia": dia_efectivo,
                "inicio": hora_ini,
                "titulo": titulo if titulo else "Programa",
                "descripcion": descripcion
            })

        # Autocompletar Horario de Fin
        for i in range(len(programas_dia)):
            item = programas_dia[i]
            if i < len(programas_dia) - 1:
                item["fin"] = programas_dia[i+1]["inicio"]
            else:
                item["fin"] = programas_dia[0]["inicio"] if len(programas_dia) > 1 else ""

            fila = [item["dia"], item["inicio"], item["fin"], item["titulo"], item["descripcion"]]
            if fila not in filas_epg:
                filas_epg.append(fila)

    browser.close()

# 3. Volcado limpio a Google Sheets
sheet.clear()
sheet.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se actualizaron {len(filas_epg)-1} registros limpios.")
