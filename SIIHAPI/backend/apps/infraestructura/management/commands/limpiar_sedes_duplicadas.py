"""
Elimina las sedes duplicadas/demo que ya no se usan (Fase 4/4b/4c, 2026-09-05):
id_sede 1 (C73, "Sede Calle 73 (Demo)"), 2 (NTE, "Sede Norte (Demo)") y
6 (C80_R, "Sede Calle 80", inactiva).

IMPORTANTE sobre el shell interactivo en Windows: "python manage.py shell -c"
con un comando de VARIAS lineas no funciona bien en cmd.exe -- por eso este
comando existe como archivo en vez de pedirte pegar un -c largo.

Ojo: aunque se borren (o no) estas filas de Sede, el Motor IA YA deja de
usar los salones de una sede con estado='I' (Inactiva) -- ver
motor_ia/jornadas.py / frontend_views.py, Fase 4. Borrar estas filas es
solo limpieza de datos, no un requisito para esa regla.

Fase 4c: se mapeo (con mapa_dependencias_salones) la cadena COMPLETA de
tablas que dependen de estos 42 salones, incluyendo varias tablas
huerfanas sin modelo Django (probablemente de SISCA):

    salones (42)
      <- salones_equipamiento (0)                          [modelo Django, CASCADE]
      <- SIIHAPI_HORARIO (252)                              [modelo Django, PROTECT]
      <- horario_bloques (10)                               [sin modelo Django]
           <- sesiones_clase (3)                            [sin modelo Django]
                <- codigos_qr (2)                           [sin modelo Django]
                <- asistencias (5)                          [sin modelo Django]
                     <- justificaciones (1)                 [sin modelo Django]

Este comando ahora borra TODA esa cadena cuando se usa --forzar-horarios,
recorriendo pg_constraint igual que el comando de mapeo, en vez de tener
cada tabla escrita a mano -- asi tambien cubre cualquier tabla nueva que
aparezca en esa cadena. El orden de borrado NO se calcula a mano (eso
fallo una vez: "asistencias" se borro antes que "justificaciones" que
dependia de ella) -- en vez de eso, cada tabla se intenta borrar dentro
de su propio savepoint y, si Postgres la rechaza por una FK todavia sin
resolver, se reintenta en la siguiente vuelta hasta que ya no haya
progreso.

SIEMPRE corre primero SIN --aplicar (diagnostico: no borra nada). Si hay
registros bloqueando el borrado, --aplicar solo (sin --forzar-horarios)
aborta sin borrar nada. Solo con --forzar-horarios ademas de --aplicar,
el comando borra tambien esos registros (PERMANENTE, no se puede
deshacer) antes de borrar la sede.

Uso:
    python manage.py limpiar_sedes_duplicadas                        # diagnostico
    python manage.py limpiar_sedes_duplicadas --aplicar                # borra sedes+salones si no hay nada mas
    python manage.py limpiar_sedes_duplicadas --aplicar --forzar-horarios  # borra TODA la cadena (PERMANENTE)
"""
from django.core.management.base import BaseCommand
from django.db import transaction, connection, IntegrityError
from django.db.models import ProtectedError

from apps.infraestructura.models import Sede, Salon
from apps.horarios.models import Horario

IDS_A_BORRAR = [1, 2, 6]
MAX_PROFUNDIDAD = 6


def _hijos_de(cur, tabla):
    """[(tabla_hija, columna_hija, columna_padre)] para toda FK de
    Postgres cuyo destino (confrelid) sea `tabla`."""
    cur.execute('''
        SELECT
            hijo.relname AS tabla_hija,
            col_hija.attname AS columna_hija,
            col_padre.attname AS columna_padre
        FROM pg_constraint con
        JOIN pg_class hijo ON hijo.oid = con.conrelid
        JOIN pg_class padre ON padre.oid = con.confrelid
        JOIN unnest(con.conkey) WITH ORDINALITY AS ck(attnum, ord) ON true
        JOIN unnest(con.confkey) WITH ORDINALITY AS pk(attnum, ord) ON pk.ord = ck.ord
        JOIN pg_attribute col_hija ON col_hija.attrelid = hijo.oid AND col_hija.attnum = ck.attnum
        JOIN pg_attribute col_padre ON col_padre.attrelid = padre.oid AND col_padre.attnum = pk.attnum
        WHERE con.contype = 'f' AND padre.relname = %s
    ''', [tabla])
    return cur.fetchall()


def _pk_de(cur, tabla):
    """Columna PK de `tabla` (PK de una sola columna). Usa relname en vez
    de un cast ::regclass porque SIIHAPI_HORARIO tiene mayusculas."""
    cur.execute('''
        SELECT a.attname
        FROM pg_constraint con
        JOIN pg_class c ON c.oid = con.conrelid
        JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = ANY(con.conkey)
        WHERE con.contype = 'p' AND c.relname = %s
        LIMIT 1
    ''', [tabla])
    row = cur.fetchone()
    return row[0] if row else 'id'


