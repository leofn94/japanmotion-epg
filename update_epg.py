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

dias_semana = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

def obtener_nombre_dia_limpio(texto_pestana):
    txt = texto_pestana.lower()
    for d in dias_semana:
        if d in txt:
            return d.capitalize()
    
    # Si dice "Hoy" o no detecta el día exacto, tomamos el día actual del sistema
    d_num = datetime.now().weekday()
    return dias_semana[d_num].capitalize()

def siguiente_dia(dia_actual_nombre):
    dia_clean = dia_actual_nombre.lower().replace("miércoles", "miercoles")
    mapa_dias = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    mapa_dias_out = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    
    if dia_clean in mapa_dias:
        idx = (mapa_dias.index(dia_clean) + 1) % 7
        return mapa_dias_out[idx]
    return dia_actual_nombre

def extraer_titulo_y_descripcion(texto_bruto):
    # Limpiar textos basura de la web
    texto_limpio = re.sub(r'(Agendar|Google Calendar|Descargar|\.ics|18\+|13\+|TODOS|\b\d{1,2}:\d{2}\b)', '', texto_bruto, flags=re.I).strip()
    
    # Caso 1: Estructura "Título Ep. XX — Sinopsis"
    if "—" in texto_limpio:
        partes = texto_limpio.split("—", 1)
        return partes[0].strip(), partes[1].strip()
    
    # Caso 2: Estructura "Título Ep. XX Sinopsis"
    match_ep = re.search(r'^(.*?Ep\.\s*\d+)(.*)$', texto_limpio, re.I)
    if match_ep:
        return match_ep.group(1).strip(), match_ep.group(2).strip()

    # Caso 3: Tomar las primeras palabras hasta la primera oración o frase larga
    partes_oracion = re.split(r'(?<=[a-z0-9])\s+(?=[A-Z0-9])', texto_limpio)
    if len(partes_oracion) > 1:
        # El título suele ser el primer bloque corto
        titulo = partes_oracion[0].strip()
        descripcion = texto_limpio[len(titulo):].strip()
        return titulo, descripcion

    return texto_limpio[:30].strip(), texto_limpio.strip()

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
    
    try:
        page.wait_for_selector("article, [class*='schedule']", timeout=20000)
    except Exception:
        page.wait_for_timeout(4000)

    pestañas = page.query_selector_all("button, [role='tab'], .nav-link, .day-tab")
    pestañas_dias = [btn for btn in pestañas if any(d in btn.inner_text().lower() for d in dias_semana + ["hoy"])]
    
    if not pestañas_dias:
        pestañas_dias = [None]

    for btn in pestañas_dias:
        if btn:
            dia_base = obtener_nombre_dia_limpio(btn.inner_text())
            try:
                btn.click()
                page.wait_for_timeout(1500)
            except Exception:
                pass
        else:
            dia_base = obtener_nombre_dia_limpio("Hoy")

        html_content = page.content()
        soup = BeautifulSoup(html_content, "html.parser")
        articulos = soup.find_all("article")
        
        programas_dia = []
        paso_medianoche = False

        for art in articulos:
            texto_art = art.get_text(" ", strip=True)
            hora_match = re.search(r'\b\d{1,2}:\d{2}\b', texto_art)
            if not hora_match:
                continue
                
            hora_ini = hora_match.group(0)
            if len(hora_ini) == 4:
                hora_ini = "0" + hora_ini

            # Control de salto de día a partir de las 00:00
            if len(programas_dia) > 0:
                hora_prev = programas_dia[-1]["inicio"]
                if hora_prev >= "23:00" and hora_ini < "06:00":
                    paso_medianoche = True

            dia_efectivo = siguiente_dia(dia_base) if paso_medianoche else dia_base

            # Intentar leer primero del h3/h4 si existe
            titulo_tag = art.find(["h3", "h4", "h5", "strong"])
            if titulo_tag:
                titulo = titulo_tag.get_text(strip=True)
                desc = texto_art.replace(titulo, "", 1)
                desc = re.sub(r'(Agendar|Google Calendar|Descargar|\.ics|18\+|13\+|TODOS|\b\d{1,2}:\d{2}\b)', '', desc, flags=re.I).strip()
            else:
                titulo, desc = extraer_titulo_y_descripcion(texto_art)

            programas_dia.append({
                "dia": dia_efectivo,
                "inicio": hora_ini,
                "titulo": titulo,
                "descripcion": desc
            })

        # Calcular hora de Fin
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
