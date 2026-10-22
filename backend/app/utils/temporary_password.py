"""Temporary passwords use OS randomness and omit ambiguous characters."""
import secrets

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def temporary_password() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(16))
