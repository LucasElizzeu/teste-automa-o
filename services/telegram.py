"""Cliente do Bot do Telegram (envio de imagens, mensagens e documentos).

Usa a API HTTP do Telegram via requests - sem dependencia extra de framework.
O token NUNCA aparece em log (filtro de segredo no logging_setup) nem em
mensagens de erro devolvidas ao usuario.
"""

from __future__ import annotations

import os
from pathlib import Path

import requests

from core.config import TelegramSettings

API_BASE = "https://api.telegram.org"

SEND_IMAGE_TIMEOUT = 60
SEND_MESSAGE_TIMEOUT = 30
SEND_DOCUMENT_TIMEOUT = 120


class TelegramError(RuntimeError):
    """Falha ao falar com a API do Telegram (mensagem ja higienizada)."""


def _clean(text: str, token: str = "") -> str:
    """Remove o token de qualquer texto que va para log ou para o usuario."""
    value = str(text or "")
    if token:
        value = value.replace(token, "[TOKEN]")
    return value


class TelegramClient:
    configured = False

    def __init__(
        self,
        settings: TelegramSettings,
        logger,
        chat_id: str | None = None,
    ):
        self.settings = settings
        self.logger = logger
        self.token = (settings.token or "").strip()
        self.chat_id = str(chat_id or settings.chat_id or "").strip()
        self.configured = bool(self.token and self.chat_id)

    # ------------------------------------------------------------- internos

    @property
    def _api(self) -> str:
        if not self.token:
            raise TelegramError("TELEGRAM_BOT_TOKEN nao configurado no .env.")
        return f"{API_BASE}/bot{self.token}"

    def _post(self, method: str, timeout: int, **kwargs) -> dict:
        if not self.configured:
            raise TelegramError(
                "Telegram nao configurado. Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env."
            )
        url = f"{self._api}/{method}"
        try:
            response = requests.post(url, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            raise TelegramError(f"Falha de rede ao chamar {method}: {_clean(exc, self.token)}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise TelegramError(
                f"Resposta invalida da API ({response.status_code}): {_clean(response.text[:200], self.token)}"
            ) from exc

        if not payload.get("ok"):
            description = _clean(payload.get("description") or "erro desconhecido", self.token)
            code = payload.get("error_code")
            raise TelegramError(f"API do Telegram recusou {method} ({code}): {description}")

        return payload.get("result") or {}

    # --------------------------------------------------------------- envios

    def send_message(self, text: str, parse_mode: str = "HTML", chat_id: str | None = None) -> bool:
        """Envia mensagem de texto. Devolve True/False e registra o motivo."""
        chat = str(chat_id or self.chat_id).strip()
        if not self.configured or not chat:
            self.logger.error("Telegram: credenciais ausentes; mensagem nao enviada.")
            return False
        try:
            self._post(
                "sendMessage",
                SEND_MESSAGE_TIMEOUT,
                data={
                    "chat_id": chat,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": "true",
                    "disable_notification": "true" if self.settings.silent_notifications else "false",
                },
            )
            return True
        except TelegramError as exc:
            self.logger.error("Telegram: %s", exc)
            return False

    def send_photo(self, image_path: str | Path, caption: str = "", chat_id: str | None = None) -> bool:
        """Envia imagem com legenda. Respeita o limite de legenda da API."""
        path = Path(image_path)
        chat = str(chat_id or self.chat_id).strip()
        if not self.configured or not chat:
            self.logger.error("Telegram: credenciais ausentes; imagem nao enviada.")
            return False
        if not path.exists():
            self.logger.error("Telegram: arquivo inexistente (%s).", path.name)
            return False

        caption_text = self._fit_caption(caption)
        try:
            with path.open("rb") as handle:
                self._post(
                    "sendPhoto",
                    SEND_IMAGE_TIMEOUT,
                    data={
                        "chat_id": chat,
                        "caption": caption_text,
                        "parse_mode": "HTML",
                        "disable_notification": "true" if self.settings.silent_notifications else "false",
                    },
                    files={"photo": (path.name, handle, "image/png")},
                )
            return True
        except TelegramError as exc:
            self.logger.error("Telegram: %s", exc)
            return False

    def send_document(self, file_path: str | Path, caption: str = "", chat_id: str | None = None) -> bool:
        """Envia documento (relatorio, csv, pdf)."""
        path = Path(file_path)
        chat = str(chat_id or self.chat_id).strip()
        if not self.configured or not chat:
            self.logger.error("Telegram: credenciais ausentes; documento nao enviado.")
            return False
        if not path.exists():
            self.logger.error("Telegram: arquivo inexistente (%s).", path.name)
            return False
        try:
            with path.open("rb") as handle:
                self._post(
                    "sendDocument",
                    SEND_DOCUMENT_TIMEOUT,
                    data={"chat_id": chat, "caption": self._fit_caption(caption)},
                    files={"document": (path.name, handle, "application/octet-stream")},
                )
            return True
        except TelegramError as exc:
            self.logger.error("Telegram: %s", exc)
            return False

    # ------------------------------------------------------------ utilitarios

    def _fit_caption(self, caption: str) -> str:
        limit = int(self.settings.max_caption_length or 1024)
        if len(caption) <= limit:
            return caption
        return caption[: max(0, limit - 20)].rstrip() + "\n(...)"

    def get_me(self) -> dict | None:
        """Valida o token consultando o proprio bot (usado no --telegram-test)."""
        try:
            return self._post("getMe", SEND_MESSAGE_TIMEOUT)
        except TelegramError as exc:
            self.logger.error("Telegram: %s", exc)
            return None

    def send_error(self, site_name: str, system_id: str, error: str, chat_id: str | None = None) -> bool:
        message = (
            "⚠️ <b>Falha no monitoramento</b>\n\n"
            f"<b>Site:</b> {site_name}\n"
            f"<b>Sistema:</b> {system_id.capitalize()}\n"
            f"<b>Erro:</b> {error}"
        )
        return self.send_message(message, chat_id=chat_id)


def build_client(settings, logger, chat_id: str | None = None) -> TelegramClient:
    """Fatora o cliente sem exigir que o chamador monte as configs."""
    telegram_settings: TelegramSettings = settings.telegram
    env_chat = os.getenv("TELEGRAM_CHAT_ID")
    return TelegramClient(
        telegram_settings,
        logger,
        chat_id=chat_id or env_chat or None,
    )
