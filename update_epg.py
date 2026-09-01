import os
import json
import re
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

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        timezone_id="America/Argentina/Buenos_Aires",
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    
    # Navegar a la página
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    
    # Esperar explícitamente a que aparezca cualquier elemento de la programación
    try:
        page.wait_for_selector("article, .schedule-item, [class*='schedule']", timeout=20000)
    except Exception:
        page.wait_for_timeout(5000)

    # Intentar obtener las pestañas de días
    pestañas = page.query_selector_all("button, [role='tab'], .nav-link, .day-tab")
    
    # Filtramos solo aquellos botones que tengan texto de días/meses
    pestañas_dias = []
    for btn in pestañas:
        txt = btn.inner_text().strip().lower()
        if any(d in txt for d in ["hoy", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo", "ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]):
            pestañas_dias.append(btn)

    # Si no detecta pestañas con texto de día, procesamos la página tal cual
    if not pestañas_dias:
        pestañas_dias = [None]

    for btn in pestañas_dias:
        if btn:
            nombre_dia = btn.inner_text().strip().replace("\n", " ")
            try:
                btn.click()
                page.wait_for_timeout(1500)
            except Exception:
                pass
        else:
            nombre_dia = "Hoy"

        html_content = page.content()
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Buscar artículos o divs contenedores de programas
        articulos = soup.find_all("article")
        if not articulos:
            articulos = soup.find_all("div", class_=re.compile(r'schedule-item|program|card|event', re.I))

        programas_dia = []

        for art in articulos:
            # Extraer Hora de Inicio (formato HH:MM)
            texto_articulo = art.get_text(" ", strip=True)
            hora_match = re.search(r'\b\d{1,2}:\d{2}\b', texto_articulo)
            
            if not hora_match:
                continue
                
            hora_ini = hora_match.group(0)
            if len(hora_ini) == 4:
                hora_ini = "0" + hora_ini

            # Buscar Título
            titulo_elem = art.find(["h3", "h4", "h5", "strong", "b"])
            if titulo_elem:
                titulo = titulo_elem.get_text(strip=True)
            else:
                # Si no encuentra tag de encabezado, tomar la primera línea con texto largo
                lineas = [l.strip() for l in texto_articulo.split(" ") if l.strip()]
                titulo = lineas[0] if lineas else "Programa Sin Título"

            # Limpieza del título (quitar horarios o frases parásitas)
            titulo = re.sub(r'^\d{1,2}:\d{2}\s*', '', titulo)
            titulo = re.sub(r'(Google Calendar|Agendar|Descargar|\.ics)', '', titulo, flags=re.I).strip()

            # Descripción completa omitiendo el título y horas
            descripcion = texto_articulo
            if titulo and titulo in descripcion:
                descripcion = descripcion.replace(titulo, "", 1)
            
            descripcion = re.sub(r'\b\d{1,2}:\d{2}\b', '', descripcion)
            descripcion = re.sub(r'(Agendar|Google Calendar|Descargar|\.ics|18\+|13\+|TODOS)', '', descripcion, flags=re.I).strip()

            programas_dia.append({
                "dia": nombre_dia,
                "inicio": hora_ini,
                "titulo": titulo if titulo else "Programa",
                "descripcion": descripcion
            })

        # Autocompletar Horario de Fin (Horario de inicio del siguiente programa)
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

# 3. Actualizar la planilla de Google Sheets
sheet.clear()
sheet.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se actualizaron {len(filas_epg)-1} registros correctamente en Google Sheets.")
