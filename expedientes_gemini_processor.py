import io
import os
import re
import zipfile
import concurrent.futures
from google import genai
from google.genai import types
from pypdf import PdfReader
from PIL import Image

# Inicializar cliente de Google Gen AI (Lee GEMINI_API_KEY)
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def extraer_imagen_de_pdf_escaneado(pdf_bytes: bytes) -> bytes:
    """Extrae la imagen principal incrustada por la impresora en el PDF escaneado."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if not reader.pages:
            return None

        primera_pagina = reader.pages[0]
        images = primera_pagina.images

        if images:
            # Tomar la primera imagen que colocó el escáner
            img_obj = images[0]
            pil_img = Image.open(io.BytesIO(img_obj.data))

            # Convertir a RGB si viene en CMYK o escala de grises
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")

            buffer = io.BytesIO()
            pil_img.save(buffer, format="JPEG", quality=85)
            return buffer.getvalue()
    except Exception as e:
        print(f"[ERROR EXTRACCIÓN IMAGEN PDF]: {e}")

    return None


def extraer_datos_con_gemini(contenido_bytes: bytes, filename: str) -> str:
    """Extrae imagen del PDF escaneado y consulta a Gemini."""

    bytes_a_enviar = contenido_bytes
    mime_type = "application/pdf"

    if filename.lower().endswith('.pdf'):
        img_bytes = extraer_imagen_de_pdf_escaneado(contenido_bytes)
        if img_bytes:
            bytes_a_enviar = img_bytes
            mime_type = "image/jpeg"

    prompt = """
    Analiza esta hoja de control/pesaje/expediente escaneado.
    
    Busca los siguientes 3 campos:
    1. FECHA: Formato YYYY-MM-DD
    2. CLIENTE: Nombre de la empresa (Ejemplo: SECHE, KANAY, MAVER, etc. Si no es claro o no está, escribe OTRO).
    3. ORDEN/TICKET: Número de orden o ticket (Ejemplo: 1581_001, 1582_001, PV-2621425).

    Responde ÚNICAMENTE con los datos unidos por guion bajo (_).
    
    FORMATO OBLIGATORIO:
    YYYY-MM-DD_CLIENTE_ORDEN

    Ejemplos válidos:
    2026-09-24_OTRO_1581_001
    2026-09-24_SECHE_1582_001

    No agregues introducciones, markdown, ni texto adicional.
    """

    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=[
                types.Part.from_bytes(data=bytes_a_enviar, mime_type=mime_type),
                prompt
            ]
        )

        texto_raw = response.text.strip() if response and response.text else ""
        print(f"[RESPUESTA GEMINI RAW]: {texto_raw}")

        # Tomamos la primera línea limpia
        linea = texto_raw.split('\n')[0].strip()
        # Permitimos letras, números, guiones y guion bajo
        resultado_limpio = re.sub(r'[^A-Za-z0-9_-]', '', linea)

        # Si tiene al menos una fecha o formato válido (ej. longitud mayor a 10)
        if len(resultado_limpio) >= 10:
            # Reemplazar cualquier residuo de DESCONOCIDO por OTRO
            resultado_limpio = resultado_limpio.replace("DESCONOCIDO", "OTRO")
            return resultado_limpio

    except Exception as e:
        print(f"[ERROR GEMINI]: {e}")

    return None
def procesar_un_archivo_gemini(args) -> tuple[str, bytes]:
    filename, pdf_or_img_bytes = args

    nombre_extraido = extraer_datos_con_gemini(pdf_or_img_bytes, filename)
    ext = os.path.splitext(filename)[1].lower() or ".pdf"

    if nombre_extraido:
        nuevo_nombre = f"{nombre_extraido}{ext}"
    else:
        # Mantiene el nombre si no logra extraer los 3 campos completos
        nombre_base = os.path.splitext(filename)[0]
        nuevo_nombre = f"sin_extraer_{nombre_base}{ext}"

    return nuevo_nombre, pdf_or_img_bytes


def procesar_expedientes_gemini_masivo(archivos_subidos: list) -> tuple[dict, bytes]:
    lista_tareas = [(file_obj["filename"], file_obj["bytes"]) for file_obj in archivos_subidos]

    zip_buffer_salida = io.BytesIO()
    nombres_existentes = set()
    renombrados = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
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