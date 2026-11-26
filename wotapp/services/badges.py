import os
import re
import secrets
import tempfile

import badgesModifier.modifier as modifier

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_FILES = 3
ALLOWED_EXTENSIONS = {".dds", ".xml"}
DOWNLOAD_TYPES = {"dds", "xml"}
_OUTPUT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_NANO_ALPHABET = "useandom-26T198340PX75pxJACKVERYMINDBUSHWOLF_GQZbfghjklqvwyzrict"


class PayloadTooLarge(Exception):
    pass


def extension_of(filename: str | None) -> str:
    return os.path.splitext(filename or "")[1].lower()


def intake_error(entries: list[tuple[str, str | None]]) -> str | None:
    if len(entries) > MAX_FILES:
        return "Reach files limit"
    for _field, filename in entries:
        if extension_of(filename) not in ALLOWED_EXTENSIONS:
            return "Invalid filename"
    return None


def new_output_name() -> str:
    return "".join(secrets.choice(_NANO_ALPHABET) for _ in range(21))


async def read_upload(upload) -> bytes:
    chunks = []
    total = 0
    while True:
        block = await upload.read(1024 * 1024)
        if not block:
            break
        total += len(block)
        if total > MAX_FILE_BYTES:
            raise PayloadTooLarge()
        chunks.append(block)
    return b"".join(chunks)


def run_modifier(dds_name: str, dds_bytes: bytes, xml_name: str, xml_bytes: bytes) -> str:
    output_name = new_output_name()
    with tempfile.TemporaryDirectory() as tmp:
        dds_path = os.path.join(tmp, os.path.basename(dds_name) or "upload.dds")
        xml_path = os.path.join(tmp, os.path.basename(xml_name) or "upload.xml")
        with open(dds_path, "wb") as handle:
            handle.write(dds_bytes)
        with open(xml_path, "wb") as handle:
            handle.write(xml_bytes)
        modifier.main(dds_path, xml_path, output_name)
    return output_name


def download_path(name: str, kind: str):
    if kind not in DOWNLOAD_TYPES or not _OUTPUT_ID.fullmatch(name or ""):
        return None
    path = os.path.join(modifier.OUTPUT_PATH, f"{name}.{kind}")
    if not os.path.isfile(path):
        return None
    return path
