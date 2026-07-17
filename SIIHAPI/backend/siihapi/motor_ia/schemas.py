"""
SIIHAPI - Schemas de validacion para salidas del LLM.

Cada vez que el LLM devuelve JSON, lo pasamos por estos schemas
para detectar campos faltantes, tipos incorrectos o valores fuera
de rango ANTES de guardar en BD o retornar al usuario.

Sin esta capa, un LLM que alucina o retorna JSON malformado
podria insertar horarios con codigos vacios, horas invalidas
o docentes inventados — bugs que en produccion son silenciosos.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import time as dtime
from typing import List, Optional, Tuple


# ── Helpers ───────────────────────────────────────────────────────────────────

_DIAS_VALIDOS = {'LUNES', 'MARTES', 'MIERCOLES', 'JUEVES', 'VIERNES', 'SABADO', 'DOMINGO'}
_HORA_RE      = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')


def _parse_hora(s: str) -> Optional[dtime]:
    s = str(s or '').strip()
    m = _HORA_RE.match(s)
    if not m:
        return None
    return dtime(int(m.group(1)), int(m.group(2)))


@dataclass
class HorarioExtraido:
    """Representa un horario tal como lo devuelve el LLM / parser de archivos."""
    codigo_materia: str
    nombre_materia: str
    dia:            str
    hora_inicio:    str
    hora_fin:       str
    docente:        str         = ''
    docente_email:  str         = ''
    salon:          str         = ''
    grupo:          str         = 'A'
    creditos:       int         = 3

    # campos calculados tras validacion
    _errores: List[str] = field(default_factory=list, repr=False)
    _hora_inicio_obj: Optional[dtime] = field(default=None, repr=False)
    _hora_fin_obj:    Optional[dtime] = field(default=None, repr=False)

    @property
    def es_valido(self) -> bool:
        return len(self._errores) == 0

    @property
    def errores(self) -> List[str]:
        return self._errores

    def validar(self) -> 'HorarioExtraido':
        """Valida todos los campos y rellena _errores. Retorna self (fluent)."""
        errs = []

        # codigo_materia
        c = str(self.codigo_materia or '').strip()
        if not c:
            errs.append("codigo_materia vacio")
        elif len(c) > 30:
            errs.append(f"codigo_materia demasiado largo ({len(c)} chars)")
        else:
            self.codigo_materia = c.upper()

        # nombre_materia
        n = str(self.nombre_materia or '').strip()
        if not n:
            errs.append("nombre_materia vacio")
        elif len(n) > 120:
            self.nombre_materia = n[:120]
        else:
            self.nombre_materia = n

        # dia
        dia = str(self.dia or '').strip().upper()
        if dia not in _DIAS_VALIDOS:
            errs.append(f"dia invalido: '{self.dia}' (validos: {sorted(_DIAS_VALIDOS)})")
        else:
            self.dia = dia

        # hora_inicio / hora_fin
        hi = _parse_hora(self.hora_inicio)
        hf = _parse_hora(self.hora_fin)
        if hi is None:
            errs.append(f"hora_inicio invalida: '{self.hora_inicio}'")
        if hf is None:
            errs.append(f"hora_fin invalida: '{self.hora_fin}'")
        if hi and hf:
            if hf <= hi:
                errs.append(f"hora_fin ({self.hora_fin}) debe ser > hora_inicio ({self.hora_inicio})")
            duracion_h = (hf.hour * 60 + hf.minute - hi.hour * 60 - hi.minute) / 60
            if duracion_h > 6:
                errs.append(f"duracion sospechosa: {duracion_h:.1f}h (max 6h)")
            self._hora_inicio_obj = hi
            self._hora_fin_obj    = hf

        # creditos
        try:
            c_int = int(self.creditos)
            if not (1 <= c_int <= 10):
                errs.append(f"creditos fuera de rango: {c_int}")
            else:
                self.creditos = c_int
        except (TypeError, ValueError):
            self.creditos = 3  # default seguro

        # email docente (opcional pero si viene debe tener @)
        em = str(self.docente_email or '').strip().lower()
        if em and '@' not in em:
            errs.append(f"docente_email invalido: '{em}'")
        self.docente_email = em

        self._errores = errs
        return self


@dataclass
class ResultadoValidacion:
    """
    Resultado de validar una lista de HorarioExtraido.

    confianza_global: 0-100, calculada como:
        80% peso en % de filas validas
        20% peso en completitud de campos opcionales
    """
    horarios_validos:    List[HorarioExtraido] = field(default_factory=list)
    horarios_invalidos:  List[HorarioExtraido] = field(default_factory=list)
    confianza_global:    int   = 0
    advertencias:        List[str] = field(default_factory=list)
    requiere_revision:   bool  = False   # True si confianza < 75

    @classmethod
    def desde_lista(cls, horarios: List[HorarioExtraido]) -> 'ResultadoValidacion':
        rv = cls()
        if not horarios:
            rv.advertencias.append("El LLM/parser no extrajo ningun horario.")
            rv.confianza_global = 0
            rv.requiere_revision = True
            return rv

        for h in horarios:
            h.validar()
            if h.es_valido:
                rv.horarios_validos.append(h)
            else:
                rv.horarios_invalidos.append(h)

        total = len(horarios)
        pct_validos = len(rv.horarios_validos) / total * 100

        # completitud de campos opcionales en los validos
        if rv.horarios_validos:
            con_docente = sum(1 for h in rv.horarios_validos if h.docente)
            con_salon   = sum(1 for h in rv.horarios_validos if h.salon)
            v = len(rv.horarios_validos)
            completitud = ((con_docente + con_salon) / (v * 2)) * 100
        else:
            completitud = 0

        rv.confianza_global = int(pct_validos * 0.8 + completitud * 0.2)

        if rv.horarios_invalidos:
            rv.advertencias.append(
                f"{len(rv.horarios_invalidos)}/{total} filas tienen errores y fueron descartadas."
            )
        if rv.confianza_global < 75:
            rv.requiere_revision = True
            rv.advertencias.append(
                f"Confianza {rv.confianza_global}% < 75% — se recomienda revision manual antes de aprobar."
            )

        return rv

    def resumen(self) -> dict:
        return {
            'total_extraidos':    len(self.horarios_validos) + len(self.horarios_invalidos),
            'validos':            len(self.horarios_validos),
            'invalidos':          len(self.horarios_invalidos),
            'confianza_global':   self.confianza_global,
            'requiere_revision':  self.requiere_revision,
            'advertencias':       self.advertencias,
            'errores_detalle':    [
                {'fila': i + 1, 'errores': h.errores,
                 'codigo': h.codigo_materia, 'nombre': h.nombre_materia}
                for i, h in enumerate(self.horarios_invalidos)
            ],
        }
