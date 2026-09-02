import io
import json
import os
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from boletas_processor import procesar_boletas_pdf_en_memoria
from expedientes_processor import procesar_expedientes_en_memoria  # <-- 1. IMPORTACIÓN AGREGADA

MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "10")) * 1024 * 1024
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
        raise HTTPException(status_code=413, detail=f"El archivo supera el límite de {MAX_FILE_SIZE // 1024 // 1024} MB")
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
# 2. NUEVO ENDPOINT PARA EXPEDIENTES ESCANEADOS
# ==============================================================================
@app.post("/api/procesar-expedientes")
async def procesar_expedientes(file: UploadFile = File(...)):
    """Recibe un PDF o ZIP de expedientes escaneados, ejecuta OCR Cloud y devuelve el ZIP renombrado."""
    filename = Path(file.filename or "expediente.pdf").name
    es_zip = filename.lower().endswith(".zip")
    es_pdf = filename.lower().endswith(".pdf")

    if not (es_zip or es_pdf):
        raise HTTPException(status_code=400, detail="El archivo debe ser un PDF o ZIP")

    contenido = await file.read(MAX_FILE_SIZE + 1)
    await file.close()

    if not contenido:
        raise HTTPException(status_code=400, detail="El archivo está vacío")
    if len(contenido) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"El archivo supera el límite de {MAX_FILE_SIZE // 1024 // 1024} MB")

    # Procesar expedientes usando OCR.space
    resultado, zip_bytes = procesar_expedientes_en_memoria(contenido, es_zip=es_zip)

    if not resultado.get("success"):
        raise HTTPException(status_code=422, detail="Ocurrió un error al procesar los expedientes")

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=expedientes_renombrados.zip"}
    )