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

# Función para restar 3 horas a los horarios traídos por el servidor en la nube
def ajustar_zona_horaria(hora_str, horas_restar=3):
    try:
        dt = datetime.strptime(hora_str.strip(), "%H:%M")
        dt_ajustada = dt - timedelta(hours=horas_restar)
        return dt_ajustada.strftime("%H:%M")
    except Exception:
        return hora_str

filas_epg = [
    ["Dia", "Inicio", "Fin", "Programa", "Descripcion"]
]

# 2. Navegación e interacción por pestañas con Playwright
url = "https://www.japanmotion.com/horarios"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    # Definimos la zona horaria del navegador simulado
    context = browser.new_context(
        timezone_id="America/Argentina/Buenos_Aires",
        viewport={"width": 1280, "height": 800}
    )
    page = context.new_page()
    page.goto(url, wait_until="networkidle", timeout=60000)

    # Buscamos los botones/pestañas de los días en la parte superior
    pestañas = page.query_selector_all(".schedule-days button, .nav-tabs a, [role='tab']")
    
    # Si no encuentra botones específicos, extraemos la vista general
    if not pestañas:
        pestañas = [None]

    for index in range(len(pestañas)):
        if pestañas[index]:
            nombre_dia = pestañas[index].inner_text().strip().replace("\n", " ")
            pestañas[index].click()
            page.wait_for_timeout(1000) # Esperar a que renderice la pestaña
        else:
            nombre_dia = "Hoy"

        html_content = page.content()
        soup = BeautifulSoup(html_content, "html.parser")
        
        articulos = soup.find_all("article")
        programas_dia = []

        for art in articulos:
            # Extraer Hora de Inicio limpia
            hora_elem = art.find(class_=re.compile(r'time|hora', re.I))
            hora_ini_raw = hora_elem.get_text(strip=True) if hora_elem else ""
            
            # Buscar el patrón HH:MM
            hora_match = re.search(r'\b\d{1,2}:\d{2}\b', hora_ini_raw)
            if not hora_match:
                continue
                
            hora_ini = hora_match.group(0)
            if len(hora_ini) == 4: # Formato 2:34 -> 02:34
                hora_ini = "0" + hora_ini

            # Extraer Título y Descripción limpios
            info_div = art.find("div", class_="schedule-info")
            if not info_div:
                continue

            # El título está en el h3/h4/strong
            titulo_elem = info_div.find(["h3", "h4", "h5", "strong"])
            if titulo_elem:
                titulo = titulo_elem.get_text(strip=True)
            else:
                titulo = "Programa Sin Título"

            # La descripción es el texto restante dentro del div descartando el título
            texto_completo = info_div.get_text(" ", strip=True)
            descripcion = texto_completo.replace(titulo, "", 1).strip()
            
            # Limpiar textos de botones residuales de la descripción
            descripcion = re.sub(r'(Agendar|Google Calendar|Descargar|\.ics|18\+|13\+|TODOS)', '', descripcion).strip()

            programas_dia.append({
                "dia": nombre_dia,
                "inicio": hora_ini,
                "titulo": titulo,
                "descripcion": descripcion
            })

        # Autocompletar Horario de Fin (Inicio del siguiente programa)
        for i in range(len(programas_dia)):
            item = programas_dia[i]
            if i < len(programas_dia) - 1:
                item["fin"] = programas_dia[i+1]["inicio"]
            else:
                # El último programa del día termina cuando empieza el primero
                item["fin"] = programas_dia[0]["inicio"] if len(programas_dia) > 1 else ""

            fila = [item["dia"], item["inicio"], item["fin"], item["titulo"], item["descripcion"]]
            
            # Evitar filas duplicadas
            if fila not in filas_epg:
                filas_epg.append(fila)

    browser.close()

# 3. Volcar datos ordenados en Google Sheets
sheet.clear()
sheet.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se procesaron {len(filas_epg)-1} registros limpios con horarios y días correspondientes.")
