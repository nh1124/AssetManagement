from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from .config import settings

# Global encryption handler. Pattern from VisionArk.
ENCRYPTION_KEY = settings.encryption_key


def build_fernet(keys: list[str]) -> MultiFernet:
    """The first key encrypts; every key decrypts.

    That is what lets the key be replaced on a live system: make the new key
    current, keep the old one as previous, re-encrypt the stored values with
    app.maintenance.reencrypt_secrets, then drop the old key.
    """
    return MultiFernet([Fernet(key.encode()) for key in keys])


fernet = build_fernet(settings.encryption_keys)

def encrypt_key(plain_text: str) -> str:
    if not plain_text:
        return None
    return fernet.encrypt(plain_text.encode()).decode()

def decrypt_key(cipher_text: str) -> str:
    if not cipher_text:
        return None
    try:
        return fernet.decrypt(cipher_text.encode()).decode()
    except Exception:
        return None


def rotate_token(cipher_text: str) -> str | None:
    """Re-encrypt a stored value under the current key. None if no known key
    can read it."""
    try:
        return fernet.rotate(cipher_text.encode()).decode()
    except InvalidToken:
        return None
