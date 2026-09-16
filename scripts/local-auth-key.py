#!/usr/bin/env python3
"""Create a private local Supabase signing key without replacing an existing key."""

import json
import os
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

path = Path(__file__).resolve().parents[1] / "supabase" / "signing_keys.json"
if path.exists():
    print("Local signing key already exists; retained.")
else:
    key = json.loads(ECAlgorithm.to_jwk(ec.generate_private_key(ec.SECP256R1())))
    key.update({"kid": str(uuid4()), "alg": "ES256", "use": "sig", "key_ops": ["sign", "verify"]})
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as target:
        json.dump([key], target)
    print("Created private local signing key (not printed; ignored by git).")
