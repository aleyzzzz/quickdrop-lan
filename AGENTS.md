# AGENTS.md — Antigravity-Hub

## Entorno y preferencias técnicas
- Sistema operativo: Windows 11.
- Herramientas preferidas: PowerShell, Python 3 (priorizar librería estándar) y utilidades CLI livianas. Evitar runtimes pesados o apps Electron innecesarias.
- Directorio raíz: `C:\Antigravity-Hub`.

## Estructura obligatoria
- `skills/`: Skills reutilizables en Markdown.
- `scripts/common/`: utilidades compartidas (`notify_telegram.py`).
- `scripts/system/`: red local, discos y salud del sistema (Rama 5).
- `scripts/media/`: renombrado, organización multimedia y nube (Rama 1).
- `scripts/trackers/`: precios, vacantes y boletines diarios (Rama 2).
- `state/`: archivos JSON para evitar alertas duplicadas.
- `logs/`: un `.log` por módulo con fecha ISO-8601.
- `staging/`: zona temporal antes de eliminar o mover archivos definitivamente.

## Reglas de seguridad (estrictas)
1. Nunca imprimir ni loguear el contenido de `.env`.
2. Nunca borrar archivos de usuario definitivamente de forma automática; mover primero a `staging/` o pedir confirmación.
3. Todo script que mueva archivos, corra `rclone` o toque paquetes por ADB debe tener `--dry-run` y probarse primero simulando.
4. En Android TV (ADB), usar `pm disable-user` en vez de desinstalar definitivamente salvo confirmación expresa.
5. No tocar registro de Windows, firewall ni configuración de red sin respaldo y aprobación previa.

## Alertas y verificación
- Todas las alertas salen por `scripts/common/notify_telegram.py`.
- Modo silencioso: si todo está normal, solo registrar en `logs/`; avisar por Telegram únicamente ante anomalías, bajas de precio o novedades.
- Verificar sintaxis o correr prueba controlada antes de dar un módulo por terminado.
