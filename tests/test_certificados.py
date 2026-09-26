import io
import json
import unittest
import zipfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

import app as api


def certificado_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({
        NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'),
    })
    page[NameObject('/Resources')] = DictionaryObject({
        NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})
    })
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 20 700 Td 16 TL '
                    b'(Fecha Servicio: 26/09/2026) Tj T* '
                    b'(N Certificado: CERT-903023KANAY) Tj T* '
                    b'(de los residuos ingresados por la empresa: KANAY) Tj T* '
                    b'(Generador: SECHE) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class CertificadosTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app, raise_server_exceptions=False)
        self.pdf = certificado_pdf()

    def test_health(self):
        self.assertEqual(self.client.get('/api/health').status_code, 200)

    def test_zip_names_manifest_and_duplicate(self):
        response = self.client.post('/api/procesar-certificados', files=[
            ('files', ('uno.pdf', self.pdf, 'application/pdf')),
            ('files', ('dos.pdf', self.pdf, 'application/pdf')),
        ], headers={'Origin': 'http://localhost:3000'})
        self.assertEqual(response.status_code, 200, response.text if response.status_code != 200 else '')
        self.assertEqual(response.headers['x-archivos-procesados'], '2')
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            expected = '2026-09-26-CERT-903023-KANAY-KANAY-SECHE.pdf'
            self.assertEqual(manifest['archivos_generados'][0], expected)
            self.assertEqual(archive.read(expected), self.pdf)
            self.assertEqual(len(set(manifest['archivos_generados'])), 2)

    def test_invalid_files_fail_whole_batch(self):
        for name, content, status in [('a.txt', b'text', 400), ('a.pdf', b'', 400),
                                     ('a.pdf', b'not pdf', 400), ('a.pdf', b'%PDF-broken', 422)]:
            with self.subTest(name=name, content=content):
                response = self.client.post('/api/procesar-certificados', files=[
                    ('files', ('valid.pdf', self.pdf, 'application/pdf')),
                    ('files', (name, content, 'application/pdf')),
                ])
                self.assertEqual(response.status_code, status)
                self.assertIsInstance(response.json()['detail'], str)

    def test_size_and_missing_field(self):
        with patch.object(api, 'MAX_FILE_SIZE', 10):
            response = self.client.post('/api/procesar-certificados', files={'files': ('a.pdf', self.pdf)})
            self.assertEqual(response.status_code, 413)
        self.assertEqual(self.client.post('/api/procesar-certificados').status_code, 422)

    def test_cors_preflight(self):
        response = self.client.options('/api/procesar-certificados', headers={
            'Origin': 'http://localhost:3000', 'Access-Control-Request-Method': 'POST',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('access-control-allow-origin', response.headers)

    def test_unexpected_error_respects_origin(self):
        with patch.object(api, 'ALLOWED_ORIGINS', ['https://example.com']), patch.object(
            api, 'procesar_certificados_pdf_en_memoria', side_effect=RuntimeError('internal data')
        ):
            response = self.client.post('/api/procesar-certificados',
                files={'files': ('a.pdf', self.pdf)}, headers={'Origin': 'https://example.com'})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers['access-control-allow-origin'], 'https://example.com')
        self.assertNotIn('internal data', response.text)


if __name__ == '__main__':
    unittest.main()
