# API de procesamiento de boletas

API FastAPI para Vercel. Recibe un reporte PDF, agrupa las páginas por hora de
ingreso y devuelve un ZIP con los PDFs renombrados y un `manifest.json`.

## Desarrollo local

```bash
python -m venv .venv
pip install -r requirements.txt
uvicorn app:app --reload
```

Documentación: `http://localhost:8000/docs`.

Variables de Vercel:

- `ALLOWED_ORIGINS`: dominio de Nuxt (o varios separados por comas).
- `MAX_FILE_SIZE_MB`: tamaño máximo; por defecto `10`.

## Nuxt 2 con Axios

```js
async descargarBoletas(file) {
  const formData = new FormData()
  formData.append('file', file)
  const blob = await this.$axios.$post('/api/procesar-boletas', formData, {
    responseType: 'blob'
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'boletas_procesadas.zip'
  link.click()
  URL.revokeObjectURL(url)
}
```

Configure el `baseURL` de Axios con la URL de la API si están en dominios distintos.
