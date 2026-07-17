"""
SISCA - Blueprint de documentación Swagger / OpenAPI.

Rutas expuestas:
    GET /api/docs        → Swagger UI (v5, CDN) que carga el spec desde /api/openapi.json
    GET /api/openapi.json → Especificación OpenAPI 3.0 en JSON
"""
import os
import json
from flask import Blueprint, jsonify, current_app, send_from_directory

swagger_bp = Blueprint('swagger', __name__)

# Ruta del archivo spec relativa al directorio static de la app
_SPEC_FILENAME = 'openapi.json'
_SPEC_SUBDIR   = 'swagger'


@swagger_bp.route('/openapi.json', methods=['GET'])
def openapi_spec():
    """Devuelve la especificación OpenAPI 3.0 como JSON."""
    static_folder = current_app.static_folder or os.path.join(
        os.path.dirname(__file__), '..', 'static'
    )
    spec_path = os.path.join(static_folder, _SPEC_SUBDIR, _SPEC_FILENAME)
    try:
        with open(spec_path, 'r', encoding='utf-8') as fh:
            spec = json.load(fh)
        return jsonify(spec)
    except FileNotFoundError:
        return jsonify({'error': f'Spec no encontrada en {spec_path}'}), 404


_SWAGGER_UI_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>SISCA API — Documentación</title>
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css" />
  <style>
    body { margin: 0; background: #fafafa; }
    .topbar { display: none !important; }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
  <script>
    window.onload = function () {
      SwaggerUIBundle({
        url: "/api/openapi.json",
        dom_id: "#swagger-ui",
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIStandalonePreset,
        ],
        layout: "StandaloneLayout",
        deepLinking: true,
        filter: true,
        tryItOutEnabled: true,
        persistAuthorization: true,
      });
    };
  </script>
</body>
</html>"""


@swagger_bp.route('/docs', methods=['GET'])
def swagger_ui():
    """Sirve la interfaz Swagger UI para explorar y probar la API de SISCA."""
    return _SWAGGER_UI_HTML, 200, {'Content-Type': 'text/html; charset=utf-8'}
