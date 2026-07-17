"""
SISCA — Modelo Usuario (M1)
Herencia: USUARIO → ADMINISTRADOR / DOCENTE / ESTUDIANTE
"""
import bcrypt
from app.database.connection import execute_query, execute_one

class Usuario:
    def __init__(self, data: dict):
        self.id_usuario      = data.get('id_usuario')
        self.estado          = data.get('estado', 'A')
        self.nombre          = data.get('nombre', '')
        self.apellido        = data.get('apellido', '')
        self.correo          = data.get('correo', '')
        self.contrasena      = data.get('contrasena', '')
        self.rol             = data.get('rol', '')
        self.documento       = data.get('documento', '')
        self.acepta_terminos = data.get('acepta_terminos', 'N')
        self.fecha_registro  = data.get('fecha_registro')

    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}"

    @property
    def is_active(self):
        return self.estado == 'A'

    @property
    def is_admin(self):
        return self.rol == 'ADMINISTRADOR'

    @property
    def is_docente(self):
        return self.rol == 'DOCENTE'

    @property
    def is_estudiante(self):
        return self.rol == 'ESTUDIANTE'

    # ── CRUD ────────────────────────────────────────────────
    @staticmethod
    def get_by_id(id_usuario: int):
        row = execute_one(
            "SELECT * FROM USUARIO WHERE ID_USUARIO = :id",
            {'id': id_usuario}
        )
        return Usuario(row) if row else None

    @staticmethod
    def get_by_correo(correo: str):
        row = execute_one(
            "SELECT * FROM USUARIO WHERE CORREO = :correo",
            {'correo': correo.lower().strip()}
        )
        return Usuario(row) if row else None

    @staticmethod
    def get_by_documento(documento: str):
        row = execute_one(
            "SELECT * FROM USUARIO WHERE DOCUMENTO = :doc",
            {'doc': documento.strip()}
        )
        return Usuario(row) if row else None

    @staticmethod
    def get_all():
        rows = execute_query("SELECT * FROM USUARIO ORDER BY NOMBRE")
        return [Usuario(r) for r in rows]

    @staticmethod
    def get_by_rol(rol: str):
        rows = execute_query(
            "SELECT * FROM USUARIO WHERE ROL = :rol AND ESTADO = 'A' ORDER BY NOMBRE",
            {'rol': rol}
        )
        return [Usuario(r) for r in rows]

    def save(self):
        """Inserta o actualiza el usuario en Oracle."""
        if self.id_usuario:
            execute_query(
                """UPDATE USUARIO SET ESTADO=:estado, NOMBRE=:nombre,
                   APELLIDO=:apellido, DOCUMENTO=:doc, ROL=:rol
                   WHERE ID_USUARIO=:id""",
                {'estado': self.estado, 'nombre': self.nombre,
                 'apellido': self.apellido, 'doc': self.documento, 'rol': self.rol, 'id': self.id_usuario},
                fetch=False, commit=True
            )
        else:
            execute_query(
                """INSERT INTO USUARIO (ESTADO,NOMBRE,APELLIDO,DOCUMENTO,CORREO,CONTRASENA,ROL,ACEPTA_TERMINOS)
                   VALUES (:estado,:nombre,:apellido,:doc,:correo,:contrasena,:rol,:acepta)""",
                {'estado': self.estado, 'nombre': self.nombre, 'apellido': self.apellido,
                 'doc': self.documento, 'correo': self.correo.lower().strip(), 'contrasena': self.contrasena,
                 'rol': self.rol, 'acepta': self.acepta_terminos},
                fetch=False, commit=True
            )

    def delete(self):
        execute_query(
            "UPDATE USUARIO SET ESTADO='I' WHERE ID_USUARIO=:id",
            {'id': self.id_usuario},
            fetch=False, commit=True
        )

    # ── Contraseña ──────────────────────────────────────────
    @staticmethod
    def hash_password(plain: str) -> str:
        return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()

    def check_password(self, plain: str) -> bool:
        try:
            return bcrypt.checkpw(plain.encode(), self.contrasena.encode())
        except Exception:
            return False

    def get_id(self) -> str:
        """Compatibilidad futura con Flask-Login."""
        return str(self.id_usuario)


class Docente(Usuario):
    def __init__(self, data: dict):
        super().__init__(data)
        self.id_docente  = data.get('id_docente')
        self.especialidad = data.get('especialidad', '')
        self.telefono    = data.get('telefono', '')

    def save_perfil(self):
        if self.id_docente:
            execute_query(
                "UPDATE DOCENTE SET ESPECIALIDAD=:esp, TELEFONO=:tel WHERE ID_DOCENTE=:id",
                {'esp': self.especialidad, 'tel': self.telefono, 'id': self.id_docente},
                fetch=False, commit=True
            )
        else:
            execute_query(
                "INSERT INTO DOCENTE (ID_USUARIO, ESPECIALIDAD, TELEFONO) VALUES (:user_id,:esp,:tel)",
                {'user_id': self.id_usuario, 'esp': self.especialidad, 'tel': self.telefono},
                fetch=False, commit=True
            )


class Estudiante(Usuario):
    def __init__(self, data: dict):
        super().__init__(data)
        self.id_estudiante     = data.get('id_estudiante')
        self.semestre          = data.get('semestre')
        self.codigo_estudiante = data.get('codigo_estudiante')

    def get_porcentaje_asistencia(self, id_materia: int) -> float:
        row = execute_one(
            """SELECT ROUND(
                SUM(CASE WHEN a.ESTADO='PRESENTE' THEN 1 ELSE 0 END) * 100.0
                / NULLIF(COUNT(a.ID_ASISTENCIA), 0), 2
               ) AS pct
               FROM ASISTENCIA a
               JOIN SESION_CLASE sc ON a.ID_SESION = sc.ID_SESION
               JOIN HORARIO h ON sc.ID_HORARIO = h.ID_HORARIO
               WHERE a.ID_ESTUDIANTE = :est AND h.ID_MATERIA = :mat""",
            {'est': self.id_estudiante, 'mat': id_materia}
        )
        return row.get('pct', 0.0) if row else 0.0
