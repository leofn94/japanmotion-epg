import os
import json
from datetime import datetime, timedelta
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# 1. Conexión con Google Sheets mediante Service Account
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

# --- CONFIGURACIÓN DE SHEETS ---
SHEET_ORIGEN_ID = "1GSqqTGAGtW32-n3XMFOaVs9bUEJSxgGfZe57yOqBS2o"  # Matriz origen en EST
SHEET_DESTINO_ID = "1JKs0R5aFs4uWMBFDAuVtf2-hDDYd87ZkibTqFV600Rs" # Tu planilla principal
NOMBRE_PESTANA = "BLAST"                                          # Pestaña objetivo

# Acceso a las hojas
sheet_origen = client.open_by_key(SHEET_ORIGEN_ID).sheet1
doc_destino = client.open_by_key(SHEET_DESTINO_ID)

try:
    sheet_destino = doc_destino.worksheet(NOMBRE_PESTANA)
except Exception:
    sheet_destino = doc_destino.add_worksheet(title=NOMBRE_PESTANA, rows=1000, cols=10)

# 2. Descargar todos los datos de la matriz origen
datos_matriz = sheet_origen.get_all_values()

if not datos_matriz:
    raise ValueError("No se encontraron datos en la hoja de origen.")

headers = datos_matriz[0]
df = pd.DataFrame(datos_matriz[1:], columns=headers)

# Mapeo de días de inglés a español
DIAS_MAPA = {
    "Monday": "Lunes",
    "Tuesday": "Martes",
    "Wednesday": "Miércoles",
    "Thursday": "Jueves",
    "Friday": "Viernes",
    "Saturday": "Sábado",
    "Sunday": "Domingo"
}

DIAS_ORDEN = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

programas_procesados = []

# 3. Procesar día por día desde la matriz
col_hora = headers[0]  # Primera columna ("Time in EST")

for col_dia in headers[1:]:
    dia_encontrado = None
    for k_eng, v_esp in DIAS_MAPA.items():
        if k_eng.lower() in col_dia.lower():
            dia_encontrado = v_esp
            break

    if not dia_encontrado:
        continue

    for idx, row in df.iterrows():
        hora_raw = str(row[col_hora]).strip()
        nombre_prog = str(row[col_dia]).strip()

        if not hora_raw or not nombre_prog or nombre_prog.lower() in ["nan", "none", ""]:
            continue

        # Convertir texto de hora EST a objeto datetime
        try:
            if "AM" in hora_raw.upper() or "PM" in hora_raw.upper():
                dt_est = datetime.strptime(hora_raw.upper(), "%I:%M %p")
            elif len(hora_raw.split(":")) == 3:
                dt_est = datetime.strptime(hora_raw, "%H:%M:%S")
            else:
                dt_est = datetime.strptime(hora_raw, "%H:%M")
        except Exception:
            continue

        # SUMA DE 1 HORA (EST -> ART)
        dt_art = dt_est + timedelta(hours=1)
        hora_art_str = dt_art.strftime("%H:%M")

        # Si al sumar 1 hora pasa de las 23:xx a las 00:xx, avanza al día siguiente
        if dt_est.hour == 23 and dt_art.hour == 0:
            idx_dia_sig = (DIAS_ORDEN.index(dia_encontrado) + 1) % 7
            dia_efectivo = DIAS_ORDEN[idx_dia_sig]
        else:
            dia_efectivo = dia_encontrado

        programas_procesados.append({
            "dia": dia_efectivo,
            "inicio": hora_art_str,
            "programa": nombre_prog
        })

# 4. Ordenar y calcular horas de fin
filas_epg = [
    ["Dia", "Inicio", "Fin", "Programa", "Descripcion"]
]

for dia_nombre in DIAS_ORDEN:
    progs_dia = [p for p in programas_procesados if p["dia"] == dia_nombre]
    
    # Ordenar por horario de inicio
    progs_dia.sort(key=lambda x: x["inicio"])

    for i in range(len(progs_dia)):
        p_curr = progs_dia[i]
        
        # Calcular hora de Fin
        if i < len(progs_dia) - 1:
            fin = progs_dia[i+1]["inicio"]
        else:
            fin = progs_dia[0]["inicio"]

        filas_epg.append([p_curr["dia"], p_curr["inicio"], fin, p_curr["programa"], ""])

# 5. Volcar en la pestaña 'BLAST'
sheet_destino.clear()
sheet_destino.update(range_name='A1', values=filas_epg)
print(f"¡Éxito! Se procesó la matriz y se cargaron {len(filas_epg)-1} registros formateados a hora de Argentina en la pestaña BLAST.")