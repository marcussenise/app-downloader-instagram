import logging
import os
import re
import subprocess
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

_termux_storage = Path("/storage/emulated/0/Downloads/Instagram")
_termux_fallback = Path.home() / "storage" / "downloads" / "Instagram"
SAVE_DIR = _termux_storage if Path("/storage/emulated/0").exists() else _termux_fallback
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
    home = Path.home()
    storage_link = home / "storage"
    downloads_link = home / "storage" / "downloads"
    files = sorted(SAVE_DIR.iterdir()) if SAVE_DIR.exists() else []
    return jsonify(
        home=str(home),
        storage_exists=storage_link.exists(),
        storage_is_symlink=storage_link.is_symlink(),
        downloads_exists=downloads_link.exists(),
        save_dir=str(SAVE_DIR),
        save_dir_exists=SAVE_DIR.exists(),
        save_dir_writable=os.access(SAVE_DIR, os.W_OK) if SAVE_DIR.exists() else False,
        files_in_dir=[f.name for f in files],
        log_file=str(LOG_FILE),
        cwd=os.getcwd(),
    )


@app.route("/log")
def view_log():
    """Mostra as últimas 80 linhas do debug.log no navegador."""
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
        tail = "\n".join(lines[-80:])
    except Exception as e:
        tail = f"Erro ao ler log: {e}"
    return f"<pre style='font-size:12px;white-space:pre-wrap;word-break:break-all'>{tail}</pre>"


@app.route("/download", methods=["POST"])
def download():
    url = (request.json or {}).get("url", "").strip()
    log.info("Download solicitado: %s", url)

    if not url or "instagram.com" not in url:
        return jsonify(error="Cole um link válido do Instagram."), 400

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

    # Pega os arquivos a partir do requested_downloads (funciona mesmo se já existia)
    requested = info.get("requested_downloads") or []
    novos = [Path(d["filepath"]).name for d in requested if d.get("filepath")]
    log.info("Arquivos (requested_downloads): %s", novos)

    if not novos:
        log.warning("requested_downloads vazio em %s", SAVE_DIR)
        return jsonify(
            error=f"yt-dlp terminou sem criar arquivos. Veja debug.log para detalhes. Pasta: {SAVE_DIR}"
        ), 500

    # Extrai metadados do post
    entries = info.get("entries") or []
    first = entries[0] if entries else info
    log.info("RAW uploader=%r  uploader_id=%r  uploader_url=%r",
             info.get("uploader"), info.get("uploader_id"), info.get("uploader_url"))
    if first is not info:
        log.info("RAW(first) uploader=%r  uploader_id=%r  uploader_url=%r",
                 first.get("uploader"), first.get("uploader_id"), first.get("uploader_url"))
    uploader = _instagram_username(info, first)
    description = (info.get("description") or first.get("description") or "")
    log.info("uploader=%r  description=%d chars", uploader, len(description))

    _media_scan(novos)

    count = len(novos)
    tipo = "1 vídeo" if count == 1 else f"{count} arquivos"
    return jsonify(ok=True, tipo=tipo, pasta=str(SAVE_DIR), arquivos=novos,
                   uploader=uploader, description=description)


def _media_scan(filenames):
    """Avisa o Android sobre arquivos novos para aparecerem na galeria."""
    for name in filenames:
        path = str(SAVE_DIR / name)
        try:
            subprocess.run(["termux-media-scan", path], timeout=10, check=False)
            log.info("termux-media-scan: %s", path)
        except FileNotFoundError:
            log.debug("termux-media-scan não disponível (sem termux-api)")
        except Exception as e:
            log.warning("termux-media-scan falhou: %s", e)


def _instagram_username(info, first):
    """Extrai o @username tentando vários campos do yt-dlp."""
    for src in (info, first):
        # uploader_url nem sempre existe, mas vale tentar
        url = src.get("uploader_url") or ""
        m = re.search(r"instagram\.com/([A-Za-z0-9_.]+)/?", url)
        if m:
            log.debug("username via uploader_url: %s", m.group(1))
            return f"@{m.group(1)}"

    # channel costuma ser o username no extractor do Instagram
    for src in (info, first):
        ch = (src.get("channel") or "").lstrip("@").strip()
        if ch and not ch.isdigit():
            log.debug("username via channel: %s", ch)
            return f"@{ch}"

    # uploader_id se não for numérico
    for src in (info, first):
        uid = (src.get("uploader_id") or "").lstrip("@").strip()
        if uid and not uid.isdigit():
            log.debug("username via uploader_id: %s", uid)
            return f"@{uid}"

    log.warning("username não encontrado. uploader=%r uploader_id=%r channel=%r uploader_url=%r",
                info.get("uploader"), info.get("uploader_id"),
                info.get("channel"), info.get("uploader_url"))
    return ""


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
