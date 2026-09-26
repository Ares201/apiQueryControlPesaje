import io
import re

from pypdf import PdfReader


def _primera_coincidencia(patron, texto, default):
    match = re.search(patron, texto, re.IGNORECASE)
    return match.group(1).strip() if match else default


def _normalizar_fecha_certificado(texto):
    """Fecha Servicio: dd/mm/yyyy -> yyyy-mm-dd"""
    match = re.search(
        r"Fecha\s*Servicio:\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})",
        texto,
        re.IGNORECASE,
    )
    if not match:
        return None
    dia, mes, anio = match.groups()
    return f"{anio}-{mes.zfill(2)}-{dia.zfill(2)}"


def _normalizar_certificado(texto):
    cert = _primera_coincidencia(
        r"N[º°]?\s*Certificado:\s*([A-Z0-9]+(?:-[A-Z0-9]+)*)",
        texto,
        None,
    )
    if not cert:
        return None
    cert = cert.upper()
    # CERT-903023KANAY -> CERT-903023-KANAY
    cert = re.sub(r"^(CERT-\d+)([A-Z]+)$", r"\1-\2", cert)
    return cert


def _extraer_datos_certificado(texto):
    fecha = _normalizar_fecha_certificado(texto)
    cert = _normalizar_certificado(texto)

    empresa = _primera_coincidencia(
        r"de los residuos ingresados por la empresa:\s*\n?\s*([A-Z0-9áéíóúñÁÉÍÓÚÑ]+)",
        texto,
        None,
    )
    generador = _primera_coincidencia(
        r"Generador:\s*([A-Z0-9áéíóúñÁÉÍÓÚÑ]+)",
        texto,
        None,
    )

    return {
        "fecha": fecha,
        "certificado": cert,
        "empresa": empresa.upper() if empresa else None,
        "generador": generador.upper() if generador else None,
    }


def _nombre_seguro(valor, default):
    if not valor:
        return default
    limpio = re.sub(r'[\\/*?:"<>|]', "", valor).strip(" .")
    return limpio[:120] or default


def procesar_certificados_pdf_en_memoria(archivos):
    """
    archivos: lista de tuplas (nombre_original, bytes_pdf)
    Devuelve (resultado, {ruta_relativa: bytes_pdf})
    """
    resultado = {
        "success": False,
        "mensaje": "",
        "certificados": [],
        "archivos_generados": [],
        "errores": [],
    }
    archivos_memoria = {}
    usados = set()
    contador_otro = 1

    try:
        for nombre_original, contenido in archivos:
            try:
                reader = PdfReader(io.BytesIO(contenido))
                texto = "\n".join((p.extract_text() or "") for p in reader.pages)

                datos = _extraer_datos_certificado(texto)

                if all(datos.values()):
                    base = (
                        f"{datos['fecha']}-{datos['certificado']}-"
                        f"{datos['empresa']}-{datos['generador']}"
                    )
                else:
                    base = f"otro_cert_{contador_otro}"
                    contador_otro += 1

                nombre_pdf = _nombre_seguro(base, "certificado.pdf") + ".pdf"

                # Evitar colisiones
                i = 1
                while nombre_pdf in usados:
                    nombre_pdf = _nombre_seguro(base, "certificado") + f"_{i}.pdf"
                    i += 1
                usados.add(nombre_pdf)

                archivos_memoria[nombre_pdf] = contenido
                resultado["certificados"].append({
                    "archivo_original": nombre_original,
                    "archivo": nombre_pdf,
                    **datos,
                })
                resultado["archivos_generados"].append(nombre_pdf)

            except Exception as exc:
                resultado["errores"].append(f"{nombre_original}: {exc}")

        resultado["success"] = True
        resultado["mensaje"] = (
            f"Procesamiento exitoso. {len(resultado['certificados'])} certificado(s)"
        )
        return resultado, archivos_memoria

    except Exception as exc:
        resultado["mensaje"] = f"Error procesando archivos: {exc}"
        resultado["errores"].append(str(exc))
        return resultado, {}
