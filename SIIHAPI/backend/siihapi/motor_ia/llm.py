"""
SIIHAPI - Capa LLM (Large Language Model).

Conecta con Google Gemini, OpenAI o Anthropic Claude para:
    - Generar resumen ejecutivo del horario en lenguaje natural
    - Detectar anomalias y sugerir optimizaciones
    - Responder preguntas sobre el horario
    - Generar reportes formales

Selecciona automaticamente el proveedor segun la API key configurada:
    GEMINI_API_KEY    -> Google Gemini 1.5 Flash
    OPENAI_API_KEY    -> OpenAI GPT-4o-mini
    ANTHROPIC_API_KEY -> Claude 3.5 Haiku
    (ninguna)         -> Analizador heuristico local
"""
import os
import json
from dataclasses import dataclass
from typing import Optional, Dict, Any

from django.conf import settings


@dataclass
class LLMResult:
    proveedor: str
    modelo: str
    resumen_ejecutivo: str
    sugerencias: list
    anomalias: list
    score_calidad: int  # 0-100
    raw_response: str = ''


# ════════════════════════════════════════════════════════════════
#  Deteccion de proveedores disponibles
# ════════════════════════════════════════════════════════════════
def _get_api_key(nombre):
    """Busca primero en Django settings, luego en env vars."""
    siihapi_cfg = getattr(settings, 'SIIHAPI', {})
    return (
        siihapi_cfg.get(nombre)
        or os.environ.get(nombre)
        or ''
    )


def proveedor_disponible():
    """Retorna el primer proveedor con key valida."""
    if _get_api_key('GEMINI_API_KEY'):
        try:
            import google.generativeai  # noqa
            return 'GEMINI'
        except ImportError:
            pass
    if _get_api_key('OPENAI_API_KEY'):
        try:
            import openai  # noqa
            return 'OPENAI'
        except ImportError:
            pass
    if _get_api_key('ANTHROPIC_API_KEY'):
        try:
            import anthropic  # noqa
            return 'ANTHROPIC'
        except ImportError:
            pass
    return 'HEURISTIC'


# ════════════════════════════════════════════════════════════════
#  Prompt base
# ════════════════════════════════════════════════════════════════
PROMPT_TEMPLATE = """Actua como un experto en planificacion academica universitaria.
Te paso datos de una asignacion de horarios generada por un solver CSP para el Politecnico Internacional.

Datos del periodo {periodo}:
- Total matriculas activas: {total_matriculas}
- Horarios asignados: {asignadas}
- Conflictos no resueltos: {conflictos}
- Tasa de exito: {tasa_exito}%
- Algoritmo usado: {algoritmo}
- Duracion del solver: {duracion_ms} ms
- Sedes activas: {sedes}
- Salones disponibles: {salones}
- Docentes disponibles: {docentes}

Distribucion por dia:
{distribucion_dia}

Distribucion por tipo de salon:
{distribucion_salon}

Carga por docente (top 5):
{carga_docente}

Responde EN JSON con esta estructura exacta:
{{
  "resumen_ejecutivo": "(2-3 frases en español, profesional, sobre la calidad de la asignacion)",
  "sugerencias": ["(sugerencia 1)", "(sugerencia 2)", "(sugerencia 3)"],
  "anomalias": ["(anomalia 1)", "(anomalia 2)"],
  "score_calidad": (entero 0-100)
}}

Importante: responde SOLO con el JSON, sin markdown, sin texto antes ni despues."""


# ════════════════════════════════════════════════════════════════
#  IMPLEMENTACION 1: Google Gemini
# ════════════════════════════════════════════════════════════════
GEMINI_MODELOS = [
    'gemini-2.5-flash',         # mas reciente
    'gemini-2.0-flash',
    'gemini-2.0-flash-exp',
    'gemini-1.5-flash-002',
    'gemini-1.5-flash-latest',
    'gemini-pro',
]


def _llm_gemini(prompt, api_key):
    """Prueba varios modelos en orden hasta encontrar uno disponible."""
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    ultimo_error = None
    for modelo in GEMINI_MODELOS:
        try:
            model = genai.GenerativeModel(modelo)
            response = model.generate_content(prompt)
            return response.text, modelo
        except Exception as e:
            ultimo_error = e
            # Solo seguimos si es error de modelo, no de auth
            if '404' in str(e) or 'not found' in str(e).lower() or 'not supported' in str(e).lower():
                continue
            raise
    raise Exception(f'Ningun modelo Gemini funciono. Ultimo error: {ultimo_error}')


