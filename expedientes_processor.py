import io
import re
import zipfile
import requests

# Clave asignada por OCR.space
OCR_SPACE_API_KEY = "K85071803688957"


def obtener_primera_palabra(texto: str) -> str:
    """Obtiene solo la primera palabra del texto"""
    if not texto:
        return None
    texto_limpio = re.sub(r'[^A-Za-z0-9\s-]', '', texto)
    partes = re.split(r'[\s-]+', texto_limpio.strip())
    if partes and len(partes[0]) > 0:
        return partes[0].upper()
    return None


def extraer_fecha(texto: str) -> str:
    """Extrae fecha en formato DD/MM/YYYY y la convierte a YYYY-MM-DD"""
    match = re.search(r'(\d{2})/(\d{2})/(\d{4})', texto)
    if match:
        dia, mes, anio = match.groups()
        return f"{anio}-{mes}-{dia}"
    return None


def extraer_orden(texto: str) -> str:
    """Extrae el número de orden"""
    patrones = [
        r'(?:Order|Orden)\s*No\.?\s*[:.]?\s*([A-Z0-9-]+)',
        r'PV-\d+',
        r'[A-Z]{2}-\d{7}',
    ]
    for patron in patrones:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            if match.lastindex:
                return match.group(1)
            return match.group(0)
    return None


def extraer_cliente(texto: str) -> str:
    """Extrae SOLO el nombre del cliente y devuelve la primera palabra"""
    lineas = texto.split('\n')
    
    for i, linea in enumerate(lineas):
        linea = linea.strip()
        if 'Cliente' in linea and 'RUC' not in linea and 'Transportista' not in linea:
            match = re.search(r'Cliente\s*[:.]?\s*(.+)', linea, re.IGNORECASE)
            if match:
                cliente = match.group(1).strip()
                if len(cliente) < 3 or cliente.isdigit():
                    if i + 1 < len(lineas):
                        siguiente = lineas[i + 1].strip()
                        if siguiente and not siguiente.isdigit():
                            return obtener_primera_palabra(siguiente)
                return obtener_primera_palabra(cliente)
        
        if 'RUC Cliente' in linea:
            for j in range(i + 1, min(i + 4, len(lineas))):
                posible_cliente = lineas[j].strip()
                if posible_cliente and not posible_cliente.isdigit() and 'Transportista' not in posible_cliente:
                    cliente_limpio = re.sub(r'[^A-Za-z0-9\s]', '', posible_cliente)
                    if len(cliente_limpio) > 3:
                        return obtener_primera_palabra(cliente_limpio)
    
    match_ruc = re.search(r'RUC Cliente.*?\n\s*\d+\s*\n\s*([A-Z\s]+)', texto, re.DOTALL)
    if match_ruc:
        cliente = match_ruc.group(1).strip()
        cliente = re.sub(r'[^A-Za-z0-9\s]', '', cliente)
        if len(cliente) > 3:
            return obtener_primera_palabra(cliente)
    
    return None


def ejecutar_ocr_space(pdf_bytes: bytes) -> str:
    """Envía el PDF escaneado a la API de OCR.space"""
    url = "https://api.ocr.space/parse/image"
    
    payload = {
        'apikey': OCR_SPACE_API_KEY,
        'language': 'spa',
        'isTable': 'true',
        'OCREngine': '2'
    }
    
    files = [
        ('file', ('expediente.pdf', pdf_bytes, 'application/pdf'))
    ]
    
    try:
        response = requests.post(url, data=payload, files=files, timeout=9)
        datos = response.json()
        
        if datos.get("IsErroredOnProcessing"):
            print("Error OCR.space:", datos.get("ErrorMessage"))
            return ""
            
        parsed_results = datos.get("ParsedResults", [])
        return "\n".join([p.get("ParsedText", "") for p in parsed_results])
    except Exception as e:
        print(f"Error al conectar con OCR.space: {e}")
        return ""


def procesar_expediente_bytes(pdf_bytes: bytes, filename: str) -> tuple[str, bytes]:
    """Obtiene el texto del escaneo mediante OCR Cloud y calcula el nuevo nombre"""
    texto = ejecutar_ocr_space(pdf_bytes)

    fecha = extraer_fecha(texto)
    orden = extraer_orden(texto)
    cliente = extraer_cliente(texto)

    if fecha and orden and cliente:
        cliente_formateado = cliente.upper().strip()
        cliente_formateado = re.sub(r'[^A-Za-z0-9\s-]', '', cliente_formateado)
        partes = re.split(r'[\s-]+', cliente_formateado)
        cliente_formateado = partes[0] if partes else "CLIENTE"

        if len(cliente_formateado) > 20:
            cliente_formateado = cliente_formateado[:20]

        nuevo_nombre = f"{fecha}-{orden}-{cliente_formateado}.pdf"
    else:
        nuevo_nombre = f"otro_{filename}"

    return nuevo_nombre, pdf_bytes


def procesar_expedientes_en_memoria(contenido_zip_o_pdf: bytes, es_zip: bool = False) -> tuple[dict, bytes]:
    """Procesa el PDF o ZIP recibido y retorna un ZIP listo con los archivos renombrados"""
    zip_buffer_salida = io.BytesIO()
    renombrados = 0

    with zipfile.ZipFile(zip_buffer_salida, "w", zipfile.ZIP_DEFLATED) as zip_salida:
        if es_zip:
            with zipfile.ZipFile(io.BytesIO(contenido_zip_o_pdf), "r") as zip_entrada:
                nombres_existentes = set()
                for nombre_archivo in zip_entrada.namelist():
                    if nombre_archivo.endswith(".pdf") and not nombre_archivo.startswith("__MACOSX"):
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