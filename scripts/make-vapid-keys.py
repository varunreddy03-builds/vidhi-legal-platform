"""Makes the signing key for browser notifications. Run once, paste the printed line into your .env on the server, and keep it secret.

    python scripts/make-vapid-keys.py

The public half is derived from this key by the server; nothing else needs to be stored. If you ever replace the key, every browser
must subscribe again."""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

key = ec.generate_private_key(ec.SECP256R1())
der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
print("VAPID_PRIVATE_KEY=" + base64.urlsafe_b64encode(der).rstrip(b"=").decode())