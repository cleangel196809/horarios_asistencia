"""
SIIHAPI · Pruebas de los módulos de la modularización (2026-10-05).

Cubre `apps.eventos` (API REST nueva), `apps.aula_virtual` y
`apps.evaluacion_docente`.

Cómo correrlas:

    cd SIIHAPI/backend
    python manage.py makemigrations --settings=siihapi.settings_test_sqlite
    pytest tests/ -q --ds=siihapi.settings_test_sqlite

El `makemigrations` previo NO es opcional: este repo ignora los archivos de
migración por diseño (ver .gitignore y el Dockerfile, que los genera en
build time), así que hay que generarlos con las MISMAS settings con las que
se va a correr. Importa además porque `apps.aula_virtual` y
`apps.evaluacion_docente` declaran sus tablas con esquema de Postgres
(`"aula_virtual"."canales"`) y nombre plano en cualquier otro motor
(`aula_virtual_canales`) — ver `siihapi/esquemas.py`.

Lo que se prueba es el COMPORTAMIENTO que importa, no el CRUD por el CRUD:
que una nota nunca se confirme sola, que un ajuste de syllabus no pueda
quedar sin motivo, que la dirección IN/OUT de un escaneo no la decida el
cliente y que un estudiante no matriculado no obtenga el enlace de la sala.
"""
import datetime
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.academico.models import Facultad, Materia, Programa
from apps.aula_virtual.models import CanalVirtual, ParticipanteSesion, SesionVirtual
from apps.autenticacion.models import Usuario
from apps.evaluacion_docente.models import (
    ActividadSyllabus, Calificacion, CriterioRubrica, HistorialAjusteSyllabus,
    NivelDesempeno, Rubrica, Syllabus, UnidadSyllabus,
)
from apps.eventos.models import AsistenciaEvento, Evento, InscripcionEvento
from apps.matriculas.models import Estudiante, Matricula, Periodo
from apps.personal.models import Docente

pytestmark = pytest.mark.django_db


# ════════════════════════════════════════════════════════════
#  Fixtures
# ════════════════════════════════════════════════════════════
@pytest.fixture
def facultad():
    return Facultad.objects.create(codigo='FTI', nombre='Técnicas de Ingeniería')


@pytest.fixture
def programa(facultad):
    return Programa.objects.create(
        facultad=facultad, codigo='TDSAM', nombre='Desarrollo de Software', tipo='TEC')


@pytest.fixture
def materia(programa):
    return Materia.objects.create(
        programa=programa, codigo='PRG1', nombre='Programación I', ciclo='1',
        creditos=Decimal('3.0'), horas_semanales=4)


@pytest.fixture
def periodo():
    return Periodo.objects.create(
        codigo='2026-2', nombre='Segundo ciclo 2026',
        fecha_inicio=datetime.date(2026, 7, 1), fecha_fin=datetime.date(2026, 12, 15),
        activo=True)


def _usuario(correo, rol, nombre='Nombre', apellido='Apellido'):
    u = Usuario.objects.create(correo=correo, rol=rol, nombre=nombre, apellido=apellido)
    u.set_password('Clave.Segura1')
    u.save()
    return u


@pytest.fixture
def admin_user():
    return _usuario('admin@pi.edu.co', 'ADMINISTRADOR', 'Ada', 'Admin')


@pytest.fixture
def docente_user():
    return _usuario('docente@pi.edu.co', 'DOCENTE', 'Edgar', 'Ángel')


@pytest.fixture
def docente(docente_user, facultad):
    return Docente.objects.create(usuario=docente_user, facultad=facultad, tipo_contrato='TC')


@pytest.fixture
def estudiante_user():
    return _usuario('estudiante@pi.edu.co', 'ESTUDIANTE', 'Sara', 'Estudiante')


@pytest.fixture
def estudiante(estudiante_user, programa):
    return Estudiante.objects.create(
        usuario=estudiante_user, codigo='20261234', programa=programa, semestre_actual=1)


@pytest.fixture
def otro_estudiante(programa):
    u = _usuario('otro@pi.edu.co', 'ESTUDIANTE', 'Otro', 'Alumno')
    return Estudiante.objects.create(
        usuario=u, codigo='20269999', programa=programa, semestre_actual=1)


