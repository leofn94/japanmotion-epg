import os
import json
import re
from datetime import datetime
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

def obtener_nombre_dia_limpio(texto, indice_fallback):
    txt = texto.lower()
    for d in ["lunes", "martes", "miércoles", "miercoles", "jueves", "viernes", "sábado", "sabado", "domingo"]:
        if d in txt:
            if "mier" in d: return "Miércoles"
            if "sab" in d: return "Sábado"
            return d.capitalize()
    return dias_mapa[(datetime.now().weekday() + indice_fallback) % 7]

def siguiente_dia(dia_actual):
    if dia_actual in dias_mapa:
        idx = (dias_mapa.index(dia_actual) + 1) % 7
        return dias_mapa[idx]
    return dia_actual

def extraer_programa_y_descripcion(texto_raw):
    # Limpiar textos del sistema / botones
    texto = re.sub(r'(Agendar|Google Calendar|Descargar|\.ics|18\+|13\+|TODOS)', '', texto_raw, flags=re.I).strip()
    
    # Separación por guión si existe (ej. "Steamboy — Ambientada en...")
    if "—" in texto:
        partes = texto.split("—", 1)
        return partes[0].strip(), partes[1].strip()
    
    # Separación si existe indicador de episodio
    match_ep = re.search(r'^(.*?(?:Ep\.|Episode|Cap\.|Capítulo)\s*\d+)(.*)$', texto, re.I)
    if match_ep:
        return match_ep.group(1).strip(), match_ep.group(2).strip()
    
    # Separación por patrón de primera frase / título
    partes = re.split(r'(?<=[a-z0-9])\s+(?=[A-Z0-9])', texto, maxsplit=1)
    if len(partes) == 2:
        return partes[0].strip(), partes[1].strip()
        
    return texto[:35].strip(), texto.strip()

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
    
    # Pausa de hidratación explícita para evitar TimeoutError
    page.wait_for_timeout(5000)

    # Buscar pestañas de días
    pestañas = page.query_selector_all("button, [role='tab'], .schedule-days a, .nav-tabs a")
    pestañas_validas = [btn for btn in pestañas if btn.inner_text().strip()]

    if not pestañas_validas:
        pestañas_validas = [None]

    for idx, btn in enumerate(pestañas_validas):
        if btn:
            texto_btn = btn.inner_text().strip()
            dia_base = obtener_nombre_dia_limpio(texto_btn, idx)
            try:
                btn.click()
                page.wait_for_timeout(1500)
            except Exception:
                pass
        else:
            dia_base = dias_mapa[datetime.now().weekday()]

        html_content = page.content()
        soup = BeautifulSoup(html_content, "html.parser")
        
        articulos = soup.find_all("article")
        if not articulos:
            articulos = soup.find_all("div", class_=re.compile(r'schedule|program|card|item', re.I))

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

            # Transición de día pasadas las 00:00
            if len(programas_dia) > 0:
                hora_prev = programas_dia[-1]["inicio"]
                if hora_prev >= "23:00" and hora_ini < "06:00":
                    paso_medianoche = True

            dia_efectivo = siguiente_dia(dia_base) if paso_medianoche else dia_base

            # Extraer Título/Programa vs Descripción
            titulo_tag = art.find(["h2", "h3", "h4", "h5", "strong", "b"])
            if titulo_tag:
                titulo = titulo_tag.get_text(strip=True)
                titulo = re.sub(r'^\d{1,2}:\d{2}\s*', '', titulo).strip()
                desc = texto_art.replace(titulo, "", 1)
                desc = re.sub(r'\b\d{1,2}:\d{2}\b', '', desc)
                desc = re.sub(r'(Agendar|Google Calendar|Descargar|\.ics|18\+|13\+|TODOS)', '', desc, flags=re.I).strip()
            else:
                texto_sin_hora = re.sub(r'^\d{1,2}:\d{2}\s*', '', texto_art)
                titulo, desc = extraer_programa_y_descripcion(texto_sin_hora)

            programas_dia.append({
                "dia": dia_efectivo,
                "inicio": hora_ini,
                "titulo": titulo if titulo else "Programa",
                "descripcion": desc
            })

        # Asignar Horario de Fin
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
print(f"¡Éxito! Se actualizaron {len(filas_epg)-1} registros correctamente.")
