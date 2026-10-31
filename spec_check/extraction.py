"""Use pdfplumber for text and structured tables; never merge PDF pages."""
import io
import re
import pdfplumber

MAX_PAGES = 500


def clean_cell(value):
    return re.sub(r"\s+", " ", value or "").strip().replace("|", "\\|")


def markdown_table(rows):
    rows = [row for row in rows if any(cell for cell in row)]
    if not rows:
        return ""
    width = max(map(len, rows))
    normalized = [[clean_cell(cell) for cell in row] + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(row) + " |" for row in normalized]
    lines.insert(1, "| " + " | ".join(["---"] * width) + " |")
    return "\n".join(lines)


def split_text(text, limit=2400, overlap=350):
    """Line-aware windows with overlap; long single lines are also bounded."""
    text = text.strip()
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start + limit // 2, end)
            if boundary > start:
                end = boundary
        yield text[start:end]
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


def extract_pdf(content: bytes):
    chunks, warnings = [], []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        if not pdf.pages or len(pdf.pages) > MAX_PAGES:
            raise ValueError(f"PDF must have between 1 and {MAX_PAGES} pages.")
        total = len(pdf.pages)
        for number, page in enumerate(pdf.pages, 1):
            # A 3pt default merges words in small-font electrical tables (e.g.
            # 'Supplyvoltage'); a smaller gap threshold preserves actual spaces.
            text = page.extract_text(layout=False, x_tolerance=1) or ""
            if len(text.strip()) < 40:
                warnings.append(f"Page {number}: little extractable text; may need OCR or visual inspection.")
            for part in split_text(text):
                chunks.append({"page": number, "kind": "text", "text": part})
            # Bordered tables are preserved as Markdown. Borderless tables may remain in text.
            try:
                tables = page.extract_tables(table_settings={"text_x_tolerance": 1})
            except Exception:
                tables = []
                warnings.append(f"Page {number}: table extraction failed; inspect the original page.")
            for rows in tables:
                if len(rows) < 2:
                    continue
                # Repeat the header in bounded table groups to retain column meaning.
                group, size = [rows[0]], 0
                for row in rows[1:]:
                    row_size = sum(len(cell or "") for cell in row)
                    if size + row_size > 3000 and len(group) > 1:
                        chunks.append({"page": number, "kind": "table", "text": markdown_table(group)})
                        group, size = [rows[0]], 0
                    group.append(row)
                    size += row_size
                if len(group) > 1:
                    chunks.append({"page": number, "kind": "table", "text": markdown_table(group)})
            page.close()
    if not chunks:
        raise ValueError("No text or tables could be extracted. Scanned PDFs need OCR first.")
    return total, chunks, warnings
