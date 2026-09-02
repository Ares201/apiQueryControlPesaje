import io
import json
import os
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from boletas_processor import procesar_boletas_pdf_en_memoria

MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "10")) * 1024 * 1024
ALLOWED_ORIGINS = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "*").split(",") if x.strip()]

app = FastAPI(
    title="API de Procesamiento de Boletas",
    description="Separa y renombra boletas PDF agrupadas por hora de ingreso.",
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
    return {"status": "ok", "service": "procesador-boletas"}

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
        # Agregar los PDFs individuales
        for ruta_relativa, pdf_bytes in archivos_pdf.items():
            zip_file.writestr(ruta_relativa, pdf_bytes)
        # Agregar manifest.json
        zip_file.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    zip_buffer.seek(0)

    # Devolver el ZIP en la respuesta HTTP directamente sin tocar disco
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=boletas_procesadas.zip"}
    )