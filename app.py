import os
import uuid
from pathlib import Path
from flask import Flask, render_template, request, jsonify
import yt_dlp

app = Flask(__name__)

# Salva direto na pasta Downloads/Instagram do Android
SAVE_DIR = Path.home() / "storage" / "downloads" / "Instagram"
SAVE_DIR.mkdir(parents=True, exist_ok=True)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/download", methods=["POST"])
def download():
    url = (request.json or {}).get("url", "").strip()
    if not url or "instagram.com" not in url:
        return jsonify(error="Cole um link válido do Instagram."), 400

    ydl_opts = {
        "outtmpl": str(SAVE_DIR / "%(autonumber)s_%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "autonumber_start": 1,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if "login" in msg.lower() or "private" in msg.lower():
            return jsonify(error="Post privado ou requer login no Instagram."), 400
        return jsonify(error=f"Erro ao baixar: {msg}"), 400
    except Exception as e:
        return jsonify(error=f"Erro inesperado: {e}"), 500

    count = len(info.get("entries", [])) or 1
    tipo = "vídeo" if count == 1 else f"{count} arquivos"
    return jsonify(ok=True, tipo=tipo, pasta="Downloads/Instagram")


if __name__ == "__main__":
    print("\n  Abra no navegador do celular: http://localhost:5000\n")
    app.run(host="127.0.0.1", port=5000, debug=False)