# ════════════════════════════════════════════════════════════════
#  IMPLEMENTACION 2: OpenAI
# ════════════════════════════════════════════════════════════════
def _llm_openai(prompt, api_key):
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[{'role': 'user', 'content': prompt}],
        response_format={'type': 'json_object'},
        max_tokens=600,
    )
    return response.choices[0].message.content, 'gpt-4o-mini'


# ════════════════════════════════════════════════════════════════
#  IMPLEMENTACION 3: Anthropic Claude
# ════════════════════════════════════════════════════════════════
def _llm_anthropic(prompt, api_key):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model='claude-3-5-haiku-20241022',
        max_tokens=600,
        messages=[{'role': 'user', 'content': prompt}],
    )
    return response.content[0].text, 'claude-3-5-haiku'


# ════════════════════════════════════════════════════════════════
#  IMPLEMENTACION 4: Analizador heuristico local (sin API key)
# ════════════════════════════════════════════════════════════════
def _llm_heuristico(datos):
    """Genera un analisis basado en reglas sin necesidad de API externa."""
    tasa = datos['tasa_exito']
    conflictos = datos['conflictos']
    matriculas = datos['total_matriculas']

    # Resumen
    if tasa >= 95:
        resumen = (f"La asignacion del periodo {datos['periodo']} fue exitosa con una tasa del "
                   f"{tasa}%. El solver {datos['algoritmo']} logro asignar {datos['asignadas']} "
                   f"horarios en {datos['duracion_ms']} ms, cumpliendo con los RNF-04 (<60s).")
    elif tasa >= 80:
        resumen = (f"La asignacion del periodo {datos['periodo']} fue aceptable con tasa de "
                   f"{tasa}%, pero quedaron {conflictos} matriculas sin asignar. Se recomienda "
                   f"revisar la disponibilidad de docentes y salones.")
    else:
        resumen = (f"La asignacion del periodo {datos['periodo']} requiere atencion: solo se logro "
                   f"el {tasa}% de cobertura con {conflictos} conflictos no resueltos.")

    # Sugerencias basadas en reglas
    sugerencias = []
    if tasa < 100:
        sugerencias.append(
            f"Aumentar la disponibilidad de docentes: actualmente hay {datos['docentes']} para "
            f"{matriculas} matriculas (ratio {matriculas/max(datos['docentes'],1):.1f}:1)."
        )
    if conflictos > matriculas * 0.05:
        sugerencias.append(
            "Reducir las restricciones DisponibilidadDocente o agregar mas docentes con "
            "carga horaria flexible."
        )
    if datos['duracion_ms'] > 30000:
        sugerencias.append(
            "Considerar pre-filtrar matriculas por programa para acelerar el solver."
        )
    if not sugerencias:
        sugerencias.append(
            "El horario esta optimo. Considerar publicar a SISCA inmediatamente."
        )
    sugerencias.append(
        f"Distribuir mejor la carga entre los {datos['docentes']} docentes activos para "
        f"evitar saturacion del mismo profesor."
    )

    # Anomalias
    anomalias = []
    if conflictos > 0:
        anomalias.append(f"{conflictos} matriculas sin asignar - posible falta de recursos.")
    if datos['duracion_ms'] < 100 and datos['asignadas'] > 100:
        anomalias.append("Duracion sospechosamente baja para el volumen - verificar restricciones.")
    if datos['asignadas'] == 0:
        anomalias.append("Cero asignaciones generadas - revisar datos de entrada.")

    # Score
    score = min(100, int(tasa * 0.9 + (10 if datos['duracion_ms'] < 5000 else 0)))

    return {
        'resumen_ejecutivo': resumen,
        'sugerencias': sugerencias[:4],
        'anomalias': anomalias[:3],
        'score_calidad': score,
    }


# ════════════════════════════════════════════════════════════════
#  API PUBLICA
# ════════════════════════════════════════════════════════════════
SISTEMA_PROMPT_CHAT = """Eres un asistente experto en planificacion academica y gestion de horarios
del Politecnico Internacional. Ayudas a coordinadores y administradores a:

  - Entender el sistema SIIHAPI (Sistema Inteligente e Integrado de Horarios Academicos)
  - Analizar archivos CSV/Excel con datos de estudiantes, docentes, materias o horarios
  - Sugerir como armar los horarios de cada periodo
  - Detectar conflictos en datos cargados
  - Explicar el flujo: ejecutar IA -> aprobar -> publicar a SISCA

Conocimiento del sistema:
- 3 sedes (Calle 73, Norte, Sur), 135 salones reales
- 27 programas en 4 tipos: Tecnicos Laborales, Profesionales, Tecnologias, Ingles
- Periodos academicos con 14 bloques horarios de 80 min (6:00 a 22:00)
- Motor IA usa CSP (OR-Tools) + LLM para asignacion automatica
- Integracion con SISCA (control de asistencia) vine REST API

Responde en español de Colombia, profesional pero amable. Usa **negritas** cuando sea util.
Si te dan un archivo o datos, analizalos y da recomendaciones concretas."""


