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
sheet = client.open(japn epg).sheet1

# 2. Scraping de Japan Motion con cabeceras anti-bloqueo
url = "https://www.japanmotion.com/horarios"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}

# Usamos una sesión para manejar correctamente la conexión
session = requests.Session()
response = session.get(url, headers=headers, timeout=15)
response.raise_for_status()

# Aseguramos la codificación correcta para caracteres en español
response.encoding = 'utf-8'

soup = BeautifulSoup(response.text, "html.parser")

filas_epg = [
    ["Programa", "Informacion", "Detalles", "Clasificacion"] # Encabezados para el Sheet
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

# 3. Borrar contenido anterior y volcar nuevos datos
sheet.clear()
sheet.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se actualizaron {len(articulos)} programas en Google Sheets.")
