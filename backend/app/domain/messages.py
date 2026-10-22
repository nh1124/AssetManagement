"""Text a person reads, in both UI languages (WP29).

The studio and the mobile app show what an error says, and they ask for it in the
language the screen is in. A Message is the text as it was written -- to anything
that never asks for a language (logs, str(error), the MCP server, tests) it is that
plain str -- and it carries its translation for the places that do ask: the HTTP
error handlers and the few responses that hold a reason for the screen.
"""
from __future__ import annotations

LANGUAGES = ("ja", "en")


class Message(str):
    """The text as written, with its translation: Message("…", en="…") or Message("…", ja="…")."""

    def __new__(cls, text: str, *, ja: str | None = None, en: str | None = None) -> "Message":
        message = super().__new__(cls, text)
        message.ja = text if ja is None else ja
        message.en = text if en is None else en
        return message

    def in_language(self, language: str | None) -> str:
        """The text in that language; as written when the language is neither."""
        if language == "en":
            return self.en
        if language == "ja":
            return self.ja
        return str(self)


def localize(value, language: str | None):
    """Every Message in a response body, in that language; everything else unchanged."""
    if isinstance(value, Message):
        return value.in_language(language)
    if isinstance(value, dict):
        return {key: localize(item, language) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [localize(item, language) for item in value]
    return value


def message_of(error: BaseException) -> str:
    """An exception's text, keeping its translation; str(error) would drop it."""
    text = error.args[0] if len(error.args) == 1 else None
    return text if isinstance(text, Message) else str(error)