def chat_llm(mensaje, historial=None, contexto_archivo='', forzar_proveedor=None):
    """
    Chat conversacional con el LLM, conservando historial.

    Args:
        mensaje:           texto del usuario
        historial:         lista de dicts [{'rol': 'user'|'assistant', 'texto': '...'}]
        contexto_archivo:  texto adicional (ej: contenido de un CSV subido)
        forzar_proveedor:  'GEMINI' | 'OPENAI' | 'ANTHROPIC' | None=auto

    Returns:
        dict con {success, respuesta, proveedor, modelo}
    """
    historial = historial or []
    proveedor = forzar_proveedor or proveedor_disponible()

    # Construir mensajes con historial
    full_user_msg = mensaje
    if contexto_archivo:
        full_user_msg = (f"He subido este archivo con datos para que lo analices:\n"
                         f"```\n{contexto_archivo[:8000]}\n```\n\n"
                         f"Pregunta: {mensaje}")

    try:
        if proveedor == 'GEMINI':
            key = _get_api_key('GEMINI_API_KEY')
            if not key:
                raise Exception('Sin GEMINI_API_KEY')
            import google.generativeai as genai
            genai.configure(api_key=key)
            modelo_id = 'gemini-2.5-flash'
            model = genai.GenerativeModel(modelo_id, system_instruction=SISTEMA_PROMPT_CHAT)
            chat = model.start_chat(history=[
                {'role': 'user' if h['rol'] == 'user' else 'model',
                 'parts': [h['texto']]}
                for h in historial[-10:]  # ultimos 10 turnos
            ])
            resp = chat.send_message(full_user_msg)
            return {
                'success':   True,
                'respuesta': resp.text,
                'proveedor': 'GEMINI',
                'modelo':    modelo_id,
            }

        elif proveedor == 'OPENAI':
            key = _get_api_key('OPENAI_API_KEY')
            if not key:
                raise Exception('Sin OPENAI_API_KEY')
            from openai import OpenAI
            client = OpenAI(api_key=key)
            messages = [{'role': 'system', 'content': SISTEMA_PROMPT_CHAT}]
            for h in historial[-10:]:
                messages.append({
                    'role': 'user' if h['rol'] == 'user' else 'assistant',
                    'content': h['texto'],
                })
            messages.append({'role': 'user', 'content': full_user_msg})

            resp = client.chat.completions.create(
                model='gpt-4o-mini',
                messages=messages,
                max_tokens=1200,
            )
            return {
                'success':   True,
                'respuesta': resp.choices[0].message.content,
                'proveedor': 'OPENAI',
                'modelo':    'gpt-4o-mini',
            }

        elif proveedor == 'ANTHROPIC':
            key = _get_api_key('ANTHROPIC_API_KEY')
            if not key:
                raise Exception('Sin ANTHROPIC_API_KEY')
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            messages = []
            for h in historial[-10:]:
                messages.append({
                    'role': 'user' if h['rol'] == 'user' else 'assistant',
                    'content': h['texto'],
                })
            messages.append({'role': 'user', 'content': full_user_msg})
            resp = client.messages.create(
                model='claude-3-5-haiku-20241022',
                system=SISTEMA_PROMPT_CHAT,
                messages=messages,
                max_tokens=1200,
            )
            return {
                'success':   True,
                'respuesta': resp.content[0].text,
                'proveedor': 'ANTHROPIC',
                'modelo':    'claude-3-5-haiku',
            }
    except Exception as e:
        return {
            'success':   False,
            'error':     str(e)[:300],
            'respuesta': (f"No pude conectar con {proveedor}. Razon: {str(e)[:200]}.\n\n"
                          f"Asegurate de tener la API key configurada en backend/.env"),
            'proveedor': proveedor,
            'modelo':    '',
        }

    # Heuristico fallback (sin red)
    return {
        'success':   True,
        'respuesta': (
            f"Hola, soy el asistente local de SIIHAPI (modo offline, sin LLM real).\n\n"
            f"Recibi tu mensaje: '{mensaje[:200]}'.\n\n"
            f"Para tener respuestas reales con IA, configura una API key en backend/.env:\n"
            f"  - GEMINI_API_KEY (gratis en https://aistudio.google.com/apikey)\n"
            f"  - OPENAI_API_KEY (pago en https://platform.openai.com/api-keys)\n\n"
            f"Mientras tanto, puedo ayudarte recordandote:\n"
            f"  1. El Motor IA (boton 'Ejecutar') genera horarios automaticamente.\n"
            f"  2. Aprueba los horarios PROPUESTOS desde el panel Horarios.\n"
            f"  3. Publicalos a SISCA desde Integracion SISCA."
        ),
        'proveedor': 'HEURISTIC',
        'modelo':    'Asistente local',
    }
