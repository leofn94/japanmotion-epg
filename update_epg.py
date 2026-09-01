import os
import json
import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

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

# REEMPLAZA CON EL NOMBRE EXACTO DE TU PLANILLA EN GOOGLE DRIVE
NOMBRE_PLANILLA = "japn epg" 
sheet = client.open(NOMBRE_PLANILLA).sheet1

# 2. Scraping de Japan Motion
url = "https://www.japanmotion.com/horarios"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

response = requests.get(url, headers=headers)
response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

filas_epg = [
    ["Programa", "Informacion", "Detalles", "Clasificacion"] # Encabezados para el Sheet
]

articulos = soup.find_all("article")
for art in articulos:
    # Extraemos info basada en la estructura confirmada (<article>)
    thumb = art.find("div", class_="schedule-thumb")
    info = art.find("div", class_="schedule-info")
    actions = art.find("div", class_="schedule-actions")

    texto_info = info.get_text(strip=True, separator=" ") if info else ""
    texto_thumb = thumb.get_text(strip=True, separator=" ") if thumb else ""
    texto_actions = actions.get_text(strip=True, separator=" ") if actions else ""

    # Extraemos el título o encabezado si existe dentro de info
    titulo_elem = info.find(["h2", "h3", "h4", "strong"]) if info else None
    titulo = titulo_elem.get_text(strip=True) if titulo_elem else "Sin Título"

    filas_epg.append([titulo, texto_info, texto_thumb, texto_actions])

# 3. Borrar contenido anterior y volcar nuevos datos
sheet.clear()
sheet.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se actualizaron {len(articulos)} programas en Google Sheets.")