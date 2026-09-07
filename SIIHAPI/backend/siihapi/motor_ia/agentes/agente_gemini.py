"""SIIHAPI · Agente Google Gemini (Fase 3, 2026-09-04)."""
from ..llm import (
    _get_api_key, analizar_horario_con_ia, chat_llm, extraer_horarios_con_ia,
)
from .base import AgenteIA


class AgenteGemini(AgenteIA):
    codigo = 'GEMINI'
    nombre_visible = 'Google Gemini'
    descripcion = 'Gemini 2.5/2.0/1.5 Flash vía GEMINI_API_KEY.'
    icono = '🧠'

    def disponible(self) -> bool:
        if not _get_api_key('GEMINI_API_KEY'):
            return False
        try:
            import google.generativeai  # noqa
            return True
        except ImportError:
            return False

    def analizar_horario(self, datos: dict):
        return analizar_horario_con_ia(datos, forzar_proveedor='GEMINI')

    def chat(self, mensaje: str, historial=None, contexto_archivo: str = '') -> dict:
        return chat_llm(mensaje, historial=historial, contexto_archivo=contexto_archivo,
                         forzar_proveedor='GEMINI')

    def extraer_horarios(self, texto: str, periodo: str = '2026-2', catalogo=None):
        return extraer_horarios_con_ia(texto, periodo=periodo, catalogo=catalogo,
                                        forzar_proveedor='GEMINI')
