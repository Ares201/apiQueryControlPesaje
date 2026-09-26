import io
import os
import re
import zipfile
import concurrent.futures
from google import genai
from google.genai import types
from pypdf import PdfReader
from PIL import Image

# Inicializar cliente de Google Gen AI
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def extraer_imagen_de_pdf_escaneado(pdf_bytes: bytes) -> bytes:
    """Extrae la imagen del PDF manteniendo la mayor resolución posible."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if not reader.pages:
            return None

        primera_pagina = reader.pages[0]
        
        # 1. Intentar extraer imagen incrustada
        if primera_pagina.images:
            img_obj = primera_pagina.images[0]
            pil_img = Image.open(io.BytesIO(img_obj.data))

            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")

            buffer = io.BytesIO()
            # Guardar con alta calidad para no perder nitidez en los textos pequeños
            pil_img.save(buffer, format="JPEG", quality=95)
            return buffer.getvalue()
    except Exception as e:
        print(f"[ERROR EXTRACCIÓN IMAGEN]: {e}")

    return None


def extraer_datos_con_gemini(contenido_bytes: bytes, filename: str) -> str:
    """Lee el documento de Control de Ingreso y extrae Fecha, Cliente y Order No."""

    bytes_a_enviar = contenido_bytes
    mime_type = "application/pdf"

    if filename.lower().endswith('.pdf'):
        img_bytes = extraer_imagen_de_pdf_escaneado(contenido_bytes)
        if img_bytes:
            bytes_a_enviar = img_bytes
            mime_type = "image/jpeg"

    # Prompt diseñado específicamente para las hojas de Control de Ingreso de Séché Group
    prompt = """
    Eres un asistente experto en lectura de documentos operativos de Séché Group / Control de Ingreso de Residuos.
    
    Analiza la imagen adjunta y extrae EXACTAMENTE los siguientes 3 campos ubicados en el encabezado superior:

    1. FECHA:
       - Búscala en el campo 'Fecha:' (ejemplo: 24/09/2026).
       - Conviértela SIEMPRE al formato YYYY-MM-DD (ejemplo: 2026-09-24).

    2. CLIENTE:
       - Búscalo en la línea 'Cliente:' (ejemplo: ANCRO S.R.L. o FAMESA EXPLOSIVOS S.A.C. o SECHE).
       - Extrae solo la primera palabra o el nombre comercial principal en MAYÚSCULAS (ejemplo: ANCRO, FAMESA, SECHE, KANAY).
       - Omita sufijos como 'S.R.L.', 'S.A.C.', 'S.A.'.
       - Si no se lee claramente, responde OTRO.

    3. ORDEN / TICKET:
       - Búscalo en 'Order No.' o en la esquina superior derecha bajo 'Page 1 of 1' (ejemplo: PV-2624522 o 1581_001).
       - Mantiene guiones e identificadores completos.

    REGLA DE SALIDA STRICTA:
    Responde ÚNICAMENTE una cadena formateada exactamente así:
    FECHA_CLIENTE_ORDEN

    Ejemplo para la imagen adjunta:
    2026-09-24_ANCRO_PV-2624522

    No incluyas explicaciones, ni etiquetas, ni saltos de línea adicionales.
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
        print(f"[RESPUESTA GEMINI RAW PARA {filename}]: {texto_raw}")

        # Limpieza básica
        linea = texto_raw.split('\n')[0].strip()
        resultado_limpio = re.sub(r'[^A-Za-z0-9_-]', '', linea)

        if len(resultado_limpio) >= 10:
            return resultado_limpio

    except Exception as e:
        print(f"[ERROR LLAMADA GEMINI]: {e}")

    return None


def procesar_un_archivo_gemini(args) -> tuple[str, bytes]:
    filename, pdf_or_img_bytes = args

    nombre_extraido = extraer_datos_con_gemini(pdf_or_img_bytes, filename)
    ext = os.path.splitext(filename)[1].lower() or ".pdf"

    if nombre_extraido:
        nuevo_nombre = f"{nombre_extraido}{ext}"
    else:
        nombre_base = os.path.splitext(filename)[0]
        nuevo_nombre = f"no_reconocido_{nombre_base}{ext}"

    return nuevo_nombre, pdf_or_img_bytes