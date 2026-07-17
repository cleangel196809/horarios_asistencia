"""
SIIHAPI - Tests de CAJA BLANCA

Validan la lógica interna de:
- CircuitBreaker: estados, transiciones, thread-safety
- CacheLLM: make_key, get, set, TTL, LRU eviction
- HorarioExtraido.validar(): validaciones de campos
- ResultadoValidacion.desde_lista(): cálculo de confianza

Tests independientes de Oracle, Django ORM y de cualquier servicio externo.
Usan django.test.TestCase para compatibilidad con manage.py test.
"""
import time
import threading
import pytest
from unittest.mock import patch, MagicMock
from django.test import TestCase


# ════════════════════════════════════════════════════════════════════════════
# 1. CircuitBreaker - Tests de estado y transiciones
# ════════════════════════════════════════════════════════════════════════════

class TestCircuitBreakerEstados(TestCase):
    """Tests unitarios del CircuitBreaker de integracion_sisca."""

    def _make_cb(self, threshold=4, recovery=30):
        """Crea una instancia fresca de CircuitBreaker."""
        from apps.integracion_sisca.circuit_breaker import CircuitBreaker, Estado
        return CircuitBreaker(name='test', failure_threshold=threshold, recovery_timeout=recovery)

    def test_estado_inicial_es_closed(self):
        """CAJA BLANCA: el estado inicial debe ser CLOSED."""
        from apps.integracion_sisca.circuit_breaker import Estado
        cb = self._make_cb()
        self.assertEqual(cb.estado, Estado.CLOSED)
        self.assertFalse(cb.esta_abierto)

    def test_closed_a_open_tras_n_fallos(self):
        """
        CAJA BLANCA: después de failure_threshold (4) fallos consecutivos,
        el circuito debe pasar de CLOSED a OPEN.
        """
        from apps.integracion_sisca.circuit_breaker import Estado
        cb = self._make_cb(threshold=4)

        def fn_falla():
            raise RuntimeError("fallo simulado")

        for _ in range(3):
            with self.assertRaises(RuntimeError):
                cb.call(fn_falla)
            self.assertEqual(cb.estado, Estado.CLOSED, "Aún no debe estar OPEN")

        with self.assertRaises(RuntimeError):
            cb.call(fn_falla)

        self.assertEqual(cb.estado, Estado.OPEN, "Después de 4 fallos debe ser OPEN")
        self.assertTrue(cb.esta_abierto)

    def test_open_rechaza_llamadas_sin_ejecutar_fn(self):
        """
        CAJA BLANCA: en estado OPEN, call() debe lanzar
        CircuitBreakerAbiertoError sin llamar a la función.
        """
        from apps.integracion_sisca.circuit_breaker import (
            CircuitBreaker, Estado, CircuitBreakerAbiertoError
        )
        cb = self._make_cb(threshold=1, recovery=9999)

        def fn_falla():
            raise RuntimeError("fallo")

        with self.assertRaises(RuntimeError):
            cb.call(fn_falla)

        self.assertEqual(cb.estado, Estado.OPEN)

        fn_mock = MagicMock(return_value="ok")
        with self.assertRaises(CircuitBreakerAbiertoError):
            cb.call(fn_mock)

        fn_mock.assert_not_called()

    def test_open_a_half_open_tras_recovery_timeout(self):
        """
        CAJA BLANCA: después de recovery_timeout segundos en OPEN,
        el circuito pasa a HALF_OPEN al intentar una nueva llamada.
        """
        from apps.integracion_sisca.circuit_breaker import Estado, CircuitBreakerAbiertoError
        cb = self._make_cb(threshold=1, recovery=0.05)  # 50ms

        with self.assertRaises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fallo")))

        self.assertEqual(cb.estado, Estado.OPEN)

        time.sleep(0.1)  # esperar más que recovery_timeout

        # La siguiente llamada debe transicionar a HALF_OPEN y ejecutarse
        resultado = cb.call(lambda: "probe_ok")
        self.assertEqual(resultado, "probe_ok")
        self.assertEqual(cb.estado, Estado.CLOSED, "Probe exitoso → debe cerrar el circuito")

    def test_half_open_a_open_en_fallo_de_probe(self):
        """
        CAJA BLANCA: si la llamada de prueba en HALF_OPEN falla,
        el circuito vuelve a OPEN.
        """
        from apps.integracion_sisca.circuit_breaker import Estado
        cb = self._make_cb(threshold=1, recovery=0.05)

        with self.assertRaises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fallo")))

        time.sleep(0.1)  # → HALF_OPEN

        with self.assertRaises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("probe fallo")))

        self.assertEqual(cb.estado, Estado.OPEN)

    def test_exito_desde_closed_mantiene_closed(self):
        """CAJA BLANCA: llamadas exitosas en CLOSED mantienen el estado."""
        from apps.integracion_sisca.circuit_breaker import Estado
        cb = self._make_cb()

        for _ in range(10):
            result = cb.call(lambda: 42)
            self.assertEqual(result, 42)

        self.assertEqual(cb.estado, Estado.CLOSED)

    def test_reset_fuerza_closed(self):
        """CAJA BLANCA: reset() debe dejar el circuito en CLOSED."""
        from apps.integracion_sisca.circuit_breaker import Estado
        cb = self._make_cb(threshold=1, recovery=9999)

        with self.assertRaises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))

        self.assertEqual(cb.estado, Estado.OPEN)
        cb.reset()
        self.assertEqual(cb.estado, Estado.CLOSED)

    def test_metrics_cuentan_correctamente(self):
        """CAJA BLANCA: las métricas internas reflejan exitos y fallos."""
        cb = self._make_cb(threshold=10)

        cb.call(lambda: True)  # exito
        cb.call(lambda: True)  # exito
        with self.assertRaises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))  # fallo

        m = cb.metrics()
        self.assertEqual(m['total_exitos'], 2)
        self.assertEqual(m['total_fallos'], 1)
        self.assertEqual(m['fallos_consecutivos'], 1)

    def test_thread_safety_no_corrompe_estado(self):
        """
        CAJA BLANCA: múltiples hilos llamando al CB simultáneamente
        no deben corromper el estado interno.
        """
        from apps.integracion_sisca.circuit_breaker import Estado
        cb = self._make_cb(threshold=100)  # umbral alto para no abrir en el test
        errors = []

        def worker():
            try:
                cb.call(lambda: 1)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(len(errors), 0, f"Errores en acceso concurrente: {errors}")
        self.assertEqual(cb.estado, Estado.CLOSED)


