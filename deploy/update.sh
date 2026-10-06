#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Atualiza o projeto em producao sem interromper o que ja funciona:
#   1) backup dos arquivos de configuracao;
#   2) atualiza o codigo;
#   3) reinstala dependencias;
#   4) valida a config ANTES de reiniciar;
#   5) reinicia o servico e mostra o status.
#
#   sudo ./deploy/update.sh /caminho/do/projeto/atualizado
# -----------------------------------------------------------------------------
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/monitoramento}"
APP_USER="${APP_USER:-monitor}"
SOURCE_DIR="${1:-}"

log()  { printf '\033[1;34m[update]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31}[erro]\033[0m   %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "Execute com sudo."
[[ -d "$APP_DIR" ]] || fail "Projeto nao encontrado em $APP_DIR."

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$APP_DIR/backups/$STAMP"

log "Fazendo backup de config.yaml, .env e sessions/ em $BACKUP_DIR..."
mkdir -p "$BACKUP_DIR"
for item in config.yaml .env; do
  [[ -f "$APP_DIR/$item" ]] && cp -p "$APP_DIR/$item" "$BACKUP_DIR/" || true
done
[[ -d "$APP_DIR/sessions" ]] && cp -r "$APP_DIR/sessions" "$BACKUP_DIR/" || true

if [[ -n "$SOURCE_DIR" ]]; then
  [[ -d "$SOURCE_DIR" ]] || fail "Diretorio de origem invalido: $SOURCE_DIR"
  log "Sincronizando codigo de $SOURCE_DIR (sem tocar em .env/config.yaml/sessions)..."
  rsync -a --delete \
    --exclude '.env' \
    --exclude 'config.yaml' \
    --exclude 'sessions/' \
    --exclude 'screenshots/' \
    --exclude 'logs/' \
    --exclude '.venv/' \
    --exclude 'backups/' \
    "$SOURCE_DIR"/ "$APP_DIR"/
else
  log "Nenhum diretorio de origem informado; mantendo o codigo atual."
fi

log "Atualizando dependencias Python..."
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

log "Verificando o Chromium do Playwright..."
"$APP_DIR/.venv/bin/python" -m playwright install --with-deps chromium

chown -R "$APP_USER:$APP_USER" "$APP_DIR/screenshots" "$APP_DIR/logs" "$APP_DIR/sessions" "$APP_DIR/.tmp"

log "Validando configuracao antes de reiniciar (rollback se falhar)..."
if ! sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" "$APP_DIR/main.py" --list; then
  printf '\033[1;31m[erro]\033[0m   Configuracao invalida apos a atualizacao.\n' >&2
  echo "Restaurando backup de $BACKUP_DIR ..." >&2
  for item in config.yaml .env; do
    [[ -f "$BACKUP_DIR/$item" ]] && cp -p "$BACKUP_DIR/$item" "$APP_DIR/" || true
  done
  [[ -d "$BACKUP_DIR/sessions" ]] && cp -r "$BACKUP_DIR/sessions/." "$APP_DIR/sessions/" || true
  fail "Atualizacao abortada; backup restaurado."
fi

log "Reiniciando servico..."
systemctl restart monitoramento
sleep 3
systemctl --no-pager --lines=15 status monitoramento || true

log "Concluido. Backup em $BACKUP_DIR"
