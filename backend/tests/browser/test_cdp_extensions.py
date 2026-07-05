"""P0-5: extension flag building, CRX unpacking, and (critically) graceful degradation when the
download fails — a run must still start with no extensions rather than crash. No network here: the
downloader is injected."""
import io
import os
import zipfile

from app.browser.cdp.extensions import ensure_extensions, extension_args, unpack_crx


def _fake_crx3(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    zip_bytes = buf.getvalue()
    header = b""  # a valid-enough empty CRX3 header for our offset logic
    return b"Cr24" + (3).to_bytes(4, "little") + len(header).to_bytes(4, "little") + header + zip_bytes


def test_extension_args_empty_is_no_flags():
    assert extension_args([]) == []


def test_extension_args_builds_both_flags():
    args = extension_args(["/e/a", "/e/b"])
    assert "--disable-extensions-except=/e/a,/e/b" in args
    assert "--load-extension=/e/a,/e/b" in args


def test_unpack_crx3_extracts_the_embedded_zip(tmp_path):
    crx = _fake_crx3({"manifest.json": '{"name":"x"}'})
    dest = unpack_crx(crx, str(tmp_path / "ext"))
    assert os.path.exists(os.path.join(dest, "manifest.json"))


async def test_ensure_extensions_unpacks_via_injected_download(tmp_path):
    async def fake_download(ext_id):
        return _fake_crx3({"manifest.json": f'{{"id":"{ext_id}"}}'})

    dirs = await ensure_extensions(str(tmp_path), ids=["extone"], download=fake_download)
    assert len(dirs) == 1 and os.path.exists(os.path.join(dirs[0], "manifest.json"))


async def test_ensure_extensions_degrades_to_empty_on_download_failure(tmp_path):
    async def failing_download(ext_id):
        raise RuntimeError("offline")

    dirs = await ensure_extensions(str(tmp_path), ids=["a", "b"], download=failing_download)
    assert dirs == []  # never raises; run still starts with no extensions
