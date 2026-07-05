"""P0-5: auto-load reliability extensions (uBlock Origin Lite + a cookie-banner killer) at launch.

Under raw CDP this is just two launch flags. We fetch each extension's CRX from the Chrome Web Store
update endpoint, unpack it once into a cache dir, and pass --load-extension. Entirely best-effort: any
failure (offline, blocked, bad CRX) skips that extension and logs — a run must never fail to start
because an ad-blocker couldn't be downloaded.
"""
from __future__ import annotations

import io
import logging
import os
import zipfile

import httpx

logger = logging.getLogger(__name__)

_CRX_MAGIC = b"Cr24"

# Chrome Web Store extension IDs (MV3).
UBLOCK_LITE = "ddkjiahejlhfcafbddmgiahcphecmpfh"      # uBlock Origin Lite — ad/tracker blocking
COOKIE_KILLER = "edibdbjcniadpccecjdfdjjppcpchdlm"    # "I still don't care about cookies"
DEFAULT_EXTENSION_IDS = [UBLOCK_LITE, COOKIE_KILLER]

_CWS_URL = (
    "https://clients2.google.com/service/update2/crx?response=redirect"
    "&acceptformat=crx2,crx3&prodversion=120.0&x=id%3D{id}%26installsource%3Dondemand%26uc"
)


def extension_args(dirs: list[str]) -> list[str]:
    """The Chrome flags to load the given unpacked extension dirs (empty list → no flags)."""
    if not dirs:
        return []
    joined = ",".join(dirs)
    return [f"--disable-extensions-except={joined}", f"--load-extension={joined}"]


def unpack_crx(crx: bytes, dest: str) -> str:
    """Extract the ZIP embedded in a CRX (v2/v3) — or a bare ZIP — into `dest`."""
    if crx[:4] != _CRX_MAGIC:
        zip_bytes = crx  # some mirrors serve a plain zip
    else:
        version = int.from_bytes(crx[4:8], "little")
        if version == 3:
            header_len = int.from_bytes(crx[8:12], "little")
            zip_bytes = crx[12 + header_len:]
        else:  # crx2: magic, version, pubkey_len, sig_len, then pubkey+sig, then zip
            pubkey_len = int.from_bytes(crx[8:12], "little")
            sig_len = int.from_bytes(crx[12:16], "little")
            zip_bytes = crx[16 + pubkey_len + sig_len:]
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        z.extractall(dest)
    return dest


async def _download(ext_id: str) -> bytes:
    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
        resp = await client.get(_CWS_URL.format(id=ext_id))
        resp.raise_for_status()
        return resp.content


async def ensure_extensions(cache_dir: str, ids: list[str] | None = None, *, download=_download) -> list[str]:
    """Ensure each extension is unpacked under cache_dir/<id>, returning the ready dirs.

    Best-effort per extension: a failure is logged and skipped, never raised. `download` is injectable
    so the unpack/degradation logic is testable without the network.
    """
    dirs: list[str] = []
    for ext_id in ids or DEFAULT_EXTENSION_IDS:
        dest = os.path.join(cache_dir, ext_id)
        manifest = os.path.join(dest, "manifest.json")
        try:
            if not os.path.exists(manifest):
                unpack_crx(await download(ext_id), dest)
            if os.path.exists(manifest):
                dirs.append(dest)
        except Exception as exc:  # offline, blocked, bad CRX — skip this one
            logger.warning("extension %s unavailable, skipping: %s", ext_id, exc)
    return dirs
