"""
═══════════════════════════════════════════════════════════════════════════════
 MÓDULO DE GESTIÓN DOCUMENTAL INTELIGENTE (User-in-the-Loop)
 SIIHAPI · Politécnico Internacional
═══════════════════════════════════════════════════════════════════════════════

Flujo (estricto):
  1) analizar_documentos()      -> carga N archivos, los cruza, resumen + dataset unificado
  2) [el sistema pregunta al usuario que ajustes desea]
  3) aplicar_cambios_usuario()  -> NL -> operaciones estructuradas -> borrador validado
  4) [ciclo de revisión: el usuario pide mas cambios sobre el borrador]
  5) exportar_documento_limpio()-> validacion final + archivo .xlsx definitivo

Patrón de seguridad: el LLM NUNCA modifica datos directamente. El LLM solo
traduce el lenguaje natural a una LISTA DE OPERACIONES estructuradas (JSON), que
un ejecutor determinista aplica sobre un DataFrame de pandas. Esto hace el flujo
predecible, auditable y testeable.
"""
from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any

log = logging.getLogger(__name__)

# Import protegido: si pandas no esta disponible, el modulo IGUAL se importa
# (no rompe el URLconf ni la API). Solo fallan las funciones que lo usan,
# devolviendo un error claro en el endpoint.
try:
    import pandas as pd
    _PANDAS_OK = True
except Exception as _e:  # pragma: no cover
    pd = None
    _PANDAS_OK = False
    logging.getLogger(__name__).warning(f"pandas no disponible: {_e}")


def _requiere_pandas():
    if not _PANDAS_OK:
        raise RuntimeError("El modulo de gestion documental requiere 'pandas'. "
                           "Instala con: pip install pandas openpyxl")

# Columnas canónicas del dataset unificado de horarios
COLUMNAS = [
    "codigo_materia", "nombre_materia", "dia", "hora_inicio", "hora_fin",
    "docente", "docente_email", "salon", "grupo", "creditos",
]
DIAS_VALIDOS = {"LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"}


# ═══════════════════════════════════════════════════════════════════
#  SYSTEM PROMPT del agente interno (traductor NL -> operaciones)
# ═══════════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """Eres el motor de reglas de un gestor documental de horarios del Politécnico Internacional.
Tu ÚNICA función es traducir las instrucciones en lenguaje natural del usuario a una lista
de OPERACIONES estructuradas en JSON. NO conversas, NO explicas, NO inventas datos.

Trabajas sobre una tabla de horarios con estas columnas:
codigo_materia, nombre_materia, dia, hora_inicio (HH:MM 24h), hora_fin (HH:MM 24h),
docente, docente_email, salon, grupo, creditos.

Días válidos: LUNES, MARTES, MIERCOLES, JUEVES, VIERNES, SABADO, DOMINGO.

OPERACIONES PERMITIDAS (usa exactamente estos nombres de "accion"):
- "mover_dia"        : cambia el dia.            valor = "MARTES"
- "cambiar_hora"     : cambia horas.            valor = {"hora_inicio":"08:00","hora_fin":"09:30"}
- "reasignar_salon"  : cambia salon.            valor = "SOFT-210"
- "reasignar_docente": cambia docente.          valor = {"docente":"Ana Gomez","docente_email":"ana@pi.edu.co"}
- "eliminar"         : elimina las filas que cumplan el filtro.   (sin valor)
- "duplicar"         : duplica filas (otro grupo/dia).            valor = {"dia":"JUEVES"}

Cada operación lleva un "filtro" que selecciona las filas afectadas. El filtro puede combinar:
codigo_materia, nombre_materia, dia, docente, salon, grupo. Filtro vacío {} = TODAS las filas.
Para rangos de hora usa "jornada": "DIURNA"(07:00-10:00), "ESPECIAL"(10:00-13:00), "NOCTURNA"(18:00-21:00).

