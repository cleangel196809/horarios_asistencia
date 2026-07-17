# SISCA Mobile · iOS & Android

App móvil **idéntica** a la web SISCA, construida con **Capacitor**: una sola base de código que genera apps nativas para **iOS** y **Android**. Consume tu backend Flask vía la API `/api/...` (login, dashboard, asistencia).

## ✨ Características

- 🎨 **Misma identidad visual** que la web (glassmorphism + 3D cinematográfico, mobile-first)
- 📷 **Cámara nativa** con escáner QR optimizado (Google ML Kit)
- 🔔 **Push notifications** (FCM en Android, APNs en iOS)
- 🌐 Conexión a tu servidor Flask vía API REST (`/api/login`, `/api/dashboard`, `/api/asistencia`)
- 💾 Almacenamiento local cifrado (Capacitor Preferences)
- 📳 Vibración háptica
- 🌒 Modo oscuro nativo, splash screen, status bar configurada
- 🔋 Optimizado para batería (canvas WebGL ligero, animaciones respetan `prefers-reduced-motion`)

## 📋 Requisitos

| Sistema | Para Android | Para iOS |
| --- | --- | --- |
| **Tu PC** | Windows / macOS / Linux | macOS obligatorio |
| **IDE** | Android Studio (Hedgehog 2023.1+) | Xcode 15+ |
| **Runtime** | Node.js 18+, JDK 17+ | Node.js 18+, CocoaPods |
| **SDK** | Android SDK 33+ | iOS SDK 16+ |

## 🚀 Setup (una sola vez)

```bash
cd SISCA-Mobile
npm install
```

### Añadir plataformas

**Android** (puedes hacerlo en Windows):
```bash
npx cap add android
```

**iOS** (solo desde macOS):
```bash
npx cap add ios
cd ios/App && pod install && cd ../..
```

### Generar iconos y splash screens

```bash
npx capacitor-assets generate
```

Esto toma `resources/icon.svg` y `resources/splash.svg` y genera **todos** los tamaños necesarios para ambas plataformas automáticamente.

## ⚙️ Configurar el servidor SISCA

La app pregunta la URL de tu servidor Flask la primera vez que se abre. Para desarrollo:

- En **emulador Android**: usa `http://10.0.2.2:5000` (apunta al `localhost` de tu PC)
- En **dispositivo Android físico**: usa la IP de tu PC en la red local, ej. `http://192.168.1.100:5000`
- En **simulador iOS**: usa `http://localhost:5000`
- En **dispositivo iOS físico**: IP local de tu PC

> 🔐 Para producción usa **HTTPS**. Si tu servidor es solo HTTP, el campo `cleartext: true` en `capacitor.config.json` lo permite (no recomendado para stores).

## 🛠️ Desarrollo y build

### Sincronizar cambios web → nativo

Cada vez que modifiques `www/`:
```bash
npx cap sync
```

### Android

Abrir el proyecto en Android Studio:
```bash
npx cap open android
```
Luego en Android Studio: **Run ▶** sobre un emulador o dispositivo USB con depuración activada.

Para generar el **APK** firmado:
1. *Build* → *Generate Signed Bundle / APK*
2. Sigue el asistente. El archivo final estará en `android/app/build/outputs/`.

### iOS

```bash
npx cap open ios
```
En Xcode: selecciona tu *signing team*, conecta tu iPhone o usa un simulador, y pulsa **▶ Run**.

Para subir a **TestFlight / App Store**:
1. *Product* → *Archive*
2. *Window* → *Organizer* → *Distribute App*

## 🔔 Push notifications

### Android — Firebase Cloud Messaging (FCM)

1. Crea un proyecto en [Firebase Console](https://console.firebase.google.com)
2. Añade una app Android con package `co.edu.politecnico.sisca`
3. Descarga `google-services.json` y colócalo en `android/app/`
4. Sincroniza Gradle

### iOS — Apple Push Notifications (APNs)

1. Habilita **Push Notifications** en tu Apple Developer Account
2. En Xcode: *Signing & Capabilities* → *+ Capability* → *Push Notifications*
3. Sube tu **APNs Auth Key** a Firebase si lo usas como gateway

## 📷 Permisos de cámara (ya configurados)

El plugin de escaneo añade automáticamente:
- **Android**: `<uses-permission android:name="android.permission.CAMERA"/>`
- **iOS**: clave `NSCameraUsageDescription` en `Info.plist`

Si necesitas personalizar el mensaje en iOS, edita `ios/App/App/Info.plist`:
```xml
<key>NSCameraUsageDescription</key>
<string>SISCA usa la cámara para escanear códigos QR de asistencia.</string>
```

## 🔌 Endpoints que consume la app

Tu Flask ya los tiene en `app/controllers/api_mobile.py`:

| Método | Ruta | Uso |
|--------|------|-----|
| POST | `/api/login` | Login con correo, contraseña, rol |
| GET | `/api/dashboard?rol=&id=` | Estadísticas del dashboard |
| POST | `/api/asistencia` | Registrar asistencia escaneada |

**Recomendado añadir** (para push notifications):
```python
@api_bp.route("/push/register", methods=["POST"])
def api_push_register():
    data = request.get_json()
    token = data.get("token")
    # Guardar token asociado al usuario actual
    return jsonify({"success": True})
```

## 🗂️ Estructura del proyecto

```
SISCA-Mobile/
├── www/                    Frontend móvil (HTML/CSS/JS)
│   ├── index.html          Splash + welcome con role picker
│   ├── login.html          Login táctil con biometría
│   ├── dashboard.html      Dashboard por rol con KPIs
│   ├── scanner.html        QR scanner nativo
│   ├── settings.html       Configuración de servidor + push
│   ├── offline.html        Pantalla sin conexión
│   ├── css/mobile.css      Estilos cinematográficos mobile-first
│   ├── js/
│   │   ├── api.js          Cliente HTTP
│   │   ├── auth.js         Helpers de sesión
│   │   ├── storage.js      Preferences (Capacitor + fallback)
│   │   ├── bg3d.js         Fondo Three.js
│   │   ├── app.js          Toasts + haptics + status bar
│   │   ├── scanner.js      QR con ML Kit
│   │   └── push.js         Push notifications
│   └── assets/             Logo y recursos web
├── resources/              icon.svg + splash.svg para generación
├── android/                Generado por `npx cap add android`
├── ios/                    Generado por `npx cap add ios`
├── capacitor.config.json   Config principal de Capacitor
└── package.json
```

## 🐛 Troubleshooting

**"Servidor no configurado"**: Ve a *Ajustes* → URL del servidor.

**"Sin conexión al servidor"**: Asegúrate de que tu Flask corre en `0.0.0.0:5000` (no `127.0.0.1`) para que el dispositivo pueda alcanzarlo en la LAN.

**Cámara no abre**: En Android, ve a *Ajustes del sistema* → *Apps* → *SISCA* → *Permisos* → activa Cámara.

**Build Android falla**: Verifica JDK 17 (`java -version`). En Android Studio: *File* → *Project Structure* → *Gradle Settings* → *Gradle JDK*.

**Build iOS falla**: `cd ios/App && pod install`. Reinstala CocoaPods si es la primera vez: `sudo gem install cocoapods`.

## 📦 Distribución

- **Android**: Sube el AAB firmado a [Play Console](https://play.google.com/console).
- **iOS**: Archive en Xcode → *Distribute App* → *App Store Connect*.

## 📜 Licencia

MIT · Politécnico Internacional · 2026