# ════════════════════════════════════════════════════════════════
#  MOTOR DE EXTRACCION INTELIGENTE (documento -> horarios estructurados)
# ════════════════════════════════════════════════════════════════
PROMPT_EXTRACCION = """Eres un sistema experto de extraccion de informacion academica del Politecnico Internacional.
Recibes el TEXTO CRUDO de un documento (PDF/Word/Excel/CSV) que contiene un horario o una lista de clases,
posiblemente desordenado, con tablas mal alineadas o formatos variados.

Tu tarea: EXTRAER cada clase como un objeto estructurado y NORMALIZAR los datos.

REGLAS DE NORMALIZACION:
- dia: convierte a uno de exactamente {{LUNES, MARTES, MIERCOLES, JUEVES, VIERNES, SABADO, DOMINGO}}.
  Acepta abreviaturas (LU, MA, MI, X, JU, VI, SA, DO) y nombres con acento.
- hora_inicio / hora_fin: formato 24h "HH:MM". Si ves "7:00 a.m." -> "07:00"; "1 pm" -> "13:00".
- codigo_materia: el codigo entre corchetes o la primera columna (ej "[0569]" -> "0569"). Si no hay, invéntalo a partir del nombre (primeras letras).
- nombre_materia: el nombre completo de la asignatura, en mayuscula inicial.
- docente: nombre completo del profesor si aparece; si no, cadena vacia.
- docente_email: si aparece un correo; si no, cadena vacia.
- salon: aula/salon. Si dice "ASIGNATURA ASISTIDA POR TECNOLOGIA" o "virtual/sincronico" -> "VIRTUAL".
- grupo: codigo de grupo si aparece (ej "SOFE1-6TC"); si no, "A".
- creditos: numero entero si aparece; si no, 3.

{contexto_catalogo}

REGLAS DE CALIDAD:
- NO inventes clases que no esten en el texto.
- Si una fila no tiene hora valida, omitela.
- Combina lineas partidas (una clase puede ocupar varias lineas en el texto).
- Devuelve TODAS las clases que encuentres.

Responde EXCLUSIVAMENTE con un JSON valido con esta forma (sin markdown, sin texto extra):
{{"horarios": [
  {{"codigo_materia":"0569","nombre_materia":"Aplicaciones II","dia":"LUNES","hora_inicio":"08:30","hora_fin":"11:30","docente":"Edgar Angel","docente_email":"","salon":"SOFT-214","grupo":"SOFE1-6TC","creditos":4}}
]}}

TEXTO DEL DOCUMENTO (periodo {periodo}):
\"\"\"
{texto}
\"\"\"
"""


def _llm_gemini_json(prompt, api_key, temperatura=0.1):
    """Gemini en modo JSON con temperatura baja (extraccion determinista)."""
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    cfg = {'temperature': temperatura, 'response_mime_type': 'application/json'}
    ultimo = None
    for modelo in GEMINI_MODELOS:
        try:
            m = genai.GenerativeModel(modelo, generation_config=cfg)
            r = m.generate_content(prompt)
            return r.text, modelo
        except Exception as e:
            ultimo = e
            es = str(e).lower()
            if '404' in es or 'not found' in es or 'not supported' in es or 'mime' in es:
                # reintenta sin response_mime_type (modelos viejos)
                try:
                    m = genai.GenerativeModel(modelo, generation_config={'temperature': temperatura})
                    r = m.generate_content(prompt)
                    return r.text, modelo
                except Exception as e2:
                    ultimo = e2
                    continue
            raise
    raise Exception(f'Gemini extraccion fallo: {ultimo}')


