"""
Extract and structure the PDF book into Markdown files organized by chapter.

Handles:
- Regular text pages (pymupdf extraction)
- Table pages (pdfplumber extraction)
- Descriptor pages with two-column layout and rotated decorative text
- Drop cap letters at paragraph starts
"""

import re
from pathlib import Path

import pdfplumber
import pymupdf


PDF_PATH = "02 Inicial Lactantes e Inicial 1_Web.pdf"
OUTPUT_DIR = Path("output")

# Chapter structure derived from the TOC (pages 8-9)
# (chapter_id, title, start_page, end_page) — pages are 1-indexed
CHAPTERS = [
    ("00", "Portada y presentación", 1, 7),
    ("01", "Introducción", 8, 11),
    ("02", "Finalidad de los programas", 12, 17),
    ("03", "¿Quiénes son los niños de Inicial lactantes e Inicial 1?", 18, 21),
    ("04", "Programas para las secciones de Inicial lactantes e Inicial 1", 22, 65),
    ("05", "Orientaciones para la implementación de las estrategias pedagógicas", 66, 75),
    ("06", "Orientaciones para el diseño de ambientes", 76, 79),
    ("07", "Orientaciones para la organización de la rutina", 80, 83),
    ("08", "Orientaciones para la planificación docente", 84, 87),
    ("09", "Orientaciones para la evaluación y el seguimiento", 88, 91),
    ("10", "Bibliografía", 92, 96),
]

# Pages known to have real tables (detected by pdfplumber)
PAGES_WITH_TABLES = {16, 26, 84, 85}
# Note: pages 84-85 have the routine schedule table (MOMENTOS/DESCRIPCIÓN/TIEMPO)

# Pages with two-column descriptor layout (have rotated decorative text)
DESCRIPTOR_PAGES = {
    28, 29, 30, 36, 38, 39, 40, 41, 42,
    46, 47, 48, 49, 50, 54, 55, 60, 61, 62,
}

# Approximate X midpoint separating left/right columns on descriptor pages
COLUMN_SPLIT_X = 400.0


def extract_text_pymupdf(doc: pymupdf.Document, page_num: int) -> str:
    """Extract text from a page using pymupdf (0-indexed)."""
    page = doc[page_num]
    return page.get_text("text")


def extract_horizontal_lines(doc: pymupdf.Document, page_num: int):
    """Extract only horizontal (non-rotated) text lines with their positions.
    Returns list of (x, y, text) tuples."""
    page = doc[page_num]
    blocks = page.get_text("rawdict")["blocks"]
    lines_out = []

    for b in blocks:
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            d = line.get("dir", (1.0, 0.0))
            # Skip rotated text (decorative "Inicial lactantes" / "Inicial 1" labels)
            if abs(d[0] - 1.0) > 0.01 or abs(d[1]) > 0.01:
                continue

            # In rawdict mode, spans have 'chars' not 'text'
            text_parts = []
            for span in line["spans"]:
                if "text" in span:
                    text_parts.append(span["text"])
                elif "chars" in span:
                    text_parts.append("".join(c.get("c", "") for c in span["chars"]))
            text = "".join(text_parts).strip()
            if not text:
                continue

            bbox = line["bbox"]
            x = bbox[0]
            y = bbox[1]
            lines_out.append((x, y, text))

    return lines_out


