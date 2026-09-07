"""
SIIHAPI · Motor IA — Interfaz comun de "agente" para cada IA del modulo.

Fase 3 (2026-09-04). Cada IA que el Motor IA puede usar (Gemini, OpenAI,
Anthropic Claude, Microsoft Copilot y el analizador heuristico local) se
expone aqui como un "agente" con la misma interfaz: disponible(),
analizar_horario(), chat() y extraer_horarios(). Los agentes son wrappers
delgados sobre las funciones ya existentes y probadas en motor_ia/llm.py
(no reimplementan nada): el objetivo es dar una fachada uniforme para que
el resto del sistema (vistas, UI) pueda elegir/iterar sobre "los agentes
disponibles" sin conocer los detalles de cada proveedor.
"""
from abc import ABC, abstractmethod


class AgenteIA(ABC):
    """Contrato que cumple cada agente de IA del Motor IA."""

    #: Codigo interno (coincide con 'proveedor' en motor_ia/llm.py):
    #: 'GEMINI' | 'OPENAI' | 'ANTHROPIC' | 'COPILOT' | 'HEURISTIC'
    codigo: str = ''
    #: Nombre para mostrar en la interfaz.
    nombre_visible: str = ''
    #: Descripcion corta (que credenciales necesita, que modelo usa).
    descripcion: str = ''
    #: Emoji/insignia para la UI (opcional).
    icono: str = '🤖'

    @abstractmethod
    def disponible(self) -> bool:
        """True si este agente tiene lo que necesita para funcionar
        (API key configurada + libreria instalada)."""
        raise NotImplementedError

    @abstractmethod
    def analizar_horario(self, datos: dict):
        """Analiza un resumen de asignacion de horarios (dict) y devuelve
        un motor_ia.llm.LLMResult con resumen ejecutivo, sugerencias,
        anomalias y score de calidad."""
        raise NotImplementedError

    @abstractmethod
    def chat(self, mensaje: str, historial=None, contexto_archivo: str = '') -> dict:
        """Turno de chat conversacional. Devuelve un dict
        {success, respuesta, proveedor, modelo}."""
        raise NotImplementedError

    @abstractmethod
    def extraer_horarios(self, texto: str, periodo: str = '2026-2', catalogo=None):
        """Extrae horarios estructurados desde texto crudo de un documento.
        Devuelve (lista_de_dicts, proveedor, modelo)."""
        raise NotImplementedError

    def __repr__(self):
        return f'<Agente {self.codigo}: {self.nombre_visible}>'
