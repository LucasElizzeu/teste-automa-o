# Monitoramento Operacional

Sistema de captura automatizada de dashboards (Grafana, Flowbix e outros) com
envio dos prints para um grupo do Telegram, em horarios configurados.

O fluxo, do inicio ao fim:

```text
AGENDADOR
   ↓
ABRIR GRAFANA / FLOWBIX
   ↓
AUTENTICAR (ou reutilizar storage_state.json)
   ↓
ABRIR DASHBOARD
   ↓
APLICAR PERIODO
   ↓
AGUARDAR CARREGAMENTO DOS GRAFICOS
   ↓
CAPTURAR SCREENSHOT (elemento > regiao > pagina)
   ↓
RECORTAR + ADICIONAR IDENTIFICACAO
   ↓
SALVAR IMAGEM
   ↓
ENVIAR AO TELEGRAM
   ↓
REGISTRAR NO LOG
```

---

## 1. Instalacao rapida (Ubuntu)

```bash
sudo ./deploy/install.sh
sudo nano /opt/monitoramento/.env          # tokens e senhas
sudo nano /opt/monitoramento/config.yaml   # URLs reais e seletores
sudo -u monitor /opt/monitoramento/.venv/bin/python /opt/monitoramento/main.py --telegram-test
sudo systemctl enable --now monitoramento
sudo journalctl -u monitoramento -f
```

Instalacao manual, sem o script:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install --with-deps chromium
cp .env.example .env && chmod 600 .env
python main.py --list
```

## 2. Execucao manual (teste de seletores)

```bash
python main.py --list                          # mostra os sites cadastrados
python main.py --site "MANAUS - TEFE" --no-send # captura sem enviar
python main.py --site "MANAUS - TEFE" --send    # captura e envia
python main.py --all                            # todos os sites habilitados
python main.py --telegram-test                  # valida bot, chat e permissao
python main.py --schedule                        # agendador residente
python main.py --cleanup                         # aplica a politica de retencao
python main.py --site "MANAUS - TEFE" --headed   # navegador visivel (debug)
```

O comparador de nomes ignora acento, caixa e o tipo de traco, entao
`"MANAUS - TEFE"`, `"manaus - tefe"` e `"MANAUS → TEFÉ"` encontram o mesmo site.

## 3. Configuracao

**Todos os segredos ficam no `.env`** (nunca no `config.yaml`, nunca no codigo):

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
GRAFANA_USERNAME=
GRAFANA_PASSWORD=
FLOWBIX_USERNAME=
FLOWBIX_PASSWORD=
HEADLESS=true
SCREENSHOT_RETENTION_DAYS=7
```

O `config.yaml` guarda o que nao e segredo: horarios, sites, timezone,
viewport, retencao, e os seletores HTML.

### Adicionar um dashboard novo

Basta acrescentar um item em `sites:` — nenhum codigo muda:

```yaml
sites:
  - nome: "MANAUS - TEFE"
    sistema: "grafana"
    url: "https://grafana.suaempresa.com/d/abc123/circuito?orgId=1"
    periodo: "6h"
    enabled: true
```

Para o Grafana, o periodo tambem vai na URL (`from=now-6h&to=now`), evitando
depender de cliques na interface.

### Horarios

```yaml
schedule:
  mode: "mixed"            # cron | every | mixed
  times: ["08:00", "12:00", "16:00", "20:00", "00:00"]
  every_hours: []          # [1] = a cada 1h, [2] = a cada 2h
  timezone: "America/Manaus"
```

O agendador interno deriva o horario do relogio real a cada ciclo, entao nao
acumula atraso. Se preferir, use o timer do systemd (`deploy/monitoramento.timer`)
com `main.py --all` e mantenha o servico residente desligado — os dois modos
existem, mas use apenas um por vez.

## 4. Como a captura funciona

A ordem de preferencia na captura e:

1. **elemento HTML do painel** (`systems.<sistema>.panel.container_selector`);
2. **regiao fixa** (`crop_region` no site ou em `output`);
3. **pagina inteira** (fallback).

Antes do print, o sistema espera a rede ficar ociosa, aguarda o indicador de
carregamento sumir, confere se ha `canvas`/`svg` renderizados e so entao
adiciona alguns segundos extras (`extra_settle_seconds`).

## 5. Sessao e autenticacao

Cada sistema tem seu proprio `sessions/<sistema>_storage_state.json`, salvo
atomicamente. Se a sessao salva ainda for valida, nao ha login novo. Se o
servidor derrubar a sessao, o sistema detecta a tela de login, autentica,
atualiza o arquivo e continua — sem intervencao.

Sessoes mais antigas que `auth.session_max_age_hours` sao refeitas por
precaucao, mesmo que pareçam validas.

## 6. Retry e isolamento de falhas

