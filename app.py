import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from boletas_processor import procesar_boletas_pdf

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


@app.post("/api/procesar-boletas", response_class=FileResponse)
async def procesar_boletas(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Recibe un PDF multipart/form-data y devuelve un ZIP con el resultado."""
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

    carpeta_temp = Path(tempfile.mkdtemp(prefix="boletas_"))
    salida = carpeta_temp / "salida"
    zip_path = carpeta_temp / "boletas_procesadas.zip"
    try:
        resultado = procesar_boletas_pdf(contenido, filename, salida)
        if not resultado["success"]:
            raise HTTPException(status_code=422, detail=resultado["mensaje"])
        if not resultado["boletas"]:
            raise HTTPException(status_code=422, detail="No se encontraron boletas con texto, fecha y hora reconocibles")

        manifest = {**resultado, "archivos_generados": resultado["archivos_generados"]}
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archivo_zip:
            for ruta in salida.rglob("*.pdf"):
                archivo_zip.write(ruta, ruta.relative_to(salida).as_posix())
            archivo_zip.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    except HTTPException:
        shutil.rmtree(carpeta_temp, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(carpeta_temp, ignore_errors=True)
        raise HTTPException(status_code=500, detail="Error interno procesando el PDF") from exc

    background_tasks.add_task(shutil.rmtree, carpeta_temp, True)
    return FileResponse(zip_path, media_type="application/zip", filename="boletas_procesadas.zip", background=background_tasks)
