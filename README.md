# QuickDrop LAN

Herramienta personal ultrarrápida y liviana para enviar y recibir links, texto, imágenes, GIFs, audios y archivos de hasta **2 GB** entre **Android** y **Windows** por red local (Wi-Fi / LAN), sin servidores externos ni límites de velocidad.

## Estructura del proyecto

- `/pc-server` — Servidor Windows en Python 3.11+ (`FastAPI` + `uvicorn` en streaming por chunks de 1 MB, `zeroconf` mDNS, bandeja del sistema con `pystray` + `Pillow`, notificaciones nativas `winotify`, portapapeles `pyperclip` e interfaz web minimalista en `http://localhost:8765`).
- `/android-app` — App Android en Kotlin + Jetpack Compose (Material 3 oscuro, `OkHttp` con `RequestBody` en streaming de 64 KB, `NsdManager` para detección automática + fallback de IP manual, notificaciones locales por SSE y Share Sheet `ACTION_SEND` / `ACTION_SEND_MULTIPLE`).

---

## 1. Servidor PC (Windows 11)

### Arranque rápido
1. Abre la carpeta `pc-server` y haz doble clic en `setup_and_run.bat`.
   - Crea automáticamente `.venv`, instala las dependencias y levanta el servicio sin ventana de consola (`pythonw.exe`).
2. Aparecerá el ícono de **QuickDrop LAN** en la bandeja del sistema:
   - **Doble clic**: abre la interfaz web en `http://localhost:8765` (con drag-and-drop para enviar al teléfono).
   - **Clic derecho**: copiar URL LAN, abrir `~/Downloads/QuickDrop`, activar/desactivar auto-copiado al portapapeles o notificaciones, y salir.

> **Firewall de Windows (red privada):** la primera vez que inicies el servicio, Windows puede pedir permiso para Python en redes privadas. Acéptalo para permitir conexiones en el puerto TCP `8765` (y UDP `5353` para mDNS) dentro de tu Wi-Fi local.

### Empaquetar en `.exe` único (opcional)
Ejecuta `pc-server\build_exe.bat` para generar `pc-server\dist\QuickDropLAN.exe` (sin consola, con PyInstaller).

### Dejar iniciando automáticamente con Windows
**Opción A (sin modificar el Registro, recomendada):**
1. Presiona `Win + R`, escribe `shell:startup` y pulsa **Enter**.
2. Crea un acceso directo dentro de esa carpeta apuntando a una de estas dos rutas:
   - Usando el entorno virtual (sin consola):
     - **Destino:** `C:\Antigravity-Hub\pc-server\.venv\Scripts\pythonw.exe "C:\Antigravity-Hub\pc-server\tray_app.py"`
     - **Iniciar en:** `C:\Antigravity-Hub\pc-server`
   - O si generaste el ejecutable único:
     - **Destino:** `C:\Antigravity-Hub\pc-server\dist\QuickDropLAN.exe`

**Opción B (Programador de tareas):** crea una tarea básica al iniciar sesión del usuario que ejecute `pythonw.exe` con argumento `C:\Antigravity-Hub\pc-server\tray_app.py`.

### Prueba automatizada del servidor PC
```powershell
C:\Antigravity-Hub\pc-server\.venv\Scripts\python.exe C:\Antigravity-Hub\pc-server\tests\test_server.py
```

---

## 2. App Android (`/android-app`)

### Requisitos
- **Android Studio** (Koala / Ladybug o superior) con JDK 17 y Android SDK 34.
- Teléfono Android (Android 8.0 / API 26 o superior) conectado a la **misma red Wi-Fi** que la PC.

### Compilar e instalar el APK Debug
**Desde Android Studio:**
1. Abre Android Studio -> **File -> Open** y selecciona la carpeta `C:\Antigravity-Hub\android-app`.
2. Espera a que termine **Gradle Sync** (usa Gradle 8.7 y `compileSdk = 34`).
3. Para generar el APK: menú **Build -> Build Bundle(s) / APK(s) -> Build APK(s)**.
   - El APK se genera en: `android-app\app\build\outputs\apk\debug\app-debug.apk`.
4. Para instalar directamente en tu teléfono por USB (con Depuración USB activa): pulsa **Run (▶)** o ejecuta:
   ```powershell
   adb install -r android-app\app\build\outputs\apk\debug\app-debug.apk
   ```

**Desde terminal (tras sincronizar el proyecto en Android Studio o generar el wrapper con `gradle wrapper`):**
```powershell
cd C:\Antigravity-Hub\android-app
.\gradlew.bat assembleDebug
```

### Uso en Android
- **Detección automática:** al abrir QuickDrop LAN, detectará tu PC automáticamente vía mDNS (`_quickdrop._tcp.`). Si tu router aísla tráfico multicast, toca el ícono de engranaje (⚙) e ingresa la IP LAN que muestra el ícono de la bandeja en Windows (puerto `8765`).
- **Compartir en un toque:** desde YouTube, Chrome, Galería, WhatsApp o cualquier app, toca **Compartir -> Enviar a PC (QuickDrop)**.
- **Recibidos desde la PC:** lo que envíes desde `http://localhost:8765` llega al instante con notificación local y aparece en la pestaña **Recibidos** (los archivos descargados se guardan en `Descargas/QuickDrop`).
