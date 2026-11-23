import os
import sys
import shutil
import subprocess
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
AUDIO_DIR = DATA_DIR / "audio"
JOBS_DIR = DATA_DIR / "jobs"
MODELS_DIR = BASE_DIR / "models_cache"
STATIC_DIR = BASE_DIR / "static"

for directory in (DATA_DIR, AUDIO_DIR, JOBS_DIR, MODELS_DIR, STATIC_DIR):
    directory.mkdir(parents=True, exist_ok=True)

_dll_handles = []


def setup_nvidia_dlls() -> list[str]:
    """Registra en Windows las DLLs de CUDA/cuDNN instaladas en el entorno virtual."""
    added = []
    if sys.platform != "win32":
        return added

    site_packages_candidates = [Path(p) for p in sys.path if "site-packages" in p]
    for sp in site_packages_candidates:
        nvidia_dir = sp / "nvidia"
        if not nvidia_dir.exists():
            continue
        for sub in nvidia_dir.iterdir():
            bin_dir = sub / "bin"
            if bin_dir.is_dir():
                bin_str = str(bin_dir.resolve())
                if bin_str not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = bin_str + os.pathsep + os.environ.get("PATH", "")
                if hasattr(os, "add_dll_directory"):
                    try:
                        _dll_handles.append(os.add_dll_directory(bin_str))
                        added.append(bin_str)
                    except OSError:
                        pass
    return added


def ensure_ffmpeg() -> str | None:
    """Garantiza que ffmpeg y ffprobe estén disponibles en el PATH."""
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
        return shutil.which("ffmpeg")
    except Exception:
        return None


# Inicializar DLLs de NVIDIA antes de importar ctranslate2 / faster_whisper
setup_nvidia_dlls()


def detect_gpu() -> dict:
    """Detecta disponibilidad de CUDA y nombre de la GPU si existe."""
    gpu_name = None
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if res.returncode == 0 and res.stdout.strip():
            gpu_name = res.stdout.strip().splitlines()[0].strip()
    except Exception:
        pass

    cuda_available = False
    cuda_device_count = 0
    try:
        import ctranslate2
        cuda_device_count = ctranslate2.get_cuda_device_count()
        cuda_available = cuda_device_count > 0
    except Exception:
        cuda_available = False

    return {
        "cuda_available": cuda_available,
        "cuda_device_count": cuda_device_count,
        "gpu_name": gpu_name,
        "recommended_device": "cuda" if cuda_available else "cpu",
        "recommended_model": "large-v3-turbo" if cuda_available else "small",
    }


def get_system_info() -> dict:
    gpu = detect_gpu()
    ffmpeg_bin = shutil.which("ffmpeg")
    return {
        **gpu,
        "ffmpeg_ready": ffmpeg_bin is not None,
        "has_env_openai_key": bool(os.getenv("OPENAI_API_KEY")),
        "has_env_groq_key": bool(os.getenv("GROQ_API_KEY")),
    }
