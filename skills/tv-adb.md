# Skill: Gestor de Android TV por ADB (`tv-adb`)

## Cuándo usar esta skill
Activar cuando el usuario pida:
- Ver estado, almacenamiento o apps instaladas en su Android TV.
- Hacer respaldo de la lista de aplicaciones (`state/tv-apps.txt`).
- Instalar un `.apk` local en la TV por red local (ADB).
- Limpiar caché de aplicaciones para liberar espacio en la TV.
- Deshabilitar bloatware de forma segura y reversible (`pm disable-user`).

## Script asociado
- Ruta: `C:\Antigravity-Hub\scripts\media\tv_adb.py`
- Binario ADB detectado: `C:\Users\alejandro\platform-tools\adb.exe`
- Respaldo de paquetes: `C:\Antigravity-Hub\state\tv-apps.txt`
- Log (ISO-8601): `C:\Antigravity-Hub\logs\tv_adb.log`
- IP configurada: variable `TV_IP` en `.env` (actualmente `192.168.1.65`, puerto `5555`).

## Comandos principales
1. **Estado general de la TV (solo lectura):**
   ```powershell
   python C:\Antigravity-Hub\scripts\media\tv_adb.py status
   ```
2. **Backup de lista de apps (solo lectura -> `state/tv-apps.txt`):**
   ```powershell
   python C:\Antigravity-Hub\scripts\media\tv_adb.py backup-list
   ```
3. **Instalar un APK (probar primero con `--dry-run`):**
   ```powershell
   python C:\Antigravity-Hub\scripts\media\tv_adb.py install "C:\ruta\app.apk" --dry-run
   python C:\Antigravity-Hub\scripts\media\tv_adb.py install "C:\ruta\app.apk"
   ```
4. **Limpiar caché sin borrar datos de usuario:**
   ```powershell
   python C:\Antigravity-Hub\scripts\media\tv_adb.py clean-cache --dry-run
   python C:\Antigravity-Hub\scripts\media\tv_adb.py clean-cache
   ```
5. **Debloat seguro (dry-run obligatorio por defecto; solo `pm disable-user`):**
   ```powershell
   python C:\Antigravity-Hub\scripts\media\tv_adb.py debloat --dry-run
   python C:\Antigravity-Hub\scripts\media\tv_adb.py debloat --apply
   ```
   *(Para revertir cualquier paquete: `tv_adb.py debloat --re-enable <paquete> --apply`).*

## Reglas de seguridad (AGENTS.md)
- **Nunca desinstalar paquetes definitivamente** (`pm uninstall`): usar únicamente `pm disable-user --user 0` y respetar la lista blanca de paquetes críticos del sistema.
- Probar siempre con `--dry-run` antes de aplicar cambios en paquetes o instalar APKs.
- Si la TV devuelve `unauthorized`, pedir al usuario que acepte el cartel de depuración ADB en la pantalla del televisor.
- Nunca imprimir ni loguear `.env`.
