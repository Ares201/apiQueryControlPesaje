import io
import re
import zipfile
import requests

OCR_SPACE_API_KEY = "K85071803688957"


def obtener_primera_palabra(texto: str) -> str:
    """Extrae solo la primera palabra alfabética relevante"""
    if not texto:
        return None
    # Eliminar etiquetas o caracteres extraños
    texto_limpio = re.sub(r'[^A-Za-z0-9\s-]', '', texto)
    palabras = texto_limpio.strip().split()
    
    # Omitir palabras genéricas si la búsqueda capturó etiquetas del formulario
    omitir = {"CLIENTE", "RUC", "TRANSPORTISTA", "PLACA", "FECHA", "ORDEN", "ORDER", "S.A.C.", "SAC", "PERU"}
    for p in palabras:
        p_upper = p.upper()
        if p_upper not in omitir and len(p_upper) > 2:
            return p_upper
            
    return palabras[0].upper() if palabras else None


def extraer_fecha(texto: str) -> str:
    """Extrae fecha DD/MM/YYYY y la formatea como YYYY-MM-DD"""
    match = re.search(r'(\d{2})[/.-](\d{2})[/.-](\d{4})', texto)
    if match:
        dia, mes, anio = match.groups()
        return f"{anio}-{mes}-{dia}"
    return None


def extraer_orden(texto: str) -> str:
    """Extrae la orden (ejemplo: PV-2621425)"""
    # Buscar patrones comunes como PV-XXXXXXX o "Order No PV-..."
    match = re.search(r'(?:Order\s*No\.?|Orden)?\s*[:.]?\s*(PV-\d+)', texto, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    # Búsqueda secundaria de códigos con guion si la etiqueta no se leyó bien
    match_gen = re.search(r'\b([A-Z]{2,3}-\d{5,8})\b', texto)
    if match_gen:
        return match_gen.group(1).upper()
        
    return None


def extraer_cliente(texto: str) -> str:
    """Extrae el cliente para documentos de Séché Group y similares"""
    # 1. Patrón directo: "Cliente MAVER PERU S.A.C."
    match = re.search(r'Cliente\s*[:.]?\s*([A-Za-z0-9\s.&-]+)', texto, re.IGNORECASE)
    if match:
        linea_cliente = match.group(1).split('\n')[0].strip()
        palabra = obtener_primera_palabra(linea_cliente)
        if palabra:
            return palabra

    # 2. Búsqueda por posición en caso de tablas (línea siguiente a Cliente)
    lineas = [l.strip() for l in texto.split('\n') if l.strip()]
    for i, linea in enumerate(lineas):
        if re.search(r'^Cliente\b', linea, re.IGNORECASE) and not re.search(r'RUC', linea, re.IGNORECASE):
            # Probar en la misma línea
            partes = linea.split(':')
            if len(partes) > 1 and len(partes[1].strip()) > 2:
                return obtener_primera_palabra(partes[1])
            # Probar en la siguiente línea
            if i + 1 < len(lineas):
                return obtener_primera_palabra(lineas[i + 1])

    return None


def ejecutar_ocr_space(pdf_bytes: bytes) -> str:
    """Petición a OCR.space optimizada para PDFs escaneados de control de ingreso"""
    url = "https://api.ocr.space/parse/image"
    
    payload = {
        'apikey': OCR_SPACE_API_KEY,
        'language': 'spa',
        'isTable': 'true',
        'OCREngine': '2',          # Motor 2 es muy superior para documentos de texto e impresos
        'scale': 'true',            # Mejora la resolución automáticamente
        'detectOrientation': 'true' # Corrige si el documento vino chueco o escaneado horizontalmente
    }
    
    files = [
        ('file', ('documento.pdf', pdf_bytes, 'application/pdf'))
    ]
    
    try:
        response = requests.post(url, data=payload, files=files, timeout=25)
        datos = response.json()
        
        if datos.get("IsErroredOnProcessing"):
            print("Error OCR.space:", datos.get("ErrorMessage"))
            return ""
            
        parsed_results = datos.get("ParsedResults", [])
        texto_completo = "\n".join([p.get("ParsedText", "") for p in parsed_results])
        
        # Imprimir en consola de Vercel/Terminal para depurar
        print("=== TEXTO RECONOCIDO POR OCR ===")
        print(texto_completo[:500]) 
        print("================================")
        
        return texto_completo
    except Exception as e:
        print(f"Error en comunicación OCR: {e}")
        return ""


def procesar_expediente_bytes(pdf_bytes: bytes, filename: str) -> tuple[str, bytes]:
    """Extrae texto con OCR y arma la estructura YYYY-MM-DD-ORDEN-CLIENTE.pdf"""
    texto = ejecutar_ocr_space(pdf_bytes)

    fecha = extraer_fecha(texto)
    orden = extraer_orden(texto)
    cliente = extraer_cliente(texto)

    print(f"Campos detectados -> Fecha: {fecha} | Orden: {orden} | Cliente: {cliente}")

    if fecha and orden and cliente:
        nuevo_nombre = f"{fecha}-{orden}-{cliente}.pdf"
    elif fecha and orden:
        nuevo_nombre = f"{fecha}-{orden}-CLIENTE.pdf"
    elif orden and cliente:
        nuevo_nombre = f"SINFCHA-{orden}-{cliente}.pdf"
    else:
        nuevo_nombre = f"otro_{filename}"

    return nuevo_nombre, pdf_bytes


def procesar_expedientes_en_memoria(contenido_zip_o_pdf: bytes, es_zip: bool = False) -> tuple[dict, bytes]:
    """Procesa expedientes agrupados en ZIP o individuales"""
    zip_buffer_salida = io.BytesIO()
    renombrados = 0

    with zipfile.ZipFile(zip_buffer_salida, "w", zipfile.ZIP_DEFLATED) as zip_salida:
        if es_zip:
            with zipfile.ZipFile(io.BytesIO(contenido_zip_o_pdf), "r") as zip_entrada:
                nombres_existentes = set()
                for nombre_archivo in zip_entrada.namelist():
                    if nombre_archivo.lower().endswith(".pdf") and not nombre_archivo.startswith("__MACOSX"):
                        pdf_bytes = zip_entrada.read(nombre_archivo)
                        nuevo_nombre, bytes_salida = procesar_expediente_bytes(pdf_bytes, nombre_archivo)
                        
                        base = nuevo_nombre.replace(".pdf", "")
                        contador = 1
                        while nuevo_nombre in nombres_existentes:
                            nuevo_nombre = f"{base}_{contador}.pdf"
                            contador += 1
                        nombres_existentes.add(nuevo_nombre)

                        zip_salida.writestr(nuevo_nombre, bytes_salida)
                        renombrados += 1
        else:
            nuevo_nombre, bytes_salida = procesar_expediente_bytes(contenido_zip_o_pdf, "expediente.pdf")
            zip_salida.writestr(nuevo_nombre, bytes_salida)
            renombrados += 1

    zip_buffer_salida.seek(0)
    return {"success": True, "renombrados": renombrados}, zip_buffer_salida.getvalue()