def extract_descriptor_page(doc: pymupdf.Document, page_num: int) -> str:
    """Extract a two-column descriptor page into structured markdown.

    Each column (Inicial lactantes / Inicial 1) contains blocks of:
    - Núcleo pedagógico name (only on some pages, in a label box)
    - "Proceso de desarrollo y aprendizaje" header
    - Process description text
    - "Descriptor de progresión" header
    - 3 descriptor cells side by side
    """
    lines = extract_horizontal_lines(doc, page_num)
    if not lines:
        return ""

    # Separate into left column (Inicial lactantes) and right column (Inicial 1)
    left_lines = [(x, y, t) for x, y, t in lines if x < COLUMN_SPLIT_X]
    right_lines = [(x, y, t) for x, y, t in lines if x >= COLUMN_SPLIT_X]

    # Extract Núcleo pedagógico labels (far left, x < 90) before column processing
    # The label box sits at x ~50-88, while descriptor sub-columns start at x ~93+
    far_left = [(x, y, t) for x, y, t in left_lines if x < 90]
    left_lines = [(x, y, t) for x, y, t in left_lines if x >= 90]

    def extract_nucleo_labels(far_left_lines):
        """Extract Núcleo pedagógico labels from far-left text.

        Groups lines into label blocks by finding 'Núcleo' or 'pedagógico'
        anchors and collecting nearby lines (within 60px vertically).
        Filters out page numbers and unrelated body text.
        """
        if not far_left_lines:
            return []

        far_left_lines.sort(key=lambda item: item[1])

        # Find anchor lines containing 'Núcleo' (the start of a label block)
        anchors = []
        for x, y, t in far_left_lines:
            if "úcleo" in t:
                anchors.append(y)

        if not anchors:
            return []

        # Group lines near each anchor (within 60px below the anchor)
        labels = []
        for anchor_y in anchors:
            group = []
            for x, y, t in far_left_lines:
                if t.strip().isdigit():
                    continue
                if anchor_y - 5 <= y <= anchor_y + 60:
                    group.append((x, y, t))
            if group:
                group.sort(key=lambda item: item[1])
                label = " ".join(t for _, _, t in group).strip()
                labels.append(label)

        return labels

    def parse_column_blocks(column_lines):
        """Parse a column into a list of structured blocks.

        Each block is a dict with:
        - proceso: str (the process description text)
        - descriptores: list[str] (the 3 descriptor texts)

        Handles descriptor sub-columns by tracking X-position clusters.
        """
        if not column_lines:
            return []

        # Group lines by Y-band (within 8px tolerance)
        y_bands = []
        column_lines.sort(key=lambda item: (item[1], item[0]))
        for x, y, text in column_lines:
            placed = False
            for band in y_bands:
                if abs(band[0][1] - y) < 8:
                    band.append((x, y, text))
                    placed = True
                    break
            if not placed:
                y_bands.append([(x, y, text)])

        y_bands.sort(key=lambda band: band[0][1])

        # Flatten into a sequence of text elements, collecting descriptors
        elements = []  # list of ("text", str) or ("descriptors", [str, str, str])
        i = 0
        while i < len(y_bands):
            band = y_bands[i]
            band.sort(key=lambda item: item[0])

            if len(band) >= 3:
                # Descriptor cells: establish X-position clusters
                cluster_centers = [item[0] for item in band]
                n_clusters = len(cluster_centers)
                cells = [[] for _ in range(n_clusters)]

                for idx, (_, _, t) in enumerate(band):
                    cells[idx].append(t)
                i += 1

                while i < len(y_bands):
                    cur_band = y_bands[i]
                    cur_band.sort(key=lambda item: item[0])
                    cur_y = cur_band[0][1]
                    prev_y = y_bands[i - 1][0][1]

                    if cur_y - prev_y > 25:
                        break

                    if len(cur_band) == 1:
                        text = cur_band[0][2]
                        if any(h in text.lower() for h in [
                            "proceso de desarrollo", "descriptor de progresión",
                            "núcleo", "pedagógico",
                        ]):
                            break
                        x = cur_band[0][0]
                        nearest_idx = min(
                            range(n_clusters),
                            key=lambda ci: abs(cluster_centers[ci] - x),
                        )
                        if abs(cluster_centers[nearest_idx] - x) < 40:
                            cells[nearest_idx].append(text)
                            i += 1
                            continue
                        break

                    for x, _, t in cur_band:
                        nearest_idx = min(
                            range(n_clusters),
                            key=lambda ci: abs(cluster_centers[ci] - x),
                        )
                        cells[nearest_idx].append(t)
                    i += 1

                cell_texts = [" ".join(c) for c in cells if c]
                # Clean trailing page numbers from descriptor text
                cell_texts = [re.sub(r"\s+\d{1,2}$", "", ct) for ct in cell_texts]
                elements.append(("descriptors", cell_texts))
            else:
                texts = [t for _, _, t in band]
                line_text = " ".join(texts)
                # Filter standalone page numbers
                if not line_text.strip().isdigit():
                    elements.append(("text", line_text))
                i += 1

        # Now group elements into blocks: each block starts at "Proceso de desarrollo"
        blocks = []
        current_block = {"proceso": [], "descriptores": []}

        for kind, content in elements:
            if kind == "text":
                text = content
                if "proceso de desarrollo" in text.lower():
                    # If current block has content, save it
                    if current_block["proceso"] or current_block["descriptores"]:
                        blocks.append(current_block)
                        current_block = {"proceso": [], "descriptores": []}
                    # Skip the header text itself
                    continue
                if "descriptor de progresión" in text.lower():
                    continue
                if "y aprendizaje" == text.lower().strip():
                    continue
                current_block["proceso"].append(text)
            elif kind == "descriptors":
                current_block["descriptores"] = content

        # Don't forget the last block
        if current_block["proceso"] or current_block["descriptores"]:
            blocks.append(current_block)

        return blocks

    left_blocks = parse_column_blocks(left_lines)
    right_blocks = parse_column_blocks(right_lines)
    nucleo_labels = extract_nucleo_labels(far_left)

    # Build output: pair left and right blocks into rows
    parts = []
    for label in nucleo_labels:
        parts.append(f"### {label}\n")

    n_rows = max(len(left_blocks), len(right_blocks))
    for row_idx in range(n_rows):
        left = left_blocks[row_idx] if row_idx < len(left_blocks) else None
        right = right_blocks[row_idx] if row_idx < len(right_blocks) else None

        if left and left["proceso"]:
            parts.append("**Inicial lactantes**\n")
            parts.append(f"Proceso de desarrollo y aprendizaje: {' '.join(left['proceso'])}\n")
            if left["descriptores"]:
                parts.append("Descriptores de progresión:")
                for d in left["descriptores"]:
                    parts.append(f"- {d}")
                parts.append("")

        if right and right["proceso"]:
            parts.append("**Inicial 1**\n")
            parts.append(f"Proceso de desarrollo y aprendizaje: {' '.join(right['proceso'])}\n")
            if right["descriptores"]:
                parts.append("Descriptores de progresión:")
                for d in right["descriptores"]:
                    parts.append(f"- {d}")
                parts.append("")

        if row_idx < n_rows - 1:
            parts.append("---\n")

    return "\n".join(parts)


