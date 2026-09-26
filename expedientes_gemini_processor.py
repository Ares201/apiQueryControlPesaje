import io
import os
import re
import zipfile
import concurrent.futures
from google import genai
from google.genai import types

# Inicializar cliente de Google Gen AI (Lee la variable GEMINI_API_KEY)
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def extraer_datos_con_gemini(contenido_bytes: bytes, mime_type: str) -> str:
    """Envía la imagen o PDF directamente a Gemini para extraer FECHA-ORDEN-CLIENTE."""
    prompt = """
    Analiza esta imagen/documento de control de ingreso o expediente.
    Extrae la siguiente información:
    1. FECHA en formato YYYY-MM-DD. Si no hay fecha, pon 'SINFCHA'.
    2. ORDEN o NÚMERO DE ORDEN (ejemplo: PV-2621425, ORD-1234, etc.).
    3. CLIENTE (nombre corto de la primera palabra relevante del cliente, omitiendo 'SAC', 'PERU', etc.).

    Responde ÚNICAMENTE en este formato exacto de una sola línea:
    FECHA-ORDEN-CLIENTE

    Ejemplo de respuesta válida: 2026-05-18-PV-2621425-MAVER
    Si falta la orden, responde: OTRO
    """

    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=[
                types.Part.from_bytes(data=contenido_bytes, mime_type=mime_type),
                prompt
            ]
        )
        
        resultado = response.text.strip().replace("\n", "")
        resultado_limpio = re.sub(r'[^A-Za-z0-9_-]', '', resultado)
        return resultado_limpio if resultado_limpio else "OTRO"

    except Exception as e:
        print(f"Error al procesar con Gemini: {e}")
        return "OTRO"


def procesar_un_archivo_gemini(args) -> tuple[str, bytes]:
    """Procesa un solo archivo en paralelo."""
    filename, pdf_or_img_bytes, mime_type = args
    
    nombre_extraido = extraer_datos_con_gemini(pdf_or_img_bytes, mime_type)
    ext = ".pdf" if "pdf" in mime_type else ".png"
    
    if nombre_extraido != "OTRO":
        nuevo_nombre = f"{nombre_extraido}{ext}"
    else:
        nuevo_nombre = f"otro_{filename}"
        
    return nuevo_nombre, pdf_or_img_bytes


def procesar_expedientes_gemini_masivo(archivos_subidos: list) -> tuple[dict, bytes]:
    """Procesa hasta 50 o más archivos en paralelo y genera el ZIP."""
    lista_tareas = []
    
    for file_obj in archivos_subidos:
        contenido = file_obj.get("bytes")
        filename = file_obj.get("filename", "expediente.pdf")
        mime_type = "application/pdf" if filename.lower().endswith(".pdf") else "image/png"
        lista_tareas.append((filename, contenido, mime_type))

    zip_buffer_salida = io.BytesIO()
    nombres_existentes = set()
    renombrados = 0

    # Ejecutar hasta 5 lecturas al mismo tiempo
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        resultados = list(executor.map(procesar_un_archivo_gemini, lista_tareas))

    with zipfile.ZipFile(zip_buffer_salida, "w", zipfile.ZIP_DEFLATED) as zip_salida:
        for nuevo_nombre, bytes_archivo in resultados:
            base, ext = os.path.splitext(nuevo_nombre)
            contador = 1
            nombre_final = nuevo_nombre
            
            while nombre_final in nombres_existentes:
                nombre_final = f"{base}_{contador}{ext}"
                contador += 1
                
            nombres_existentes.add(nombre_final)
            zip_salida.writestr(nombre_final, bytes_archivo)
            renombrados += 1

    zip_buffer_salida.seek(0)
    return {"success": True, "renombrados": renombrados}, zip_buffer_salida.getvalue()