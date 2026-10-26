"""Speech-to-Text portabile: MLX su Mac, faster-whisper (CUDA o CPU) su Windows/Linux.
Il modello viene caricato al primo uso e scaricato dopo un periodo di inattività,
così quando nessuno detta non occupa né RAM né memoria della GPU."""
import gc
import os
import platform
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from config import CONFIG

# MLX non è thread-safe e anche su CPU conviene una trascrizione alla volta
_lock = threading.Lock()
_esecutore = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper")
_modello = None
_ultimo_uso = 0.0

MODELLI_MLX = {
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "medium": "mlx-community/whisper-medium-mlx",
    "small": "mlx-community/whisper-small-mlx",
}


def _dll_nvidia():
    """Windows: le DLL CUDA dei pacchetti nvidia-* (requirements.txt) non sono nel percorso di ricerca."""
    if platform.system() != "Windows":
        return
    import glob
    import sysconfig
    for cartella in glob.glob(os.path.join(sysconfig.get_paths()["purelib"], "nvidia", "*", "bin")):
        os.add_dll_directory(cartella)
        # ctranslate2 carica cuBLAS/cuDNN al primo uso con LoadLibrary, che guarda il PATH
        os.environ["PATH"] = cartella + os.pathsep + os.environ.get("PATH", "")


_dll_nvidia()


def _scegli_backend() -> str:
    scelta = CONFIG["whisper_backend"]
    if scelta != "auto":
        return scelta
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        try:
            import mlx_whisper  # noqa: F401
            return "mlx"
        except ImportError:
            pass
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


BACKEND = _scegli_backend()


def _glossario() -> str:
    """Parole suggerite a Whisper: da config.json, altrimenti da dati/vocabolario.txt."""
    if CONFIG["glossario"]:
        return CONFIG["glossario"]
    from catalogo import DATI_DIR, _righe_non_vuote
    return ", ".join(_righe_non_vuote(os.path.join(DATI_DIR, "vocabolario.txt")))


GLOSSARIO = _glossario()


def _carica():
    global _modello, _ultimo_uso
    _ultimo_uso = time.monotonic()
    if _modello is not None:
        return _modello
    nome = CONFIG["whisper_modello"]
    print(f"[🎙️] Carico Whisper {nome} ({BACKEND})...", flush=True)
    if BACKEND == "mlx":
        from mlx_whisper.transcribe import ModelHolder
        import mlx.core as mx
        _modello = ModelHolder.get_model(MODELLI_MLX.get(nome, nome), mx.float16)
    else:
        from faster_whisper import WhisperModel
        if BACKEND == "cuda":
            # int8_float16: circa metà della memoria video rispetto a float16
            _modello = WhisperModel(nome, device="cuda", compute_type="int8_float16")
        else:
            _modello = WhisperModel(nome, device="cpu", compute_type="int8",
                                    cpu_threads=CONFIG["thread_cpu"])
    print("[🎙️] Whisper pronto.", flush=True)
    return _modello


def _scarica():
    global _modello
    if _modello is None:
        return
    if BACKEND == "mlx":
        from mlx_whisper.transcribe import ModelHolder
        ModelHolder.model = None
        ModelHolder.model_path = None
    _modello = None
    gc.collect()
    print("[🎙️] Whisper scaricato dalla memoria (inattivo).", flush=True)


def trascrivi(percorso: str) -> str:
    # MLX lega il modello al thread che lo ha caricato: tutto il lavoro passa da un unico thread
    return _esecutore.submit(_trascrivi, percorso).result()


def _trascrivi(percorso: str) -> str:
    global _ultimo_uso
    with _lock:
        _carica()
        try:
            if BACKEND == "mlx":
                import mlx_whisper
                nome = CONFIG["whisper_modello"]
                testo = mlx_whisper.transcribe(
                    percorso, path_or_hf_repo=MODELLI_MLX.get(nome, nome),
                    language="it", initial_prompt=GLOSSARIO,
                )["text"]
            else:
                segmenti, _ = _modello.transcribe(
                    percorso, language="it", initial_prompt=GLOSSARIO,
                    vad_filter=True, beam_size=1,
                )
                testo = " ".join(s.text for s in segmenti)
        finally:
            _ultimo_uso = time.monotonic()
    return testo.strip()


def precarica():
    _esecutore.submit(_carica).result()


def _scarica_se_inattivo():
    with _lock:
        if _modello is not None and time.monotonic() - _ultimo_uso > CONFIG["whisper_minuti_inattivita"] * 60:
            _scarica()


def _sorveglia_inattivita():
    while True:
        time.sleep(30)
        _esecutore.submit(_scarica_se_inattivo).result()


if CONFIG["whisper_minuti_inattivita"] > 0:
    threading.Thread(target=_sorveglia_inattivita, daemon=True).start()
