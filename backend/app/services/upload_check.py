"""Checks for uploaded report files: allowed types and a match between the declared type and the first bytes
(does not depend on python-magic)."""
OLE_HEADER = bytes.fromhex("d0cf11e0")  # .doc and .xls
ZIP_HEADER = bytes.fromhex("504b0304")  # .docx and .xlsx
BOM_AND_SPACE = bytes.fromhex("efbbbf20090d0a")  # byte order mark, space, tab, CR, LF

DOCUMENT_MIME_TYPES = {
    "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain", "text/csv", "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def looks_like(content_type: str, head: bytes) -> bool:
    if content_type == "application/pdf":
        return head.lstrip(BOM_AND_SPACE).startswith(b"%PDF")
    if content_type in ("application/msword", "application/vnd.ms-excel"):
        return head.startswith(OLE_HEADER)
    if content_type.startswith("application/vnd.openxmlformats"):
        return head.startswith(ZIP_HEADER)
    return bytes(1) not in head  # text and CSV: no NUL bytes
