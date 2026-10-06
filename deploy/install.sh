#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Provisiona o projeto em um servidor Linux/Ubuntu limpo.
#
#   chmod +x deploy/install.sh
#   sudo ./deploy/install.sh
#
# O script e idempotente: rodar de novo nao quebra o que ja existe.
# -----------------------------------------------------------------------------
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/monitoramento}"
APP_USER="${APP_USER:-monitor}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

log()  { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[aviso]\033[0m  %s\n' "$*"; }
fail() { printf '\033[1;31m[erro]\033[0m   %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "Execute com sudo."

log "Instalando dependencias de sistema..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip tzdata fonts-dejavu-core curl

log "Configurando timezone America/Manaus..."
ln -snf /usr/share/zoneinfo/America/Manaus /etc/localtime
echo "America/Manaus" > /etc/timezone

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  log "Criando usuario de servico '$APP_USER'..."
  useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
fi

log "Copiando projeto para $APP_DIR..."
mkdir -p "$APP_DIR"
if [[ -f "$(dirname "$0")/../requirements.txt" ]]; then
  SRC="$(cd "$(dirname "$0")/.." && pwd)"
  cp -r "$SRC"/. "$APP_DIR"/
else
  warn "Nao encontrei o projeto ao lado deste script; assumindo que ja esta em $APP_DIR."
fi

if [[ ! -f "$APP_DIR/.env" ]]; then
  if [[ -f "$APP_DIR/.env.example" ]]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
    warn "Criei $APP_DIR/.env a partir do exemplo. EDITE e preencha tokens/senhas antes de rodar."
  fi
else
  chmod 600 "$APP_DIR/.env"
fi

log "Criando virtualenv e instalando dependencias Python..."
"$PYTHON_BIN" -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

log "Instalando Chromium do Playwright (com dependencias de sistema)..."
"$APP_DIR/.venv/bin/python" -m playwright install --with-deps chromium

log "Ajustando permissoes..."
mkdir -p "$APP_DIR/screenshots" "$APP_DIR/logs" "$APP_DIR/sessions" "$APP_DIR/.tmp"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 750 "$APP_DIR/sessions" "$APP_DIR/logs"

log "Instalando servico systemd..."
install -m 644 "$APP_DIR/deploy/monitoramento.service" /etc/systemd/system/monitoramento.service
systemctl daemon-reload

log "Validando a configuracao..."
if ! sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" "$APP_DIR/main.py" --list; then
  warn "A validacao falhou. Corrija o config.yaml/.env e rode: sudo systemctl restart monitoramento"
fi

log ""
log "Proximos passos:"
log "  1) Edite $APP_DIR/.env (Telegram, Grafana, Flowbix)"
log "  2) Edite $APP_DIR/config.yaml (URLs reais e seletores)"
log "  3) Teste:   sudo -u $APP_USER $APP_DIR/.venv/bin/python $APP_DIR/main.py --telegram-test"
log "  4) Ative:   sudo systemctl enable --now monitoramento"
log "  5) Logs:    sudo journalctl -u monitoramento -f"
