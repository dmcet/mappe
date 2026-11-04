"""Render the export report, and pack it with the application documents into a ZIP.

The report is compiled by Typst (``typst/export.typ``) in the Mappe look. It is the internal
document (list, assessments, reviews); the tailored CVs and cover letters are the
deliverables and stay separate files, exactly as delivered. The report's buttons to them are
written as ``mappe://doc/<run>/<kind>`` links and turned into links to the file next to the
report here (``GoToR``, opened by desktop PDF viewers).
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from mappe.export.data import DOC_SCHEME, Document
from mappe.render.typst import render


class ExportError(RuntimeError):
    pass


def render_report(data: dict[str, Any]) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.pdf"
        result = render("export", data, out, app_fonts=True)
        if not result.ok:
            raise ExportError(f"Rendering the export failed: {result.error}")
        return out.read_bytes()


def _file_action(path: str) -> DictionaryObject:
    """Open the first page of ``path`` (relative to the report)."""
    spec = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Filespec"),
            NameObject("/F"): TextStringObject(path),
            NameObject("/UF"): TextStringObject(path),
        }
    )
    return DictionaryObject(
        {
            NameObject("/S"): NameObject("/GoToR"),
            NameObject("/F"): spec,
            NameObject("/D"): ArrayObject([NumberObject(0), NameObject("/Fit")]),
            NameObject("/NewWindow"): BooleanObject(True),
        }
    )


def link_files(pdf: bytes, files: dict[str, str]) -> bytes:
    """Point the report's ``mappe://doc/...`` links at the files they stand for."""
    writer = PdfWriter(clone_from=io.BytesIO(pdf))
    for page in writer.pages:
        for ref in page.get("/Annots", []):
            annot = ref.get_object()
            action = annot.get("/A")
            if action is None:
                continue
            uri = str(action.get_object().get("/URI", ""))
            if uri.startswith(DOC_SCHEME) and uri in files:
                annot[NameObject("/A")] = _file_action(files[uri])
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def build_zip(data: dict[str, Any], report_name: str, documents: list[Document]) -> bytes:
    """The report at the top of the archive, the documents at their ``file`` paths."""
    report = link_files(render_report(data), {d.link: d.file for d in documents})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(report_name, report)
        for doc in documents:
            z.write(doc.path, doc.file)
    return buffer.getvalue()