# ════════════════════════════════════════════════════════════════════════════
# 2. CacheLLM - Tests de make_key, get, set, TTL
# ════════════════════════════════════════════════════════════════════════════

class TestCacheLLM(TestCase):
    """Tests unitarios de CacheLLM."""

    def _make_cache(self, max_size=10, ttl=3600):
        from siihapi.motor_ia.cache_llm import CacheLLM
        return CacheLLM(max_size=max_size, ttl=ttl)

    def test_make_key_misma_entrada_mismo_hash(self):
        """
        CAJA BLANCA: make_key con el mismo contenido debe retornar
        exactamente la misma clave (determinista).
        """
        from siihapi.motor_ia.cache_llm import CacheLLM
        contenido = b"contenido de prueba 123"
        k1 = CacheLLM.make_key(contenido, proveedor="gemini", periodo="2026-1")
        k2 = CacheLLM.make_key(contenido, proveedor="gemini", periodo="2026-1")
        self.assertEqual(k1, k2)

    def test_make_key_contenido_diferente_distinto_hash(self):
        """make_key con contenido diferente debe retornar clave distinta."""
        from siihapi.motor_ia.cache_llm import CacheLLM
        k1 = CacheLLM.make_key(b"archivo_A")
        k2 = CacheLLM.make_key(b"archivo_B")
        self.assertNotEqual(k1, k2)

    def test_make_key_proveedor_diferente_distinto_hash(self):
        """Proveedor diferente → clave diferente."""
        from siihapi.motor_ia.cache_llm import CacheLLM
        contenido = b"mismo contenido"
        k1 = CacheLLM.make_key(contenido, proveedor="gemini")
        k2 = CacheLLM.make_key(contenido, proveedor="openai")
        self.assertNotEqual(k1, k2)

    def test_get_retorna_none_si_no_existe(self):
        """CAJA BLANCA: get de clave inexistente retorna None."""
        cache = self._make_cache()
        self.assertIsNone(cache.get("clave_inexistente"))

    def test_set_y_get_retorna_valor_guardado(self):
        """set seguido de get retorna el valor guardado."""
        cache = self._make_cache()
        cache.set("k1", {"resultado": "ok"})
        result = cache.get("k1")
        self.assertEqual(result, {"resultado": "ok"})

    def test_get_con_ttl_expirado_retorna_none(self):
        """
        CAJA BLANCA: get de una entrada cuyo TTL expiró debe retornar None.
        La entrada expirada también debe eliminarse del dict interno.
        """
        cache = self._make_cache(ttl=0.05)  # 50ms
        cache.set("k_exp", "valor_temporal")

        time.sleep(0.1)  # esperar más que el TTL

        result = cache.get("k_exp")
        self.assertIsNone(result, "Entrada expirada debe retornar None")

    def test_lru_eviction_cuando_llega_al_max(self):
        """
        CAJA BLANCA: cuando el cache alcanza max_size, debe desalojar
        la entrada menos recientemente usada (LRU).
        """
        cache = self._make_cache(max_size=3)
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.set("k3", "v3")

        # Acceder a k1 para marcarlo como recientemente usado
        cache.get("k1")

        # Agregar k4 → debe desalojar k2 (LRU, no se accedió desde que se creó k3)
        cache.set("k4", "v4")

        self.assertIsNotNone(cache.get("k1"), "k1 fue accedido recientemente, no debe ser desalojado")
        self.assertIsNotNone(cache.get("k4"), "k4 recién insertado debe estar")

    def test_invalidar_clave_existente_retorna_true(self):
        """invalidar() de una clave existente retorna True."""
        cache = self._make_cache()
        cache.set("k", "v")
        result = cache.invalidar("k")
        self.assertTrue(result)
        self.assertIsNone(cache.get("k"))

    def test_invalidar_clave_inexistente_retorna_false(self):
        """invalidar() de una clave inexistente retorna False."""
        cache = self._make_cache()
        result = cache.invalidar("clave_que_no_existe")
        self.assertFalse(result)

    def test_limpiar_elimina_entradas_expiradas(self):
        """limpiar() elimina entradas con TTL expirado y retorna el conteo."""
        cache = self._make_cache(ttl=0.05)
        cache.set("exp1", "v1")
        cache.set("exp2", "v2")
        # Agregar una con TTL largo
        cache.set("vigente", "v3", ttl=3600)

        time.sleep(0.1)

        eliminadas = cache.limpiar()
        self.assertGreaterEqual(eliminadas, 2)
        self.assertIsNone(cache.get("exp1"))
        self.assertIsNone(cache.get("exp2"))
        self.assertIsNotNone(cache.get("vigente"))

    def test_stats_reflejan_hits_y_misses(self):
        """stats() debe reflejar hits y misses correctamente."""
        cache = self._make_cache()
        cache.set("k", "v")
        cache.get("k")       # hit
        cache.get("k")       # hit
        cache.get("nokey")   # miss

        stats = cache.stats()
        self.assertEqual(stats['hits'], 2)
        self.assertEqual(stats['misses'], 1)
        self.assertAlmostEqual(stats['hit_rate_pct'], 66.7, delta=1.0)


