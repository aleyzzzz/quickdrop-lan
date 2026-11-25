# Skill: Organizador de Biblioteca Multimedia (`organizar-media`)

## Cuándo usar esta skill
Activar cuando el usuario pida:
- Ordenar descargas completadas de series o películas dentro de `D:\descarga jdownloader` (usando `DOWNLOADS_DIR` y `MEDIA_LIB_DIR` en `.env`).
- Renombrar capítulos y películas a formato limpio compatible con Jellyfin (`Series/<Nombre>/Season XX/<Nombre> - SXXEXX.<ext>` y `Peliculas/<Nombre> (Año)/...`).
- Sincronizar la biblioteca con la nube mediante `rclone copy` incremental (si está configurado).

## Script asociado
- Ruta: `C:\Antigravity-Hub\scripts\media\organizar_media.py`
- Estado (deduplicación): `C:\Antigravity-Hub\state\organizar_media.json`
- Log (ISO-8601): `C:\Antigravity-Hub\logs\organizar_media.log`
- Variables en `.env`: `DOWNLOADS_DIR=D:\descarga jdownloader`, `MEDIA_LIB_DIR=D:\descarga jdownloader`, `RCLONE_REMOTE`.

## Comandos principales
1. **Simulación segura obligatoria antes de mover:**
   ```powershell
   python C:\Antigravity-Hub\scripts\media\organizar_media.py --dry-run
   ```
2. **Ejecución real (ordena completados en `D:\descarga jdownloader` y avisa por Telegram si hubo novedades):**
   ```powershell
   python C:\Antigravity-Hub\scripts\media\organizar_media.py
   ```
3. **Probar con carpetas personalizadas:**
   ```powershell
   python C:\Antigravity-Hub\scripts\media\organizar_media.py --source C:\Antigravity-Hub\staging\test_in --dest C:\Antigravity-Hub\staging\test_out --min-age-sec 0 --dry-run
   ```

## Reglas de seguridad (AGENTS.md)
- Ignora automáticamente descargas en curso (`.part`, `.!qB`, `.tmp`, `.crdownload`, `.downloading`, `.aria2` y archivos modificados hace menos de 60s).
- Nunca borra archivos de usuario ni sobrescribe archivos existentes en destino; omite archivos que ya están en su ruta final.
- Usa únicamente `rclone copy --update` (incremental, nunca borra en la nube) y respeta `--dry-run`.
- Modo silencioso: si no hay títulos nuevos, solo escribe en `logs/organizar_media.log` sin enviar Telegram.
- Nunca imprimir ni loguear `.env`.
