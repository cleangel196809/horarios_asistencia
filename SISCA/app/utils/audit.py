"""
SISCA — Auditoría del sistema (RF-19)
Registra todas las acciones en la tabla AUDITORIA de Oracle.
"""
from app.database.connection import execute_query


def registrar_auditoria(id_usuario, accion: str,
                         tabla: str = "", ip: str = "") -> None:
    """Inserta un log en AUDITORIA. Nunca propaga excepciones."""
    try:
        execute_query(
            """INSERT INTO AUDITORIA (ID_USUARIO, ACCION, TABLA_AFECTADA, IP)
               VALUES (:user_id, :accion, :tabla, :ip)""",
            {
                "user_id": id_usuario,
                "accion":  str(accion)[:150],
                "tabla":   str(tabla)[:50],
                "ip":      str(ip)[:50],
            },
            fetch=False,
            commit=True,
        )
    except Exception:
        pass  # La auditoría nunca debe interrumpir el flujo principal
