#!/bin/bash
# =====================================================
# GRP Bot — Setup para VPS Oracle E2.1.Micro (Ubuntu 22.04)
# ⚠️  1 OCPU / 1 GB RAM — Só interface web (Streamlit)
#     O robô Playwright roda no PC local
# Execute: bash setup_vps.sh
# =====================================================

set -e

echo "======================================"
echo "  GRP Bot — Setup VPS E2.1.Micro"
echo "======================================"

# ── 1. Atualiza sistema ─────────────────────────────
echo ""
echo "📦 [1/7] Atualizando sistema..."
sudo apt-get update -y && sudo apt-get upgrade -y

# ── 2. Pacotes base ─────────────────────────────────
echo ""
echo "🔧 [2/7] Instalando pacotes base..."
sudo apt-get install -y python3 python3-pip python3-venv git curl nano wget ufw

# ── 3. Swap de 2GB (compensa o 1GB de RAM) ──────────
echo ""
echo "💾 [3/7] Criando swap de 2GB..."
if [ ! -f /swapfile ]; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    echo "vm.swappiness=10" | sudo tee -a /etc/sysctl.conf
    sudo sysctl -p
    echo "✅ Swap criado: $(free -h | grep Swap)"
else
    echo "✅ Swap já existe"
fi

# ── 4. Firewall ─────────────────────────────────────
echo ""
echo "🔥 [4/7] Configurando firewall (porta 8501)..."
sudo ufw allow OpenSSH
sudo ufw allow 8501/tcp
sudo ufw --force enable
echo "✅ Firewall ativo. Portas abertas: 22 (SSH) e 8501 (Streamlit)"

# ── 5. Ambiente virtual Python ──────────────────────
echo ""
echo "🐍 [5/7] Criando ambiente virtual Python..."
cd ~
python3 -m venv grp_venv
source grp_venv/bin/activate

# ── 6. Clona repositório ────────────────────────────
echo ""
echo "📁 [6/7] Clonando repositório..."
if [ -d "grp_bot" ]; then
    echo "Atualizando repo existente..."
    cd grp_bot && git pull && cd ..
else
    # Substitua pela URL real do seu repositório GitHub
    git clone https://github.com/SEU_USUARIO/grp_bot.git
fi
cd grp_bot

pip install --upgrade pip
pip install -r requirements.txt

# ── 7. Serviço systemd ──────────────────────────────
echo ""
echo "⚙️  [7/7] Criando serviço systemd..."

sudo tee /etc/systemd/system/grpbot.service > /dev/null << EOF
[Unit]
Description=GRP Bot Streamlit
After=network.target

[Service]
User=$USER
WorkingDirectory=$HOME/grp_bot/organizador de planilha
ExecStart=$HOME/grp_venv/bin/streamlit run organizadorsheets.py \
    --server.address=0.0.0.0 \
    --server.port=8501 \
    --server.headless=true \
    --server.maxUploadSize=10
Restart=always
RestartSec=10
Environment=PATH=$HOME/grp_venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable grpbot

# ── Resumo final ─────────────────────────────────────
IP=$(curl -s ifconfig.me 2>/dev/null || echo "IP_DA_VM")
echo ""
echo "======================================"
echo "  ✅ Setup concluído!"
echo "======================================"
echo ""
echo "🔐 Agora crie os arquivos secretos:"
echo ""
echo "  1. Credenciais GRP:"
echo "     nano ~/grp_bot/.env"
echo "     → GRP_USUARIO=seu_usuario"
echo "     → GRP_SENHA=sua_senha"
echo ""
echo "  2. Google Sheets:"
echo "     nano ~/grp_bot/organizador\ de\ planilha/credenciais.json"
echo "     → Cole o conteúdo do seu credenciais.json local"
echo ""
echo "  3. Inicie o serviço:"
echo "     sudo systemctl start grpbot"
echo "     sudo systemctl status grpbot"
echo ""
echo "  4. Acesse no navegador:"
echo "     http://$IP:8501"
echo ""
echo "⚠️  Lembre-se de abrir porta 8501 no firewall da Oracle Console!"
echo "   (VCN → Security Lists → Add Ingress Rule → TCP 8501)"
