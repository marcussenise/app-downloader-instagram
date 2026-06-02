import logging
import os
from pathlib import Path
from flask import Flask, render_template, request, jsonify
import yt_dlp

# --- logging ------------------------------------------------------------------
LOG_FILE = Path(__file__).parent / "debug.log"
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),          # também aparece no terminal do Termux
    ],
)
log = logging.getLogger(__name__)

# --- app ----------------------------------------------------------------------
app = Flask(__name__)

SAVE_DIR = Path.home() / "storage" / "downloads" / "Instagram"
log.info("SAVE_DIR = %s  (existe: %s)", SAVE_DIR, SAVE_DIR.exists())

try:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Pasta criada/confirmada com sucesso.")
except Exception as e:
    log.error("Não foi possível criar SAVE_DIR: %s", e)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/status")
def status():
    """Rota de diagnóstico — abra /status no navegador para ver o estado."""
    files = sorted(SAVE_DIR.iterdir()) if SAVE_DIR.exists() else []
    return jsonify(
        save_dir=str(SAVE_DIR),
        save_dir_exists=SAVE_DIR.exists(),
        files_in_dir=[f.name for f in files],
        log_file=str(LOG_FILE),
    )


@app.route("/download", methods=["POST"])
def download():
    url = (request.json or {}).get("url", "").strip()
    log.info("Download solicitado: %s", url)

    if not url or "instagram.com" not in url:
        return jsonify(error="Cole um link válido do Instagram."), 400

    # Arquivos presentes ANTES do download (para detectar o que foi criado)
    antes = set(SAVE_DIR.iterdir()) if SAVE_DIR.exists() else set()

    ydl_opts = {
        "outtmpl": str(SAVE_DIR / "%(autonumber)s_%(id)s.%(ext)s"),
        "quiet": False,        # mostra tudo no terminal/log
        "no_warnings": False,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "autonumber_start": 1,
        "logger": _YtdlpLogger(),
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            log.info("extract_info concluído. Keys: %s", list((info or {}).keys()))
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        log.error("DownloadError: %s", msg)
        if "login" in msg.lower() or "private" in msg.lower():
            return jsonify(error="Post privado ou requer login no Instagram."), 400
        return jsonify(error=f"Erro ao baixar: {msg}"), 400
    except Exception as e:
        log.exception("Erro inesperado")
        return jsonify(error=f"Erro inesperado: {e}"), 500

    # Arquivos criados APÓS o download
    depois = set(SAVE_DIR.iterdir()) if SAVE_DIR.exists() else set()
    novos = [f.name for f in (depois - antes) if not f.name.endswith(".part")]
    log.info("Arquivos novos: %s", novos)

    if not novos:
        log.warning("Nenhum arquivo novo encontrado em %s", SAVE_DIR)
        return jsonify(
            error=f"yt-dlp terminou sem criar arquivos. Veja debug.log para detalhes. Pasta: {SAVE_DIR}"
        ), 500

    # Extrai metadados do post
    entries = info.get("entries") or []
    first = entries[0] if entries else info
    uploader = (info.get("uploader") or info.get("uploader_id")
                or first.get("uploader") or first.get("uploader_id") or "")
    description = (info.get("description") or first.get("description") or "")
    log.info("uploader=%s  description=%s chars", uploader, len(description))

    count = len(novos)
    tipo = "1 vídeo" if count == 1 else f"{count} arquivos"
    return jsonify(ok=True, tipo=tipo, pasta=str(SAVE_DIR), arquivos=novos,
                   uploader=uploader, description=description)


class _YtdlpLogger:
    """Redireciona logs do yt-dlp para o nosso logger."""
    def debug(self, msg):
        if msg.startswith("[debug]"):
            log.debug("yt-dlp: %s", msg)
        else:
            log.info("yt-dlp: %s", msg)
    def warning(self, msg):
        log.warning("yt-dlp: %s", msg)
    def error(self, msg):
        log.error("yt-dlp: %s", msg)


if __name__ == "__main__":
    log.info("Iniciando servidor em http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