def _llm_openai_json(prompt, api_key, temperatura=0.1):
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    r = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[
            {'role': 'system', 'content': 'Extraes horarios academicos a JSON estructurado. Responde solo JSON.'},
            {'role': 'user', 'content': prompt},
        ],
        response_format={'type': 'json_object'},
        temperature=temperatura,
        max_tokens=4000,
    )
    return r.choices[0].message.content, 'gpt-4o-mini'


def _llm_anthropic_json(prompt, api_key, temperatura=0.1):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    r = client.messages.create(
        model='claude-3-5-haiku-20241022',
        max_tokens=4000,
        temperature=temperatura,
        messages=[{'role': 'user', 'content': prompt}],
    )
    return r.content[0].text, 'claude-3-5-haiku'


def _limpiar_json(txt):
    """Quita envoltura markdown y extrae el primer objeto/array JSON."""
    t = (txt or '').strip()
    if t.startswith('```'):
        t = t[3:]
        if t[:4].lower() == 'json':
            t = t[4:]
        if t.endswith('```'):
            t = t[:-3]
        t = t.strip()
    # localizar el JSON
    import re
    m = re.search(r'(\{.*\}|\[.*\])', t, re.DOTALL)
    return m.group(1) if m else t


def extraer_horarios_con_ia(texto, periodo='2026-2', catalogo=None, forzar_proveedor=None):
    """
    Extrae una lista de horarios estructurados desde texto crudo de un documento.

    Returns: (lista_de_dicts, proveedor, modelo)
    """
    contexto = ''
    if catalogo:
        partes = []
        if catalogo.get('materias'):
            partes.append('Materias conocidas (codigo: nombre): ' +
                          '; '.join(f"{c}:{n}" for c, n in list(catalogo['materias'].items())[:80]))
        if catalogo.get('docentes'):
            partes.append('Docentes conocidos (nombre <correo>): ' +
                          '; '.join(catalogo['docentes'][:60]))
        if catalogo.get('salones'):
            partes.append('Salones conocidos: ' + ', '.join(catalogo['salones'][:80]))
        if partes:
            contexto = ('CATALOGO DE REFERENCIA (usa estos codigos/correos exactos cuando coincidan '
                        'por nombre):\n' + '\n'.join(partes) + '\n')

    prompt = PROMPT_EXTRACCION.format(periodo=periodo, texto=(texto or '')[:14000],
                                      contexto_catalogo=contexto)

    proveedor = forzar_proveedor or proveedor_disponible()
    raw, modelo = '', ''
    if proveedor in ('GEMINI', 'OPENAI', 'ANTHROPIC'):
        try:
            if proveedor == 'GEMINI':
                raw, modelo = _llm_gemini_json(prompt, _get_api_key('GEMINI_API_KEY'))
            elif proveedor == 'OPENAI':
                raw, modelo = _llm_openai_json(prompt, _get_api_key('OPENAI_API_KEY'))
            else:
                raw, modelo = _llm_anthropic_json(prompt, _get_api_key('ANTHROPIC_API_KEY'))
            data = json.loads(_limpiar_json(raw))
            lista = data.get('horarios', data) if isinstance(data, dict) else data
            if isinstance(lista, list):
                return lista, proveedor, modelo
        except Exception as e:
            print(f"[EXTRACCION] {proveedor} fallo: {e}. Usando extractor heuristico.")

    # Fallback heuristico (sin API key o si el LLM fallo)
    return _extraer_heuristico(texto), 'HEURISTIC', 'regex'


