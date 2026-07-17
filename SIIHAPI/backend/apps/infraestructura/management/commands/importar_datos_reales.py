# -*- coding: utf-8 -*-
"""
SIIHAPI · Importador de DATOS REALES del Politecnico Internacional.

Lee los CSV ubicados en  backend/datos_reales/  y los carga a la base de
datos (Oracle en produccion) de forma IDEMPOTENTE y NO destructiva:

  * Salones por sede ......  SALONES SEDES 2026(*.csv
  * Programas / Materias ..  Horarios clases en linea 2020-2(*.csv
  * Docentes (opcional) ...  derivados de los horarios (PROFESOR + CORREO PI)

Diseno seguro:
  - NUNCA borra registros existentes. Usa get_or_create / update_or_create.
  - No toca el esquema SISCA ni las conexiones Oracle ya configuradas.
  - Cada bloque va en su propia transaccion; si uno falla, los demas siguen.
  - Cruza la lista "ASIGNATURA EN SISTEMA" para marcar requiere_sala_sistemas.

Uso (en la maquina con Oracle conectado):

    python manage.py importar_datos_reales            # importa todo
    python manage.py importar_datos_reales --dry-run  # simula, no guarda
    python manage.py importar_datos_reales --solo salones
    python manage.py importar_datos_reales --solo academico
    python manage.py importar_datos_reales --no-docentes
    python manage.py importar_datos_reales --ruta /otra/carpeta
"""
import os
import re
import csv
import glob
import hashlib

from django.core.management.base import BaseCommand
from django.db import transaction


# ───────────────────────────── utilidades ──────────────────────────────
def _norm(txt):
    return re.sub(r"\s+", " ", (txt or "").strip())


def _solo_num(txt):
    """Extrae el primer entero de un texto ('25' -> 25, 'cap 30' -> 30)."""
    m = re.search(r"\d+", str(txt or ""))
    return int(m.group(0)) if m else None


def _codigo_estable(nombre, prefijo="", largo=20):
    """Codigo deterministico (mismo nombre -> mismo codigo) y unico-ish."""
    base = re.sub(r"[^A-Z0-9]+", "_", _norm(nombre).upper()).strip("_")
    cod = (prefijo + base) if prefijo else base
    if len(cod) <= largo:
        return cod
    h = hashlib.md5(_norm(nombre).upper().encode("utf-8")).hexdigest()[:4].upper()
    return (cod[: largo - 5] + "_" + h)[:largo]


# ─────────────────────── mapeo de sedes / tipos ────────────────────────
_SEDES = {
    "CALLE 80": ("CLL80", "Calle 80"),
    "NORTE":    ("NORTE", "Norte"),
    "SUR":      ("SUR",   "Sur"),
    "CALLE 73": ("CLL73", "Calle 73"),
}


def _sede_de_archivo(nombre_archivo):
    up = nombre_archivo.upper()
    for clave, (cod, nom) in _SEDES.items():
        if clave in up:
            return cod, nom
    return None


# Reglas de tipo de salon segun palabras clave en el NOMBRE (orden importa:
# las mas especificas primero).
_REGLAS_TIPO = [
    ("GOURMET",                         "GOURMET"),
    ("REPOSTER",                        "REPOSTERIA"),
    ("COCINA",                          "COCINA"),
    ("CATA",                            "CATA"),
    ("COCTEL",                          "CATA"),
    (" BAR",                            "MESA_BAR"),
    ("MESA Y BAR",                      "MESA_BAR"),
    ("SISTEMAS",                        "LAB_SIST"),
    ("SOFT",                            "LAB_SIST"),
    ("INF ",                            "LAB_SIST"),
    ("ENFERMER",                        "LAB_ENF"),
    ("YESOS",                           "YESOS"),
    ("MOTORES",                         "MOTORES"),
    ("CERAMICA",                        "CERAMICA"),
    ("COLADOS",                         "COLADOS"),
    ("ACRILIC",                         "ACRILICOS"),
    ("ORTODONCIA",                      "ORTODONCIA"),
    ("METALURG",                        "METALURGIA"),
    ("MODA",                            "LAB_MODA"),
    ("AMBIENTAL",                       "LAB_AMB"),
    ("DENTAL",                          "LAB_SALUD"),
    ("SALUD ORAL",                      "LAB_SALUD"),
    ("SALUD",                           "LAB_SALUD"),
    ("LABORATORIO",                     "LAB_SALUD"),
    ("GIMNASIO",                        "GIMNASIO"),
    ("BIBLIOTECA",                      "BIBLIOTECA"),
    ("AUDITORIO",                       "AUDITORIO"),
    ("OFICINA",                         "OFICINA"),
    ("BODEGA",                          "BODEGA"),
    ("FLOTANTE",                        "FLOTANTE"),
    ("SALON",                           "AULA"),
    ("AULA",                            "AULA"),
]


