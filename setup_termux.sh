#!/data/data/com.termux/files/usr/bin/bash
set -e

echo "==> Atualizando pacotes..."
pkg update -y && pkg upgrade -y

echo "==> Instalando Python e ffmpeg..."
pkg install python ffmpeg -y

echo "==> Liberando acesso ao armazenamento..."
termux-setup-storage

echo "==> Instalando dependências Python..."
pip install flask yt-dlp

echo ""
echo "✓ Pronto! Para iniciar o app, rode:"
echo "   python app.py"
echo ""
echo "Depois abra no navegador: http://localhost:5000"