def _mapear_cadena(cur, tabla_raiz, ids_raiz):
    """BFS por pg_constraint desde `tabla_raiz`/`ids_raiz`. Devuelve una
    lista [(tabla, columna_fk, ids_de_esa_tabla), ...] en orden de
    descubrimiento (nivel 1, nivel 2, ...)."""
    resultado = []
    nivel = [(tabla_raiz, ids_raiz)]
    visitadas = {tabla_raiz}
    profundidad = 0
    while nivel and profundidad < MAX_PROFUNDIDAD:
        profundidad += 1
        siguiente = []
        for tabla, ids in nivel:
            if not ids:
                continue
            for tabla_hija, col_hija, _col_padre in _hijos_de(cur, tabla):
                if tabla_hija in visitadas:
                    continue
                pk_hija = _pk_de(cur, tabla_hija)
                cur.execute(
                    f'SELECT "{pk_hija}" FROM "{tabla_hija}" WHERE "{col_hija}" = ANY(%s)',
                    [ids],
                )
                ids_hija = [r[0] for r in cur.fetchall()]
                if ids_hija:
                    visitadas.add(tabla_hija)
                    resultado.append((tabla_hija, col_hija, ids_hija))
                    siguiente.append((tabla_hija, ids_hija))
        nivel = siguiente
    return resultado


def _contar_cadena(cur, ids_sede):
    """Total de filas en toda la cadena huerfana (todo lo que no sea
    salones_equipamiento ni SIIHAPI_HORARIO, que ya maneja Django)."""
    cur.execute('SELECT id FROM salones WHERE sede_id = ANY(%s)', [ids_sede])
    ids_salones = [r[0] for r in cur.fetchall()]
    if not ids_salones:
        return 0
    cadena = _mapear_cadena(cur, 'salones', ids_salones)
    return sum(len(ids) for tabla, _col, ids in cadena
               if tabla not in ('salones_equipamiento', 'SIIHAPI_HORARIO'))


def _borrar_cadena(cur, ids_sede):
    """Borra TODA la cadena huerfana (sin modelo Django) que cuelga de
    los salones de estas sedes.

    NO asume que el orden en que _mapear_cadena descubrio las tablas ya
    es el orden correcto para borrar (probamos eso primero y fallo: una
    tabla puede tener mas de un padre, o el orden entre "hermanas" del
    mismo nivel puede no coincidir con sus propias dependencias -- eso
    causo un IntegrityError borrando "asistencias" antes que
    "justificaciones"). En vez de eso, intenta borrar cada tabla dentro
    de su propio SAVEPOINT (transaction.atomic anidado): si Postgres la
    rechaza por una FK todavia sin resolver, se reintenta en la
    siguiente vuelta -- dejando que la base de datos misma valide el
    orden, en vez de calcularlo a mano."""
    cur.execute('SELECT id FROM salones WHERE sede_id = ANY(%s)', [ids_sede])
    ids_salones = [r[0] for r in cur.fetchall()]
    if not ids_salones:
        return []

    cadena = _mapear_cadena(cur, 'salones', ids_salones)
    pendientes = [(tabla, col, ids) for tabla, col, ids in cadena
                  if tabla not in ('salones_equipamiento', 'SIIHAPI_HORARIO')]

    borrados = []
    while pendientes:
        progreso = False
        siguiente_pendientes = []
        for tabla, col, ids in pendientes:
            try:
                with transaction.atomic():
                    cur.execute(f'DELETE FROM "{tabla}" WHERE "{col}" = ANY(%s)', [ids])
            except IntegrityError:
                siguiente_pendientes.append((tabla, col, ids))
            else:
                borrados.append((tabla, cur.rowcount))
                progreso = True
        pendientes = siguiente_pendientes
        if not progreso and pendientes:
            tablas_bloqueadas = ', '.join(t for t, _c, _i in pendientes)
            raise RuntimeError(
                f'No se pudo determinar un orden de borrado valido para: {tablas_bloqueadas} '
                '(siguen bloqueadas por alguna llave foranea que este comando no mapeo).'
            )
    return borrados


