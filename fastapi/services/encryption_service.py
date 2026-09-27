import os
import json
import base64
from cryptography.fernet import Fernet
import logging

logger = logging.getLogger("siparta.encryption")

# Load or generate key
_ENCRYPTION_KEY = os.getenv("SIPARTA_ENCRYPTION_KEY")

if not _ENCRYPTION_KEY:
    # Generate a default key if not provided (for development).
    # In production, this MUST be set in environment variables.
    logger.warning("SIPARTA_ENCRYPTION_KEY is not set. Using a temporary key for this session!")
    _ENCRYPTION_KEY = Fernet.generate_key().decode("utf-8")

_fernet = Fernet(_ENCRYPTION_KEY.encode("utf-8"))

def encrypt_payload(payload: dict) -> str:
    """
    Encrypts a JSON dictionary into a Fernet token (base64 string).
    """
    try:
        json_bytes = json.dumps(payload).encode("utf-8")
        encrypted_bytes = _fernet.encrypt(json_bytes)
        return encrypted_bytes.decode("utf-8")
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        raise

def decrypt_payload(token: str) -> dict:
    """
    Decrypts a Fernet token back into a JSON dictionary.
    """
    try:
        decrypted_bytes = _fernet.decrypt(token.encode("utf-8"))
        return json.loads(decrypted_bytes.decode("utf-8"))
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        raise
