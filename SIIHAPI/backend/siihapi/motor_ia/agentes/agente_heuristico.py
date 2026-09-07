"""SIIHAPI · Agente heuristico local (Fase 3, 2026-09-04).

Siempre disponible (no necesita red ni API key): reglas locales para
analizar, responder en chat y extraer horarios cuando ningun proveedor
externo esta configurado. Es el agente de respaldo final -- el registro
de agentes (registry.py) siempre puede devolver este si ningun otro
agente esta disponible."""
from ..llm import analizar_horario_con_ia, chat_llm, extraer_horarios_con_ia
from .base import AgenteIA


class AgenteHeuristico(AgenteIA):
    codigo = 'HEURISTIC'
    nombre_visible = 'Heurístico local'
    descripcion = 'Analizador por reglas, sin red ni API key. Siempre disponible.'
    icono = '⚙️'

    def disponible(self) -> bool:
        return True

    def analizar_horario(self, datos: dict):
        return analizar_horario_con_ia(datos, forzar_proveedor='HEURISTIC')

    def chat(self, mensaje: str, historial=None, contexto_archivo: str = '') -> dict:
        return chat_llm(mensaje, historial=historial, contexto_archivo=contexto_archivo,
                         forzar_proveedor='HEURISTIC')

    def extraer_horarios(self, texto: str, periodo: str = '2026-2', catalogo=None):
        return extraer_horarios_con_ia(texto, periodo=periodo, catalogo=catalogo,
                                        forzar_proveedor='HEURISTIC')
