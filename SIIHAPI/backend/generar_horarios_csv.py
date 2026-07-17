"""
Genera un CSV de horarios LISTO PARA CARGA MASIVA usando los datos reales
de tu base de datos (matriculas, docentes, salones, bloques).

Salida: horarios_para_cargar.csv  (formato: matricula_id, materia_codigo,
docente_correo, salon_codigo, dia, bloque)

USO (desde SIIHAPI/backend, con el venv activado):
    python generar_horarios_csv.py
Luego sube ese CSV en  Carga Masiva  ->  tipo "horarios".
"""
import os
import csv
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'siihapi.settings')
django.setup()

from apps.matriculas.models import Matricula          # noqa: E402
from apps.personal.models import Docente              # noqa: E402
from apps.infraestructura.models import Salon         # noqa: E402
from apps.horarios.models import Bloque               # noqa: E402

SALIDA = 'horarios_para_cargar.csv'
DIAS = ['LU', 'MA', 'MI', 'JU', 'VI']   # de lunes a viernes (agrega 'SA' si quieres)


def main():
    matriculas = list(
        Matricula.objects.filter(estado='ACTIVA')
        .select_related('materia', 'estudiante')
        .order_by('id_matricula')
    )
    docentes = list(Docente.objects.filter(activo=True).select_related('usuario'))
    salones = list(Salon.objects.filter(activo=True))
    bloques = list(Bloque.objects.order_by('numero'))

    if not matriculas:
        print('⚠ No hay matriculas ACTIVAS. Carga estudiantes/matriculas primero.')
        return
    if not (docentes and salones and bloques):
        print(f'⚠ Faltan datos: docentes={len(docentes)} salones={len(salones)} bloques={len(bloques)}')
        return

    # Evitar choques: un (dia, bloque, salon) y (dia, bloque, docente) no se repiten
    ocupado_salon = set()
    ocupado_docente = set()
    filas = []
    di = 0  # indice de dia/bloque rotativo

    for idx, mat in enumerate(matriculas):
        docente = docentes[idx % len(docentes)]
        correo = getattr(docente.usuario, 'correo', '') or getattr(docente.usuario, 'email', '')

        # Buscar un (dia, bloque, salon) libre
        colocado = False
        intentos = 0
        total_combos = len(DIAS) * len(bloques) * len(salones)
        while not colocado and intentos < total_combos:
            dia = DIAS[(di) % len(DIAS)]
            bloque = bloques[(di // len(DIAS)) % len(bloques)]
            salon = salones[(di // (len(DIAS) * len(bloques))) % len(salones)]
            di += 1
            intentos += 1
            k_salon = (dia, bloque.numero, salon.codigo)
            k_doc = (dia, bloque.numero, correo)
            if k_salon in ocupado_salon or k_doc in ocupado_docente:
                continue
            ocupado_salon.add(k_salon)
            ocupado_docente.add(k_doc)
            filas.append({
                'matricula_id':  mat.id_matricula,
                'materia_codigo': mat.materia.codigo,
                'docente_correo': correo,
                'salon_codigo':  salon.codigo,
                'dia':           dia,
                'bloque':        bloque.numero,
            })
            colocado = True

        if not colocado:
            print(f'  (sin cupo libre para matricula {mat.id_matricula}, omitida)')

    with open(SALIDA, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['matricula_id', 'materia_codigo',
                                          'docente_correo', 'salon_codigo', 'dia', 'bloque'])
        w.writeheader()
        w.writerows(filas)

    print(f'✅ Generado "{SALIDA}" con {len(filas)} horarios a partir de '
          f'{len(matriculas)} matriculas reales.')
    print('   Subelo en Carga Masiva -> tipo "horarios".')


if __name__ == '__main__':
    main()