def extract_tables_pdfplumber(pdf: pdfplumber.PDF, page_num: int) -> list[list[list[str]]]:
    """Extract tables from a page using pdfplumber (0-indexed).
    Only returns tables with more than 1 row (filters out false positives)."""
    page = pdf.pages[page_num]
    tables = page.extract_tables()
    return [t for t in tables if len(t) > 1]


def table_to_markdown(table: list[list[str]]) -> str:
    """Convert a table (list of rows) to Markdown table format."""
    if not table:
        return ""

    def clean_cell(cell: str | None) -> str:
        if not cell:
            return ""
        return cell.replace("\n", " ").strip()

    rows = [[clean_cell(c) for c in row] for row in table]
    col_count = max(len(r) for r in rows)
    rows = [r + [""] * (col_count - len(r)) for r in rows]

    lines = []
    lines.append("| " + " | ".join(rows[0]) + " |")
    lines.append("| " + " | ".join(["---"] * col_count) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def clean_text(text: str) -> str:
    """Clean extracted text: fix spacing, remove page numbers, drop caps, normalize."""
    # Remove isolated page numbers (standalone numbers on a line)
    text = re.sub(r"^\d{1,2}\s*$", "", text, flags=re.MULTILINE)
    # Fix drop cap letters: a single letter on its own line followed by text starting lowercase
    # e.g. "L\nos Programas" -> "Los Programas"
    text = re.sub(r"^([A-ZÁÉÍÓÚÑ])\n([a-záéíóúñ])", r"\1\2", text, flags=re.MULTILINE)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_chapter(
    doc: pymupdf.Document,
    pdf: pdfplumber.PDF,
    start_page: int,
    end_page: int,
) -> str:
    """Extract all content from a range of pages (1-indexed)."""
    parts = []

    for page_num in range(start_page, end_page + 1):
        idx = page_num - 1  # 0-indexed

        # Descriptor pages get special two-column extraction
        if page_num in DESCRIPTOR_PAGES:
            page_text = extract_descriptor_page(doc, idx)
            if page_text.strip():
                parts.append(f"<!-- Página {page_num} -->")
                parts.append(page_text)
                parts.append("")
            continue

        page_text = extract_text_pymupdf(doc, idx)
        page_text = clean_text(page_text)

        if not page_text and page_num not in PAGES_WITH_TABLES:
            continue

        parts.append(f"<!-- Página {page_num} -->")

        if page_num in PAGES_WITH_TABLES:
            tables = extract_tables_pdfplumber(pdf, idx)
            if tables:
                if page_text:
                    parts.append(page_text)
                for table in tables:
                    parts.append("")
                    parts.append(table_to_markdown(table))
                    parts.append("")
            else:
                if page_text:
                    parts.append(page_text)
        else:
            if page_text:
                parts.append(page_text)

        parts.append("")

    return "\n".join(parts)


def sanitize_filename(name: str) -> str:
    """Convert a title to a safe filename."""
    name = name.lower()
    name = re.sub(r"[¿?¡!]", "", name)
    name = name.replace(" ", "_")
    replacements = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "ñ": "n", "ü": "u",
    }
    for k, v in replacements.items():
        name = name.replace(k, v)
    name = re.sub(r"[^a-z0-9_]", "", name)
    return name[:60]


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    doc = pymupdf.open(PDF_PATH)
    pdf = pdfplumber.open(PDF_PATH)

    print(f"PDF loaded: {len(doc)} pages")

    for chapter_id, title, start, end in CHAPTERS:
        filename = f"{chapter_id}_{sanitize_filename(title)}.md"
        filepath = OUTPUT_DIR / filename

        content = extract_chapter(doc, pdf, start, end)

        md = f"# {title}\n\n{content}\n"
        filepath.write_text(md, encoding="utf-8")
        print(f"  {filename} (pages {start}-{end})")

    doc.close()
    pdf.close()

    # Create an index file
    index_lines = ["# Programas de Desarrollo y Aprendizaje — Inicial Lactantes e Inicial 1\n"]
    for chapter_id, title, start, end in CHAPTERS:
        filename = f"{chapter_id}_{sanitize_filename(title)}.md"
        index_lines.append(f"- [{chapter_id}. {title}]({filename})")
    index_lines.append("")
    (OUTPUT_DIR / "INDEX.md").write_text("\n".join(index_lines), encoding="utf-8")
    print("  INDEX.md")

    print("\nDone! Output in ./output/")


if __name__ == "__main__":
    main()