def _extraer_heuristico(texto):
    """Extractor por reglas, linea por linea (fallback sin IA).
    Cada linea con un dia + [codigo] + 2 horas se interpreta como una clase."""
    import re
    if not texto:
        return []
    DIA = {
        'lunes':'LUNES','lu':'LUNES','martes':'MARTES','ma':'MARTES',
        'miercoles':'MIERCOLES','miércoles':'MIERCOLES','mi':'MIERCOLES','x':'MIERCOLES',
        'jueves':'JUEVES','ju':'JUEVES','viernes':'VIERNES','vi':'VIERNES',
        'sabado':'SABADO','sábado':'SABADO','sa':'SABADO','domingo':'DOMINGO','do':'DOMINGO',
    }
    salida = []
    for linea in texto.splitlines():
        l = linea.strip()
        if not l:
            continue
        # dia (primera palabra-clave de dia en la linea)
        dia = ''
        mdia = re.search(r'\b(LUNES|MARTES|MI[EÉ]RCOLES|JUEVES|VIERNES|S[AÁ]BADO|DOMINGO)\b', l, re.I)
        if mdia:
            dia = DIA.get(mdia.group(1).lower(), mdia.group(1).upper())
        else:
            mab = re.match(r'\s*(LU|MA|MI|JU|VI|SA|DO|X)\b', l, re.I)
            if mab:
                dia = DIA.get(mab.group(1).lower(), '')
        horas = re.findall(r'(\d{1,2}:\d{2})', l)
        mcod = re.search(r'\[(\d{3,5})\]\s*([A-Za-zÁÉÍÓÚÑáéíóúñ .\-]{3,60}?)(?=\s{2,}|\s+\d{1,2}:|\s+(?:LUNES|MARTES|MI|JU|VI|SA)|$)', l)
        if not (dia and mcod and len(horas) >= 2):
            continue
        memail = re.search(r'[\w.\-]+@[\w.\-]+', l)
        salon = 'VIRTUAL' if re.search(r'virtual|sincronic|asistida por tecnologia', l, re.I) else ''
        msalon = re.search(r'\b([A-Z]{2,5}[\- ]?\d{2,4})\b', l)
        if not salon and msalon:
            salon = msalon.group(1)
        salida.append({
            'codigo_materia': mcod.group(1).strip(),
            'nombre_materia': mcod.group(2).strip().title(),
            'dia': dia,
            'hora_inicio': horas[0],
            'hora_fin': horas[1],
            'docente': '',
            'docente_email': memail.group(0) if memail else '',
            'salon': salon,
            'grupo': 'A',
            'creditos': 3,
        })
    return salida

def analizar_horario_con_ia(datos: Dict[str, Any], forzar_proveedor: Optional[str] = None) -> LLMResult:
    """
    Genera analisis del horario usando el LLM disponible.

    Args:
        datos: dict con resumen del horario:
            - periodo, total_matriculas, asignadas, conflictos, tasa_exito,
              algoritmo, duracion_ms, sedes, salones, docentes,
              distribucion_dia, distribucion_salon, carga_docente
        forzar_proveedor: 'GEMINI' | 'OPENAI' | 'ANTHROPIC' | 'HEURISTIC'

    Returns:
        LLMResult con analisis estructurado.
    """
    proveedor = forzar_proveedor or proveedor_disponible()
    raw = ''
    modelo = ''

    if proveedor in ('GEMINI', 'OPENAI', 'ANTHROPIC'):
        prompt = PROMPT_TEMPLATE.format(**datos)
        try:
            if proveedor == 'GEMINI':
                raw, modelo = _llm_gemini(prompt, _get_api_key('GEMINI_API_KEY'))
            elif proveedor == 'OPENAI':
                raw, modelo = _llm_openai(prompt, _get_api_key('OPENAI_API_KEY'))
            elif proveedor == 'ANTHROPIC':
                raw, modelo = _llm_anthropic(prompt, _get_api_key('ANTHROPIC_API_KEY'))

            # Limpiar markdown wrappers comunes
            txt = raw.strip()
            if txt.startswith('```'):
                txt = txt.split('```', 2)[1] if '```' in txt[3:] else txt[3:]
                if txt.startswith('json'):
                    txt = txt[4:]
                txt = txt.strip()
            if txt.endswith('```'):
                txt = txt[:-3].strip()

            parsed = json.loads(txt)
            return LLMResult(
                proveedor=proveedor,
                modelo=modelo,
                resumen_ejecutivo=parsed.get('resumen_ejecutivo', ''),
                sugerencias=parsed.get('sugerencias', []),
                anomalias=parsed.get('anomalias', []),
                score_calidad=int(parsed.get('score_calidad', 0)),
                raw_response=raw[:2000],
            )
        except Exception as e:
            # Si el LLM externo falla, caemos al heuristico
            print(f"[LLM ERROR] {proveedor} fallo: {e}. Usando heuristico.")
            proveedor = 'HEURISTIC'

    # HEURISTIC (sin API key o fallback)
    parsed = _llm_heuristico(datos)
    return LLMResult(
        proveedor='HEURISTIC',
        modelo='Analizador local basado en reglas',
        resumen_ejecutivo=parsed['resumen_ejecutivo'],
        sugerencias=parsed['sugerencias'],
        anomalias=parsed['anomalias'],
        score_calidad=parsed['score_calidad'],
        raw_response='',
    )
