# Skill: Auditor de Red Local (`auditor-red`)

## Cuándo usar esta skill
Activar cuando el usuario pida:
- Ver qué equipos o dispositivos están conectados a su Wi-Fi / red local.
- Diagnosticar por qué internet anda lento o está caído (separar problema de router/Wi-Fi vs proveedor ISP vs DNS vs HTTPS).
- Detectar dispositivos nuevos o desconocidos en su red doméstica.

## Script asociado
- Ruta: `C:\Antigravity-Hub\scripts\system\auditor_red.py`
- Estado (equipos conocidos y deduplicación): `C:\Antigravity-Hub\state\auditor_red.json`
- Log (con fecha ISO-8601): `C:\Antigravity-Hub\logs\auditor_red.log`
- Notificaciones: `C:\Antigravity-Hub\scripts\common\notify_telegram.py` (modo silencioso).

## Comandos principales
1. **Auditoría completa (conectividad + equipos en la LAN):**
   ```powershell
   python C:\Antigravity-Hub\scripts\system\auditor_red.py
   ```
2. **Diagnóstico rápido de conectividad (sin barrido de dispositivos):**
   ```powershell
   python C:\Antigravity-Hub\scripts\system\auditor_red.py --no-scan
   ```
3. **Modo silencioso con alerta por Telegram ante fallas o equipos nuevos:**
   ```powershell
   python C:\Antigravity-Hub\scripts\system\auditor_red.py --notify
   ```
4. **Simulación segura (sin guardar estado ni enviar alertas):**
   ```powershell
   python C:\Antigravity-Hub\scripts\system\auditor_red.py --dry-run
   ```
5. **Salida estructurada para automatizaciones:**
   ```powershell
   python C:\Antigravity-Hub\scripts\system\auditor_red.py --json
   ```

## Interpretación del diagnóstico
- `OK`: router, salida a Internet por IP (`1.1.1.1`), DNS y HTTPS responden normalmente.
- `DEGRADED`: hay conectividad pero con latencia alta o pérdida de paquetes.
- `ERROR_ROUTER`: no responde la puerta de enlace predeterminada -> falla en el cable/Wi-Fi o router colgado.
- `ERROR_INTERNET`: el router responde, pero no hay salida a `1.1.1.1`/`8.8.8.8` -> problema del proveedor (ISP) o módem.
- `ERROR_DNS`: hay salida por IP, pero no resuelven dominios -> problema de servidores DNS.
- `ERROR_HTTPS`: router, IP y DNS responden, pero falla HTTPS -> posible portal cautivo, firewall o proxy/VPN.

## Reglas de seguridad
- Operación estrictamente de **solo lectura** (no modifica interfaces, DNS, firewall ni Registro de Windows).
- Nunca imprimir ni loguear el contenido de `.env`.
- En modo `--notify`, solo envía alerta por Telegram ante anomalías o MACs nuevas respecto a `state/auditor_red.json`.
