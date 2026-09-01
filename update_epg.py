import os
import json
import re
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials
from curl_cffi import requests

# 1. Conexión con Google Sheets mediante las credenciales de GitHub Secrets
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

gcp_key = os.environ.get("GCP_SA_KEY")
if not gcp_key:
    raise ValueError("No se encontró la clave GCP_SA_KEY en los Secrets del repositorio.")

credentials_info = json.loads(gcp_key)
credentials = Credentials.from_service_account_info(credentials_info, scopes=SCOPES)
client = gspread.authorize(credentials)

# ID de tu planilla de Google Sheets
SPREADSHEET_ID = "1JKs0R5aFs4uWMBFDAuVtf2-hDDYd87ZkibTqFV600Rs"
sheet = client.open_by_key(SPREADSHEET_ID).sheet1

# 2. Scraping pasando por proxy reflector para evitar el bloqueo 403 por IP
url = "https://www.japanmotion.com/horarios"
proxy_url = f"https://api.allorigins.win/raw?url={url}"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

response = requests.get(proxy_url, headers=headers, impersonate="chrome120", timeout=30)
response.raise_for_status()

# Asegurar codificación utf-8 para tildes y caracteres especiales
response.encoding = 'utf-8'
soup = BeautifulSoup(response.text, "html.parser")

# Encabezados estructurados exactamente como en tu planilla de ejemplo
filas_epg = [
    ["Dia", "Inicio", "Fin", "Programa", "Descripcion"]
]

main = soup.find("main")
if main:
    dia_actual = "Hoy"
    
    # Recorremos los elementos principales manteniendo el orden cronológico
    for elemento in main.find_all(["h2", "h3", "article", "div"]):
        
        clases = elemento.get("class", [])
        texto_elem = elemento.get_text(strip=True)
        
        # Detectar el encabezado o nombre del día
        if any(c in clases for c in ["schedule-day", "day-header", "date-title"]) or elemento.name in ["h2", "h3"]:
            if any(d in texto_elem.lower() for d in ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo", "hoy", "agosto", "septiembre"]):
                dia_actual = texto_elem
                continue

        # Procesar los programas (<article>)
        if elemento.name == "article":
            hora_ini = ""
            hora_fin = ""
            
            # Extraer horario si el bloque contiene la etiqueta de hora
            hora_elem = elemento.find(class_=re.compile(r'time|hora', re.I))
            if hora_elem:
                partes_hora = hora_elem.get_text(strip=True).split("-")
                hora_ini = partes_hora[0].strip() if len(partes_hora) > 0 else ""
                hora_fin = partes_hora[1].strip() if len(partes_hora) > 1 else ""

            # Extraer contenedor de información del programa
            info_div = elemento.find("div", class_="schedule-info")
            if not info_div:
                info_div = elemento

            # Buscar etiquetas de títulos
            titulo_tag = info_div.find(["h3", "h4", "h5", "strong", "b", "a"])
            
            if titulo_tag:
                titulo = titulo_tag.get_text(strip=True)
                desc_texto = info_div.get_text(" ", strip=True).replace(titulo, "", 1).strip()
            else:
                texto_completo = info_div.get_text(" ", strip=True)
                # Separar el título de la sinopsis/episodio usando guiones largos o saltos
                partes = re.split(r'(?<=\w)\s+—\s+|\n', texto_completo, maxsplit=1)
                titulo = partes[0].strip() if len(partes) > 0 else "Programa"
                desc_texto = partes[1].strip() if len(partes) > 1 else texto_completo

            # Limpiar elementos irrelevantes de las descripciones
            desc_texto = re.sub(r'Agendar\s*Google Calendar\s*Descargar\s*\.ics', '', desc_texto).strip()

            nueva_fila = [dia_actual, hora_ini, hora_fin, titulo, desc_texto]
            
            # Evitar repeticiones continuas en la matriz de datos
            if not filas_epg or filas_epg[-1] != nueva_fila:
                filas_epg.append(nueva_fila)

# 3. Limpiar contenido anterior de la planilla y escribir los datos limpios
sheet.clear()
sheet.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se actualizaron {len(filas_epg)-1} filas correctamente en Google Sheets.")
