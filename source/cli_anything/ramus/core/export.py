"""Export and import, rendered by Ramus itself.

Images come out of ``com.ramussoft.pb.print.PIDEF0painter``, the painter behind
the Ramus GUI's own image export and printing, so a diagram exported here is the
diagram Ramus draws. PDF wraps that painter in iText, mirroring the bundled
print-to-pdf plugin. IDL uses the engine's own IDEF0 interchange codec.
"""

from __future__ import annotations

import os
from pathlib import Path

from .session import get_session

IMAGE_FORMATS = ("png", "jpg", "bmp", "svg", "emf")
ALL_FORMATS = IMAGE_FORMATS + ("pdf",)

#: Leading bytes that identify each rendered format, used to verify output.
MAGIC = {
    "png": b"\x89PNG\r\n\x1a\n",
    "jpg": b"\xff\xd8\xff",
    "bmp": b"BM",
    "pdf": b"%PDF-",
}


def _read(op: str, **args) -> dict:
    session = get_session()
    session.require_project()
    return session.bridge.call(op, **args)


def formats() -> dict:
    """What this build can render, and with what."""
    return _read("export.formats")


def export_diagram(
    path: str,
    diagram: str | None = None,
    model: str | None = None,
    format: str | None = None,
    width: int | None = None,
    height: int | None = None,
    overwrite: bool = False,
) -> dict:
    """Render one diagram to an image file."""
    resolved = format or Path(path).suffix.lstrip(".").lower() or "png"
    if resolved not in IMAGE_FORMATS:
        raise ValueError(
            f"Unknown image format '{resolved}'. Use one of: {', '.join(IMAGE_FORMATS)}"
            " (PDF has its own command: export pdf)"
        )
    return _read(
        "export.diagram",
        path=str(Path(path).expanduser().absolute()),
        diagram=diagram,
        model=model,
        format=resolved,
        width=width,
        height=height,
        overwrite=overwrite,
    )


def export_all(
    directory: str,
    model: str | None = None,
    format: str = "png",
    width: int | None = None,
    height: int | None = None,
    overwrite: bool = False,
) -> dict:
    """Render every decomposed diagram in a model into a directory."""
    if format not in IMAGE_FORMATS:
        raise ValueError(f"Unknown image format '{format}'. Use one of: {', '.join(IMAGE_FORMATS)}")
    return _read(
        "export.all",
        dir=str(Path(directory).expanduser().absolute()),
        model=model,
        format=format,
        width=width,
        height=height,
        overwrite=overwrite,
    )


def export_pdf(
    path: str,
    model: str | None = None,
    diagram: str | None = None,
    width: int | None = None,
    height: int | None = None,
    overwrite: bool = False,
) -> dict:
    """Render the model to PDF, one page per decomposed diagram."""
    return _read(
        "export.pdf",
        path=str(Path(path).expanduser().absolute()),
        model=model,
        diagram=diagram,
        width=width,
        height=height,
        overwrite=overwrite,
    )


def export_idl(
    path: str,
    model: str | None = None,
    encoding: str = "UTF-8",
    overwrite: bool = False,
) -> dict:
    """Export a model to IDL, the IDEF0 interchange format.

    Ramus's IDL writer has a defect: it crashes on arrows that show a label.
    The CLI turns that crash into a clear message rather than a stack trace,
    but it cannot make the export succeed — the Ramus GUI fails identically.
    """
    return _read(
        "export.idl",
        path=str(Path(path).expanduser().absolute()),
        model=model,
        encoding=encoding,
        overwrite=overwrite,
    )


def import_idl(path: str, name: str | None = None, encoding: str = "cp1251") -> dict:
    """Import an IDL file as a new model in the open project."""
    session = get_session()
    session.require_project()
    session.snapshot()
    result = session.bridge.call(
        "import.idl",
        path=str(Path(path).expanduser().absolute()),
        name=name,
        encoding=encoding,
    )
    session.mark_modified()
    return result


def verify_output(path: str, format: str | None = None) -> dict:
    """Check a rendered file really is what it claims to be.

    Exit status alone does not prove a render worked, so callers and tests use
    this: the file must exist, be non-trivial in size, and start with the right
    bytes (or, for the text formats, the right root element).
    """
    file = Path(path)
    resolved = (format or file.suffix.lstrip(".")).lower()
    if resolved == "jpeg":
        resolved = "jpg"
    result = {
        "path": str(file),
        "format": resolved,
        "exists": file.is_file(),
        "size": file.stat().st_size if file.is_file() else 0,
        "valid": False,
        "detail": "",
    }
    if not result["exists"]:
        result["detail"] = "file does not exist"
        return result
    if result["size"] == 0:
        result["detail"] = "file is empty"
        return result

    with open(file, "rb") as handle:
        head = handle.read(2048)

    expected = MAGIC.get(resolved)
    if expected is not None:
        result["valid"] = head.startswith(expected)
        result["detail"] = (
            "magic bytes match" if result["valid"] else f"expected {expected!r} at offset 0"
        )
    elif resolved == "svg":
        text = head.decode("utf-8", "replace")
        result["valid"] = "<svg" in text
        result["detail"] = "contains an <svg> root" if result["valid"] else "no <svg> element found"
    elif resolved == "emf":
        # EMF records start with EMR_HEADER (type 1) and the ' EMF' signature.
        result["valid"] = head[:4] == b"\x01\x00\x00\x00" and head[40:44] == b" EMF"
        result["detail"] = "EMF header found" if result["valid"] else "no EMF signature"
    elif resolved == "idl":
        text = head.decode("utf-8", "replace")
        result["valid"] = "IDL VERSION" in text
        result["detail"] = "IDL header found" if result["valid"] else "no IDL header"
    elif resolved == "rsf":
        result["valid"] = head.startswith(b"PK\x03\x04")
        result["detail"] = "ZIP header found" if result["valid"] else "not a ZIP archive"
    else:
        result["detail"] = f"no verification rule for '{resolved}'"
    return result


def human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size} B"


def ensure_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