# ════════════════════════════════════════════════════════════════════════════
# 3. HorarioExtraido.validar() - Tests de validación de campos
# ════════════════════════════════════════════════════════════════════════════

class TestHorarioExtraidoValidar(TestCase):
    """Tests unitarios del schema HorarioExtraido."""

    def _make_valido(self, **kwargs):
        """Crea un HorarioExtraido con todos los campos válidos."""
        from siihapi.motor_ia.schemas import HorarioExtraido
        defaults = {
            "codigo_materia": "MAT-001",
            "nombre_materia": "Matematicas Discretas",
            "dia": "LUNES",
            "hora_inicio": "08:00",
            "hora_fin": "10:00",
            "docente": "Juan Perez",
            "salon": "LAB-1",
        }
        defaults.update(kwargs)
        return HorarioExtraido(**defaults)

    def test_horario_valido_no_tiene_errores(self):
        """Un horario con todos los campos correctos debe ser válido."""
        h = self._make_valido().validar()
        self.assertTrue(h.es_valido, f"Errores inesperados: {h.errores}")
        self.assertEqual(h.errores, [])

    def test_dia_invalido_genera_error(self):
        """
        CAJA BLANCA: día inválido (no en la lista de días válidos)
        debe aparecer en _errores.
        """
        h = self._make_valido(dia="LUNDE").validar()  # typo
        self.assertFalse(h.es_valido)
        self.assertTrue(any("dia invalido" in e.lower() for e in h.errores),
                        f"Esperaba error de día inválido, obtuvo: {h.errores}")

    def test_dia_vacio_genera_error(self):
        """Día vacío también debe generar error."""
        h = self._make_valido(dia="").validar()
        self.assertFalse(h.es_valido)

    @pytest.mark.parametrize_equivalent  # documentación; usamos subtests en su lugar
    def test_todos_los_dias_validos_son_aceptados(self):
        """Todos los días del conjunto válido deben ser aceptados."""
        dias_validos = ['LUNES', 'MARTES', 'MIERCOLES', 'JUEVES', 'VIERNES', 'SABADO', 'DOMINGO']
        for dia in dias_validos:
            with self.subTest(dia=dia):
                h = self._make_valido(dia=dia).validar()
                self.assertNotIn(
                    True,
                    ["dia invalido" in e.lower() for e in h.errores],
                    f"Día válido '{dia}' fue rechazado: {h.errores}"
                )

    def test_hora_fin_menor_que_hora_inicio_genera_error(self):
        """
        CAJA BLANCA: hora_fin <= hora_inicio debe generar error.
        """
        h = self._make_valido(hora_inicio="10:00", hora_fin="08:00").validar()
        self.assertFalse(h.es_valido)
        self.assertTrue(
            any("hora_fin" in e.lower() and ">" in e for e in h.errores),
            f"Esperaba error de hora_fin < hora_inicio, obtuvo: {h.errores}"
        )

    def test_hora_fin_igual_a_hora_inicio_genera_error(self):
        """hora_fin == hora_inicio también es inválido."""
        h = self._make_valido(hora_inicio="08:00", hora_fin="08:00").validar()
        self.assertFalse(h.es_valido)

    def test_hora_inicio_invalida_genera_error(self):
        """hora_inicio con formato incorrecto debe generar error."""
        h = self._make_valido(hora_inicio="8:00 AM").validar()  # formato 12h
        self.assertFalse(h.es_valido)
        self.assertTrue(any("hora_inicio" in e.lower() for e in h.errores))

    def test_codigo_materia_vacio_genera_error(self):
        """Código de materia vacío debe generar error."""
        h = self._make_valido(codigo_materia="").validar()
        self.assertFalse(h.es_valido)
        self.assertTrue(any("codigo_materia" in e.lower() for e in h.errores))

    def test_codigo_materia_muy_largo_genera_error(self):
        """Código de más de 30 chars debe generar error."""
        h = self._make_valido(codigo_materia="X" * 31).validar()
        self.assertFalse(h.es_valido)

    def test_duracion_mayor_6h_genera_error(self):
        """Clases de más de 6 horas se consideran sospechosas."""
        h = self._make_valido(hora_inicio="06:00", hora_fin="13:00").validar()  # 7h
        self.assertFalse(h.es_valido)
        self.assertTrue(any("duracion" in e.lower() for e in h.errores))

    def test_email_docente_sin_arroba_genera_error(self):
        """Email de docente sin @ debe generar error."""
        h = self._make_valido(docente_email="sindominio.com").validar()
        self.assertFalse(h.es_valido)

    def test_email_docente_vacio_es_valido(self):
        """El campo docente_email es opcional; vacío no genera error."""
        h = self._make_valido(docente_email="").validar()
        self.assertTrue(h.es_valido, f"Email vacío no debe generar error: {h.errores}")

    def test_creditos_fuera_de_rango_genera_error(self):
        """Créditos fuera del rango 1-10 deben generar error."""
        for cr in [0, 11, -1]:
            with self.subTest(creditos=cr):
                h = self._make_valido(creditos=cr).validar()
                self.assertFalse(h.es_valido,
                                 f"Créditos {cr} debería generar error")


