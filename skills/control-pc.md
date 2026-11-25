# Skill: Control Remoto de PC (`control-pc`)

## Cuándo usar esta skill
Activar cuando el usuario (desde esta PC o desde el celular vía `agy remote-control`) pida:
- Consultar el estado actual de la PC (CPU, RAM, discos, apps multimedia y descargas activas).
- Pausar o reanudar música/videos en reproducción.
- Suspender la PC, programar un apagado en X minutos o cancelar un apagado programado.

## Script asociado
- Ruta: `C:\Antigravity-Hub\scripts\system\control_pc.py`
- Log (ISO-8601): `C:\Antigravity-Hub\logs\control_pc.log`
- Notificaciones opcionales: `C:\Antigravity-Hub\scripts\common\notify_telegram.py` (con `--notify`).

## Comandos disponibles
1. **Ver estado del sistema y descargas activas:**
   ```powershell
   python C:\Antigravity-Hub\scripts\system\control_pc.py estado
   ```
   *(Acepta `--json` y `--notify`).*
2. **Pausar / reanudar reproducción multimedia:**
   ```powershell
   python C:\Antigravity-Hub\scripts\system\control_pc.py pausar-media
   ```
3. **Suspender la PC:**
   ```powershell
   python C:\Antigravity-Hub\scripts\system\control_pc.py suspender --dry-run
   python C:\Antigravity-Hub\scripts\system\control_pc.py suspender
   ```
4. **Programar apagado en N minutos:**
   ```powershell
   python C:\Antigravity-Hub\scripts\system\control_pc.py apagar-en 30 --dry-run
   python C:\Antigravity-Hub\scripts\system\control_pc.py apagar-en 30
   ```
5. **Cancelar apagado programado:**
   ```powershell
   python C:\Antigravity-Hub\scripts\system\control_pc.py cancelar-apagado
   ```

## Control desde el celular (`agy remote-control`)
- Estado del demonio: `agy remote-control status`
- Iniciar: `agy remote-control start --name Antigravity-Hub-PC`
- Detener: `agy remote-control stop`
- Acceso móvil: abrir `https://antigravity.google` con tu cuenta de Google y elegir la instancia `Antigravity-Hub-PC`.

## Reglas de seguridad
- Antes de ejecutar `suspender` o `apagar-en`, confirmar si el usuario quiere aplicarlo en serio (o probar primero con `--dry-run`).
- Nunca imprimir ni loguear `.env`.
- Todas las acciones quedan registradas en `logs/control_pc.log`.
