"""
SIIHAPI - Reset de credenciales.

Borra los 4 usuarios principales si existen y los recrea con passwords correctas.
Despues verifica que la autenticacion funcione.
"""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / 'backend'
sys.path.insert(0, str(BASE))
os.chdir(BASE)


# Detectar Oracle automaticamente
def _oracle_ok():
    try:
        import oracledb
        oracledb.connect(user='SIIHAPI', password='siihapi_2026',
                          dsn='localhost:1521/XEPDB1').close()
        return True
    except Exception:
        return False


if _oracle_ok():
    os.environ['DJANGO_SETTINGS_MODULE'] = 'siihapi.settings'
    BD = 'Oracle XE 21c (SIIHAPI)'
else:
    os.environ['DJANGO_SETTINGS_MODULE'] = 'siihapi.settings_test'
    BD = 'SQLite local (Oracle no detectado)'

print(f"\n[BD] Trabajando en: {BD}\n")

import django
django.setup()

from django.contrib.auth import get_user_model, authenticate
from django.utils import timezone
from django.db import connection

User = get_user_model()


USUARIOS = [
    ('admin@pi.edu.co',      'Admin2026!',      'Francisco',  'Navarro',  'ADMINISTRADOR', True, True),
    ('coord@pi.edu.co',      'Coord2026!',      'Maria',      'Rodriguez', 'COORDINADOR',  True, False),
    ('docente@pi.edu.co',    'Docente2026!',    'Carlos',     'Gomez',    'DOCENTE',      False, False),
    ('estudiante@pi.edu.co', 'Estudiante2026!', 'Laura',      'Martinez', 'ESTUDIANTE',   False, False),
]


def banner(s):
    print()
    print("=" * 65)
    print(f"  {s}")
    print("=" * 65)


# ── 1. Diagnostico ──
banner("1. Estado actual")
try:
    with connection.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM user_tables WHERE table_name = 'SIIHAPI_USUARIO'")
        existe = cur.fetchone()[0]
    if not existe:
        print("[ERROR] La tabla SIIHAPI_USUARIO NO existe en esta BD.")
        print("        Ejecuta setup.bat para crear todo desde cero.")
        sys.exit(1)
except Exception as e:
    # SQLite no tiene user_tables. Asumimos que existe.
    pass

total = User.objects.count()
print(f"Usuarios actuales: {total}")
for u in User.objects.all()[:10]:
    print(f"   - {u.correo:30s} rol={u.rol}")


# ── 2. Borrar los 4 principales y recrear ──
banner("2. Reseteando los 4 usuarios principales")

for correo, password, nombre, apellido, rol, is_staff, is_super in USUARIOS:
    # Borrar si existe
    User.objects.filter(correo=correo).delete()

    user = User.objects.create(
        correo=correo,
        nombre=nombre, apellido=apellido,
        cedula=f'{abs(hash(correo)) % 10000000000}',
        rol=rol,
        is_staff=is_staff, is_superuser=is_super,
        estado='A',
        acepta_terminos=True,
        fecha_aceptacion_habeas_data=timezone.now(),
    )
    user.set_password(password)
    user.save()

    # Verificar hash
    partes = user.password.split('$')
    hash_len = len(partes[2]) if len(partes) >= 3 else 0
    print(f"   [OK] {correo:30s} -> {rol:14s} hash={partes[0]} ({hash_len}c)")


# ── 3. Verificar autenticacion ──
banner("3. Verificando que se puede hacer login")
todos_ok = True
for correo, password, *_ in USUARIOS:
    user = authenticate(correo=correo, password=password)
    if user:
        print(f"   [OK]  authenticate({correo}) -> exitoso")
    else:
        print(f"   [FAIL] authenticate({correo}) -> FALLO")
        todos_ok = False


# ── 4. Resumen ──
banner("CREDENCIALES LISTAS" if todos_ok else "HAY PROBLEMAS")
print()
print("  Login en: http://localhost:8000/login/")
print()
print("  +---------------+-------------------------+--------------------+")
print("  | Rol           | Correo                  | Password           |")
print("  +---------------+-------------------------+--------------------+")
for correo, password, *_, rol, _, _ in USUARIOS:
    print(f"  | {rol:13s} | {correo:23s} | {password:18s} |")
print("  +---------------+-------------------------+--------------------+")
print()
if todos_ok:
    print("  Todos los usuarios pueden hacer login correctamente.")
else:
    print("  ALGUNOS FALLARON. Pega este output y te ayudo a debuggear.")
