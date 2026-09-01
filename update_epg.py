import os
import json
import re
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials
from curl_cffi import requests

# 1. Conexión con Google Sheets
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

gcp_key = os.environ.get("GCP_SA_KEY")
if not gcp_key:
    raise ValueError("No se encontró la clave GCP_SA_KEY en las variables del entorno.")

credentials_info = json.loads(gcp_key)
credentials = Credentials.from_service_account_info(credentials_info, scopes=SCOPES)
client = gspread.authorize(credentials)

SPREADSHEET_ID = "japn epg"  # Recuerda mantener tu ID aquí
sheet = client.open_by_key(SPREADSHEET_ID).sheet1

# 2. Scraping pasando por proxy anti-bloqueo
url = "https://www.japanmotion.com/horarios"
proxy_url = f"https://api.allorigins.win/raw?url={url}"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

response = requests.get(proxy_url, headers=headers, impersonate="chrome120", timeout=30)
response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

# Encabezados exactos a tu plantilla de ejemplo
filas_epg = [
    ["Dia", "Inicio", "Fin", "Programa", "Descripcion"]
]

main = soup.find("main")
if main:
    dia_actual = "Hoy"
    
    # Recorremos todos los elementos dentro de <main> para mantener el orden cronológico
    for elemento in main.find_all(["h2", "h3", "article", "div"]):
        
        # 1. Detectar cambio de Día
        clases = elemento.get("class", [])
        texto_elem = elemento.get_text(strip=True)
        
        # Si encontramos una etiqueta de encabezado o fecha de día
        if any(c in clases for c in ["schedule-day", "day-header", "date-title"]) or elemento.name in ["h2", "h3"]:
            if any(d in texto_elem.lower() for d in ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo", "hoy"]):
                dia_actual = texto_elem
                continue

        # 2. Extracción de datos del Programa (<article>)
        if elemento.name == "article":
            # Extraer Hora si existe explícitamente, o dejar vacío si el sitio no muestra hora exacta
            hora_ini = ""
            hora_fin = ""
            hora_elem = elemento.find(class_=re.compile(r'time|hora', re.I))
            if hora_elem:
                partes_hora = hora_elem.get_text(strip=True).split("-")
                hora_ini = partes_hora[0] if len(partes_hora) > 0 else ""
                hora_fin = partes_hora[1] if len(partes_hora) > 1 else ""

            # Extraer Info del Bloque
            info_div = elemento.find("div", class_="schedule-info")
            if not info_div:
                info_div = elemento

            # Buscar posibles títulos dentro de tags fuertes o encabezados
            titulo_tag = info_div.find(["h3", "h4", "h5", "strong", "b", "a"])
            
            if titulo_tag:
                titulo = titulo_tag.get_text(strip=True)
                # La descripción es el texto restante quitando el título
                desc_texto = info_div.get_text(" ", strip=True).replace(titulo, "", 1).strip()
            else:
                # Si todo viene en texto plano, intentamos separar el primer punto/guión como título
                texto_completo = info_div.get_text(" ", strip=True)
                partes = re.split(r'(?<=\w)\s+—\s+|\n', texto_completo, maxsplit=1)
                titulo = partes[0] if len(partes) > 0 else "Programa"
                desc_texto = partes[1] if len(partes) > 1 else texto_completo

            # Limpiar descripciones residuales como links de agendar o clasificaciones
            desc_texto = re.sub(r'Agendar\s*Google Calendar\s*Descargar\s*\.ics', '', desc_texto).strip()

            # Evitar agregar duplicados continuos en el bucle
            nueva_fila = [dia_actual, hora_ini, hora_fin, titulo, desc_texto]
            if not filas_epg or filas_epg[-1] != nueva_fila:
                filas_epg.append(nueva_fila)

# 3. Borrar contenido anterior y volcar la grilla limpia
sheet.clear()
sheet.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se volcaron {len(filas_epg)-1} registros limpios a Google Sheets.")
