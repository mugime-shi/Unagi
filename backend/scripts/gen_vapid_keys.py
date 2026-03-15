#!/usr/bin/env python3
"""
Generate VAPID key pair for Web Push notifications.

Run once, then add the output to backend/.env:
    cd backend
    python scripts/gen_vapid_keys.py

VAPID (Voluntary Application Server Identification) is how the push service
(Google FCM, Mozilla, etc.) verifies that push messages come from our server.

Key formats:
  VAPID_PRIVATE_KEY — base64url-encoded raw 32-byte P-256 private scalar
                      (pywebpush accepts this directly as vapid_private_key)
  VAPID_PUBLIC_KEY  — base64url-encoded uncompressed EC point (65 bytes, starts 0x04)
                      (passed to browser's pushManager.subscribe as applicationServerKey)
"""

import base64

from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

key = generate_private_key(SECP256R1())

# Private key: raw 32-byte scalar (big-endian)
private_int = key.private_numbers().private_value
private_bytes = private_int.to_bytes(32, byteorder="big")
private_b64 = base64.urlsafe_b64encode(private_bytes).rstrip(b"=").decode()

# Public key: uncompressed EC point = 0x04 || x (32 bytes) || y (32 bytes) → 65 bytes
public_bytes = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
public_b64 = base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode()

print("Add the following to backend/.env:\n")
print(f"VAPID_PRIVATE_KEY={private_b64}")
print(f"VAPID_PUBLIC_KEY={public_b64}")
print(f'VAPID_CONTACT=mailto:you@example.com')
