"""SIIHAPI · Agente Anthropic Claude (Fase 3, 2026-09-04)."""
from ..llm import (
    _get_api_key, analizar_horario_con_ia, chat_llm, extraer_horarios_con_ia,
)
from .base import AgenteIA


class AgenteAnthropic(AgenteIA):
    codigo = 'ANTHROPIC'
    nombre_visible = 'Anthropic Claude'
    descripcion = 'Claude 3.5 Haiku vía ANTHROPIC_API_KEY.'
    icono = '🟣'

    def disponible(self) -> bool:
        if not _get_api_key('ANTHROPIC_API_KEY'):
            return False
        try:
            import anthropic  # noqa
            return True
        except ImportError:
            return False

    def analizar_horario(self, datos: dict):
        return analizar_horario_con_ia(datos, forzar_proveedor='ANTHROPIC')

    def chat(self, mensaje: str, historial=None, contexto_archivo: str = '') -> dict:
        return chat_llm(mensaje, historial=historial, contexto_archivo=contexto_archivo,
                         forzar_proveedor='ANTHROPIC')

    def extraer_horarios(self, texto: str, periodo: str = '2026-2', catalogo=None):
        return extraer_horarios_con_ia(texto, periodo=periodo, catalogo=catalogo,
                                        forzar_proveedor='ANTHROPIC')
