"""Configurazione unica per Mac (sviluppo) e PC Windows (produzione).
I valori di default vanno bene ovunque; per cambiarli sul PC di produzione
crea un file config.json accanto a questo (vedi config.example.json)."""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT = {
    # --- Whisper ---
    # "auto": MLX sui Mac Apple Silicon, CUDA se c'è una scheda NVIDIA, altrimenti CPU
    "whisper_backend": "auto",            # auto | mlx | cuda | cpu
    "whisper_modello": "large-v3-turbo",  # per CPU lente: "medium" o "small"
    "whisper_minuti_inattivita": 5,       # dopo quanti minuti scaricarlo dalla memoria (0 = mai)
    "glossario": None,                    # None = usa dati/vocabolario.txt

    # --- LLM (Ollama), usato solo se le regole non bastano ---
    "llm_attivo": True,
    "llm_modello": "qwen2.5:3b",
    "llm_keep_alive": "2m",               # quanto resta in memoria dopo l'ultimo uso

    # --- Risorse: lascia la precedenza ad AutoCAD, SketchUp, Excel ---
    "priorita_bassa": True,
    "thread_cpu": 4,                      # thread massimi per Whisper su CPU

    # --- Rete ---
    "porta": 8000,

    # --- Dati ---
    "database": "inventario.db",
    "minuti_doppione": 10,                # stessa riga entro N minuti -> avviso "possibile doppione"
    "trascrizioni_giorni": 90,            # giorni dopo la chiusura dell'inventario prima di cancellarle
    "utente_campioni": "Prova",           # solo per questo utente l'audio resta in campioni/ (None = mai)

    # --- Backup (spento finché non si indica la cartella del NAS) ---
    "backup_cartella": None,              # es. "\\\\NAS\\inventario\\backup" oppure "/Volumes/home/backup"
    "backup_minuti": 60,
    "backup_giorni": 30,
}


def carica() -> dict:
    config = dict(DEFAULT)
    percorso = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(percorso):
        with open(percorso, encoding="utf-8") as f:
            config.update(json.load(f))
    return config


CONFIG = carica()
