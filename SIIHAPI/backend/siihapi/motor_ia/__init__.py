"""
SIIHAPI - Motor IA Hibrido.

Arquitectura:
    1. CSP Solver (OR-Tools / python-constraint / heuristico fallback)
       Resuelve el problema combinatorio: asigna horarios sin choques.
    2. LLM Analyst (Gemini / OpenAI / Claude / heuristico fallback)
       Analiza el resultado, explica en lenguaje natural, sugiere mejoras.

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
