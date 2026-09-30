"""
SISCA — Sistema Institucional de Control de Asistencia
Politécnico Internacional · Bogotá, Colombia
Punto de entrada principal del servidor Flask
"""
import os
from dotenv import load_dotenv
load_dotenv()

from app import create_app

app = create_app()

if __name__ == '__main__':
    host  = os.getenv('FLASK_HOST', '0.0.0.0')
    port  = int(os.getenv('FLASK_PORT', 8080))
    debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'

    print(f"""
+------------------------------------------------------+
|  SISCA v1.0 - Politecnico Internacional              |
|  Sistema Institucional de Control de Asistencia      |
+------------------------------------------------------+
|  Servidor : http://{host}:{port}
|  Entorno  : {'Desarrollo' if debug else 'Produccion'}
|  Postgres : {os.getenv('DATABASE_URL') or (os.getenv('POSTGRES_HOST','localhost') + ':' + os.getenv('POSTGRES_PORT','5432'))}
+------------------------------------------------------+
    """)

    app.run(host=host, port=port, debug=debug)
