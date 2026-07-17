"""SISCA — Controladores: Admin, Académico, Docente, Estudiante, Asistencia, Reportes"""
from flask import (Blueprint, render_template, session, redirect,
                   url_for, request, flash, jsonify, send_file)
from functools import wraps
from app.database.connection import execute_query, execute_one
from app.utils.audit import registrar_auditoria
import csv
import io


# ── Decoradores ──────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("usuario_id"):
            flash("Debes iniciar sesión.", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get("rol") not in roles:
                flash("No tienes permisos para esta sección.", "error")
                return redirect(url_for("auth.landing"))
            return f(*args, **kwargs)
        return decorated
    return decorator


def _count(tabla: str, cond: str = "1=1") -> int:
    r = execute_one(f"SELECT COUNT(*) AS N FROM {tabla} WHERE {cond}")
    return r["n"] if r else 0


# ════════════════════════════════════════════════════════════════════════════
# ADMIN
# ════════════════════════════════════════════════════════════════════════════
admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/dashboard")
@login_required
@role_required("ADMINISTRADOR")
def dashboard():
    from datetime import datetime
    stats = {
        "usuarios":        _count("USUARIO", "ESTADO='A'"),
        "docentes":        _count("DOCENTE"),
        "estudiantes":     _count("ESTUDIANTE"),
        "materias":        _count("MATERIA", "ESTADO='A'"),
        "sesiones_hoy":    _count("SESION_CLASE", "FECHA_SESION=TRUNC(SYSDATE)"),
        "asistencias_hoy": _count("ASISTENCIA", "FECHA=TRUNC(SYSDATE)"),
    }
    usuarios_recientes = execute_query(
        "SELECT * FROM USUARIO ORDER BY FECHA_REGISTRO DESC FETCH FIRST 10 ROWS ONLY"
    ) or []
    logs = execute_query(
        "SELECT * FROM AUDITORIA ORDER BY FECHA DESC FETCH FIRST 20 ROWS ONLY"
    ) or []
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    return render_template("admin/dashboard.html",
                           stats=stats, usuarios=usuarios_recientes, logs=logs, now=now)


@admin_bp.route("/usuarios")
@login_required
@role_required("ADMINISTRADOR")
def usuarios():
    rol_f = request.args.get("rol", "")
    q     = request.args.get("q", "")
    sql   = "SELECT * FROM USUARIO WHERE 1=1"
    params = {}
    if rol_f:
        sql += " AND ROL = :rol"; params["rol"] = rol_f
    if q:
        sql += " AND (UPPER(NOMBRE) LIKE :q OR UPPER(CORREO) LIKE :q)"
        params["q"] = f"%{q.upper()}%"
    sql += " ORDER BY NOMBRE"
    lista = execute_query(sql, params) or []
    return render_template("admin/usuarios.html", usuarios=lista, rol_f=rol_f, q=q)


@admin_bp.route("/usuarios/toggle/<int:uid>", methods=["POST"])
@login_required
@role_required("ADMINISTRADOR")
def toggle_usuario(uid):
    u = execute_one("SELECT ESTADO FROM USUARIO WHERE ID_USUARIO=:id", {"id": uid})
    nuevo = "I" if u and u["estado"] == "A" else "A"
    execute_query("UPDATE USUARIO SET ESTADO=:e WHERE ID_USUARIO=:id",
                  {"e": nuevo, "id": uid}, fetch=False, commit=True)
    registrar_auditoria(session["usuario_id"],
                        f"TOGGLE_USUARIO_{uid}_{nuevo}", "USUARIO",
                        request.remote_addr)
    return jsonify({"ok": True, "nuevo_estado": nuevo})


# ─── Carga Masiva CSV ────────────────────────────────────────────────────────

@admin_bp.route("/carga-masiva")
@login_required
@role_required("ADMINISTRADOR")
def carga_masiva():
    """Pantalla principal de carga masiva por CSV."""
    return render_template("admin/carga_masiva.html")


@admin_bp.route("/carga-masiva/procesar", methods=["POST"])
@login_required
@role_required("ADMINISTRADOR")
def procesar_csv():
    """
    Procesa el archivo CSV subido.
    Parámetro de form: tipo  → estudiantes | docentes | horarios | materias | personal_administrativo
    Archivo de form:   archivo → el .csv
    """
    tipo    = request.form.get("tipo", "").strip()
    archivo = request.files.get("archivo")

    TIPOS_VALIDOS = ("estudiantes", "docentes", "horarios",
                     "materias", "personal_administrativo")
    if tipo not in TIPOS_VALIDOS:
        flash("Tipo de entidad no válido.", "error")
        return redirect(url_for("admin.carga_masiva"))

    if not archivo or archivo.filename == "":
        flash("Debes seleccionar un archivo CSV.", "error")
        return redirect(url_for("admin.carga_masiva"))

    # ── Leer CSV ────────────────────────────────────────────────────────────
    try:
        contenido = archivo.read().decode("utf-8-sig")  # utf-8-sig quita BOM
    except UnicodeDecodeError:
        try:
            archivo.seek(0)
            contenido = archivo.read().decode("latin-1")
        except Exception as exc:
            flash(f"No se pudo leer el archivo: {exc}", "error")
            return redirect(url_for("admin.carga_masiva"))

    reader  = csv.DictReader(io.StringIO(contenido))
    filas   = list(reader)
    errores = []
    ok_count = 0

    # ── Procesadores por tipo ────────────────────────────────────────────────
    if tipo == "estudiantes":
        # Columnas esperadas: nombre, apellido, documento, correo, contrasena,
        #                     semestre, codigo_estudiante  (opcionales: estado)
        REQUERIDOS = ("nombre", "apellido", "documento", "correo", "contrasena")
        for i, fila in enumerate(filas, start=2):
            fila = {k.strip().lower(): (v.strip() if v else "") for k, v in fila.items()}
            faltantes = [c for c in REQUERIDOS if not fila.get(c)]
            if faltantes:
                errores.append(f"Fila {i}: faltan columnas {faltantes}")
                continue
            # Verificar duplicados
            if execute_one("SELECT 1 FROM USUARIO WHERE DOCUMENTO=:d", {"d": fila["documento"]}):
                errores.append(f"Fila {i}: documento {fila['documento']} ya registrado — omitido")
                continue
            if execute_one("SELECT 1 FROM USUARIO WHERE CORREO=:c", {"c": fila["correo"].lower()}):
                errores.append(f"Fila {i}: correo {fila['correo']} ya registrado — omitido")
                continue
            try:
                import bcrypt
                hashed = bcrypt.hashpw(fila["contrasena"].encode(), bcrypt.gensalt()).decode()
                execute_query(
                    """INSERT INTO USUARIO (ESTADO,NOMBRE,APELLIDO,DOCUMENTO,CORREO,
                       CONTRASENA,ROL,ACEPTA_TERMINOS)
                       VALUES (:est,:nom,:ape,:doc,:cor,:con,'ESTUDIANTE','S')""",
                    {"est": fila.get("estado", "A").upper() or "A",
                     "nom": fila["nombre"], "ape": fila["apellido"],
                     "doc": fila["documento"], "cor": fila["correo"].lower(),
                     "con": hashed},
                    fetch=False, commit=True,
                )
                u = execute_one("SELECT ID_USUARIO FROM USUARIO WHERE DOCUMENTO=:d",
                                {"d": fila["documento"]})
                if u:
                    execute_query(
                        """INSERT INTO ESTUDIANTE (ID_USUARIO,SEMESTRE,CODIGO_ESTUDIANTE)
                           VALUES (:uid,:sem,:cod)""",
                        {"uid": u["id_usuario"],
                         "sem": int(fila.get("semestre") or 1),
                         "cod": fila.get("codigo_estudiante") or None},
                        fetch=False, commit=True,
                    )
                ok_count += 1
            except Exception as exc:
                errores.append(f"Fila {i}: error al insertar — {exc}")

    elif tipo == "docentes":
        # Columnas: nombre, apellido, documento, correo, contrasena,
        #           especialidad (opt), telefono (opt)
        REQUERIDOS = ("nombre", "apellido", "documento", "correo", "contrasena")
        for i, fila in enumerate(filas, start=2):
            fila = {k.strip().lower(): (v.strip() if v else "") for k, v in fila.items()}
            faltantes = [c for c in REQUERIDOS if not fila.get(c)]
            if faltantes:
                errores.append(f"Fila {i}: faltan columnas {faltantes}")
                continue
            if execute_one("SELECT 1 FROM USUARIO WHERE DOCUMENTO=:d", {"d": fila["documento"]}):
                errores.append(f"Fila {i}: documento {fila['documento']} ya registrado — omitido")
                continue
            if execute_one("SELECT 1 FROM USUARIO WHERE CORREO=:c", {"c": fila["correo"].lower()}):
                errores.append(f"Fila {i}: correo {fila['correo']} ya registrado — omitido")
                continue
            try:
                import bcrypt
                hashed = bcrypt.hashpw(fila["contrasena"].encode(), bcrypt.gensalt()).decode()
                execute_query(
                    """INSERT INTO USUARIO (ESTADO,NOMBRE,APELLIDO,DOCUMENTO,CORREO,
                       CONTRASENA,ROL,ACEPTA_TERMINOS)
                       VALUES (:est,:nom,:ape,:doc,:cor,:con,'DOCENTE','S')""",
                    {"est": fila.get("estado", "A").upper() or "A",
                     "nom": fila["nombre"], "ape": fila["apellido"],
                     "doc": fila["documento"], "cor": fila["correo"].lower(),
                     "con": hashed},
                    fetch=False, commit=True,
                )
                u = execute_one("SELECT ID_USUARIO FROM USUARIO WHERE DOCUMENTO=:d",
                                {"d": fila["documento"]})
                if u:
                    execute_query(
                        """INSERT INTO DOCENTE (ID_USUARIO,ESPECIALIDAD,TELEFONO)
                           VALUES (:uid,:esp,:tel)""",
                        {"uid": u["id_usuario"],
                         "esp": fila.get("especialidad") or "",
                         "tel": fila.get("telefono") or ""},
                        fetch=False, commit=True,
                    )
                ok_count += 1
            except Exception as exc:
                errores.append(f"Fila {i}: error al insertar — {exc}")

    elif tipo == "personal_administrativo":
        # Columnas: nombre, apellido, documento, correo, contrasena
        REQUERIDOS = ("nombre", "apellido", "documento", "correo", "contrasena")
        for i, fila in enumerate(filas, start=2):
            fila = {k.strip().lower(): (v.strip() if v else "") for k, v in fila.items()}
            faltantes = [c for c in REQUERIDOS if not fila.get(c)]
            if faltantes:
                errores.append(f"Fila {i}: faltan columnas {faltantes}")
                continue
            if execute_one("SELECT 1 FROM USUARIO WHERE DOCUMENTO=:d", {"d": fila["documento"]}):
                errores.append(f"Fila {i}: documento {fila['documento']} ya registrado — omitido")
                continue
            if execute_one("SELECT 1 FROM USUARIO WHERE CORREO=:c", {"c": fila["correo"].lower()}):
                errores.append(f"Fila {i}: correo {fila['correo']} ya registrado — omitido")
                continue
            try:
                import bcrypt
                hashed = bcrypt.hashpw(fila["contrasena"].encode(), bcrypt.gensalt()).decode()
                execute_query(
                    """INSERT INTO USUARIO (ESTADO,NOMBRE,APELLIDO,DOCUMENTO,CORREO,
                       CONTRASENA,ROL,ACEPTA_TERMINOS)
                       VALUES (:est,:nom,:ape,:doc,:cor,:con,'ADMINISTRADOR','S')""",
                    {"est": fila.get("estado", "A").upper() or "A",
                     "nom": fila["nombre"], "ape": fila["apellido"],
                     "doc": fila["documento"], "cor": fila["correo"].lower(),
                     "con": hashed},
                    fetch=False, commit=True,
                )
                ok_count += 1
            except Exception as exc:
                errores.append(f"Fila {i}: error al insertar — {exc}")

    elif tipo == "materias":
        # Columnas: nombre_materia, codigo, creditos, semestre,
        #           porcentaje_min (opt), nombre_carrera (opt), documento_docente (opt)
        REQUERIDOS = ("nombre_materia", "codigo", "creditos", "semestre")
        for i, fila in enumerate(filas, start=2):
            fila = {k.strip().lower(): (v.strip() if v else "") for k, v in fila.items()}
            faltantes = [c for c in REQUERIDOS if not fila.get(c)]
            if faltantes:
                errores.append(f"Fila {i}: faltan columnas {faltantes}")
                continue
            if execute_one("SELECT 1 FROM MATERIA WHERE CODIGO=:c", {"c": fila["codigo"]}):
                errores.append(f"Fila {i}: código de materia {fila['codigo']} ya existe — omitido")
                continue
            # Resolver carrera por nombre si viene
            id_carrera = None
            if fila.get("nombre_carrera"):
                c = execute_one(
                    "SELECT ID_CARRERA FROM CARRERA WHERE UPPER(NOMBRE_CARRERA)=UPPER(:n)",
                    {"n": fila["nombre_carrera"]}
                )
                if c:
                    id_carrera = c["id_carrera"]
                else:
                    errores.append(f"Fila {i}: carrera '{fila['nombre_carrera']}' no encontrada — se deja sin carrera")
            # Resolver docente por documento si viene
            id_docente = None
            if fila.get("documento_docente"):
                u = execute_one("SELECT ID_USUARIO FROM USUARIO WHERE DOCUMENTO=:d",
                                {"d": fila["documento_docente"]})
                if u:
                    d = execute_one("SELECT ID_DOCENTE FROM DOCENTE WHERE ID_USUARIO=:uid",
                                    {"uid": u["id_usuario"]})
                    if d:
                        id_docente = d["id_docente"]
                if not id_docente:
                    errores.append(f"Fila {i}: docente con documento {fila['documento_docente']} no encontrado — se deja sin docente")
            try:
                execute_query(
                    """INSERT INTO MATERIA
                       (NOMBRE_MATERIA,CODIGO,CREDITOS,SEMESTRE,PORCENTAJE_MIN,ID_CARRERA,ID_DOCENTE)
                       VALUES (:nm,:cod,:cred,:sem,:pct,:ic,:id)""",
                    {"nm":  fila["nombre_materia"],
                     "cod": fila["codigo"],
                     "cred": int(fila["creditos"]),
                     "sem":  int(fila["semestre"]),
                     "pct":  float(fila.get("porcentaje_min") or 75),
                     "ic":   id_carrera,
                     "id":   id_docente},
                    fetch=False, commit=True,
                )
                ok_count += 1
            except Exception as exc:
                errores.append(f"Fila {i}: error al insertar — {exc}")

    elif tipo == "horarios":
        # Columnas: codigo_materia, dia, hora_inicio (HH:MM), hora_fin (HH:MM), aula (opt)
        REQUERIDOS = ("codigo_materia", "dia", "hora_inicio", "hora_fin")
        for i, fila in enumerate(filas, start=2):
            fila = {k.strip().lower(): (v.strip() if v else "") for k, v in fila.items()}
            faltantes = [c for c in REQUERIDOS if not fila.get(c)]
            if faltantes:
                errores.append(f"Fila {i}: faltan columnas {faltantes}")
                continue
            mat = execute_one("SELECT ID_MATERIA FROM MATERIA WHERE CODIGO=:c",
                              {"c": fila["codigo_materia"]})
            if not mat:
                errores.append(f"Fila {i}: materia con código {fila['codigo_materia']} no encontrada — omitido")
                continue
            try:
                hi = fila["hora_inicio"] + ":00"
                hf = fila["hora_fin"]    + ":00"
                execute_query(
                    """INSERT INTO HORARIO (ID_MATERIA,HORA_INICIO,HORA_FIN,DIA,AULA)
                       VALUES (:im,
                               TO_TIMESTAMP(:hi,'HH24:MI:SS'),
                               TO_TIMESTAMP(:hf,'HH24:MI:SS'),
                               :dia,:aula)""",
                    {"im":  mat["id_materia"],
                     "hi":  hi, "hf": hf,
                     "dia": fila["dia"].upper(),
                     "aula": fila.get("aula") or None},
                    fetch=False, commit=True,
                )
                ok_count += 1
            except Exception as exc:
                errores.append(f"Fila {i}: error al insertar — {exc}")

    # ── Auditoría ────────────────────────────────────────────────────────────
    registrar_auditoria(
        session["usuario_id"],
        f"CARGA_MASIVA_CSV_{tipo.upper()}_{ok_count}ok_{len(errores)}err",
        "VARIOS",
        request.remote_addr,
    )

    return render_template(
        "admin/carga_masiva.html",
        resultado={
            "tipo":     tipo,
            "total":    len(filas),
            "ok":       ok_count,
            "errores":  errores,
        },
    )


# ════════════════════════════════════════════════════════════════════════════
# ACADÉMICO
# ════════════════════════════════════════════════════════════════════════════
academico_bp = Blueprint("academico", __name__)


@academico_bp.route("/materias")
@login_required
@role_required("ADMINISTRADOR")
def materias():
    lista = execute_query(
        """SELECT m.*, c.NOMBRE_CARRERA,
                  u.NOMBRE || ' ' || u.APELLIDO AS DOCENTE_NOMBRE
           FROM MATERIA m
           LEFT JOIN CARRERA c ON m.ID_CARRERA = c.ID_CARRERA
           LEFT JOIN DOCENTE d ON m.ID_DOCENTE = d.ID_DOCENTE
           LEFT JOIN USUARIO u ON d.ID_USUARIO = u.ID_USUARIO
           ORDER BY m.SEMESTRE, m.NOMBRE_MATERIA"""
    ) or []
    carreras = execute_query("SELECT * FROM CARRERA ORDER BY NOMBRE_CARRERA") or []
    docentes = execute_query(
        """SELECT d.ID_DOCENTE,
                  u.NOMBRE || ' ' || u.APELLIDO AS NOMBRE
           FROM DOCENTE d JOIN USUARIO u ON d.ID_USUARIO = u.ID_USUARIO
           ORDER BY u.NOMBRE"""
    ) or []
    return render_template("academico/materias.html",
                           materias=lista, carreras=carreras, docentes=docentes)


@academico_bp.route("/materias/guardar", methods=["POST"])
@login_required
@role_required("ADMINISTRADOR")
def guardar_materia():
    d = request.form
    p = {
        "nm":  d.get("nombre_materia"),
        "cod": d.get("codigo"),
        "cred":d.get("creditos"),
        "sem": d.get("semestre"),
        "pct": d.get("porcentaje_min", 75),
        "ic":  d.get("id_carrera") or None,
        "id":  d.get("id_docente") or None,
    }
    if d.get("id_materia"):
        p["im"] = d["id_materia"]
        execute_query(
            """UPDATE MATERIA SET NOMBRE_MATERIA=:nm, CODIGO=:cod,
               CREDITOS=:cred, SEMESTRE=:sem, PORCENTAJE_MIN=:pct,
               ID_CARRERA=:ic, ID_DOCENTE=:id
               WHERE ID_MATERIA=:im""",
            p, fetch=False, commit=True)
    else:
        execute_query(
            """INSERT INTO MATERIA
               (NOMBRE_MATERIA,CODIGO,CREDITOS,SEMESTRE,PORCENTAJE_MIN,ID_CARRERA,ID_DOCENTE)
               VALUES (:nm,:cod,:cred,:sem,:pct,:ic,:id)""",
            p, fetch=False, commit=True)
    registrar_auditoria(session["usuario_id"], "GUARDAR_MATERIA",
                        "MATERIA", request.remote_addr)
    flash("Materia guardada correctamente.", "success")
    return redirect(url_for("academico.materias"))


@academico_bp.route("/horarios")
@login_required
@role_required("ADMINISTRADOR")
def horarios():
    # LEFT JOIN para mostrar horarios incluso si la materia se eliminó/cambió
    lista = execute_query(
        """SELECT h.ID_HORARIO,
                  h.ID_MATERIA,
                  h.DIA,
                  h.HORA_INICIO,
                  h.HORA_FIN,
                  h.AULA,
                  NVL(h.ESTADO, 'A') AS ESTADO,
                  NVL(m.NOMBRE_MATERIA, '(Sin materia)') AS NOMBRE_MATERIA
           FROM HORARIO h
           LEFT JOIN MATERIA m ON h.ID_MATERIA = m.ID_MATERIA
           WHERE NVL(h.ESTADO,'A') = 'A'
           ORDER BY
             DECODE(h.DIA,'LUNES',1,'MARTES',2,'MIERCOLES',3,'JUEVES',4,'VIERNES',5,'SABADO',6,7),
             h.HORA_INICIO"""
    ) or []
    mat = execute_query(
        "SELECT ID_MATERIA, NOMBRE_MATERIA FROM MATERIA WHERE NVL(ESTADO,'A')='A' ORDER BY NOMBRE_MATERIA"
    ) or []
    # Log para diagnóstico
    import logging
    logging.info(f"[SISCA] /horarios -> {len(lista)} horarios, {len(mat)} materias")
    return render_template("academico/horarios.html", horarios=lista, materias=mat)


@academico_bp.route("/horarios/guardar", methods=["POST"])
@login_required
@role_required("ADMINISTRADOR")
def guardar_horario():
    d  = request.form
    # Normaliza HH:MM -> HH:MM:00 sin duplicar segundos si ya vienen incluidos
    def _norm_time(t: str) -> str:
        t = (t or "").strip()
        parts = t.split(":")
        if len(parts) == 2:
            return t + ":00"
        return t  # ya tiene segundos
    hi = _norm_time(d.get("hora_inicio", ""))
    hf = _norm_time(d.get("hora_fin",    ""))
    p  = {"im": d["id_materia"], "hi": hi, "hf": hf,
          "dia": d["dia"], "aula": d.get("aula")}
    if d.get("id_horario"):
        p["ih"] = d["id_horario"]
        execute_query(
            """UPDATE HORARIO SET ID_MATERIA=:im,
               HORA_INICIO=TO_TIMESTAMP(:hi,'HH24:MI:SS'),
               HORA_FIN=TO_TIMESTAMP(:hf,'HH24:MI:SS'),
               DIA=:dia, AULA=:aula WHERE ID_HORARIO=:ih""",
            p, fetch=False, commit=True)
    else:
        execute_query(
            """INSERT INTO HORARIO (ID_MATERIA,HORA_INICIO,HORA_FIN,DIA,AULA)
               VALUES (:im,TO_TIMESTAMP(:hi,'HH24:MI:SS'),
                       TO_TIMESTAMP(:hf,'HH24:MI:SS'),:dia,:aula)""",
            p, fetch=False, commit=True)
    flash("Horario guardado.", "success")
    return redirect(url_for("academico.horarios"))


@academico_bp.route("/carreras")
@login_required
@role_required("ADMINISTRADOR")
def carreras():
    lista = execute_query("SELECT * FROM CARRERA ORDER BY NOMBRE_CARRERA") or []
    return render_template("academico/carreras.html", carreras=lista)


@academico_bp.route("/carreras/guardar", methods=["POST"])
@login_required
@role_required("ADMINISTRADOR")
def guardar_carrera():
    d = request.form
    p = {"n": d["nombre_carrera"], "f": d.get("facultad"),
         "c": d.get("codigo_carrera")}
    if d.get("id_carrera"):
        p["id"] = d["id_carrera"]
        execute_query(
            "UPDATE CARRERA SET NOMBRE_CARRERA=:n, FACULTAD=:f, CODIGO_CARRERA=:c WHERE ID_CARRERA=:id",
            p, fetch=False, commit=True)
    else:
        execute_query(
            "INSERT INTO CARRERA (NOMBRE_CARRERA,FACULTAD,CODIGO_CARRERA) VALUES (:n,:f,:c)",
            p, fetch=False, commit=True)
    flash("Carrera guardada.", "success")
    return redirect(url_for("academico.carreras"))


# ════════════════════════════════════════════════════════════════════════════
# DOCENTE
# ════════════════════════════════════════════════════════════════════════════
docente_bp = Blueprint("docente", __name__)


@docente_bp.route("/dashboard")
@login_required
@role_required("DOCENTE")
def dashboard():
    uid     = session["usuario_id"]
    docente = execute_one(
        "SELECT ID_DOCENTE FROM DOCENTE WHERE ID_USUARIO=:user_id", {"user_id": uid}
    )
    did = docente["id_docente"] if docente else None

    materias = []
    sesiones_activas = []
    horario_grilla = {}
    if did:
        materias = execute_query(
            "SELECT * FROM MATERIA WHERE ID_DOCENTE=:did AND ESTADO='A' ORDER BY SEMESTRE",
            {"did": did}
        ) or []
        sesiones_activas = execute_query(
            """SELECT sc.*, h.DIA, h.AULA, m.NOMBRE_MATERIA,
                      (SELECT COUNT(*) FROM ASISTENCIA a
                       WHERE a.ID_SESION = sc.ID_SESION) AS TOTAL_ASIST
               FROM SESION_CLASE sc
               JOIN HORARIO h ON sc.ID_HORARIO = h.ID_HORARIO
               JOIN MATERIA  m ON h.ID_MATERIA  = m.ID_MATERIA
               WHERE m.ID_DOCENTE = :did AND sc.ESTADO_SESION = 'ACTIVA'
               ORDER BY sc.FECHA_SESION DESC""",
            {"did": did}
        ) or []
        horarios_raw = execute_query(
            """SELECT h.ID_HORARIO, h.DIA,
                      TO_CHAR(h.HORA_INICIO, 'HH24:MI') AS HORA_INICIO,
                      TO_CHAR(h.HORA_FIN, 'HH24:MI') AS HORA_FIN,
                      h.AULA, m.NOMBRE_MATERIA, m.CODIGO
               FROM HORARIO h
               JOIN MATERIA m ON h.ID_MATERIA = m.ID_MATERIA
               WHERE m.ID_DOCENTE = :did AND h.ESTADO = 'A'
               ORDER BY DECODE(h.DIA,'LUNES',1,'MARTES',2,'MIERCOLES',3,
                               'JUEVES',4,'VIERNES',5,'SABADO',6,7),
                        h.HORA_INICIO""",
            {"did": did}
        ) or []
        for h in horarios_raw:
            dia = h.get("dia", "OTRO")
            horario_grilla.setdefault(dia, []).append(h)

    return render_template("docente/dashboard.html",
                           materias=materias,
                           sesiones_activas=sesiones_activas,
                           horario_grilla=horario_grilla,
                           did=did)


# ════════════════════════════════════════════════════════════════════════════
# ESTUDIANTE
# ════════════════════════════════════════════════════════════════════════════
estudiante_bp = Blueprint("estudiante", __name__)


@estudiante_bp.route("/dashboard")
@login_required
@role_required("ESTUDIANTE")
def dashboard():
    uid = session["usuario_id"]
    est = execute_one(
        "SELECT * FROM ESTUDIANTE WHERE ID_USUARIO=:user_id", {"user_id": uid}
    )
    eid = est["id_estudiante"] if est else None
    inscripciones = []
    sesion_activa = None
    if eid:
        inscripciones = execute_query(
            """SELECT
                 i.ID_INSCRIPCION, i.ID_MATERIA, i.SEMESTRE, i.ESTADO,
                 m.NOMBRE_MATERIA, m.PORCENTAJE_MIN,
                 NVL(ROUND(
                   (SELECT COUNT(*) FROM ASISTENCIA a
                    JOIN SESION_CLASE sc2 ON a.ID_SESION = sc2.ID_SESION
                    JOIN HORARIO h2       ON sc2.ID_HORARIO = h2.ID_HORARIO
                    WHERE h2.ID_MATERIA = i.ID_MATERIA
                      AND a.ID_ESTUDIANTE = :eid1
                      AND a.ESTADO = 'PRESENTE') * 100.0 /
                   NULLIF((SELECT COUNT(*) FROM SESION_CLASE sc3
                    JOIN HORARIO h3 ON sc3.ID_HORARIO = h3.ID_HORARIO
                    WHERE h3.ID_MATERIA = i.ID_MATERIA
                      AND sc3.ESTADO_SESION = 'CERRADA'), 0)
                 , 1), 0) AS PCT
               FROM INSCRIPCION i
               JOIN MATERIA m ON i.ID_MATERIA = m.ID_MATERIA
               WHERE i.ID_ESTUDIANTE = :eid2 AND i.ESTADO = 'ACTIVA'
               ORDER BY i.SEMESTRE, m.NOMBRE_MATERIA""",
            {"eid1": eid, "eid2": eid}
        ) or []

        horarios_raw_est = execute_query(
            """SELECT h.ID_HORARIO, h.DIA,
                      TO_CHAR(h.HORA_INICIO, 'HH24:MI') AS HORA_INICIO,
                      TO_CHAR(h.HORA_FIN, 'HH24:MI') AS HORA_FIN,
                      h.AULA, m.NOMBRE_MATERIA, m.CODIGO,
                      NVL(u.NOMBRE || ' ' || u.APELLIDO, 'N/A') AS DOCENTE_NOMBRE
               FROM HORARIO h
               JOIN MATERIA m ON h.ID_MATERIA = m.ID_MATERIA
               LEFT JOIN DOCENTE doc ON doc.ID_DOCENTE = m.ID_DOCENTE
               LEFT JOIN USUARIO u   ON u.ID_USUARIO  = doc.ID_USUARIO
               JOIN INSCRIPCION i ON i.ID_MATERIA = m.ID_MATERIA
               WHERE i.ID_ESTUDIANTE = :eid AND i.ESTADO = 'ACTIVA' AND h.ESTADO = 'A'
               ORDER BY DECODE(h.DIA,'LUNES',1,'MARTES',2,'MIERCOLES',3,
                               'JUEVES',4,'VIERNES',5,'SABADO',6,7),
                        h.HORA_INICIO""",
            {"eid": eid}
        ) or []
        horario_grilla_est = {}
        for h in horarios_raw_est:
            dia = h.get("dia", "OTRO")
            horario_grilla_est.setdefault(dia, []).append(h)

        # Buscar sesión activa en materias inscritas del estudiante
        sesion_activa = execute_one(
            """SELECT sc.ID_SESION, m.NOMBRE_MATERIA, h.AULA,
                      sc.FECHA_SESION, sc.MODO_CONEXION,
                      (SELECT cq.CODIGO FROM CODIGO_QR cq
                       WHERE cq.ID_SESION = sc.ID_SESION
                         AND cq.USADO = 'N'
                         AND cq.FECHA_EXPIRACION > SYSTIMESTAMP
                         AND ROWNUM = 1) AS QR_TOKEN
               FROM SESION_CLASE sc
               JOIN HORARIO h ON sc.ID_HORARIO = h.ID_HORARIO
               JOIN MATERIA  m ON h.ID_MATERIA  = m.ID_MATERIA
               JOIN INSCRIPCION i ON i.ID_MATERIA = m.ID_MATERIA
               WHERE i.ID_ESTUDIANTE = :eid
                 AND i.ESTADO = 'ACTIVA'
                 AND sc.ESTADO_SESION = 'ACTIVA'
               FETCH FIRST 1 ROWS ONLY""",
            {"eid": eid}
        )

    return render_template("estudiante/dashboard.html",
                           inscripciones=inscripciones,
                           est=est,
                           sesion_activa=sesion_activa,
                           horario_grilla=horario_grilla_est if eid else {})


@estudiante_bp.route("/sesion-activa/poll")
@login_required
@role_required("ESTUDIANTE")
def poll_sesion_activa():
    """API de polling — retorna si hay sesión activa para el estudiante."""
    uid = session["usuario_id"]
    est = execute_one("SELECT ID_ESTUDIANTE FROM ESTUDIANTE WHERE ID_USUARIO=:uid", {"uid": uid})
    if not est:
        return jsonify({"activa": False})
    eid = est["id_estudiante"]
    sesion = execute_one(
        """SELECT sc.ID_SESION, m.NOMBRE_MATERIA,
                  (SELECT cq.CODIGO FROM CODIGO_QR cq
                   WHERE cq.ID_SESION = sc.ID_SESION AND cq.USADO='N'
                     AND cq.FECHA_EXPIRACION > SYSTIMESTAMP AND ROWNUM=1) AS QR_TOKEN
           FROM SESION_CLASE sc
           JOIN HORARIO h ON sc.ID_HORARIO = h.ID_HORARIO
           JOIN MATERIA  m ON h.ID_MATERIA  = m.ID_MATERIA
           JOIN INSCRIPCION i ON i.ID_MATERIA = m.ID_MATERIA
           WHERE i.ID_ESTUDIANTE=:eid AND i.ESTADO='ACTIVA'
             AND sc.ESTADO_SESION='ACTIVA'
           FETCH FIRST 1 ROWS ONLY""",
        {"eid": eid}
    )
    if sesion:
        return jsonify({
            "activa": True,
            "materia": sesion.get("nombre_materia"),
            "id_sesion": sesion.get("id_sesion"),
            "qr_token": sesion.get("qr_token"),
        })
    return jsonify({"activa": False})


@estudiante_bp.route("/horario/pdf")
@login_required
@role_required("ESTUDIANTE")
def descargar_horario_pdf():
    """Genera y descarga el horario del estudiante en formato PDF institucional."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Spacer, Paragraph
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import datetime

    uid = session["usuario_id"]
    usuario = execute_one(
        "SELECT NOMBRE, APELLIDO, CORREO, NUMERO_DOCUMENTO FROM USUARIO WHERE ID_USUARIO=:uid",
        {"uid": uid}
    )
    est = execute_one(
        "SELECT e.*, p.NOMBRE_PROGRAMA AS PLAN FROM ESTUDIANTE e "
        "LEFT JOIN PROGRAMA p ON p.ID_PROGRAMA = e.ID_PROGRAMA "
        "WHERE e.ID_USUARIO=:uid",
        {"uid": uid}
    )
    eid = est["id_estudiante"] if est else None

    horarios = []
    if eid:
        horarios = execute_query(
            """SELECT h.DIA,
                      m.NOMBRE_MATERIA, m.CODIGO,
                      TO_CHAR(h.HORA_INICIO,'HH24:MI') AS HORA_INICIO,
                      TO_CHAR(h.HORA_FIN,'HH24:MI') AS HORA_FIN,
                      h.AULA,
                      NVL(u.NOMBRE || ' ' || u.APELLIDO, '') AS DOCENTE_NOMBRE,
                      h.ID_HORARIO
               FROM HORARIO h
               JOIN MATERIA m ON h.ID_MATERIA = m.ID_MATERIA
               LEFT JOIN DOCENTE doc ON doc.ID_DOCENTE = m.ID_DOCENTE
               LEFT JOIN USUARIO u   ON u.ID_USUARIO  = doc.ID_USUARIO
               JOIN INSCRIPCION i ON i.ID_MATERIA = m.ID_MATERIA
               WHERE i.ID_ESTUDIANTE = :eid AND i.ESTADO = 'ACTIVA' AND h.ESTADO = 'A'
               ORDER BY DECODE(h.DIA,'LUNES',1,'MARTES',2,'MIERCOLES',3,
                               'JUEVES',4,'VIERNES',5,'SABADO',6,7),
                        h.HORA_INICIO""",
            {"eid": eid}
        ) or []

    # ── Periodo activo: intentar cross-schema SIIHAPI, fallback a derivar fechas ──
    periodo_codigo  = "2026-2T"
    periodo_nombre  = "Trimestre Académico"
    fecha_inicio_p  = None
    fecha_fin_p     = None
    try:
        per = execute_one(
            """SELECT CODIGO, NOMBRE,
                      TO_CHAR(FECHA_INICIO,'DD/MM/YYYY') AS F_INI,
                      TO_CHAR(FECHA_FIN,   'DD/MM/YYYY') AS F_FIN
               FROM SIIHAPI.SIIHAPI_PERIODO
               WHERE ACTIVO = 1
               FETCH FIRST 1 ROWS ONLY"""
        )
        if per:
            periodo_codigo = per.get("codigo") or periodo_codigo
            periodo_nombre = per.get("nombre") or periodo_nombre
            fecha_inicio_p = per.get("f_ini")
            fecha_fin_p    = per.get("f_fin")
    except Exception:
        pass   # sin acceso cross-schema: se usan valores por defecto

    buf = io.BytesIO()
    page_w, page_h = letter
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm,  bottomMargin=1.5*cm,
    )

    # ── Colores institucionales ──────────────────────────────────────────────
    AZUL     = colors.HexColor("#003366")
    AZUL_LT  = colors.HexColor("#1F6FEB")
    GRIS_HDR = colors.HexColor("#E8F0F7")
    GRIS_SEP = colors.HexColor("#CCCCCC")
    NEGRO    = colors.black
    BLANCO   = colors.white

    # ── Estilos de párrafo ──────────────────────────────────────────────────
    sty_titulo = ParagraphStyle("titulo", fontName="Helvetica-Bold",
                                fontSize=13, textColor=AZUL, alignment=TA_CENTER)
    sty_sub    = ParagraphStyle("sub",    fontName="Helvetica",
                                fontSize=8, textColor=NEGRO, alignment=TA_LEFT, leading=11)
    sty_bold   = ParagraphStyle("bold",   fontName="Helvetica-Bold",
                                fontSize=8, textColor=NEGRO, alignment=TA_LEFT, leading=11)
    sty_cell   = ParagraphStyle("cell",   fontName="Helvetica",
                                fontSize=7.5, textColor=NEGRO, alignment=TA_LEFT, leading=10)
    sty_dia    = ParagraphStyle("dia",    fontName="Helvetica-Bold",
                                fontSize=7.5, textColor=NEGRO, alignment=TA_LEFT, leading=10)
    sty_hdr    = ParagraphStyle("hdr",    fontName="Helvetica-Bold",
                                fontSize=8, textColor=AZUL, alignment=TA_LEFT, leading=10)
    sty_foot_l = ParagraphStyle("fl",     fontName="Helvetica-Oblique",
                                fontSize=7, textColor=GRIS_SEP, alignment=TA_LEFT)
    sty_foot_r = ParagraphStyle("fr",     fontName="Helvetica",
                                fontSize=7, textColor=NEGRO, alignment=TA_RIGHT)

    elementos = []

    # ═══════════════ CABECERA ════════════════════════════════════════════════
    nombre_completo = ""
    doc_id = ""
    if usuario:
        nombre_completo = f"{usuario.get('nombre','')} {usuario.get('apellido','')}".strip().upper()
        doc_id = str(usuario.get("numero_documento") or "")

    plan = (est.get("plan") or "TECNOLOGIA") if est else "TECNOLOGIA"

    # Rango de fechas del trimestre
    if fecha_inicio_p and fecha_fin_p:
        rango_fechas = f"{fecha_inicio_p}  -  {fecha_fin_p}"
    else:
        rango_fechas = periodo_codigo

    # ═══════════════ CABECERA INSTITUCIONAL ══════════════════════════════════
    sty_inst   = ParagraphStyle("inst", fontName="Helvetica-Bold",
                                fontSize=14, textColor=AZUL, alignment=TA_CENTER, spaceAfter=2)
    sty_subtit = ParagraphStyle("subtit", fontName="Helvetica-Bold",
                                fontSize=10, textColor=AZUL_LT, alignment=TA_CENTER, spaceAfter=0)

    hdr_data = [
        # Fila 1: institución + título del documento
        [Paragraph("POLITÉCNICO INTERNACIONAL", sty_inst),
         Paragraph("Pág. 1 de 1", ParagraphStyle("pg", fontName="Helvetica",
                   fontSize=7, textColor=GRIS_SEP, alignment=TA_RIGHT))],
        # Fila 2: subtítulo
        [Paragraph("GENERACIÓN DE HORARIO DEL TRIMESTRE", sty_subtit), ""],
        # Separador
        [Paragraph(f"<b>Nombre y apellidos</b>  {nombre_completo}", sty_bold),
         Paragraph(f"<b>Doc. Ident.</b>  {doc_id}", sty_bold)],
        [Paragraph(f"<b>Curso Académico</b>  {periodo_codigo}    "
                   f"<b>Centro</b>  POLITECNICO INTERNACIONAL", sty_bold),
         Paragraph(f"<b>Plan</b>  {plan}", sty_bold)],
    ]

    hdr_tbl = Table(hdr_data, colWidths=[13.5*cm, 5*cm])
    hdr_tbl.setStyle(TableStyle([
        ("SPAN",          (0, 0), (0, 0)),
        ("SPAN",          (0, 1), (1, 1)),
        ("BOX",           (0, 0), (-1, -1), 0.8, AZUL),
        ("LINEBELOW",     (0, 0), (-1, 0), 0.5, GRIS_SEP),
        ("LINEBELOW",     (0, 1), (-1, 1), 0.8, AZUL),
        ("LINEBELOW",     (0, 2), (-1, 2), 0.3, GRIS_SEP),
        ("BACKGROUND",    (0, 0), (-1, 1), colors.HexColor("#EEF4FF")),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elementos.append(hdr_tbl)
    elementos.append(Spacer(1, 0.3*cm))

    # ═══════════════ BANDA DE PERIODO / RANGO ════════════════════════════════
    sty_rango = ParagraphStyle("rango", fontName="Helvetica-Bold",
                               fontSize=9, textColor=BLANCO, alignment=TA_LEFT)
    sty_nota  = ParagraphStyle("nota",  fontName="Helvetica-Oblique",
                               fontSize=7.5, textColor=BLANCO, alignment=TA_RIGHT)

    per_data = [[
        Paragraph(f"📅  {rango_fechas}", sty_rango),
        Paragraph("Este horario se repite semanalmente durante todo el ciclo académico", sty_nota),
    ]]
    per_tbl = Table(per_data, colWidths=[7*cm, 11.5*cm])
    per_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), AZUL),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elementos.append(per_tbl)
    elementos.append(Spacer(1, 0.25*cm))

    # ═══════════════ TABLA HORARIO ════════════════════════════════════════════
    # Agrupar por día manteniendo orden
    dias_orden = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO"]
    dias_map: dict = {}
    for h in horarios:
        dia = h.get("dia", "OTRO")
        dias_map.setdefault(dia, []).append(h)

    # Encabezado de tabla
    COL_W = [2.4*cm, 4.5*cm, 2.5*cm, 3.8*cm, 3.3*cm, 2.0*cm]
    tbl_data = [[
        Paragraph("<b>Días</b>",          sty_hdr),
        Paragraph("<b>Asignatura</b>",    sty_hdr),
        Paragraph("<b>Grupo</b>",         sty_hdr),
        Paragraph("<b>Profesor</b>",      sty_hdr),
        Paragraph("<b>Aula</b>",          sty_hdr),
        Paragraph("<b>Franja Horaria</b>",sty_hdr),
    ]]

    merge_ranges = []  # (fila_inicio, fila_fin) para cada día
    row_idx = 1

    for dia in dias_orden:
        filas = dias_map.get(dia)
        if not filas:
            continue
        start_row = row_idx
        for i, h in enumerate(filas):
            asig = f"[{h.get('codigo') or ''}] {h.get('nombre_materia','')}"
            franja = f"{h.get('hora_inicio','')}&nbsp;&nbsp;-&nbsp;&nbsp;{h.get('hora_fin','')}"
            aula_txt = h.get("aula") or "N/A"
            grupo_txt = h.get("codigo") or ""
            tbl_data.append([
                Paragraph(dia if i == 0 else "", sty_dia),
                Paragraph(asig, sty_cell),
                Paragraph(grupo_txt, sty_cell),
                Paragraph(h.get("docente_nombre",""), sty_cell),
                Paragraph(aula_txt, sty_cell),
                Paragraph(franja, sty_cell),
            ])
            row_idx += 1
        if row_idx - start_row > 1:
            merge_ranges.append((start_row, row_idx - 1))

    if not horarios:
        tbl_data.append([
            Paragraph("Sin horario publicado", sty_cell), "", "", "", "", ""
        ])

    tbl = Table(tbl_data, colWidths=COL_W, repeatRows=1)
    ts = TableStyle([
        # Encabezado
        ("BACKGROUND",    (0, 0), (-1, 0), GRIS_HDR),
        ("LINEBELOW",     (0, 0), (-1, 0), 0.8, AZUL),
        # Bordes generales
        ("GRID",          (0, 0), (-1, -1), 0.3, GRIS_SEP),
        ("BOX",           (0, 0), (-1, -1), 0.5, GRIS_SEP),
        # Padding
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ])
    # Merge celdas de día para filas con múltiples materias
    for (r0, r1) in merge_ranges:
        ts.add("SPAN",       (0, r0), (0, r1))
        ts.add("VALIGN",     (0, r0), (0, r1), "TOP")
        ts.add("LINEBELOW",  (0, r0), (-1, r1), 0.5, GRIS_SEP)
    tbl.setStyle(ts)
    elementos.append(tbl)
    elementos.append(Spacer(1, 0.5*cm))

    # ═══════════════ PIE DE PÁGINA ════════════════════════════════════════════
    generado = datetime.date.today().strftime("%d/%m/%Y")
    foot_data = [[
        Paragraph("Leyenda de abreviaturas.", sty_foot_l),
        Paragraph(f"Generado el {generado}  ·  SISCA — Politécnico Internacional", sty_foot_r),
    ]]
    foot_tbl = Table(foot_data, colWidths=[7*cm, 11.5*cm])
    foot_tbl.setStyle(TableStyle([
        ("LINEABOVE",     (0, 0), (-1, 0), 0.5, GRIS_SEP),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elementos.append(foot_tbl)

    doc.build(elementos)
    buf.seek(0)

    nombre_archivo = f"horario_{nombre_completo.replace(' ','_') or 'estudiante'}.pdf"
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=nombre_archivo,
    )


# ════════════════════════════════════════════════════════════════════════════
# ASISTENCIA
# ════════════════════════════════════════════════════════════════════════════
asistencia_bp = Blueprint("asistencia", __name__)


@asistencia_bp.route("/sesion/iniciar", methods=["POST"])
@login_required
@role_required("DOCENTE")
def iniciar_sesion():
    id_materia = request.form.get("id_horario") or request.form.get("id_materia")
    modo       = request.form.get("modo", "ONLINE")

    horario = execute_one(
        "SELECT ID_HORARIO FROM HORARIO WHERE ID_MATERIA=:mat AND ESTADO='A' AND ROWNUM=1",
        {"mat": id_materia}
    )
    if not horario:
        flash("Esta materia no tiene horario configurado.", "error")
        return redirect(url_for("docente.dashboard"))

    id_horario = horario["id_horario"]
    execute_query(
        "INSERT INTO SESION_CLASE (ID_HORARIO, MODO_CONEXION) VALUES (:ih, :modo)",
        {"ih": id_horario, "modo": modo},
        fetch=False, commit=True,
    )
    sesion = execute_one(
        """SELECT ID_SESION FROM SESION_CLASE
           WHERE ID_HORARIO=:ih ORDER BY FECHA_SESION DESC
           FETCH FIRST 1 ROWS ONLY""",
        {"ih": id_horario},
    )
    flash("Sesión iniciada correctamente.", "success")
    return redirect(url_for("asistencia.sesion_activa",
                            id_sesion=sesion["id_sesion"]))


@asistencia_bp.route("/sesion/<int:id_sesion>")
@login_required
def sesion_activa(id_sesion):
    sesion = execute_one(
        """SELECT sc.*, h.DIA, h.AULA, h.HORA_INICIO, h.HORA_FIN,
                  m.NOMBRE_MATERIA, m.PORCENTAJE_MIN
           FROM SESION_CLASE sc
           JOIN HORARIO h ON sc.ID_HORARIO = h.ID_HORARIO
           JOIN MATERIA  m ON h.ID_MATERIA  = m.ID_MATERIA
           WHERE sc.ID_SESION = :sid""",
        {"sid": id_sesion},
    )
    asistentes = execute_query(
        """SELECT a.*, u.NOMBRE, u.APELLIDO, e.CODIGO_ESTUDIANTE
           FROM ASISTENCIA a
           JOIN ESTUDIANTE e ON a.ID_ESTUDIANTE = e.ID_ESTUDIANTE
           JOIN USUARIO    u ON e.ID_USUARIO    = u.ID_USUARIO
           WHERE a.ID_SESION = :sid ORDER BY a.HORA_REGISTRO""",
        {"sid": id_sesion},
    ) or []
    qr = execute_one(
        """SELECT * FROM CODIGO_QR
           WHERE ID_SESION=:sid AND USADO='N' AND FECHA_EXPIRACION>SYSTIMESTAMP""",
        {"sid": id_sesion},
    )
    segundos_restantes = 0
    if qr:
        import datetime, os
        fecha_exp = qr.get("fecha_expiracion")
        if isinstance(fecha_exp, datetime.datetime):
            diff = fecha_exp - datetime.datetime.now()
            segundos_restantes = int(diff.total_seconds())
            if segundos_restantes < 0:
                segundos_restantes = 0
        else:
            segundos_restantes = int(os.getenv("QR_EXPIRY_MINUTES", 10)) * 60
    return render_template("asistencia/sesion_activa.html",
                           sesion=sesion, asistentes=asistentes, qr=qr,
                           segundos_restantes=segundos_restantes)


@asistencia_bp.route("/sesion/<int:id_sesion>/cerrar", methods=["POST"])
@login_required
@role_required("DOCENTE")
def cerrar_sesion(id_sesion):
    execute_query(
        "UPDATE SESION_CLASE SET ESTADO_SESION='CERRADA' WHERE ID_SESION=:sid",
        {"sid": id_sesion}, fetch=False, commit=True,
    )
    flash("Sesión cerrada correctamente.", "success")
    return redirect(url_for("docente.dashboard"))


@asistencia_bp.route("/sesion/<int:id_sesion>/count")
@login_required
def contar_asistentes(id_sesion):
    """API JSON: retorna el conteo actual de asistentes de una sesión."""
    row = execute_one(
        "SELECT COUNT(*) AS N FROM ASISTENCIA WHERE ID_SESION=:sid",
        {"sid": id_sesion}
    )
    total = row["n"] if row else 0
    return jsonify({"ok": True, "total": total, "id_sesion": id_sesion})


@asistencia_bp.route("/qr/generar/<int:id_sesion>", methods=["POST"])
@login_required
@role_required("DOCENTE")
def generar_qr(id_sesion):
    import socket, os
    from app.utils.report_generator import crear_qr

    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = "127.0.0.1"

    port       = os.getenv("FLASK_PORT", "8080")
    expiry_min = int(os.getenv("QR_EXPIRY_MINUTES", 10))

    token, _path, fecha_exp = crear_qr(id_sesion, ip, port, expiry_min)

    execute_query(
        """INSERT INTO CODIGO_QR (ID_SESION, FECHA_EXPIRACION, CODIGO, IP_LOCAL)
           VALUES (:sesion_id, :fecha_exp, :codigo, :ip_local)""",
        {"sesion_id": id_sesion, "fecha_exp": fecha_exp,
         "codigo": token, "ip_local": ip},
        fetch=False, commit=True,
    )
    url = f"http://{ip}:{port}/asistencia/registrar/{token}"
    return jsonify({"ok": True, "token": token, "ip": ip,
                    "expiry_min": expiry_min, "url": url})


@asistencia_bp.route("/registrar/<token>", methods=["GET", "POST"])
def registrar_por_qr(token):
    qr = execute_one(
        """SELECT * FROM CODIGO_QR
           WHERE CODIGO=:qr_codigo AND USADO='N' AND FECHA_EXPIRACION>SYSTIMESTAMP""",
        {"qr_codigo": token},
    )
    if not qr:
        return render_template("asistencia/qr_expirado.html")

    if request.method == "POST":
        uid = session.get("usuario_id")
        if not uid or session.get("rol") != "ESTUDIANTE":
            flash("Debes iniciar sesión como estudiante.", "error")
            return redirect(url_for("auth.login", rol="estudiante"))

        est = execute_one(
            "SELECT ID_ESTUDIANTE FROM ESTUDIANTE WHERE ID_USUARIO=:user_id",
            {"user_id": uid},
        )
        if not est:
            flash("Perfil de estudiante no encontrado.", "error")
            return redirect(url_for("estudiante.dashboard"))

        id_est = est["id_estudiante"]
        if execute_one(
            "SELECT 1 FROM ASISTENCIA WHERE ID_SESION=:sid AND ID_ESTUDIANTE=:eid",
            {"sid": qr["id_sesion"], "eid": id_est},
        ):
            return render_template("asistencia/ya_registrado.html")

        execute_query(
            "INSERT INTO ASISTENCIA (ID_SESION,ID_ESTUDIANTE,TIPO_REGISTRO) VALUES (:sid,:eid,'QR')",
            {"sid": qr["id_sesion"], "eid": id_est},
            fetch=False, commit=True,
        )
        execute_query(
            "UPDATE CODIGO_QR SET USADO='S' WHERE ID_QR=:qr_id",
            {"qr_id": qr["id_qr"]},
            fetch=False, commit=True,
        )
        registrar_auditoria(uid, "REGISTRO_QR", "ASISTENCIA", request.remote_addr)
        return render_template("asistencia/registro_exitoso.html")

    # GET — mostrar página de confirmación
    sesion = execute_one(
        """SELECT sc.*, m.NOMBRE_MATERIA, h.AULA
           FROM SESION_CLASE sc
           JOIN HORARIO h ON sc.ID_HORARIO = h.ID_HORARIO
           JOIN MATERIA  m ON h.ID_MATERIA  = m.ID_MATERIA
           WHERE sc.ID_SESION = :sid""",
        {"sid": qr["id_sesion"]},
    )
    return render_template("asistencia/registro_qr.html",
                           sesion=sesion, token=token)


@asistencia_bp.route("/manual", methods=["POST"])
@login_required
@role_required("DOCENTE")
def registro_manual():
    d      = request.form
    sid    = d.get("id_sesion")
    eid    = d.get("id_estudiante")
    estado = d.get("estado", "PRESENTE")

    if execute_one(
        "SELECT 1 FROM ASISTENCIA WHERE ID_SESION=:sid AND ID_ESTUDIANTE=:eid",
        {"sid": sid, "eid": eid},
    ):
        return jsonify({"ok": False, "msg": "Estudiante ya registrado en esta sesión."})

    execute_query(
        """INSERT INTO ASISTENCIA (ID_SESION,ID_ESTUDIANTE,ESTADO,TIPO_REGISTRO)
           VALUES (:sid,:eid,:estado,'MANUAL')""",
        {"sid": sid, "eid": eid, "estado": estado},
        fetch=False, commit=True,
    )
    registrar_auditoria(session["usuario_id"], "REGISTRO_MANUAL",
                        "ASISTENCIA", request.remote_addr)
    return jsonify({"ok": True, "msg": "Asistencia registrada manualmente."})


# ════════════════════════════════════════════════════════════════════════════
# REPORTES
# ════════════════════════════════════════════════════════════════════════════
reporte_bp = Blueprint("reportes", __name__)

_SQL_ASISTENCIA = """
    SELECT u.NOMBRE || ' ' || u.APELLIDO AS ESTUDIANTE,
           m.NOMBRE_MATERIA,
           sc.FECHA_SESION,
           a.ESTADO,
           a.TIPO_REGISTRO,
           a.HORA_REGISTRO
    FROM ASISTENCIA a
    JOIN ESTUDIANTE   e  ON a.ID_ESTUDIANTE  = e.ID_ESTUDIANTE
    JOIN USUARIO      u  ON e.ID_USUARIO     = u.ID_USUARIO
    JOIN SESION_CLASE sc ON a.ID_SESION      = sc.ID_SESION
    JOIN HORARIO      h  ON sc.ID_HORARIO    = h.ID_HORARIO
    JOIN MATERIA      m  ON h.ID_MATERIA     = m.ID_MATERIA
"""


@reporte_bp.route("/")
@login_required
@role_required("ADMINISTRADOR", "DOCENTE")
def dashboard():
    return render_template("reportes/dashboard.html")


@reporte_bp.route("/asistencia")
@login_required
def reporte_asistencia():
    id_mat = request.args.get("id_materia")
    fecha  = request.args.get("fecha", "")
    sql    = _SQL_ASISTENCIA + " WHERE 1=1"
    params = {}
    if id_mat:
        sql += " AND m.ID_MATERIA=:mat"; params["mat"] = id_mat
    if fecha:
        sql += " AND sc.FECHA_SESION=TO_DATE(:fecha,'YYYY-MM-DD')"; params["fecha"] = fecha
    sql += " ORDER BY sc.FECHA_SESION DESC, u.APELLIDO"
    datos    = execute_query(sql, params) or []
    materias = execute_query(
        "SELECT ID_MATERIA, NOMBRE_MATERIA FROM MATERIA WHERE ESTADO='A' ORDER BY NOMBRE_MATERIA"
    ) or []
    return render_template("reportes/reporte_asistencia.html",
                           datos=datos, materias=materias,
                           filtros={"id_materia": id_mat, "fecha": fecha})


@reporte_bp.route("/pdf")
@login_required
def exportar_pdf():
    from app.utils.report_generator import generar_pdf_asistencia
    id_mat = request.args.get("id_materia")
    sql    = _SQL_ASISTENCIA
    params = {}
    if id_mat:
        sql += " WHERE m.ID_MATERIA=:mat"; params["mat"] = id_mat
    sql += " ORDER BY sc.FECHA_SESION DESC"
    datos    = execute_query(sql, params) or []
    pdf_path = generar_pdf_asistencia(datos)
    return send_file(pdf_path, as_attachment=True,
                     download_name="reporte_asistencia_SISCA.pdf")


@reporte_bp.route("/excel")
@login_required
def exportar_excel():
    from app.utils.report_generator import generar_excel_asistencia
    datos = execute_query(_SQL_ASISTENCIA + " ORDER BY sc.FECHA_SESION DESC") or []
    path  = generar_excel_asistencia(datos)
    return send_file(path, as_attachment=True,
                     download_name="reporte_asistencia_SISCA.xlsx")


@reporte_bp.route("/auditoria")
@login_required
@role_required("ADMINISTRADOR")
def auditoria():
    logs = execute_query(
        """SELECT au.*, u.NOMBRE || ' ' || u.APELLIDO AS USUARIO_NOMBRE
           FROM AUDITORIA au
           LEFT JOIN USUARIO u ON au.ID_USUARIO = u.ID_USUARIO
           ORDER BY au.FECHA DESC FETCH FIRST 200 ROWS ONLY"""
    ) or []
    return render_template("reportes/auditoria.html", logs=logs)


@reporte_bp.route("/auditoria/pdf")
@login_required
@role_required("ADMINISTRADOR")
def auditoria_pdf():
    """Exporta el log de auditoría completo a PDF."""
    import tempfile, os, uuid
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from datetime import datetime

    logs = execute_query(
        """SELECT au.FECHA, u.NOMBRE || ' ' || u.APELLIDO AS USUARIO_NOMBRE,
                  au.ACCION, au.TABLA_AFECTADA, au.IP
           FROM AUDITORIA au
           LEFT JOIN USUARIO u ON au.ID_USUARIO = u.ID_USUARIO
           ORDER BY au.FECHA DESC FETCH FIRST 500 ROWS ONLY"""
    ) or []

    path = os.path.join(tempfile.gettempdir(), f"sisca_auditoria_{uuid.uuid4().hex[:8]}.pdf")
    doc  = SimpleDocTemplate(path, pagesize=landscape(A4),
                              leftMargin=20, rightMargin=20, topMargin=30, bottomMargin=20)
    styles = getSampleStyleSheet()
    BLUE   = colors.HexColor("#1F6FEB")
    DARK   = colors.HexColor("#0D1117")
    GRAY   = colors.HexColor("#F6F8FA")

    elements = [
        Paragraph("SISCA · Politécnico Internacional", styles["Title"]),
        Paragraph("Reporte de Auditoría del Sistema", styles["Heading2"]),
        Paragraph(f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}  |  Registros: {len(logs)}",
                  styles["Normal"]),
        Spacer(1, 14),
    ]

    headers = ["Fecha / Hora", "Usuario", "Acción", "Tabla", "IP"]
    rows = [headers] + [
        [
            str(r.get("fecha", ""))[:19],
            str(r.get("usuario_nombre") or "Sistema")[:30],
            str(r.get("accion", ""))[:50],
            str(r.get("tabla_afectada", ""))[:20],
            str(r.get("ip", ""))[:20],
        ]
        for r in logs
    ]

    col_widths = [120, 130, 200, 90, 100]
    tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1,  0), BLUE),
        ("TEXTCOLOR",     (0, 0), (-1,  0), colors.white),
        ("FONTNAME",      (0, 0), (-1,  0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor("#30363D")),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, GRAY]),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(tbl)
    doc.build(elements)
    return send_file(path, as_attachment=True,
                     download_name=f"auditoria_SISCA_{datetime.now().strftime('%Y%m%d')}.pdf")


@reporte_bp.route("/auditoria/excel")
@login_required
@role_required("ADMINISTRADOR")
def auditoria_excel():
    """Exporta el log de auditoría completo a Excel."""
    import tempfile, os, uuid
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from datetime import datetime

    logs = execute_query(
        """SELECT au.FECHA, u.NOMBRE || ' ' || u.APELLIDO AS USUARIO_NOMBRE,
                  au.ACCION, au.TABLA_AFECTADA, au.IP
           FROM AUDITORIA au
           LEFT JOIN USUARIO u ON au.ID_USUARIO = u.ID_USUARIO
           ORDER BY au.FECHA DESC FETCH FIRST 1000 ROWS ONLY"""
    ) or []

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Auditoría SISCA"

    # Título
    ws.merge_cells("A1:E1")
    ws["A1"] = "SISCA · Politécnico Internacional — Reporte de Auditoría"
    ws["A1"].font      = Font(bold=True, size=13, color="FFFFFF")
    ws["A1"].fill      = PatternFill("solid", fgColor="1F6FEB")
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:E2")
    ws["A2"] = f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}  |  Total registros: {len(logs)}"
    ws["A2"].font      = Font(italic=True, size=9, color="666666")
    ws["A2"].alignment = Alignment(horizontal="center")
    ws.row_dimensions[2].height = 16

    # Cabeceras
    headers = ["Fecha / Hora", "Usuario", "Acción", "Tabla Afectada", "IP"]
    col_widths = [22, 28, 42, 20, 18]
    hdr_fill = PatternFill("solid", fgColor="161B22")
    thin = Side(style='thin', color='30363D')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for ci, (h, w) in enumerate(zip(headers, col_widths), start=1):
        cell = ws.cell(row=3, column=ci, value=h)
        cell.font      = hdr_font
        cell.fill      = hdr_fill
        cell.border    = border
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[cell.column_letter].width = w
    ws.row_dimensions[3].height = 18

    alt_fill  = PatternFill("solid", fgColor="0D1117")
    norm_fill = PatternFill("solid", fgColor="161B22")
    norm_font = Font(color="C9D1D9", size=9)

    for ri, log in enumerate(logs, start=4):
        row_fill = alt_fill if ri % 2 == 0 else norm_fill
        values = [
            str(log.get('fecha_hora', '')),
            str(log.get('usuario',    '')),
            str(log.get('accion',     '')),
            str(log.get('tabla_afectada', '')),
            str(log.get('ip',         '')),
        ]
        for ci, val in enumerate(values, start=1):
            cell = ws.cell(row=ri, column=ci, value=val)
            cell.font      = norm_font
            cell.fill      = row_fill
            cell.border    = border
            cell.alignment = Alignment(vertical="center", wrap_text=(ci == 3))
        ws.row_dimensions[ri].height = 15

    ws.freeze_panes = "A4"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
