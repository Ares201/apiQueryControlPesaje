import io
import os
import re
import zipfile
import concurrent.futures
from google import genai
from google.genai import types
from pypdf import PdfReader
from PIL import Image

# Inicialización de cliente con API Key de Gemini
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def obtener_bytes_para_gemini(pdf_bytes: bytes) -> tuple[bytes, str]:
    """
    Intenta extraer la imagen rasterizada del PDF. 
    Si falla o el PDF no contiene imágenes legibles, devuelve el PDF original.
    """
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if reader.pages:
            primera_pagina = reader.pages[0]
            if len(primera_pagina.images) > 0:
                img_obj = primera_pagina.images[0]
                pil_img = Image.open(io.BytesIO(img_obj.data))

                if pil_img.mode != "RGB":
                    pil_img = pil_img.convert("RGB")

                buffer = io.BytesIO()
                pil_img.save(buffer, format="JPEG", quality=90)
                return buffer.getvalue(), "image/jpeg"
    except Exception as e:
        print(f"[AVISO EXTRACCIÓN IMAGEN]: No se pudo extraer imagen, se enviará el PDF directo. Detalle: {e}")

    # Respaldo: Enviar el archivo en formato PDF directo a Gemini
    return pdf_bytes, "application/pdf"


def extraer_datos_con_gemini(contenido_bytes: bytes, filename: str) -> str:
    """Envía el documento a Gemini 1.5 Flash para extraer Fecha, Cliente y Orden."""

    bytes_a_enviar, mime_type = obtener_bytes_para_gemini(contenido_bytes)

    prompt = """
    Analiza este documento de Control de Ingreso / Expediente de Residuos Peligrosos.
    
    Extrae exactamente 3 datos principales:
    1. FECHA: Ubicada en la sección de datos generales (ej. 24/09/2026). Conviértela a formato YYYY-MM-DD (ej. 2026-09-24).
    2. CLIENTE: Nombre principal del cliente/empresa (ej. ANCRO, FAMESA, KANAY, SECHE). Omite sufijos legales como S.R.L. o S.A.C. Si no es legible, responde OTRO.
    3. ORDEN: Número de orden o ticket ubicado en 'Order No.' o en la parte superior derecha (ej. PV-2624522 o 1581_001).

    REGLA DE SALIDA OBLIGATORIA:
    Responde ÚNICAMENTE los 3 campos separados por guion bajo (_). Sin textos explicativos ni saludos.

    Formato de salida esperado:
    YYYY-MM-DD_CLIENTE_ORDEN
    """

    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=[
                types.Part.from_bytes(data=bytes_a_enviar, mime_type=mime_type),
                prompt
            ]
        )

        if response and response.text:
            texto_raw = response.text.strip()
            print(f"[RESPUESTA GEMINI {filename}]: {texto_raw}")

            linea = texto_raw.split('\n')[0].strip()
            resultado_limpio = re.sub(r'[^A-Za-z0-9_-]', '', linea)

            if len(resultado_limpio) >= 8:
                return resultado_limpio

    except Exception as e:
        print(f"[ERROR GEMINI API]: {e}")

    return None


def procesar_un_archivo_gemini(args) -> tuple[str, bytes]:
    filename, pdf_or_img_bytes = args

    try:
        nombre_extraido = extraer_datos_con_gemini(pdf_or_img_bytes, filename)
        ext = os.path.splitext(filename)[1].lower() or ".pdf"

        if nombre_extraido:
            nuevo_nombre = f"{nombre_extraido}{ext}"
        else:
            nombre_base = os.path.splitext(filename)[0]
            nuevo_nombre = f"no_reconocido_{nombre_base}{ext}"

        return nuevo_nombre, pdf_or_img_bytes
    except Exception as e:
        print(f"[ERROR EN PROCESAMIENTO HILO]: {e}")
        return f"error_procesamiento_{filename}", pdf_or_img_bytes


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