import io
import re
from collections import defaultdict
from pathlib import Path
from pypdf import PdfReader, PdfWriter

def normalizar_fecha(fecha_str):
    if not fecha_str:
        return "SinFecha"
    partes = re.split(r"[/.-]", fecha_str.strip())
    if len(partes) != 3:
        return "SinFecha"
    dia, mes, anio = partes
    if len(anio) == 2:
        anio = f"20{anio}"
    try:
        dia_int, mes_int, anio_int = int(dia), int(mes), int(anio)
        if not (1 <= dia_int <= 31 and 1 <= mes_int <= 12 and 2000 <= anio_int <= 2100):
            return "SinFecha"
    except ValueError:
        return "SinFecha"
    return f"{anio_int:04d}-{mes_int:02d}-{dia_int:02d}"

def _primera_coincidencia(patron, texto, default):
    match = re.search(patron, texto, re.IGNORECASE)
    return match.group(1).strip() if match else default

def extraer_datos_boleta_pagina(texto_pagina):
    hora_original = _primera_coincidencia(
        r"Hora\s*(?:de\s*)?Ingreso\s*:\s*(\d{1,2}:\d{2}(?::\d{2})?)",
        texto_pagina,
        "00:00:00",
    )
    partes_hora = hora_original.split(":")
    hora = "-".join(partes_hora + (["00"] if len(partes_hora) == 2 else []))
    fecha_texto = _primera_coincidencia(
        r"Fecha\s*:\s*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})", texto_pagina, ""
    )
    ingreso = _primera_coincidencia(
        r"N(?:[º°]|ro\.?)?\s*Ingreso\s*:\s*([A-Z0-9-]+)", texto_pagina, "SinIngreso"
    )
    cliente = _primera_coincidencia(
        r"Raz[oó]n\s*Social\s*:\s*([^\r\n]+)", texto_pagina, "Cliente_Desconocido"
    )
    generador = _primera_coincidencia(
        r"Generador\s*:\s*([^\r\n]+)", texto_pagina, "GENERADOR"
    )
    return {
        "hora": hora,
        "fecha": normalizar_fecha(fecha_texto),
        "ingreso": ingreso,
        "cliente_completo": cliente,
        "cliente_palabra": cliente.split()[0].upper(),
        "generador_palabra": generador.split()[0].upper(),
    }

def _nombre_seguro(valor, default):
    limpio = re.sub(r'[\\/*?:"<>|]', "", valor).strip(" .")
    return limpio[:120] or default

def procesar_boletas_pdf_en_memoria(file_bytes):
    """Procesa el PDF y genera los archivos resultantes directamente en RAM."""
    resultado = {"success": False, "mensaje": "", "boletas": [], "archivos_generados": [], "errores": []}
    
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        grupos_por_hora = defaultdict(list)
        datos_por_hora = {}

        for indice, pagina in enumerate(reader.pages):
            texto = pagina.extract_text() or ""
            if not texto.strip():
                resultado["errores"].append(f"Página {indice + 1}: no contiene texto extraíble")
                continue
            datos = extraer_datos_boleta_pagina(texto)
            if datos["hora"] == "00-00-00" or datos["fecha"] == "SinFecha":
                resultado["errores"].append(f"Página {indice + 1}: fecha u hora no reconocida")
                continue
            grupos_por_hora[datos["hora"]].append(indice)
            datos_por_hora.setdefault(datos["hora"], datos)

        archivos_memoria = {} # Guarda { ruta_relativa: bytes_pdf }

        for hora, indices in grupos_por_hora.items():
            datos = datos_por_hora[hora]
            writer = PdfWriter()
            for indice in indices:
                writer.add_page(reader.pages[indice])

            nombre_pdf = _nombre_seguro(
                f"{datos['fecha']}-{datos['ingreso']}-{datos['cliente_palabra']}-{datos['generador_palabra']}.pdf",
                "boleta.pdf",
            )
            carpeta_cliente = _nombre_seguro(datos["cliente_completo"], "Cliente_Desconocido")
            ruta_relativa = f"{carpeta_cliente}/{nombre_pdf}"

            # Guardar PDF resultante en un buffer de memoria
            pdf_buffer = io.BytesIO()
            writer.write(pdf_buffer)
            archivos_memoria[ruta_relativa] = pdf_buffer.getvalue()

            resultado["boletas"].append({
                "hora": hora, "fecha": datos["fecha"], "ingreso": datos["ingreso"],
                "cliente": datos["cliente_completo"], "cliente_palabra": datos["cliente_palabra"],
                "generador": datos["generador_palabra"], "paginas": len(indices),
                "archivo": ruta_relativa, "nombre_archivo": nombre_pdf,
            })
            resultado["archivos_generados"].append(ruta_relativa)

        resultado["success"] = True
        resultado["mensaje"] = f"Procesamiento exitoso. {len(resultado['boletas'])} boleta(s) encontrada(s)"
        return resultado, archivos_memoria

    except Exception as exc:
        resultado["mensaje"] = f"Error procesando el archivo: {exc}"
        resultado["errores"].append(str(exc))
        return resultado, {}