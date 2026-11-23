# VoxScribe · Transcriptor de YouTube, Video y Audio

Aplicación web local para transcribir videos de YouTube (o cualquier plataforma compatible) y archivos de audio o video con marcas de tiempo interactivas.

## Características principales

- **Doble motor de transcripción**:
  - **IA Local gratuita (`faster-whisper`)**: Aprovecha tu GPU NVIDIA (CUDA) automáticamente con respaldo transparente a CPU. Sin costos ni límites de duración.
  - **API en la nube (`Groq` / `OpenAI` / compatible)**: Conecta tu propia API Key desde la interfaz o en `.env`. Divide y comprime automáticamente audios mayores a 25 MB manteniendo las marcas de tiempo exactas.
- **Cualquier fuente**:
  - Enlaces de YouTube, Shorts, directos y cientos de sitios vía `yt-dlp`.
  - Arrastrar y soltar archivos locales (`MP3`, `WAV`, `M4A`, `OGG`, `FLAC`, `MP4`, `MKV`, `WEBM`, `MOV`, `AVI`, etc.).
- **Reproductor sincronizado en tiempo real**:
  - Los segmentos aparecen en vivo conforme se transcriben.
  - Haz clic en cualquier marca de tiempo `[MM:SS]` para escuchar desde ese segundo exacto.
- **Exportación en 1 clic**:
  - `TXT` (texto limpio continuo)
  - `TXT + Tiempo` (`[MM:SS - MM:SS]`)
  - `SRT` (subtítulos SubRip)
  - `VTT` (subtítulos WebVTT)
  - `JSON` (metadatos + segmentos detallados)

## Cómo iniciar

### Opción rápida (Windows)
Haz doble clic en **`iniciar.bat`** o ejecútalo desde terminal:
```powershell
.\iniciar.bat
```

### Opción manual por consola
```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Luego abre **http://localhost:8000** en tu navegador.