class Command(BaseCommand):
    help = 'Diagnostica y (con --aplicar) elimina las sedes duplicadas/demo id_sede 1, 2 y 6.'

    def add_arguments(self, parser):
        parser.add_argument('--aplicar', action='store_true', help='Borra de verdad (por defecto solo diagnostica).')
        parser.add_argument('--forzar-horarios', action='store_true', dest='forzar_horarios',
                             help='Junto con --aplicar: borra TODA la cadena que bloquea el borrado '
                                  '(horarios y toda la cadena huerfana). PERMANENTE, no se puede deshacer.')

    def handle(self, *args, **opts):
        aplicar = opts['aplicar']
        forzar = opts['forzar_horarios']

        self.stdout.write(self.style.MIGRATE_HEADING('\n== Sedes a revisar =='))
        encontradas = []
        with connection.cursor() as cur:
            for sid in IDS_A_BORRAR:
                s = Sede.objects.filter(id_sede=sid).first()
                if not s:
                    self.stdout.write(f'  id={sid}: NO EXISTE (ya se borro antes, o el id cambio)')
                    continue
                n_salones = Salon.objects.filter(sede=s).count()
                n_horarios = Horario.objects.filter(salon__sede=s).count()
                n_cadena = _contar_cadena(cur, [s.id_sede])
                encontradas.append(s)
                self.stdout.write(
                    f'  id={s.id_sede}  {s.codigo:10} {s.nombre:30} estado={s.estado}  '
                    f'-> {n_salones} salon(es), {n_horarios} horario(s), {n_cadena} fila(s) en tablas huerfanas '
                    f'(horario_bloques y lo que cuelga de ahi)'
                )

        if not encontradas:
            self.stdout.write(self.style.WARNING('\nNinguna de esas sedes existe ya. Nada que hacer.'))
            return

        if not aplicar:
            self.stdout.write(self.style.SUCCESS(
                '\n[Solo diagnostico] Nada se borro. Corre con --aplicar para borrar estas sedes '
                '(y sus salones). Si alguna tiene horarios o filas en tablas huerfanas (columnas de '
                'arriba), --aplicar solo va a abortar sin borrar nada -- agrega ademas --forzar-horarios '
                'si de verdad quieres borrar tambien esos registros (PERMANENTE).'
            ))
            return

        ids_reales = [s.id_sede for s in encontradas]

        if forzar:
            with transaction.atomic():
                with connection.cursor() as cur:
                    borrados_cadena = _borrar_cadena(cur, ids_reales)
                for tabla, n in borrados_cadena:
                    self.stdout.write(self.style.WARNING(f'  {tabla}: {n} fila(s) borrada(s)'))
                borrados_horarios = Horario.objects.filter(salon__sede__id_sede__in=ids_reales).delete()
                self.stdout.write(self.style.WARNING(f'Horarios (SIIHAPI_HORARIO) borrados: {borrados_horarios}'))
                borrados = Sede.objects.filter(id_sede__in=ids_reales).delete()
            self.stdout.write(self.style.SUCCESS(f'\nBorrado correctamente (con toda la cadena incluida): {borrados}'))
            self.stdout.write(self.style.SUCCESS(
                'Los docentes que tuvieran alguna de estas sedes como base quedaron sin sede.'
            ))
            return

        try:
            with transaction.atomic():
                borrados = Sede.objects.filter(id_sede__in=ids_reales).delete()
        except ProtectedError as e:
            conteo_por_sede = {}
            for obj in e.protected_objects:
                sede_id = getattr(getattr(obj, 'salon', None), 'sede_id', None)
                conteo_por_sede[sede_id] = conteo_por_sede.get(sede_id, 0) + 1
            self.stdout.write(self.style.ERROR(
                '\nABORTADO: no se borro nada, hay horarios ya generados sobre salones de estas sedes:'
            ))
            for sede_id, n in conteo_por_sede.items():
                s = next((x for x in encontradas if x.id_sede == sede_id), None)
                nombre = s.nombre if s else f'id={sede_id}'
                self.stdout.write(f'    {nombre}: {n} horario(s) bloqueando el borrado')
            self.stdout.write(self.style.WARNING(
                '\nSi de verdad quieres borrar tambien esos registros (PERMANENTE, no se puede '
                'deshacer), corre: python manage.py limpiar_sedes_duplicadas --aplicar --forzar-horarios'
            ))
            return
        except IntegrityError:
            with connection.cursor() as cur:
                n_cadena = sum(_contar_cadena(cur, [sid]) for sid in ids_reales)
            self.stdout.write(self.style.ERROR(
                '\nABORTADO: no se borro nada (la transaccion se deshizo por completo). Hay '
                f'{n_cadena} fila(s) en tablas huerfanas (sin modelo Django) que todavia apuntan, '
                'directa o indirectamente, a salones de estas sedes.'
            ))
            self.stdout.write(self.style.WARNING(
                '\nSi de verdad quieres borrar tambien esas filas (PERMANENTE, no se puede '
                'deshacer), corre: python manage.py limpiar_sedes_duplicadas --aplicar --forzar-horarios'
            ))
            return

        self.stdout.write(self.style.SUCCESS(f'\nBorrado correctamente: {borrados}'))
        self.stdout.write(self.style.SUCCESS(
            'Los docentes que tuvieran alguna de estas sedes como base quedaron sin sede '
            '(no se borraron ni se afectaron).'
        ))
