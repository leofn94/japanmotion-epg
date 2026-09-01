import os
import json
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

# COLOCA AQUÍ EL NOMBRE EXACTO DE TU PLANILLA EN GOOGLE DRIVE
NOMBRE_PLANILLA = "japn epg" 
sheet = client.open(NOMBRE_PLANILLA).sheet1

# 2. Scraping usando imitación de TLS/Browser de Chrome 120
url = "https://www.japanmotion.com/horarios"

# impersonate="chrome120" engaña a las protecciones simulando un navegador real a nivel de red
response = requests.get(url, impersonate="chrome120", timeout=30)
response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

filas_epg = [
    ["Programa", "Informacion", "Detalles", "Clasificacion"] # Encabezados de la planilla
]

articulos = soup.find_all("article")
for art in articulos:
    thumb = art.find("div", class_="schedule-thumb")
    info = art.find("div", class_="schedule-info")
    actions = art.find("div", class_="schedule-actions")

    texto_info = info.get_text(strip=True, separator=" ") if info else ""
    texto_thumb = thumb.get_text(strip=True, separator=" ") if thumb else ""
    texto_actions = actions.get_text(strip=True, separator=" ") if actions else ""

    titulo_elem = info.find(["h2", "h3", "h4", "strong"]) if info else None
    titulo = titulo_elem.get_text(strip=True) if titulo_elem else "Sin Título"

    filas_epg.append([titulo, texto_info, texto_thumb, texto_actions])

# 3. Borrar contenido anterior y escribir nuevos datos
sheet.clear()
sheet.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se actualizaron {len(articulos)} programas en Google Sheets.")