def _tipo_salon(nombre):
    up = " " + _norm(nombre).upper() + " "
    for clave, tipo in _REGLAS_TIPO:
        if clave in up:
            return tipo
    return "AULA"


# ─────────────────── deteccion de fila de encabezado ───────────────────
def _leer_filas(ruta):
    """Lee un CSV ';' probando varias codificaciones. Devuelve lista de filas."""
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            with open(ruta, "r", encoding=enc, newline="") as fh:
                return list(csv.reader(fh, delimiter=";"))
        except (UnicodeDecodeError, LookupError):
            continue
    with open(ruta, "r", encoding="utf-8", errors="replace", newline="") as fh:
        return list(csv.reader(fh, delimiter=";"))


def _idx_encabezado(filas, claves):
    """Devuelve el indice de la fila cuyo contenido contiene mas 'claves'."""
    mejor, mejor_pts = 0, -1
    for i, fila in enumerate(filas[:15]):
        celdas = " ".join(c.upper() for c in fila)
        pts = sum(1 for k in claves if k in celdas)
        if pts > mejor_pts:
            mejor, mejor_pts = i, pts
    return mejor


# ════════════════════════════ COMANDO ══════════════════════════════════
class Command(BaseCommand):
    help = "Importa los datos reales (salones, programas, materias, docentes) desde backend/datos_reales/."

    def add_arguments(self, parser):
        parser.add_argument("--ruta", default=None, help="Carpeta con los CSV (def: backend/datos_reales).")
        parser.add_argument("--dry-run", action="store_true", help="Simula sin guardar en BD.")
        parser.add_argument("--solo", choices=["salones", "academico", "docentes"], default=None)
        parser.add_argument("--no-docentes", action="store_true", help="No crear usuarios docentes.")

    # ------------------------------------------------------------------ #
    def handle(self, *args, **opts):
        base = opts["ruta"] or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))),
            "datos_reales")
        if not os.path.isdir(base):
            self.stderr.write(self.style.ERROR(f"No existe la carpeta: {base}"))
            return

        self.dry = opts["dry_run"]
        self.base = base
        solo = opts["solo"]
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n=== IMPORTACION DATOS REALES {'(DRY-RUN)' if self.dry else ''} ==="))
        self.stdout.write(f"Carpeta: {base}\n")

        # Cargar el set de asignaturas que requieren sala de sistemas (cross-ref)
        self.materias_sistema = self._cargar_set_sistema()

        if solo in (None, "salones"):
            self._importar_salones()
        if solo in (None, "academico"):
            self._importar_academico()
        if solo in (None, "docentes") and not opts["no_docentes"]:
            self._importar_docentes()

        self.stdout.write(self.style.SUCCESS("\n=== FIN ==="))

    # ---------------------- cross-ref sala sistemas -------------------- #
    def _cargar_set_sistema(self):
        ruta = os.path.join(self.base, "SALONES SEDES 2026(ASIGNATURA EN SISTEMA).csv")
        nombres = set()
        if os.path.exists(ruta):
            for fila in _leer_filas(ruta):
                if not fila:
                    continue
                val = _norm(fila[0]).upper()
                if val and "ASIGNATURA" not in val and "SISTEMA" not in val:
                    nombres.add(val)
        return nombres

    # ============================ SALONES ============================== #
    def _importar_salones(self):
        from apps.infraestructura.models import Sede, Salon
        self.stdout.write(self.style.MIGRATE_HEADING("\n--- SALONES POR SEDE ---"))
        patrones = glob.glob(os.path.join(self.base, "SALONES SEDES 2026(*.csv"))
        archivos = [p for p in patrones
                    if _sede_de_archivo(os.path.basename(p)) is not None]
        tot_sal, tot_sed = 0, 0

        for ruta in sorted(archivos):
            nom = os.path.basename(ruta)
            cod_sede, nom_sede = _sede_de_archivo(nom)
            filas = _leer_filas(ruta)
            h = _idx_encabezado(filas, ["NOMBRE DE SAL", "CAPACIDAD", "PLANTA"])
            registros = []
            planta_actual = ""
            for fila in filas[h + 1:]:
                if len(fila) < 3:
                    continue
                planta = _norm(fila[0])
                nombre = _norm(fila[1])
                cap = _solo_num(fila[2])
                ident = _norm(fila[3]) if len(fila) > 3 else ""
                obs = _norm(fila[4]) if len(fila) > 4 else ""
                if planta:
                    planta_actual = planta
                if not nombre or cap is None:
                    continue
                # el codigo del salon: identificador UXII si existe, si no el nombre
                codigo = ident or _codigo_estable(nombre, largo=40)
                registros.append(dict(
                    codigo=codigo[:40], nombre=nombre[:120], capacidad=cap,
                    tipo=_tipo_salon(nombre), planta=planta_actual[:20], observaciones=obs))

            self.stdout.write(f"  {nom_sede:10s}: {len(registros):3d} salones detectados ({nom})")
            if self.dry:
                tot_sal += len(registros)
                continue

            with transaction.atomic():
                sede, creada = Sede.objects.get_or_create(
                    codigo=cod_sede,
                    defaults=dict(nombre=nom_sede, direccion=f"Sede {nom_sede}"))
                if creada:
                    tot_sed += 1
                for r in registros:
                    Salon.objects.update_or_create(
                        sede=sede, codigo=r["codigo"],
                        defaults=dict(nombre=r["nombre"], capacidad=r["capacidad"],
                                      tipo=r["tipo"], planta=r["planta"],
                                      observaciones=r["observaciones"], activo=True))
                    tot_sal += 1

        self.stdout.write(self.style.SUCCESS(
            f"  -> {tot_sal} salones, {tot_sed} sedes nuevas."))

    # =================== PROGRAMAS / MATERIAS ========================== #
    _CLAVES_HOR = ["ID_ASSIGNATURA", "ID_ASIGNATURA", "NOMBRE ASIGNATURA",
                   "PROGRAMA", "CREDITOS", "PROFESOR", "DIA", "HORA"]

    def _importar_academico(self):
        from apps.academico.models import Facultad, Programa, Materia
        self.stdout.write(self.style.MIGRATE_HEADING("\n--- PROGRAMAS Y MATERIAS ---"))
        archivos = glob.glob(os.path.join(self.base, "Horarios clases en l*nea 2020-2(*.csv"))
        tot_mat, tot_prog, tot_fac = 0, 0, 0
        prog_cache, fac_cache = {}, {}

        for ruta in sorted(archivos):
            nom = os.path.basename(ruta)
            filas = _leer_filas(ruta)
            # Facultad: primera linea no vacia del preambulo
            fac_nombre = "General"
            for fila in filas[:5]:
                if fila and _norm(fila[0]):
                    fac_nombre = _norm(fila[0])
                    break
            h = _idx_encabezado(filas, self._CLAVES_HOR)
            cab = [c.upper().strip() for c in filas[h]]

            def col(*alias):
                for a in alias:
                    if a in cab:
                        return cab.index(a)
                return None

            i_ciclo = col("CICLO_ASIGNATURA", "CICLO")
            i_cod = col("ID_ASSIGNATURA", "ID_ASIGNATURA", "ID_MATERIA")
            i_nom = col("NOMBRE ASIGNATURA", "ASIGNATURA", "MATERIA")
            i_prog = col("PROGRAMA")
            i_cred = col("CREDITOS")

            cnt = 0
            es_ingles = "INGL" in fac_nombre.upper()
            for fila in filas[h + 1:]:
                if not fila or i_nom is None or len(fila) <= i_nom:
                    continue
                nombre = _norm(fila[i_nom])
                if not nombre:
                    continue
                cod = _norm(fila[i_cod]) if (i_cod is not None and len(fila) > i_cod) else ""
                prog_nom = _norm(fila[i_prog]) if (i_prog is not None and len(fila) > i_prog) else fac_nombre
                ciclo = _solo_num(fila[i_ciclo]) if (i_ciclo is not None and len(fila) > i_ciclo) else 1
                cred = _solo_num(fila[i_cred]) if (i_cred is not None and len(fila) > i_cred) else 2
                if not cod:
                    cod = _codigo_estable(nombre, largo=20)
                if self.dry:
                    cnt += 1
                    continue

                # Facultad
                if fac_nombre not in fac_cache:
                    fac, fcre = Facultad.objects.get_or_create(
                        codigo=_codigo_estable(fac_nombre, largo=10),
                        defaults=dict(nombre=fac_nombre[:100]))
                    fac_cache[fac_nombre] = fac
                    if fcre:
                        tot_fac += 1
                fac = fac_cache[fac_nombre]

                # Programa
                if prog_nom not in prog_cache:
                    prog, pcre = Programa.objects.get_or_create(
                        codigo=_codigo_estable(prog_nom, largo=20),
                        defaults=dict(facultad=fac, nombre=prog_nom[:200],
                                      tipo=("ING" if es_ingles else "TEC"),
                                      modalidad="VIRT"))
                    prog_cache[prog_nom] = prog
                    if pcre:
                        tot_prog += 1
                prog = prog_cache[prog_nom]

                # Materia
                req_sist = nombre.upper() in self.materias_sistema
                _, mcre = Materia.objects.update_or_create(
                    programa=prog, codigo=cod[:20],
                    defaults=dict(nombre=nombre[:200], ciclo=ciclo or 1,
                                  creditos=cred or 2,
                                  horas_semanales=int(round((cred or 2) * 1.5)),
                                  requiere_sala_sistemas=req_sist, activa=True))
                if mcre:
                    tot_mat += 1
                cnt += 1

            self.stdout.write(f"  {fac_nombre[:35]:35s}: {cnt:3d} materias ({nom})")

        self.stdout.write(self.style.SUCCESS(
            f"  -> {tot_mat} materias, {tot_prog} programas, {tot_fac} facultades nuevas."))

    # ============================ DOCENTES ============================= #
    def _importar_docentes(self):
        from apps.autenticacion.models import Usuario
        from apps.personal.models import Docente
        self.stdout.write(self.style.MIGRATE_HEADING("\n--- DOCENTES ---"))
        archivos = glob.glob(os.path.join(self.base, "Horarios clases en l*nea 2020-2(*.csv"))
        vistos = {}   # correo -> nombre

        for ruta in sorted(archivos):
            filas = _leer_filas(ruta)
            h = _idx_encabezado(filas, self._CLAVES_HOR)
            cab = [c.upper().strip() for c in filas[h]]
            i_prof = cab.index("PROFESOR") if "PROFESOR" in cab else None
            i_mail = None
            for a in ("CORREO PI", "CORREO", "CORREO_PI", "EMAIL"):
                if a in cab:
                    i_mail = cab.index(a); break
            if i_prof is None:
                continue
            for fila in filas[h + 1:]:
                if len(fila) <= i_prof:
                    continue
                prof = _norm(fila[i_prof])
                if not prof:
                    continue
                correo = ""
                if i_mail is not None and len(fila) > i_mail:
                    correo = _norm(fila[i_mail]).lower()
                if not correo:
                    # sintetizar correo institucional a partir del nombre
                    partes = re.sub(r"[^a-z ]", "", prof.lower()).split()
                    if partes:
                        correo = (partes[0] + "." + (partes[-1] if len(partes) > 1 else "doc")) + "@pi.edu.co"
                if correo and correo not in vistos:
                    vistos[correo] = prof

        self.stdout.write(f"  Docentes unicos detectados: {len(vistos)}")
        if self.dry:
            return

        nuevos = 0
        for correo, prof in vistos.items():
            toks = prof.split()
            nombre = toks[0] if toks else "Docente"
            apellido = " ".join(toks[1:]) if len(toks) > 1 else "PI"
            with transaction.atomic():
                u = Usuario.objects.filter(correo__iexact=correo).first()
                if not u:
                    u = Usuario(correo=correo, nombre=nombre[:80],
                                apellido=apellido[:80], rol="DOCENTE", estado="A")
                    try:
                        u.set_password("Docente_PI_2026!")
                    except Exception:
                        pass
                    u.save()
                elif u.rol == "ESTUDIANTE":
                    pass  # no degradar/alterar roles existentes
                doc, creado = Docente.objects.get_or_create(
                    usuario=u, defaults=dict(tipo_contrato="CATEDRA",
                                             carga_horaria_max=20, activo=True))
                if creado:
                    nuevos += 1
        self.stdout.write(self.style.SUCCESS(
            f"  -> {nuevos} docentes nuevos (usuarios rol DOCENTE)."))