def api(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


# ════════════════════════════════════════════════════════════
#  apps.eventos
# ════════════════════════════════════════════════════════════
class TestEventosAPI:

    def _evento(self, propuesto_por, estado='PUBLICADO'):
        inicio = timezone.now() + datetime.timedelta(days=3)
        return Evento.objects.create(
            nombre='Ceremonia de grado', tipo='GRADO', modalidad='PRESENCIAL',
            fecha_inicio=inicio, fecha_fin=inicio + datetime.timedelta(hours=3),
            estado=estado, propuesto_por=propuesto_por)

    def test_ping_responde_ok(self, docente_user):
        r = api(docente_user).get('/api/eventos/ping/')
        assert r.status_code == 200
        assert r.json()['app'] == 'eventos'

    def test_evento_creado_nace_en_borrador_aunque_se_pida_publicado(self, docente_user):
        inicio = timezone.now() + datetime.timedelta(days=5)
        r = api(docente_user).post('/api/eventos/crear/', {
            'nombre': 'Charla de egresados', 'tipo': 'ACADEMICO',
            'fecha_inicio': inicio.isoformat(),
            'fecha_fin': (inicio + datetime.timedelta(hours=2)).isoformat(),
            'estado': 'PUBLICADO',  # el cliente lo pide…
        }, format='json')
        assert r.status_code == 201
        # …y el servidor lo ignora: publicar pasa por aprobación.
        assert r.json()['data']['estado'] == 'BORRADOR'

    def test_fecha_fin_anterior_al_inicio_es_rechazada(self, docente_user):
        inicio = timezone.now() + datetime.timedelta(days=5)
        r = api(docente_user).post('/api/eventos/crear/', {
            'nombre': 'Evento imposible', 'tipo': 'ACADEMICO',
            'fecha_inicio': inicio.isoformat(),
            'fecha_fin': (inicio - datetime.timedelta(hours=1)).isoformat(),
        }, format='json')
        assert r.status_code == 400
        assert 'fecha_fin' in r.json()['errors']

    def test_docente_no_puede_aprobar_su_propio_evento(self, docente_user):
        ev = self._evento(docente_user, estado='BORRADOR')
        r = api(docente_user).post(f'/api/eventos/{ev.pk}/aprobar/',
                                   {'estado': 'PUBLICADO'}, format='json')
        assert r.status_code == 403
        ev.refresh_from_db()
        assert ev.estado == 'BORRADOR'

    def test_admin_aprueba_y_queda_registrado_quien(self, admin_user, docente_user):
        ev = self._evento(docente_user, estado='BORRADOR')
        r = api(admin_user).post(f'/api/eventos/{ev.pk}/aprobar/',
                                 {'estado': 'PUBLICADO'}, format='json')
        assert r.status_code == 200
        ev.refresh_from_db()
        assert ev.estado == 'PUBLICADO'
        assert ev.aprobado_por_id == admin_user.pk
        assert ev.fecha_aprobacion is not None

    def test_inscripcion_es_idempotente_y_no_duplica_token(self, docente_user, estudiante_user):
        ev = self._evento(docente_user)
        cliente = api(estudiante_user)
        r1 = cliente.post(f'/api/eventos/{ev.pk}/inscribirme/', {}, format='json')
        r2 = cliente.post(f'/api/eventos/{ev.pk}/inscribirme/', {}, format='json')
        assert r1.status_code == 201 and r2.status_code == 200
        assert r2.json()['ya_inscrito'] is True
        assert InscripcionEvento.objects.filter(evento=ev).count() == 1
        assert r1.json()['data']['token_qr'] == r2.json()['data']['token_qr']

    def test_cupo_lleno_manda_a_lista_de_espera(self, docente_user, estudiante_user, otro_estudiante):
        ev = self._evento(docente_user)
        ev.cupo_maximo = 1
        ev.save(update_fields=['cupo_maximo'])
        api(estudiante_user).post(f'/api/eventos/{ev.pk}/inscribirme/', {}, format='json')
        r = api(otro_estudiante.usuario).post(f'/api/eventos/{ev.pk}/inscribirme/', {}, format='json')
        assert r.json()['data']['estado'] == 'LISTA_ESPERA'

    def test_estudiante_no_puede_escanear(self, docente_user, estudiante_user):
        ev = self._evento(docente_user)
        insc = InscripcionEvento.objects.create(evento=ev, usuario=estudiante_user)
        r = api(estudiante_user).post(f'/api/eventos/{ev.pk}/escanear/',
                                      {'token_qr': str(insc.token_qr)}, format='json')
        assert r.status_code == 403

    def test_token_no_uuid_da_400_y_no_toca_la_base(self, docente_user):
        ev = self._evento(docente_user)
        r = api(docente_user).post(f'/api/eventos/{ev.pk}/escanear/',
                                   {'token_qr': "' OR 1=1 --"}, format='json')
        assert r.status_code == 400
        assert AsistenciaEvento.objects.count() == 0

    def test_direccion_alterna_in_out_sin_que_la_mande_el_cliente(self, docente_user, estudiante_user):
        ev = self._evento(docente_user)
        insc = InscripcionEvento.objects.create(evento=ev, usuario=estudiante_user)
        cliente = api(docente_user)
        payload = {'token_qr': str(insc.token_qr), 'direccion': 'OUT'}  # el cliente intenta forzar
        r1 = cliente.post(f'/api/eventos/{ev.pk}/escanear/', payload, format='json')
        r2 = cliente.post(f'/api/eventos/{ev.pk}/escanear/', payload, format='json')
        r3 = cliente.post(f'/api/eventos/{ev.pk}/escanear/', payload, format='json')
        assert [r.json()['data']['direccion'] for r in (r1, r2, r3)] == ['IN', 'OUT', 'IN']

    def test_timestamp_futuro_se_recorta_a_la_hora_del_servidor(self, docente_user, estudiante_user):
        ev = self._evento(docente_user)
        insc = InscripcionEvento.objects.create(evento=ev, usuario=estudiante_user)
        futuro = timezone.now() + datetime.timedelta(days=30)
        r = api(docente_user).post(f'/api/eventos/{ev.pk}/escanear/', {
            'token_qr': str(insc.token_qr), 'timestamp': futuro.isoformat(),
            'sincronizado_offline': True,
        }, format='json')
        assert r.status_code == 201
        assert AsistenciaEvento.objects.get().timestamp < futuro

    def test_reporte_asistencia_distingue_asistio_de_sigue_adentro(self, docente_user, estudiante_user):
        ev = self._evento(docente_user)
        insc = InscripcionEvento.objects.create(evento=ev, usuario=estudiante_user)
        cliente = api(docente_user)
        cliente.post(f'/api/eventos/{ev.pk}/escanear/',
                     {'token_qr': str(insc.token_qr)}, format='json')

        r = cliente.get(f'/api/eventos/{ev.pk}/asistencia/')
        fila = r.json()['data'][0]
        assert fila['asistio'] is True and fila['dentro_ahora'] is True

        cliente.post(f'/api/eventos/{ev.pk}/escanear/',
                     {'token_qr': str(insc.token_qr)}, format='json')  # salida
        fila = cliente.get(f'/api/eventos/{ev.pk}/asistencia/').json()['data'][0]
        assert fila['asistio'] is True and fila['dentro_ahora'] is False

    def test_evento_sin_inscritos_no_reporta_0_por_ciento(self, docente_user):
        ev = self._evento(docente_user)
        r = api(docente_user).get(f'/api/eventos/{ev.pk}/asistencia/')
        # None = "no aplica", distinto de 0.0 = "nadie asistió".
        assert r.json()['resumen']['porcentaje_asistencia'] is None


# ════════════════════════════════════════════════════════════
#  apps.aula_virtual
# ════════════════════════════════════════════════════════════
class TestAulaVirtual:

    def _canal(self, docente, materia, periodo):
        return CanalVirtual.objects.create(
            materia=materia, docente=docente, periodo=periodo, nombre='Canal PRG1')

    def _sesion(self, canal):
        return SesionVirtual.objects.create(
            canal=canal, titulo='Clase 1', fecha_inicio=timezone.now(), duracion_minutos=60)

    def test_url_jitsi_usa_el_uuid_y_no_el_nombre_de_la_materia(self, docente, materia, periodo):
        canal = self._canal(docente, materia, periodo)
        assert str(canal.sala_uuid) in canal.url_jitsi
        assert materia.codigo not in canal.url_jitsi

    def test_estudiante_no_matriculado_no_obtiene_el_enlace(self, docente, materia, periodo, otro_estudiante):
        canal = self._canal(docente, materia, periodo)
        r = api(otro_estudiante.usuario).get(f'/api/aula-virtual/canales/{canal.pk}/')
        assert r.status_code == 403

    def test_estudiante_matriculado_si_ve_el_canal(self, docente, materia, periodo, estudiante):
        canal = self._canal(docente, materia, periodo)
        Matricula.objects.create(estudiante=estudiante, materia=materia, periodo=periodo)
        r = api(estudiante.usuario).get(f'/api/aula-virtual/canales/{canal.pk}/')
        assert r.status_code == 200
        assert str(canal.sala_uuid) in r.json()['data']['url_jitsi']

    def test_sala_uuid_no_se_expone_como_campo_suelto(self, docente, materia, periodo):
        canal = self._canal(docente, materia, periodo)
        datos = api(docente.usuario).get(f'/api/aula-virtual/canales/{canal.pk}/').json()['data']
        assert 'sala_uuid' not in datos

    def test_reentrar_no_duplica_participante(self, docente, materia, periodo, estudiante):
        canal = self._canal(docente, materia, periodo)
        Matricula.objects.create(estudiante=estudiante, materia=materia, periodo=periodo)
        sesion = self._sesion(canal)
        cliente = api(estudiante.usuario)
        cliente.post(f'/api/aula-virtual/sesiones/{sesion.pk}/unirme/', {}, format='json')
        cliente.post(f'/api/aula-virtual/sesiones/{sesion.pk}/salir/', {}, format='json')
        cliente.post(f'/api/aula-virtual/sesiones/{sesion.pk}/unirme/', {}, format='json')
        assert ParticipanteSesion.objects.filter(sesion=sesion).count() == 1
        # Al reentrar vuelve a estar "dentro": la salida anterior se limpia.
        assert ParticipanteSesion.objects.get(sesion=sesion).hora_salida is None

    def test_unirse_pone_la_sesion_en_curso(self, docente, materia, periodo):
        canal = self._canal(docente, materia, periodo)
        sesion = self._sesion(canal)
        api(docente.usuario).post(f'/api/aula-virtual/sesiones/{sesion.pk}/unirme/', {}, format='json')
        sesion.refresh_from_db()
        assert sesion.estado == 'EN_CURSO'

    def test_estudiante_no_puede_cerrar_la_clase(self, docente, materia, periodo, estudiante):
        canal = self._canal(docente, materia, periodo)
        Matricula.objects.create(estudiante=estudiante, materia=materia, periodo=periodo)
        sesion = self._sesion(canal)
        r = api(estudiante.usuario).post(
            f'/api/aula-virtual/sesiones/{sesion.pk}/cerrar/', {}, format='json')
        assert r.status_code == 403

    def test_cerrar_consolida_minutos_de_quien_no_marco_salida(
            self, docente, materia, periodo, estudiante, monkeypatch):
        import apps.aula_virtual.sisca_sync as sync
        monkeypatch.setattr(sync, 'enviar_asistencia', lambda s: (True, 'ok simulado'))

        canal = self._canal(docente, materia, periodo)
        sesion = self._sesion(canal)
        ParticipanteSesion.objects.create(
            sesion=sesion, usuario=estudiante.usuario,
            hora_entrada=timezone.now() - datetime.timedelta(minutes=45))

        r = api(docente.usuario).post(
            f'/api/aula-virtual/sesiones/{sesion.pk}/cerrar/', {}, format='json')
        assert r.status_code == 200
        p = ParticipanteSesion.objects.get(sesion=sesion)
        assert p.hora_salida is not None
        assert 44 <= p.minutos_acumulados <= 46

    def test_sisca_caido_no_impide_cerrar_la_clase(
            self, docente, materia, periodo, estudiante, monkeypatch):
        """El cierre es la operación del docente; el envío a SISCA es un
        efecto secundario que puede fallar y reintentarse después."""
        from apps.integracion_sisca.cliente import ClienteSISCAError
        import apps.aula_virtual.sisca_sync as sync

        def explota(self, payload):
            raise ClienteSISCAError('SISCA no respondió')
        monkeypatch.setattr(sync.ClienteAsistenciaVirtual, 'publicar_asistencia_virtual', explota)

        canal = self._canal(docente, materia, periodo)
        sesion = self._sesion(canal)
        ParticipanteSesion.objects.create(
            sesion=sesion, usuario=estudiante.usuario, hora_entrada=timezone.now())

        r = api(docente.usuario).post(
            f'/api/aula-virtual/sesiones/{sesion.pk}/cerrar/', {}, format='json')
        assert r.status_code == 200
        assert r.json()['data']['sincronizacion_sisca']['enviada'] is False
        sesion.refresh_from_db()
        assert sesion.estado == 'FINALIZADA'          # la clase SÍ quedó cerrada
        assert sesion.sincronizada_sisca is False     # y el envío queda pendiente
        assert 'SISCA no respondió' in sesion.error_sincronizacion

    def test_payload_a_sisca_marca_asistio_por_mitad_de_la_clase(
            self, docente, materia, periodo, estudiante, otro_estudiante):
        from apps.aula_virtual.sisca_sync import construir_payload
        canal = self._canal(docente, materia, periodo)
        sesion = self._sesion(canal)  # 60 minutos
        ahora = timezone.now()
        ParticipanteSesion.objects.create(
            sesion=sesion, usuario=estudiante.usuario, hora_entrada=ahora,
            hora_salida=ahora, minutos_acumulados=45)
        ParticipanteSesion.objects.create(
            sesion=sesion, usuario=otro_estudiante.usuario, hora_entrada=ahora,
            hora_salida=ahora, minutos_acumulados=10)

        por_correo = {p['correo']: p for p in construir_payload(sesion)['participantes']}
        assert por_correo[estudiante.usuario.correo]['asistio'] is True
        assert por_correo[otro_estudiante.usuario.correo]['asistio'] is False


# ════════════════════════════════════════════════════════════
#  apps.evaluacion_docente
# ════════════════════════════════════════════════════════════
class TestNotasPorVoz:

    def _payload(self, materia, estudiante):
        return {
            'materia': materia.pk, 'estudiante_codigo': estudiante.codigo,
            'descripcion': 'Taller 3', 'nota': '4.2', 'origen': 'VOZ',
            'texto_transcrito': 'cuatro punto dos para Sara',
        }

    def test_nota_dictada_nace_en_borrador_aunque_se_pida_confirmada(
            self, docente, materia, estudiante):
        datos = self._payload(materia, estudiante)
        datos['estado'] = 'CONFIRMADO'  # el cliente lo intenta
        r = api(docente.usuario).post(
            '/api/evaluacion-docente/calificaciones/crear/', datos, format='json')
        assert r.status_code == 201
        assert r.json()['data']['estado'] == 'BORRADOR'
        assert r.json()['data']['confirmado_por'] is None

    def test_nota_fuera_de_escala_es_rechazada(self, docente, materia, estudiante):
        datos = self._payload(materia, estudiante)
        datos['nota'] = '7.5'
        r = api(docente.usuario).post(
            '/api/evaluacion-docente/calificaciones/crear/', datos, format='json')
        assert r.status_code == 400
        assert 'nota' in r.json()['errors']

    def test_codigo_de_estudiante_inexistente_da_404(self, docente, materia, estudiante):
        datos = self._payload(materia, estudiante)
        datos['estudiante_codigo'] = '00000000'
        r = api(docente.usuario).post(
            '/api/evaluacion-docente/calificaciones/crear/', datos, format='json')
        assert r.status_code == 404

    def test_confirmar_deja_rastro_de_quien_y_cuando(self, docente, materia, estudiante):
        cliente = api(docente.usuario)
        cal_id = cliente.post('/api/evaluacion-docente/calificaciones/crear/',
                              self._payload(materia, estudiante),
                              format='json').json()['data']['id_calificacion']
        r = cliente.post(f'/api/evaluacion-docente/calificaciones/{cal_id}/confirmar/',
                         {}, format='json')
        assert r.status_code == 200
        cal = Calificacion.objects.get(pk=cal_id)
        assert cal.estado == 'CONFIRMADO'
        assert cal.confirmado_por_id == docente.usuario.pk
        assert cal.fecha_confirmacion is not None

    def test_confirmar_permite_corregir_la_nota_sin_perder_la_transcripcion(
            self, docente, materia, estudiante):
        cliente = api(docente.usuario)
        cal_id = cliente.post('/api/evaluacion-docente/calificaciones/crear/',
                              self._payload(materia, estudiante),
                              format='json').json()['data']['id_calificacion']
        cliente.post(f'/api/evaluacion-docente/calificaciones/{cal_id}/confirmar/',
                     {'nota': '3.8'}, format='json')
        cal = Calificacion.objects.get(pk=cal_id)
        assert cal.nota == Decimal('3.80')
        # La evidencia de qué se dictó NO se reescribe con la corrección.
        assert cal.texto_transcrito == 'cuatro punto dos para Sara'

    def test_una_nota_confirmada_no_se_descarta(self, docente, materia, estudiante):
        cliente = api(docente.usuario)
        cal_id = cliente.post('/api/evaluacion-docente/calificaciones/crear/',
                              self._payload(materia, estudiante),
                              format='json').json()['data']['id_calificacion']
        cliente.post(f'/api/evaluacion-docente/calificaciones/{cal_id}/confirmar/', {}, format='json')
        r = cliente.post(f'/api/evaluacion-docente/calificaciones/{cal_id}/descartar/',
                         {}, format='json')
        assert r.status_code == 409
        assert Calificacion.objects.filter(pk=cal_id).exists()

    def test_estudiante_no_ve_borradores_de_otros(self, docente, materia, estudiante, otro_estudiante):
        Calificacion.objects.create(
            materia=materia, estudiante=estudiante, docente=docente,
            descripcion='Taller', nota=Decimal('4.0'), estado='BORRADOR')
        r = api(otro_estudiante.usuario).get('/api/evaluacion-docente/calificaciones/')
        assert r.json()['total'] == 0

    def test_transcripcion_sin_audio_da_400(self, docente):
        r = api(docente.usuario).post('/api/notas/transcribir-audio', {}, format='multipart')
        assert r.status_code == 400

    def test_estudiante_no_puede_usar_la_transcripcion(self, estudiante):
        r = api(estudiante.usuario).post('/api/notas/transcribir-audio', {}, format='multipart')
        assert r.status_code == 403


class TestRubricas:

    def _rubrica_completa(self, docente, materia):
        r = Rubrica.objects.create(materia=materia, docente=docente, tema='Algoritmos')
        c1 = CriterioRubrica.objects.create(rubrica=r, nombre='Corrección', peso=Decimal('60'), orden=1)
        c2 = CriterioRubrica.objects.create(rubrica=r, nombre='Estilo', peso=Decimal('40'), orden=2)
        for c in (c1, c2):
            NivelDesempeno.objects.create(criterio=c, nombre='Superior', puntaje=Decimal('5'), orden=1)
            NivelDesempeno.objects.create(criterio=c, nombre='Básico', puntaje=Decimal('3'), orden=2)
        return r

    def test_matriz_cruza_criterios_por_niveles(self, docente, materia):
        rubrica = self._rubrica_completa(docente, materia)
        m = api(docente.usuario).get(
            f'/api/evaluacion-docente/rubricas/{rubrica.pk}/matriz/').json()['data']['matriz']
        assert m['niveles'] == ['Superior', 'Básico']
        assert len(m['filas']) == 2
        assert m['peso_total'] == 100.0
        assert m['avisos'] == []

    def test_matriz_avisa_cuando_los_pesos_no_suman_100(self, docente, materia):
        rubrica = Rubrica.objects.create(materia=materia, docente=docente, tema='Parcial')
        CriterioRubrica.objects.create(rubrica=rubrica, nombre='Único', peso=Decimal('70'))
        m = api(docente.usuario).get(
            f'/api/evaluacion-docente/rubricas/{rubrica.pk}/matriz/').json()['data']['matriz']
        assert any('70' in a for a in m['avisos'])

    def test_criterio_sin_ese_nivel_queda_en_blanco_no_en_cero(self, docente, materia):
        rubrica = Rubrica.objects.create(materia=materia, docente=docente, tema='Mixta')
        c1 = CriterioRubrica.objects.create(rubrica=rubrica, nombre='A', peso=Decimal('50'), orden=1)
        c2 = CriterioRubrica.objects.create(rubrica=rubrica, nombre='B', peso=Decimal('50'), orden=2)
        NivelDesempeno.objects.create(criterio=c1, nombre='Superior', puntaje=Decimal('5'))
        NivelDesempeno.objects.create(criterio=c2, nombre='Básico', puntaje=Decimal('3'))
        m = api(docente.usuario).get(
            f'/api/evaluacion-docente/rubricas/{rubrica.pk}/matriz/').json()['data']['matriz']
        fila_a = next(f for f in m['filas'] if f['criterio'] == 'A')
        basico = next(n for n in fila_a['niveles'] if n['nombre'] == 'Básico')
        assert basico['puntaje'] is None

    def test_exportar_matriz_devuelve_un_xlsx(self, docente, materia):
        rubrica = self._rubrica_completa(docente, materia)
        r = api(docente.usuario).get(f'/api/evaluacion-docente/rubricas/{rubrica.pk}/matriz.xlsx')
        assert r.status_code == 200
        assert 'spreadsheetml' in r['Content-Type']
        assert r['Content-Disposition'].startswith('attachment;')


class TestSyllabus:

    def _syllabus(self, docente, materia, periodo):
        syl = Syllabus.objects.create(
            materia=materia, periodo=periodo, docente=docente, version=1)
        unidad = UnidadSyllabus.objects.create(syllabus=syl, numero=1, titulo='Fundamentos')
        act = ActividadSyllabus.objects.create(
            unidad=unidad, nombre='Taller 1', fecha_planeada=datetime.date(2026, 8, 10))
        return syl, unidad, act

    def test_version_la_calcula_el_servidor(self, docente, materia, periodo):
        cliente = api(docente.usuario)
        datos = {'materia': materia.pk, 'periodo': periodo.pk, 'version': 99}
        v1 = cliente.post('/api/evaluacion-docente/syllabus/crear/', datos, format='json')
        v2 = cliente.post('/api/evaluacion-docente/syllabus/crear/', datos, format='json')
        assert v1.json()['data']['version'] == 1
        assert v2.json()['data']['version'] == 2

    def test_ajuste_sin_motivo_es_rechazado(self, docente, materia, periodo):
        syl, _, act = self._syllabus(docente, materia, periodo)
        r = api(docente.usuario).post(f'/api/evaluacion-docente/syllabus/{syl.pk}/ajustar/', {
            'objeto_tipo': 'ACTIVIDAD', 'objeto_id': act.pk,
            'campo': 'fecha_real', 'valor': '2026-08-17',
        }, format='json')
        assert r.status_code == 400
        assert 'motivo' in r.json()['error']
        act.refresh_from_db()
        assert act.fecha_real is None  # el cambio NO se aplicó

    def test_campo_fuera_de_la_lista_blanca_es_rechazado(self, docente, materia, periodo):
        syl, _, _ = self._syllabus(docente, materia, periodo)
        r = api(docente.usuario).post(f'/api/evaluacion-docente/syllabus/{syl.pk}/ajustar/', {
            'objeto_tipo': 'SYLLABUS', 'campo': 'docente',
            'valor': 1, 'motivo': 'intento de cambiar el dueño',
        }, format='json')
        assert r.status_code == 400

    def test_no_se_puede_ajustar_un_objeto_de_otro_syllabus(self, docente, materia, periodo):
        syl_a, _, _ = self._syllabus(docente, materia, periodo)
        syl_b = Syllabus.objects.create(
            materia=materia, periodo=periodo, docente=docente, version=2)
        unidad_b = UnidadSyllabus.objects.create(syllabus=syl_b, numero=1, titulo='Otra')
        act_b = ActividadSyllabus.objects.create(
            unidad=unidad_b, nombre='Ajena', fecha_planeada=datetime.date(2026, 9, 1))
        r = api(docente.usuario).post(f'/api/evaluacion-docente/syllabus/{syl_a.pk}/ajustar/', {
            'objeto_tipo': 'ACTIVIDAD', 'objeto_id': act_b.pk,
            'campo': 'fecha_real', 'valor': '2026-09-05', 'motivo': 'prueba',
        }, format='json')
        assert r.status_code == 404

    def test_ajuste_valido_queda_auditado_con_valores_anterior_y_nuevo(
            self, docente, materia, periodo):
        syl, _, act = self._syllabus(docente, materia, periodo)
        r = api(docente.usuario).post(f'/api/evaluacion-docente/syllabus/{syl.pk}/ajustar/', {
            'objeto_tipo': 'ACTIVIDAD', 'objeto_id': act.pk,
            'campo': 'fecha_real', 'valor': '2026-08-17',
            'motivo': 'Se corrió una semana por el paro de transporte',
        }, format='json')
        assert r.status_code == 201

        act.refresh_from_db()
        assert act.fecha_real == datetime.date(2026, 8, 17)
        assert act.dias_desfase == 7

        ajuste = HistorialAjusteSyllabus.objects.get(syllabus=syl, campo='fecha_real')
        # Un valor que antes era NULL se audita como cadena vacía, no como
        # el literal "None" (que parecería un valor real guardado).
        assert ajuste.valor_anterior == ''
        assert ajuste.valor_nuevo == '2026-08-17'
        assert ajuste.realizado_por_id == docente.usuario.pk
        assert 'paro de transporte' in ajuste.motivo

    def test_fecha_invalida_no_deja_ajuste_ni_auditoria(self, docente, materia, periodo):
        syl, _, act = self._syllabus(docente, materia, periodo)
        r = api(docente.usuario).post(f'/api/evaluacion-docente/syllabus/{syl.pk}/ajustar/', {
            'objeto_tipo': 'ACTIVIDAD', 'objeto_id': act.pk,
            'campo': 'fecha_real', 'valor': 'no-es-una-fecha', 'motivo': 'prueba',
        }, format='json')
        assert r.status_code == 400
        assert HistorialAjusteSyllabus.objects.count() == 0

    def test_publicar_archiva_la_version_anterior(self, docente, materia, periodo):
        v1 = Syllabus.objects.create(
            materia=materia, periodo=periodo, docente=docente, version=1, estado='VIGENTE')
        v2 = Syllabus.objects.create(
            materia=materia, periodo=periodo, docente=docente, version=2)
        r = api(docente.usuario).post(
            f'/api/evaluacion-docente/syllabus/{v2.pk}/publicar/', {}, format='json')
        assert r.status_code == 200
        v1.refresh_from_db(); v2.refresh_from_db()
        assert v1.estado == 'ARCHIVADO' and v2.estado == 'VIGENTE'
        assert HistorialAjusteSyllabus.objects.filter(syllabus=v2, campo='estado').exists()

    def test_otro_docente_no_puede_ajustar_un_syllabus_ajeno(
            self, docente, materia, periodo, facultad):
        syl, _, act = self._syllabus(docente, materia, periodo)
        intruso_user = _usuario('intruso@pi.edu.co', 'DOCENTE', 'Intruso', 'Docente')
        Docente.objects.create(usuario=intruso_user, facultad=facultad)
        r = api(intruso_user).post(f'/api/evaluacion-docente/syllabus/{syl.pk}/ajustar/', {
            'objeto_tipo': 'ACTIVIDAD', 'objeto_id': act.pk,
            'campo': 'fecha_real', 'valor': '2026-08-17', 'motivo': 'no debería poder',
        }, format='json')
        assert r.status_code == 403


# ════════════════════════════════════════════════════════════
#  Seguridad de los endpoints nuevos
# ════════════════════════════════════════════════════════════
class TestSeguridadModulos:
    """JWT, rate limiting y exposición de datos en los módulos nuevos.

    Se usa `APIClient` SIN `force_authenticate` a propósito: lo que se
    prueba aquí es justamente la capa de autenticación, que
    `force_authenticate` saltaría.
    """

    RUTAS = [
        '/api/eventos/',
        '/api/aula-virtual/canales/',
        '/api/evaluacion-docente/calificaciones/',
        '/api/evaluacion-docente/rubricas/',
        '/api/evaluacion-docente/syllabus/',
    ]

    @pytest.mark.parametrize('ruta', RUTAS)
    def test_sin_token_responde_401(self, ruta):
        assert APIClient().get(ruta).status_code == 401

    @pytest.mark.parametrize('ruta', RUTAS)
    def test_token_malformado_responde_401_y_no_500(self, ruta):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION='Bearer no-es-un-jwt')
        assert c.get(ruta).status_code == 401

    def test_jwt_expirado_responde_401(self, docente_user):
        from rest_framework_simplejwt.tokens import AccessToken
        token = AccessToken.for_user(docente_user)
        token.set_exp(from_time=timezone.now() - datetime.timedelta(days=2), lifetime=datetime.timedelta(minutes=1))
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        assert c.get('/api/eventos/').status_code == 401

    def test_jwt_firmado_con_otra_clave_responde_401(self, docente_user):
        import jwt as pyjwt
        payload = {'user_id': docente_user.pk, 'token_type': 'access',
                   'exp': int((timezone.now() + datetime.timedelta(hours=1)).timestamp()),
                   'jti': 'falso'}
        falso = pyjwt.encode(payload, 'clave-de-otro-sistema', algorithm='HS256')
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {falso}')
        assert c.get('/api/eventos/').status_code == 401

    def test_jwt_invalido_responde_json_no_html(self):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION='Bearer basura')
        r = c.get('/api/aula-virtual/canales/')
        assert r['Content-Type'].startswith('application/json')

    def test_rate_limit_del_endpoint_de_voz(self, docente, monkeypatch):
        """El endpoint de transcripción consume CPU del servidor; sin tope,
        un solo usuario puede tumbarlo.

        Se baja el límite en `SimpleRateThrottle.THROTTLE_RATES` en vez de
        tocar `settings`: DRF lee esas tarifas una sola vez, al importar, y
        las guarda como atributo de clase — cambiar settings en caliente no
        llega al throttle.
        """
        from django.core.cache import cache
        from rest_framework.throttling import SimpleRateThrottle

        cache.clear()
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, 'voz_transcripcion', '3/hour')

        cliente = api(docente.usuario)
        codigos = [cliente.post('/api/notas/transcribir-audio', {}, format='multipart').status_code
                   for _ in range(5)]
        cache.clear()
        assert 429 in codigos, f'sin rate limiting: {codigos}'
        # Las primeras sí pasan (y dan 400 por falta de audio): el tope
        # corta el abuso, no el uso normal.
        assert 400 in codigos

    def test_qr_de_otro_no_se_puede_consultar(self, docente_user, estudiante_user, otro_estudiante):
        """El token QR es la credencial de asistencia: sólo el inscrito y
        quien pueda escanear el evento deben poder verlo."""
        inicio = timezone.now() + datetime.timedelta(days=1)
        ev = Evento.objects.create(
            nombre='Grado', tipo='GRADO', fecha_inicio=inicio,
            fecha_fin=inicio + datetime.timedelta(hours=2), estado='PUBLICADO',
            propuesto_por=docente_user)
        insc = InscripcionEvento.objects.create(evento=ev, usuario=estudiante_user)
        r = api(otro_estudiante.usuario).get(f'/api/eventos/inscripciones/{insc.pk}/qr/')
        assert r.status_code == 403

    def test_escaneo_no_revela_si_el_token_existe_en_otro_evento(
            self, docente_user, estudiante_user):
        """Un mensaje distinto para "token de otro evento" permitiría sondear
        tokens ajenos a ciegas."""
        inicio = timezone.now() + datetime.timedelta(days=1)
        ev_a = Evento.objects.create(
            nombre='A', tipo='ACADEMICO', fecha_inicio=inicio,
            fecha_fin=inicio + datetime.timedelta(hours=1), estado='PUBLICADO',
            propuesto_por=docente_user)
        ev_b = Evento.objects.create(
            nombre='B', tipo='ACADEMICO', fecha_inicio=inicio,
            fecha_fin=inicio + datetime.timedelta(hours=1), estado='PUBLICADO',
            propuesto_por=docente_user)
        insc_b = InscripcionEvento.objects.create(evento=ev_b, usuario=estudiante_user)

        cliente = api(docente_user)
        import uuid as uuid_lib
        r_ajeno = cliente.post(f'/api/eventos/{ev_a.pk}/escanear/',
                               {'token_qr': str(insc_b.token_qr)}, format='json')
        r_inexistente = cliente.post(f'/api/eventos/{ev_a.pk}/escanear/',
                                     {'token_qr': str(uuid_lib.uuid4())}, format='json')
        assert r_ajeno.status_code == r_inexistente.status_code == 404
        assert r_ajeno.json()['error'] == r_inexistente.json()['error']

    def test_borrador_ajeno_no_es_visible_para_otro_usuario(self, docente_user, estudiante_user):
        inicio = timezone.now() + datetime.timedelta(days=1)
        ev = Evento.objects.create(
            nombre='Secreto', tipo='ACADEMICO', fecha_inicio=inicio,
            fecha_fin=inicio + datetime.timedelta(hours=1), estado='BORRADOR',
            propuesto_por=docente_user)
        assert api(estudiante_user).get(f'/api/eventos/{ev.pk}/').status_code == 403
        assert api(estudiante_user).get('/api/eventos/').json()['total'] == 0

    def test_filtro_invalido_da_400_y_no_lista_vacia_silenciosa(self, docente_user):
        r = api(docente_user).get('/api/eventos/?estado=NO_EXISTE')
        assert r.status_code == 400

    def test_cors_no_permite_cualquier_origen(self, settings):
        assert getattr(settings, 'CORS_ALLOW_ALL_ORIGINS', False) is False
        assert '*' not in settings.CORS_ALLOWED_ORIGINS