REGLAS:
- Responde EXCLUSIVAMENTE con JSON válido, sin markdown ni texto extra.
- Si la instrucción es ambigua o no corresponde a una operación, devuelve {"operaciones": [], "duda": "pregunta de aclaración"}.
- No inventes materias, salones ni docentes que no estén en el filtro o en el catálogo dado.

Formato de salida EXACTO:
{"operaciones": [
   {"accion":"mover_dia","filtro":{"codigo_materia":"0569"},"valor":"MARTES"}
]}
"""


# ═══════════════════════════════════════════════════════════════════
#  Estado de la sesión (serializable -> se persiste entre requests)
# ═══════════════════════════════════════════════════════════════════
@dataclass
class SesionDocumento:
    """Estado completo del trabajo. Se serializa a JSON y se guarda en BD/cache
    entre cada paso del flujo (HTTP es stateless)."""
    id: str
    periodo: str
    estado: str = "ANALIZADO"            # ANALIZADO -> BORRADOR -> APROBADO
    registros: list[dict] = field(default_factory=list)   # dataset unificado
    historial: list[dict] = field(default_factory=list)    # auditoría de cambios
    advertencias: list[str] = field(default_factory=list)
    archivos_origen: list[str] = field(default_factory=list)

    def df(self) -> pd.DataFrame:
        return pd.DataFrame(self.registros, columns=COLUMNAS)

    def set_df(self, df: pd.DataFrame):
        self.registros = df.reindex(columns=COLUMNAS).fillna("").to_dict("records")

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "SesionDocumento":
        return cls(**json.loads(raw))


# ═══════════════════════════════════════════════════════════════════
#  1) ANALIZAR DOCUMENTOS  (carga N archivos, cruza, resume)
# ═══════════════════════════════════════════════════════════════════
def analizar_documentos(archivos: list[tuple[str, bytes]], periodo: str,
                        sesion_id: str) -> SesionDocumento:
    """
    archivos: lista de (nombre, contenido_bytes). Acepta CSV/XLSX (>= 1, ideal >= 2).
    Cruza los archivos por columnas comunes (codigo_materia / grupo) y unifica
    en un solo dataset canónico.
    """
    _requiere_pandas()
    frames = []
    nombres = []
    for nombre, contenido in archivos:
        df = _leer_tabular(contenido, nombre)
        if df is None or df.empty:
            continue
        df = _normalizar_columnas(df)
        frames.append(df)
        nombres.append(nombre)

    if not frames:
        raise ValueError("Ningún archivo tabular válido (CSV/XLSX) pudo leerse.")

    # Cruce inteligente: si dos archivos comparten 'codigo_materia', se hace merge;
    # si no, se concatenan (apilan) homogeneizando columnas.
    unificado = frames[0]
    for extra in frames[1:]:
        claves = [c for c in ("codigo_materia", "grupo") if c in unificado.columns and c in extra.columns]
        if claves:
            unificado = unificado.merge(extra, on=claves, how="outer", suffixes=("", "_2"))
            # Rellenar columnas canónicas vacías con las del segundo archivo
            for col in COLUMNAS:
                c2 = f"{col}_2"
                if c2 in unificado.columns:
                    unificado[col] = unificado.get(col, "").where(
                        unificado.get(col, "").astype(str).str.len() > 0, unificado[c2])
                    unificado.drop(columns=[c2], inplace=True, errors="ignore")
        else:
            unificado = pd.concat([unificado, extra], ignore_index=True)

    unificado = unificado.reindex(columns=COLUMNAS).fillna("")
    sesion = SesionDocumento(id=sesion_id, periodo=periodo, estado="ANALIZADO",
                             archivos_origen=nombres)
    sesion.set_df(unificado)
    sesion.advertencias = [f"{p['fila']}: {p['detalle']}" for p in _validar_consistencia(unificado)]
    sesion.historial.append({"paso": "analisis", "archivos": nombres,
                             "registros": len(unificado)})
    return sesion


def resumen_para_usuario(sesion: SesionDocumento) -> dict:
    """Resumen que el sistema presenta antes de preguntar '¿Qué desea ajustar?'."""
    df = sesion.df()
    return {
        "total_clases": len(df),
        "materias": int(df["codigo_materia"].nunique()),
        "docentes": int(df[df["docente"] != ""]["docente"].nunique()),
        "salones": int(df[df["salon"] != ""]["salon"].nunique()),
        "por_dia": df["dia"].value_counts().to_dict(),
        "conflictos": len(sesion.advertencias),
        "advertencias": sesion.advertencias[:20],
        "pregunta": "¿Qué cambios o ajustes desea realizar sobre estos horarios?",
    }


# ═══════════════════════════════════════════════════════════════════
#  2) APLICAR CAMBIOS DEL USUARIO  (NL -> operaciones -> borrador)
# ═══════════════════════════════════════════════════════════════════
def aplicar_cambios_usuario(sesion: SesionDocumento, instruccion_nl: str,
                            forzar_proveedor: str | None = None) -> dict:
    """
    Traduce la instrucción del usuario a operaciones (LLM) y las aplica de forma
    determinista sobre el dataset. Devuelve el borrador + validación de choques.
    No persiste nada: el caller decide guardar el nuevo estado.
    """
    _requiere_pandas()
    operaciones, duda = _interpretar_instruccion(instruccion_nl, sesion, forzar_proveedor)
    if duda:
        return {"ok": False, "duda": duda, "operaciones": []}

    df = sesion.df()
    aplicadas = []
    for op in operaciones:
        df, info = _ejecutar_operacion(df, op)
        aplicadas.append(info)

    conflictos = _validar_consistencia(df)
    sesion.set_df(df)
    sesion.estado = "BORRADOR"
    sesion.advertencias = [f"{c['fila']}: {c['detalle']}" for c in conflictos]
    sesion.historial.append({"paso": "cambio", "instruccion": instruccion_nl,
                             "operaciones": aplicadas})
    return {
        "ok": True,
        "operaciones_aplicadas": aplicadas,
        "borrador": sesion.df().to_dict("records"),
        "conflictos": sesion.advertencias,
        "hay_conflictos": bool(conflictos),
    }


# ═══════════════════════════════════════════════════════════════════
#  3) EXPORTAR DOCUMENTO LIMPIO  (validación final + .xlsx definitivo)
# ═══════════════════════════════════════════════════════════════════
def exportar_documento_limpio(sesion: SesionDocumento) -> tuple[bytes, list[str]]:
    """
    Validación final estricta: si quedan choques o filas inválidas, NO exporta y
    devuelve los errores. Si está limpio, genera el .xlsx definitivo.
    """
    _requiere_pandas()
    df = sesion.df()
    errores = []

    # Validación de campos obligatorios y formato
    for i, fila in df.iterrows():
        if not str(fila["codigo_materia"]).strip():
            errores.append(f"Fila {i + 1}: codigo_materia vacío")
        if str(fila["dia"]).upper() not in DIAS_VALIDOS:
            errores.append(f"Fila {i + 1}: día inválido '{fila['dia']}'")
        if fila["hora_inicio"] and fila["hora_fin"] and fila["hora_fin"] <= fila["hora_inicio"]:
            errores.append(f"Fila {i + 1}: hora_fin <= hora_inicio")

    # Validación de consistencia (choques)
    for c in _validar_consistencia(df):
        errores.append(f"{c['fila']}: {c['detalle']}")

    if errores:
        return b"", errores  # NO se exporta con errores

    # Generar Excel limpio
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Horario")
    buf.seek(0)
    sesion.estado = "APROBADO"
    sesion.historial.append({"paso": "exportacion", "registros": len(df)})
    return buf.read(), []


# ═══════════════════════════════════════════════════════════════════
#  VALIDACIÓN DE CONSISTENCIA (choques de horario)
# ═══════════════════════════════════════════════════════════════════
def _solapan(hi1, hf1, hi2, hf2) -> bool:
    if not (hi1 and hf1 and hi2 and hf2):
        return False
    return hi1 < hf2 and hi2 < hf1


def _validar_consistencia(df: pd.DataFrame) -> list[dict]:
    """Detecta dos tipos de choque dentro del mismo día con franjas solapadas:
       (a) mismo SALÓN ocupado, (b) mismo DOCENTE en dos clases a la vez."""
    problemas = []
    filas = df.to_dict("records")
    for i in range(len(filas)):
        for j in range(i + 1, len(filas)):
            a, b = filas[i], filas[j]
            if a.get("dia") != b.get("dia") or not a.get("dia"):
                continue
            if not _solapan(a.get("hora_inicio"), a.get("hora_fin"),
                            b.get("hora_inicio"), b.get("hora_fin")):
                continue
            if a.get("salon") and a.get("salon") == b.get("salon"):
                problemas.append({"fila": f"{i+1}↔{j+1}",
                                  "detalle": f"Choque de salón {a['salon']} el {a['dia']}"})
            doc_a = a.get("docente_email") or a.get("docente")
            doc_b = b.get("docente_email") or b.get("docente")
            if doc_a and doc_a == doc_b:
                problemas.append({"fila": f"{i+1}↔{j+1}",
                                  "detalle": f"Docente {doc_a} con dos clases a la vez el {a['dia']}"})
    return problemas


# ═══════════════════════════════════════════════════════════════════
#  Ejecutor determinista de operaciones
# ═══════════════════════════════════════════════════════════════════
_JORNADAS = {"DIURNA": ("07:00", "10:00"), "ESPECIAL": ("10:00", "13:00"),
             "NOCTURNA": ("18:00", "21:00")}


def _mascara(df: pd.DataFrame, filtro: dict):
    m = pd.Series([True] * len(df))
    for campo, val in (filtro or {}).items():
        if campo == "jornada" and val.upper() in _JORNADAS:
            ini, fin = _JORNADAS[val.upper()]
            m &= (df["hora_inicio"] >= ini) & (df["hora_inicio"] < fin)
        elif campo in df.columns:
            m &= df[campo].astype(str).str.upper() == str(val).upper()
    return m


def _ejecutar_operacion(df: pd.DataFrame, op: dict) -> tuple[pd.DataFrame, dict]:
    accion = op.get("accion")
    filtro = op.get("filtro", {})
    valor = op.get("valor")
    m = _mascara(df, filtro)
    n = int(m.sum())

    if accion == "mover_dia":
        df.loc[m, "dia"] = str(valor).upper()
    elif accion == "cambiar_hora" and isinstance(valor, dict):
        if valor.get("hora_inicio"):
            df.loc[m, "hora_inicio"] = valor["hora_inicio"]
        if valor.get("hora_fin"):
            df.loc[m, "hora_fin"] = valor["hora_fin"]
    elif accion == "reasignar_salon":
        df.loc[m, "salon"] = str(valor)
    elif accion == "reasignar_docente" and isinstance(valor, dict):
        df.loc[m, "docente"] = valor.get("docente", "")
        df.loc[m, "docente_email"] = valor.get("docente_email", "")
    elif accion == "eliminar":
        df = df.loc[~m].reset_index(drop=True)
    elif accion == "duplicar":
        nuevas = df.loc[m].copy()
        if isinstance(valor, dict):
            for k, v in valor.items():
                if k in nuevas.columns:
                    nuevas[k] = v
        df = pd.concat([df, nuevas], ignore_index=True)

    return df, {"accion": accion, "filtro": filtro, "afectadas": n}


# ═══════════════════════════════════════════════════════════════════
#  Interpretación NL -> operaciones (LLM con fallback)
# ═══════════════════════════════════════════════════════════════════
def _interpretar_instruccion(instruccion: str, sesion: SesionDocumento,
                             forzar_proveedor: str | None):
    """Devuelve (lista_operaciones, duda|None). Usa el LLM; si no hay API, usa
    el parser heurístico del módulo de edición guiada."""
    catalogo = sorted(set(sesion.df()["codigo_materia"].tolist()))
    prompt = (f"{SYSTEM_PROMPT}\n\nCATÁLOGO de codigo_materia disponibles: {catalogo}\n\n"
              f"INSTRUCCIÓN DEL USUARIO:\n{instruccion}")
    try:
        from siihapi.motor_ia.llm import (_get_api_key, proveedor_disponible,
                                          _llm_gemini_json, _llm_openai_json,
                                          _llm_anthropic_json, _limpiar_json)
        prov = forzar_proveedor or proveedor_disponible()
        raw = ""
        if prov == "GEMINI":
            raw, _ = _llm_gemini_json(prompt, _get_api_key("GEMINI_API_KEY"))
        elif prov == "OPENAI":
            raw, _ = _llm_openai_json(prompt, _get_api_key("OPENAI_API_KEY"))
        elif prov == "ANTHROPIC":
            raw, _ = _llm_anthropic_json(prompt, _get_api_key("ANTHROPIC_API_KEY"))
        if raw:
            data = json.loads(_limpiar_json(raw))
            return data.get("operaciones", []), data.get("duda")
    except Exception as e:
        log.warning(f"[GestionDoc] LLM no disponible ({e}); usando heurístico.")

    # Fallback heurístico: reutiliza el parser de edición guiada
    try:
        from siihapi.frontend_views import _parsear_instruccion_edicion
        plan = _parsear_instruccion_edicion(instruccion)
        if plan:
            mapa = {"cambiar_dia": "mover_dia", "cambiar_estado": None}
            accion = mapa.get(plan["accion"])
            if accion:
                return [{"accion": accion, "filtro": plan["filtro"], "valor": plan["valor"]}], None
    except Exception:
        pass
    return [], "No entendí la instrucción. Reformúlala (ej: 'mueve la materia 0569 a martes')."


# ═══════════════════════════════════════════════════════════════════
#  Lectura de archivos tabulares + normalización de columnas
# ═══════════════════════════════════════════════════════════════════
def _leer_tabular(contenido: bytes, nombre: str):
    n = nombre.lower()
    try:
        if n.endswith(".csv"):
            for sep in (",", ";", "\t"):
                try:
                    df = pd.read_csv(io.BytesIO(contenido), sep=sep, dtype=str, encoding="utf-8-sig")
                    if df.shape[1] > 1:
                        return df
                except Exception:
                    continue
            return pd.read_csv(io.BytesIO(contenido), dtype=str, encoding="utf-8-sig")
        if n.endswith((".xlsx", ".xls")):
            return pd.read_excel(io.BytesIO(contenido), dtype=str)
    except Exception as e:
        log.error(f"[GestionDoc] No se pudo leer '{nombre}': {e}")
    return None


_ALIAS = {
    "codigo_materia": ["codigo_materia", "materia_codigo", "codigo", "cod_materia"],
    "nombre_materia": ["nombre_materia", "nombre", "materia", "asignatura"],
    "dia": ["dia", "día", "day", "dias"],
    "hora_inicio": ["hora_inicio", "inicio", "hora"],
    "hora_fin": ["hora_fin", "fin"],
    "docente": ["docente", "profesor", "teacher"],
    "docente_email": ["docente_email", "docente_correo", "correo", "email"],
    "salon": ["salon", "salon_codigo", "aula", "room"],
    "grupo": ["grupo", "group", "seccion"],
    "creditos": ["creditos", "créditos", "credits"],
}


def _normalizar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    import unicodedata

    def norm(s):
        s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
        return s.strip().lower().replace(" ", "_")

    rename = {}
    cols_norm = {norm(c): c for c in df.columns}
    for canon, aliases in _ALIAS.items():
        for a in aliases:
            if norm(a) in cols_norm:
                rename[cols_norm[norm(a)]] = canon
                break
    df = df.rename(columns=rename)
    # Normalizar dia a mayúscula y sin acento
    if "dia" in df.columns:
        df["dia"] = df["dia"].astype(str).map(
            lambda x: unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().strip().upper())
    return df.reindex(columns=COLUMNAS).fillna("") if set(COLUMNAS) & set(df.columns) else df
