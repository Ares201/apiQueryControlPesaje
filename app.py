import io
import json
import os
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from boletas_processor import procesar_boletas_pdf_en_memoria
from expedientes_processor import procesar_expedientes_en_memoria  # Respaldo original
from expedientes_gemini_processor import procesar_expedientes_gemini_masivo  # Nuevo motor Gemini

MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "50")) * 1024 * 1024  # Aumentado a 50MB para lotes
ALLOWED_ORIGINS = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "*").split(",") if x.strip()]

app = FastAPI(
    title="API de Procesamiento de Boletas y Expedientes",
    description="Procesa, separa y renombra boletas PDF y expedientes escaneados.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=ALLOWED_ORIGINS != ["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

@app.get("/")
@app.get("/api/health")
def health():
    return {"status": "ok", "service": "procesador-boletas-y-expedientes"}

@app.post("/api/procesar-boletas")
async def procesar_boletas(file: UploadFile = File(...)):
    """Recibe un PDF multipart/form-data y devuelve un ZIP directamente desde RAM."""
    filename = Path(file.filename or "boletas.pdf").name
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="El archivo debe ser un PDF")

    contenido = await file.read(MAX_FILE_SIZE + 1)
    await file.close()

    if not contenido:
        raise HTTPException(status_code=400, detail="El archivo está vacío")
    if len(contenido) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"El archivo supera el límite permitidos")
    if not contenido.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="El contenido no es un PDF válido")

    # Procesar en RAM
    resultado, archivos_pdf = procesar_boletas_pdf_en_memoria(contenido)

    if not resultado["success"]:
        raise HTTPException(status_code=422, detail=resultado["mensaje"])
    if not resultado["boletas"]:
        raise HTTPException(status_code=422, detail="No se encontraron boletas con texto, fecha y hora reconocibles")

    # Crear el ZIP en memoria (BytesIO)
    zip_buffer = io.BytesIO()
    manifest = {**resultado, "archivos_generados": resultado["archivos_generados"]}

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for ruta_relativa, pdf_bytes in archivos_pdf.items():
            zip_file.writestr(ruta_relativa, pdf_bytes)
        zip_file.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    zip_buffer.seek(0)

    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=boletas_procesadas.zip"}
    )

# ==============================================================================
# NUEVO ENDPOINT MASIVO PARA EXPEDIENTES USANDO GEMINI (HASTA 50 ARCHIVOS)
# ==============================================================================
@app.post("/api/procesar-expedientes")
async def procesar_expedientes(files: list[UploadFile] = File(...)):
    """
    Recibe múltiples archivos PDF o imágenes (hasta 50 en un solo envío),
    los analiza con Gemini 1.5 Flash en paralelo y devuelve un ZIP renombrado.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No se enviaron archivos")

    archivos_preparados = []

    for file in files:
        filename = Path(file.filename or "expediente.pdf").name
        contenido = await file.read()
        await file.close()

        if contenido:
            archivos_preparados.append({
                "filename": filename,
                "bytes": contenido
            })

    if not archivos_preparados:
        raise HTTPException(status_code=400, detail="Los archivos enviados estaban vacíos")

    # Ejecutar procesamiento paralelo con el motor Gemini
    resultado, zip_bytes = procesar_expedientes_gemini_masivo(archivos_preparados)

    if not resultado.get("success"):
        raise HTTPException(status_code=422, detail="Ocurrió un error al procesar los expedientes")

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=expedientes_renombrados.zip",
            "X-Archivos-Procesados": str(resultado.get("renombrados", 0))
        }
    )