"""
SIIHAPI - Motor IA Hibrido.

Arquitectura:
    1. CSP Solver (OR-Tools / python-constraint / heuristico fallback)
       Resuelve el problema combinatorio: asigna horarios sin choques.
    2. LLM Analyst -- 5 agentes (Gemini / OpenAI / Anthropic Claude /
       Microsoft Copilot vía Azure OpenAI / heuristico local; ver el
       paquete .agentes) que analizan el resultado, explican en lenguaje
       natural y sugieren mejoras.

El motor selecciona automaticamente la mejor implementacion disponible
segun las librerias instaladas y las API keys configuradas.
"""

from .solver import resolver_csp, SolverResult, SolverError  # noqa
from .llm import (
    analizar_horario_con_ia,
    proveedor_disponible,
    LLMResult,
    chat_llm,
)  # noqa
from .agentes import (  # noqa
    AgenteIA, AgenteGemini, AgenteOpenAI, AgenteAnthropic,
    AgenteCopilot, AgenteHeuristico,
    obtener_agente, agentes_disponibles, todos_los_agentes,
)
