"""Load the browser-use BU_Bench_V1 task set (100 hard browser tasks).

The published .enc is Fernet-encrypted with a key derived from the benchmark name — this is
anti-training-contamination obfuscation, not a secret (browser-use's own run_eval.py derives it the
same way). We decrypt in memory only; never write decrypted task text to disk.
Each task: {confirmed_task (the prompt, sometimes with a `website:` URL), category, task_id}.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from cryptography.fernet import Fernet

_ENC = Path(__file__).parent / "BU_Bench_V1.enc"


def load_tasks(name: str = "BU_Bench_V1") -> list[dict]:
    key = base64.urlsafe_b64encode(hashlib.sha256(name.encode()).digest())
    encrypted = base64.b64decode(_ENC.read_text())
    return json.loads(Fernet(key).decrypt(encrypted))
