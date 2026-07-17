# Despliegue en Oracle Cloud "Always Free"

Guía para correr SISCA + SIIHAPI + Oracle XE en una VM gratuita de Oracle
Cloud, usando `docker-compose.yml` (validado localmente de punta a punta:
build de las 2 imágenes, arranque de los 3 contenedores, migraciones,
resolución DNS entre contenedores y respuesta HTTP real de ambas apps).

## 1) Crear la VM (consola de Oracle Cloud)

1. Entrá a [cloud.oracle.com](https://cloud.oracle.com) y creá una cuenta
   "Always Free" si no tenés una.
2. **Compute → Instances → Create Instance**.
3. **Shape**: elegí `VM.Standard.E2.1.Micro` (AMD64, Always Free). Evitá el
   shape ARM (Ampere A1) para este proyecto — `ortools` no siempre trae
   wheel prebuilt para `aarch64`, y terminarías compilándolo desde cero
   (lento y frágil).
4. **Image**: Ubuntu 24.04 (o la LTS más reciente disponible).
5. Generá o subí un par de llaves SSH — las vas a necesitar para conectarte.
6. **Networking**: dejá la VCN/subnet por defecto que crea el wizard.
7. Creá la instancia y anotá la **IP pública**.

## 2) Abrir los puertos necesarios

En **Networking → Virtual Cloud Networks → (tu VCN) → Security Lists →
Default Security List**, agregá "Ingress Rules" para:

| Puerto | Origen | Para |
|---|---|---|
| 22 | tu IP (o 0.0.0.0/0 si no tenés IP fija) | SSH |
| 8080 | 0.0.0.0/0 | SISCA |
| 8000 | 0.0.0.0/0 | SIIHAPI |

(El puerto 1521 de Oracle **no** debería exponerse a internet — dejalo
solo accesible dentro de la VM, que es lo que hace `docker-compose.yml`
por defecto ya que Oracle no tiene `ports:` mapeado hacia afuera... en
realidad sí lo tiene para que puedas conectarte con un cliente SQL para
debug. Si no lo necesitás, quitá el bloque `ports:` del servicio `oracle`
en `docker-compose.yml` antes de desplegar.)

Ubuntu además trae su propio firewall (`ufw`) — si está activo, abrí los
mismos puertos ahí también:
```bash
sudo ufw allow 22,8080,8000/tcp
```

## 3) Conectarte e instalar Docker

```bash
ssh -i tu_llave.pem ubuntu@<IP_PUBLICA>

# Docker Engine + Compose plugin (script oficial)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker   # o cerrá y volvé a abrir la sesión SSH
```

## 4) Clonar el repo y configurar los `.env`

```bash
git clone https://github.com/cleangel196809/horarios_asistencia.git
cd horarios_asistencia

cp .env.example .env
cp SISCA/.env.example SISCA/.env
cp SIIHAPI/backend/.env.example SIIHAPI/backend/.env
```

Editá los 3 `.env` con valores reales:

- **`.env`** (raíz): `ORACLE_SYSTEM_PASSWORD` — cualquier contraseña
  Oracle-válida (mayúsculas, minúsculas, número).
- **`SISCA/.env`**: mismo `ORACLE_SYSTEM_PASSWORD` que el de arriba,
  `ORACLE_PASSWORD` para el usuario `sisca_admin` (elegís vos),
  `FLASK_SECRET_KEY` — generala con
  `python3 -c "import secrets; print(secrets.token_hex(32))"`,
  y `FLASK_ENV=production` (importante: sin esto la app corre en modo
  debug). `ORACLE_HOST` y `ORACLE_PORT` los pisa `docker-compose.yml`
  automáticamente, no hace falta tocarlos.
- **`SIIHAPI/backend/.env`**: `ORACLE_PASSWORD` (contraseña del usuario
  `SIIHAPI`, la misma que uses en el paso 5), `DJANGO_SECRET_KEY` y
  `JWT_SECRET_KEY` — generalas igual que arriba (≥32 bytes; si son más
  cortas o dejás el placeholder, **la app se niega a arrancar** con
  `DJANGO_DEBUG=False`, es intencional), `SISCA_API_TOKEN` (debe
  coincidir exactamente con el de `SISCA/.env`), `DJANGO_DEBUG=False`,
  `DJANGO_ALLOWED_HOSTS=<IP_PUBLICA>,localhost`.

## 5) Levantar Oracle y crear los esquemas

```bash
# Solo Oracle primero — tarda 2-5 min en el primer arranque
docker compose up -d oracle

# Esperar a que esté sano
docker compose ps   # oracle debe decir "healthy"

# Esquema SISCA (usa las credenciales de SISCA/.env)
docker compose run --rm sisca python setup_oracle.py

# Esquema SIIHAPI (pedirá la contraseña que definiste para SIIHAPI arriba)
docker compose exec -T oracle sqlplus system/<ORACLE_SYSTEM_PASSWORD>@//localhost:1521/XEPDB1 \
  < SIIHAPI/scripts/01_crear_esquema_oracle.sql
```

Si la contraseña de SIIHAPI que puso el script SQL (`siihapi_2026` por
defecto) no coincide con lo que pusiste en `SIIHAPI/backend/.env`, editá
`ORACLE_PASSWORD` en `01_crear_esquema_oracle.sql` antes de correrlo, o
simplemente usá `siihapi_2026` en el `.env` — es una password de esquema
interno, no de usuario final.

## 6) Levantar todo

```bash
docker compose up -d
docker compose logs -f sisca siihapi   # Ctrl+C para dejar de seguir logs
```

Verificá:
```bash
curl -I http://localhost:8080/
curl -I http://localhost:8000/
```

Desde tu navegador: `http://<IP_PUBLICA>:8080` y `http://<IP_PUBLICA>:8000`.

## 7) Cargar datos demo (opcional)

```bash
docker compose exec -T sisca python seed_data.py
docker compose exec siihapi python seed_siihapi.py
```

## Notas

- **Reinicio de la VM**: los 3 servicios tienen `restart: unless-stopped`,
  así que vuelven a levantar solos si la VM se reinicia.
- **Actualizar código**: `git pull && docker compose up -d --build` —
  reconstruye solo lo que cambió.
- **Ver logs**: `docker compose logs -f <servicio>`.
- **Backup de la base**: los datos de Oracle viven en el volumen Docker
  `oracle_data` — `docker compose down` (sin `-v`) los conserva;
  `docker compose down -v` los borra.
