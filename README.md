# API de procesamiento de boletas, expedientes y certificados

API FastAPI para Vercel. Recibe un reporte PDF, agrupa las páginas por hora de
ingreso y devuelve un ZIP con los PDFs renombrados y un `manifest.json`.

## Desarrollo local

```bash
python -m venv .venv
pip install -r requirements.txt
uvicorn app:app --reload --env-file .env
```

Documentación: `http://localhost:8000/docs`.

Variables de Vercel:

- `ALLOWED_ORIGINS`: dominio de Nuxt (o varios separados por comas).
- `MAX_FILE_SIZE_MB`: tamaño máximo por PDF de boletas/certificados; por defecto `50`.
- `GEMINI_API_KEY`: necesaria solamente para expedientes. Certificados no usa Gemini.

En local, crea `.env` antes de usar `--env-file .env`; si no necesitas variables,
puedes ejecutar `uvicorn app:app --reload`. En Vercel configura las variables
en el proyecto y vuelve a desplegar.

## Certificados y kanaySeche (Nuxt 2)

La página `pages/documentos/certificados.vue` de `kanaySeche` ya utiliza el contrato:

- `POST /api/procesar-certificados`.
- Cuerpo `FormData`: repetir el campo **`files`** por cada PDF.
- No establecer `Content-Type` manualmente: el navegador agrega el boundary.
- Éxito: ZIP binario (`application/zip`) con PDFs y `manifest.json`.
- `X-Archivos-Procesados`: cantidad procesada; expuesto mediante CORS.
- Errores: JSON con `detail`; 400 para entradas inválidas, 413 por tamaño y
  422 para PDFs ilegibles. Un PDF inválido rechaza el lote completo.

La página usa `fetch` con la URL fija
`https://api-query-control-pesaje.vercel.app/api/procesar-certificados`.
Por eso los cambios locales de esta API solo llegan a esa página después de
desplegarlos; para probar localmente, usa `http://localhost:8000` como origen
de la API en el frontend. La configuración global de Axios apunta a otra API
y no interviene en este `fetch`.

Configura `ALLOWED_ORIGINS` con los orígenes exactos de Nuxt, sin barra final,
por ejemplo `http://localhost:3000,https://tu-frontend.example.com`.
Si no se configura, el valor predeterminado es `*` sin credenciales.

El procesador extrae texto del PDF, sin OCR. Cuando faltan campos, conserva
el documento como `otro_cert_N.pdf`. Empresa y generador se toman de la
primera palabra reconocida. Revisa `manifest.json` para los datos extraídos.

**Límite de Vercel:** la solicitud completa (incluido multipart) y la respuesta
están limitadas a 4,5 MB. Configurar 50 MB en Python no aumenta ese límite.
Divide lotes pequeños; para archivos individuales mayores se necesita otra
arquitectura de carga/procesamiento.
Referencia: https://vercel.com/docs/functions/limitations

## Verificación local

```bash
pip install httpx
python -m unittest discover -s tests -v
```

Las pruebas generan PDFs sintéticos y verifican nombres, ZIP, manifest,
duplicados, validación, tamaño, CORS y manejo de errores. No llaman a Gemini.

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
