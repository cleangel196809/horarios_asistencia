from flask import Blueprint, jsonify, request
from app.database.connection import execute_one, execute_query
import bcrypt

api_bp = Blueprint("api", __name__)

@api_bp.route("/login", methods=["POST"])
def api_login():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No se enviaron datos"}), 400
    
    correo = data.get("correo")
    pwd = data.get("contrasena")
    rol = data.get("rol")
    
    if not correo or not pwd or not rol:
        return jsonify({"success": False, "error": "Faltan credenciales"}), 400
        
    sql = "SELECT ID_USUARIO, CORREO, CONTRASENA, NOMBRE, APELLIDO, ROL FROM USUARIO WHERE CORREO = :correo"
    row = execute_one(sql, {"correo": correo})
    
    # Validar contraseña usando bcrypt
    pwd_valid = False
    if row and row["contrasena"]:
        try:
            pwd_valid = bcrypt.checkpw(pwd.encode("utf-8"), row["contrasena"].encode("utf-8"))
        except Exception:
            pwd_valid = False
            
    # Validar que existe, que la pass coincide, y que el rol es el correcto
    if row and pwd_valid:
        # Mapear rol esperado vs rol real (admin vs ADMINISTRADOR)
        rol_db = row["rol"].lower()
        rol_expected = "administrador" if rol == "admin" else rol
        
        if rol_db != rol_expected:
            return jsonify({"success": False, "error": "Rol incorrecto para este usuario"}), 401
            
        nombre_completo = f"{row['nombre']} {row['apellido']}"
        return jsonify({
            "success": True, 
            "user": {
                "id": row["id_usuario"], 
                "nombre": nombre_completo, 
                "rol": rol, 
                "correo": row["correo"],
                "avatar_initials": nombre_completo[:2].upper()
            }
        })
    else:
        return jsonify({"success": False, "error": "Credenciales inválidas"}), 401

@api_bp.route("/dashboard", methods=["GET"])
def api_dashboard():
    rol = request.args.get("rol")
    user_id = request.args.get("id")
    
    if not rol or not user_id:
        return jsonify({"success": False, "error": "Parámetros insuficientes"}), 400
        
    stats = {}
    if rol == "admin":
        est = execute_one("SELECT COUNT(*) as c FROM ESTUDIANTE")
        doc = execute_one("SELECT COUNT(*) as c FROM DOCENTE")
        mat = execute_one("SELECT COUNT(*) as c FROM MATERIA")
        stats["usuarios"] = (est["c"] if est else 0) + (doc["c"] if doc else 0)
        stats["materias"] = mat["c"] if mat else 0
    elif rol == "docente":
        # Mapear user_id (ID_USUARIO) a ID_DOCENTE
        doc_row = execute_one("SELECT ID_DOCENTE FROM DOCENTE WHERE ID_USUARIO = :user_id", {"user_id": user_id})
        doc_id = doc_row["id_docente"] if doc_row else None
        
        if doc_id:
            ses = execute_one("""
                SELECT COUNT(*) as c 
                FROM SESION_CLASE SC
                JOIN HORARIO H ON SC.ID_HORARIO = H.ID_HORARIO
                JOIN MATERIA M ON H.ID_MATERIA = M.ID_MATERIA
                WHERE M.ID_DOCENTE = :id
            """, {"id": doc_id})
            stats["sesiones"] = ses["c"] if ses else 0
            
            materias_raw = execute_query("""
                SELECT ID_MATERIA, NOMBRE_MATERIA 
                FROM MATERIA 
                WHERE ID_DOCENTE = :id
            """, {"id": doc_id})
            stats["materias"] = [{"nombre": m["nombre_materia"], "id": m["id_materia"]} for m in materias_raw]
        else:
            stats["sesiones"] = 0
            stats["materias"] = []
    elif rol == "estudiante":
        # Mapear user_id (ID_USUARIO) a ID_ESTUDIANTE
        est_row = execute_one("SELECT ID_ESTUDIANTE FROM ESTUDIANTE WHERE ID_USUARIO = :user_id", {"user_id": user_id})
        est_id = est_row["id_estudiante"] if est_row else None
        
        if est_id:
            asis = execute_one("SELECT COUNT(*) as c FROM ASISTENCIA WHERE ID_ESTUDIANTE = :id", {"id": est_id})
            stats["asistencias"] = asis["c"] if asis else 0
        else:
            stats["asistencias"] = 0
            
    return jsonify({"success": True, "stats": stats})

@api_bp.route("/asistencia", methods=["POST"])
def api_asistencia():
    data = request.get_json()
    id_sesion = data.get("id_sesion")
    id_estudiante = data.get("id_estudiante") # Este es el ID_USUARIO enviado por el cliente
    
    if not id_sesion or not id_estudiante:
         return jsonify({"success": False, "error": "Faltan datos"}), 400
         
    try:
        # Obtener ID_ESTUDIANTE real a partir del ID_USUARIO
        est_row = execute_one("SELECT ID_ESTUDIANTE FROM ESTUDIANTE WHERE ID_USUARIO = :user_id", {"user_id": id_estudiante})
        if not est_row:
            return jsonify({"success": False, "error": "El usuario no está registrado como estudiante"}), 404
        real_est_id = est_row["id_estudiante"]
        
        # Si se solicita la sesión 1 (de prueba/simulación) y no existe en SESION_CLASE, la creamos dinámicamente
        if id_sesion == 1:
            session_exists = execute_one("SELECT ID_SESION FROM SESION_CLASE WHERE ID_SESION = 1")
            if not session_exists:
                horario_row = execute_one("SELECT ID_HORARIO FROM HORARIO WHERE ROWNUM = 1")
                if horario_row:
                    hid = horario_row["id_horario"]
                    try:
                        execute_query(
                            "INSERT INTO SESION_CLASE (ID_SESION, ID_HORARIO, ESTADO_SESION) VALUES (1, :hid, 'ACTIVA')",
                            {"hid": hid}, fetch=False, commit=True
                        )
                        print("[SISCA] Sesión de simulación 1 creada con éxito.")
                    except Exception as e:
                        print(f"[SISCA] Error creando sesión de simulación 1: {e}")
                        
        # Verificar si ya existe en ASISTENCIA
        existe = execute_one(
            "SELECT ID_ASISTENCIA FROM ASISTENCIA WHERE ID_SESION = :id_sesion AND ID_ESTUDIANTE = :id_estudiante",
            {"id_sesion": id_sesion, "id_estudiante": real_est_id}
        )
        if existe:
            return jsonify({"success": False, "error": "Ya registraste asistencia a esta sesión"}), 400
            
        sql = """
            INSERT INTO ASISTENCIA (ID_SESION, ID_ESTUDIANTE, FECHA, HORA_REGISTRO, ESTADO, TIPO_REGISTRO)
            VALUES (:id_sesion, :id_estudiante, SYSDATE, SYSTIMESTAMP, 'PRESENTE', 'QR')
        """
        
        from app.database.connection import get_db
        conn = get_db()
        if conn is None:
            return jsonify({"success": False, "error": "No hay conexión a la base de datos"}), 500
            
        with conn.cursor() as cur:
            cur.execute(sql, {"id_sesion": id_sesion, "id_estudiante": real_est_id})
            conn.commit()
            
        return jsonify({"success": True, "message": "Asistencia registrada correctamente"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
