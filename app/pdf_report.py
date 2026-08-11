"""Small dependency-free PDF renderer for immutable Max report snapshots."""

from __future__ import annotations

from html.parser import HTMLParser
import re


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)


def _report_lines(title: str, html_content: str) -> list[str]:
    parser = _TextExtractor()
    parser.feed(html_content)
    raw = [title, "", *parser.parts]
    lines: list[str] = []
    for value in raw:
        if not value:
            lines.append("")
            continue
        lines.extend(value[index : index + 92] for index in range(0, len(value), 92))
    return lines or [title]


def _pdf_text(value: str) -> bytes:
    value = re.sub(r"[^\x20-\x7e]", "?", value)
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1")


def render_pdf(title: str, html_content: str) -> bytes:
    """Render readable text into a valid multi-page PDF without external binaries."""
    lines = _report_lines(title, html_content)
    pages = [lines[index : index + 46] for index in range(0, len(lines), 46)] or [[]]
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    page_ids = [4 + index * 2 for index in range(len(pages))]
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page_index, page_lines in enumerate(pages):
        page_id = 4 + page_index * 2
        content_id = page_id + 1
        commands = ["BT", "/F1 10 Tf", "54 748 Td", "14 TL"]
        for line in page_lines:
            commands.append(f"({_pdf_text(line).decode('latin-1')}) Tj")
            commands.append("T*")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, value in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode())
        output.extend(value)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(output)
