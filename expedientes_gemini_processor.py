import io
import os
import re
import zipfile
import concurrent.futures
from google import genai
from google.genai import types
import pypdfium2 as pdfium

# Inicializar cliente de Gemini (Lee GEMINI_API_KEY)
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def convertir_pdf_a_imagen_bytes(pdf_bytes: bytes) -> bytes:
    """Convierte la primera página de un PDF escaneado a una imagen JPEG en memoria."""
    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
        if len(pdf) == 0:
            return None
        
        # Renderizar la primera página a alta calidad (300 DPI aprox / scale 3)
        page = pdf[0]
        image = page.render(scale=3).to_pil()
        
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()
    except Exception as e:
        print(f"[ERROR CONVERSIÓN PDF A IMAGEN]: {e}")
        return None


def extraer_datos_con_gemini(contenido_bytes: bytes, filename: str) -> str:
    """Convierte PDF a imagen si es necesario y procesa con Gemini Vision."""
    
    # 1. Si es PDF escaneado, lo convertimos a imagen JPEG
    if filename.lower().endswith('.pdf'):
        imagen_bytes = convertir_pdf_a_imagen_bytes(contenido_bytes)
        if imagen_bytes:
            bytes_a_enviar = imagen_bytes
            mime_type = "image/jpeg"
        else:
            bytes_a_enviar = contenido_bytes
            mime_type = "application/pdf"
    else:
        bytes_a_enviar = contenido_bytes
        mime_type = "image/jpeg" if filename.lower().endswith(('.jpg', '.jpeg')) else "image/png"

    # 2. Prompt optimizado para documentos e impresos escaneados
    prompt = """
    Analiza esta imagen escaneada de un expediente o control de ingreso/pesaje.
    Extrae los siguientes datos:
    1. FECHA (en formato YYYY-MM-DD).
    2. NÚMERO DE ORDEN / TICKET / GUÍA (ejemplos: 1581_001, PV-2621425, 005542).
    3. NOMBRE O SIGLA DEL CLIENTE (ejemplo: KANAY, SECHE, MAVER, etc.).

    Responde ÚNICAMENTE en una sola línea con el siguiente formato:
    FECHA_CLIENTE_ORDEN

    Ejemplo de respuesta válida:
    2026-09-24_KANAY_1581_001

    Si no identificas un dato, reemplázalo por la palabra OTRO.
    NO agregues saludos, explicaciones ni caracteres adicionales.
    """

    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=[
                types.Part.from_bytes(data=bytes_a_enviar, mime_type=mime_type),
                prompt
            ]
        )
        
        texto_raw = response.text.strip() if response.text else ""
        
        # Tomar solo la primera línea y limpiar caracteres no permitidos en nombres de archivo
        linea_unica = texto_raw.split('\n')[0].strip()
        resultado_limpio = re.sub(r'[^A-Za-z0-9_-]', '', linea_unica)

        if resultado_limpio and len(resultado_limpio) > 5:
            return resultado_limpio

    except Exception as e:
        print(f"[ERROR GEMINI VISION]: {e}")

    return None


def procesar_un_archivo_gemini(args) -> tuple[str, bytes]:
    filename, pdf_or_img_bytes = args
    
    nombre_extraido = extraer_datos_con_gemini(pdf_or_img_bytes, filename)
    ext = os.path.splitext(filename)[1].lower() or ".pdf"
    
    if nombre_extraido:
        nuevo_nombre = f"{nombre_extraido}{ext}"
    else:
        # Si no se pudo leer nada, mantenemos el nombre original con prefijo
        nombre_base = os.path.splitext(filename)[0]
        nuevo_nombre = f"escaneo_{nombre_base}{ext}"
        
    return nuevo_nombre, pdf_or_img_bytes


def procesar_expedientes_gemini_masivo(archivos_subidos: list) -> tuple[dict, bytes]:
    lista_tareas = [(file_obj["filename"], file_obj["bytes"]) for file_obj in archivos_subidos]

    zip_buffer_salida = io.BytesIO()
    nombres_existentes = set()
    renombrados = 0

    # Ejecutar máximo 4 en paralelo para no saturar límites
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
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