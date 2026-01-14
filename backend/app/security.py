from cryptography.fernet import Fernet
from .config import settings

# Global encryption handler. Pattern from VisionArk.
ENCRYPTION_KEY = settings.encryption_key
fernet = Fernet(ENCRYPTION_KEY.encode())

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