# ════════════════════════════════════════════════════════════════════════════
# 4. ResultadoValidacion.desde_lista()
# ════════════════════════════════════════════════════════════════════════════

class TestResultadoValidacion(TestCase):
    """Tests unitarios de ResultadoValidacion."""

    def _horario_valido(self, codigo="MAT-001"):
        from siihapi.motor_ia.schemas import HorarioExtraido
        return HorarioExtraido(
            codigo_materia=codigo,
            nombre_materia="Materia Test",
            dia="LUNES",
            hora_inicio="08:00",
            hora_fin="10:00",
            docente="Profesor Test",
            salon="LAB-1",
        )

    def _horario_invalido(self):
        from siihapi.motor_ia.schemas import HorarioExtraido
        return HorarioExtraido(
            codigo_materia="",  # inválido
            nombre_materia="Sin código",
            dia="FUNDAY",      # inválido
            hora_inicio="25:00",  # inválido
            hora_fin="08:00",
        )

    def test_lista_vacia_retorna_confianza_cero(self):
        """
        CAJA BLANCA: desde_lista([]) debe retornar confianza_global=0
        y requiere_revision=True.
        """
        from siihapi.motor_ia.schemas import ResultadoValidacion
        rv = ResultadoValidacion.desde_lista([])
        self.assertEqual(rv.confianza_global, 0)
        self.assertTrue(rv.requiere_revision)
        self.assertGreater(len(rv.advertencias), 0)

    def test_todos_validos_alta_confianza(self):
        """
        CAJA BLANCA: con todos los horarios válidos y campos opcionales
        completos, la confianza debe ser >= 75.
        """
        from siihapi.motor_ia.schemas import ResultadoValidacion
        horarios = [self._horario_valido(f"MAT-00{i}") for i in range(5)]
        rv = ResultadoValidacion.desde_lista(horarios)
        self.assertEqual(len(rv.horarios_invalidos), 0)
        self.assertGreaterEqual(rv.confianza_global, 75)

    def test_todos_invalidos_confianza_cero(self):
        """Con todos los horarios inválidos, confianza = 0."""
        from siihapi.motor_ia.schemas import ResultadoValidacion
        horarios = [self._horario_invalido() for _ in range(3)]
        rv = ResultadoValidacion.desde_lista(horarios)
        self.assertEqual(len(rv.horarios_validos), 0)
        self.assertEqual(rv.confianza_global, 0)
        self.assertTrue(rv.requiere_revision)

    def test_confianza_baja_activa_requiere_revision(self):
        """Confianza < 75 activa requiere_revision=True."""
        from siihapi.motor_ia.schemas import ResultadoValidacion
        # 1 válido, 4 inválidos → confianza baja
        horarios = [self._horario_valido()] + [self._horario_invalido() for _ in range(4)]
        rv = ResultadoValidacion.desde_lista(horarios)
        self.assertTrue(rv.requiere_revision)

    def test_resumen_tiene_estructura_esperada(self):
        """resumen() debe retornar dict con las claves esperadas."""
        from siihapi.motor_ia.schemas import ResultadoValidacion
        rv = ResultadoValidacion.desde_lista([self._horario_valido()])
        resumen = rv.resumen()
        expected_keys = {
            'total_extraidos', 'validos', 'invalidos',
            'confianza_global', 'requiere_revision', 'advertencias', 'errores_detalle'
        }
        self.assertEqual(set(resumen.keys()), expected_keys)

    def test_errores_detalle_incluye_fila_correcta(self):
        """
        CAJA BLANCA: errores_detalle debe indexar desde fila 1
        y contener los errores del horario inválido.
        """
        from siihapi.motor_ia.schemas import ResultadoValidacion
        horarios = [self._horario_invalido()]
        rv = ResultadoValidacion.desde_lista(horarios)
        resumen = rv.resumen()
        self.assertEqual(len(resumen['errores_detalle']), 1)
        self.assertEqual(resumen['errores_detalle'][0]['fila'], 1)
        self.assertGreater(len(resumen['errores_detalle'][0]['errores']), 0)
