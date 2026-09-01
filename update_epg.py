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

filas_epg = [
    ["Dia", "Inicio", "Fin", "Programa", "Descripcion"]
]

url = "https://www.japanmotion.com/horarios"

# 2. Navegación optimizada con Playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        timezone_id="America/Argentina/Buenos_Aires",
        viewport={"width": 1280, "height": 800}
    )
    page = context.new_page()
    
    # Cambiamos a domcontentloaded para evitar timeouts por scripts de fondo
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000) # Espera fija de 3 segundos para que renderice la grilla

    # Buscamos los botones de los días en la pestaña superior
    pestañas = page.query_selector_all(".schedule-days button, .nav-tabs a, [role='tab']")
    
    # Si no se detectaron botones explícitos, procesamos la vista general
    if not pestañas:
        pestañas = [None]

    for index in range(len(pestañas)):
        if pestañas[index]:
            nombre_dia = pestañas[index].inner_text().strip().replace("\n", " ")
            try:
                pestañas[index].click()
                page.wait_for_timeout(1500)
            except Exception:
                pass
        else:
            nombre_dia = "Hoy"

        html_content = page.content()
        soup = BeautifulSoup(html_content, "html.parser")
        
        articulos = soup.find_all("article")
        programas_dia = []

        for art in articulos:
            # Extraer Hora de Inicio
            hora_elem = art.find(class_=re.compile(r'time|hora', re.I))
            hora_ini_raw = hora_elem.get_text(strip=True) if hora_elem else ""
            
            hora_match = re.search(r'\b\d{1,2}:\d{2}\b', hora_ini_raw)
            if not hora_match:
                continue
                
            hora_ini = hora_match.group(0)
            if len(hora_ini) == 4:
                hora_ini = "0" + hora_ini

            # Extraer Título y Descripción
            info_div = art.find("div", class_="schedule-info")
            if not info_div:
                continue

            titulo_elem = info_div.find(["h3", "h4", "h5", "strong"])
            if titulo_elem:
                titulo = titulo_elem.get_text(strip=True)
            else:
                titulo = "Programa Sin Título"

            texto_completo = info_div.get_text(" ", strip=True)
            descripcion = texto_completo.replace(titulo, "", 1).strip()
            
            # Limpiar residuales
            descripcion = re.sub(r'(Agendar|Google Calendar|Descargar|\.ics|18\+|13\+|TODOS)', '', descripcion).strip()

            programas_dia.append({
                "dia": nombre_dia,
                "inicio": hora_ini,
                "titulo": titulo,
                "descripcion": descripcion
            })

        # Autocompletar Horario de Fin con el inicio del programa siguiente
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

# 3. Guardar en Google Sheets
sheet.clear()
sheet.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se actualizaron {len(filas_epg)-1} registros correctamente en Google Sheets.")