Falha de um dashboard **nao** interrompe os demais. A ordem por site e:

```text
tentativa 1 → falhou → espera 10s
tentativa 2 → falhou → espera 20s
tentativa 3 → falhou
   ↓
registra ERROR no log + envia aviso ao Telegram
   ↓
segue para o proximo site
```

Ajuste em `auth.retry_attempts` e `auth.retry_backoff_seconds`.

## 7. Estrutura do projeto

```text
monitoramento/
├── main.py                       # CLI (--all, --site, --schedule, --telegram-test, ...)
├── config.yaml                   # sites, horarios, seletores
├── .env                          # segredos (fora do Git)
├── requirements.txt
├── core/
│   ├── config.py                 # carrega e valida config.yaml + .env
│   ├── logging_setup.py          # logs + filtro que remove segredos
│   ├── paths.py
│   ├── retention.py              # politica de limpeza
│   ├── scheduler.py              # agendador (America/Manaus)
│   └── workflow.py               # captura → imagem → envio → log
├── services/
│   ├── base.py                   # contrato comum dos dashboards
│   ├── grafana.py
│   ├── flowbix.py
│   ├── registry.py               # mapa sistema → servico
│   └── telegram.py
├── browser/
│   └── playwright_manager.py     # sessao, espera e screenshot
├── utils/
│   ├── caption.py                # legendas e mensagens
│   └── images.py                 # recorte e faixa de identificacao
├── deploy/
│   ├── install.sh
│   ├── update.sh
│   ├── monitoramento.service
│   └── monitoramento.timer
├── screenshots/                  # saida (subpasta por dia)
├── logs/
└── sessions/
```

### Diferencas em relacao ao esqueleto sugerido

- `core/` foi adicionado para concentrar config/logs/agendamento, em vez de
  colocar tudo em `main.py` — e isso que permite a interface web futura
  importar o nucleo sem passar pela CLI.
- `services/registry.py` isola o mapa de sistemas: adicionar um dashboard
  novo = 1 classe + 1 linha no registro.
- `utils/images.py` separa o tratamento de imagem da automacao de navegador
  (facilita trocar Pillow, ou reprocessar prints antigos).
- `deploy/` agrupa instalacao e servico, para o container e o host usarem os
  mesmos artefatos.

## 8. Docker

```bash
cp .env.example .env && nano .env
nano config.yaml
docker compose up -d --build
docker compose logs -f

# execucoes pontuais
docker compose run --rm monitor python main.py --telegram-test
docker compose run --rm monitor python main.py --site "MANAUS - TEFE" --no-send
```

A imagem base oficial do Playwright ja traz Chromium e as bibliotecas de
sistema; o `shm_size: 1gb` evita travamento do navegador.

## 9. Seguranca

- Tokens e senhas **somente** no `.env` (permissao `600`), que esta no `.gitignore`.
- Logs passam por um filtro que substitui tokens/senhas por `[REDACTED]`,
  inclusive em mensagens de erro de rede.
- Erros enviados ao Telegram nunca contem credenciais.
- Timeout de navegacao e de elemento configuraveis; toda chamada HTTP tem timeout.
- Retry com backoff por site; falha isolada.
- `storage_state.json` fica em `sessions/`, fora do Git.
- Servico systemd roda com usuario sem privilegio e `ProtectSystem=full`.

## 10. Nome dos arquivos e retencao

Padrao: `AAAA-MM-DD_HH-MM_SITE_ORIGEM.png`, dentro de uma subpasta por dia:

```text
screenshots/2026-10-06/2026-10-06_08-00_MANAUS_TEFE_GRAFANA.png
```

Retencao configuravel por `SCREENSHOT_RETENTION_DAYS` (padrao 7). A limpeza roda
via `python main.py --cleanup` (coloque num cron diario) ou pode ser chamada
pelo painel futuro.

## 11. Evolucao para painel web

O nucleo ja esta pronto para isso: `core.workflow.CaptureRunner` recebe um
objeto `Settings` e devolve `SiteResult` — uma API web pode chamar o mesmo
runner sem passar pela CLI. O proximo passo natural e um servico FastAPI que
le/escreve o `config.yaml` (via `core.config`) e serve as imagens de
`screenshots/`, mantendo o agendador como processo separado.

## 12. Proximo passo: seletores reais

Os blocos `systems.grafana.*` e `systems.flowbix.*` estao intencionalmente
vazios. A captura funciona hoje em modo generico (pagina/regiao), mas para
recortar exatamente o painel eu preciso, de cada sistema:

1. a URL real do dashboard;
2. um screenshot da tela;
3. o HTML da area do grafico (ou o seletor, se voce ja souber);
4. credenciais de teste, se for necessario conferir o fluxo de login.

Com isso preencho `login.*`, `panel.container_selector` e os presets de periodo.
