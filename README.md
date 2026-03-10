# Transform Book: Early Childhood Education

Extracts and structures the MINEDUCYT **"Programas de Desarrollo y Aprendizaje — Inicial Lactantes e Inicial 1"** PDF (96 pages) into modifiable, chapter-organized Markdown files.

## Source

[02 Inicial Lactantes e Inicial 1_Web.pdf](https://www.mined.gob.sv/materiales/pi/02%20Inicial%20Lactantes%20e%20Inicial%201_Web.pdf) — Ministerio de Educaci&oacute;n, Ciencia y Tecnolog&iacute;a, El Salvador, 2026.

## Usage

```bash
# Download the source PDF
curl -o "02 Inicial Lactantes e Inicial 1_Web.pdf" \
  "https://www.mined.gob.sv/materiales/pi/02%20Inicial%20Lactantes%20e%20Inicial%201_Web.pdf"

# Install dependencies and run
uv run python3 extract.py
```

Output is written to `./output/` as Markdown files organized by chapter, with an `INDEX.md` linking them all.

## What the script handles

- **Direct text extraction** from embedded text (no OCR needed)
- **Two-column descriptor pages** — rotated decorative text ("Inicial lactantes" / "Inicial 1" curved labels) is filtered out
- **Sub-column descriptor cells** — 3 side-by-side progression descriptors are grouped into structured bullet lists
- **Tables** — education levels (page 16), curriculum areas (page 26), routine schedules (pages 84-85)
- **N&uacute;cleo pedag&oacute;gico labels** — extracted from the circular label box and rendered as `###` headings
- **Row-paired output** — each process pairs Inicial lactantes and Inicial 1 together, matching the book's visual layout

## Output structure

```
output/
  INDEX.md
  00_portada_y_presentacion.md
  01_introduccion.md
  02_finalidad_de_los_programas.md
  03_quienes_son_los_ninos_de_inicial_lactantes_e_inicial_1.md
  04_programas_para_las_secciones_de_inicial_lactantes_e_inicial_.md
  05_orientaciones_para_la_implementacion_de_las_estrategias_peda.md
  06_orientaciones_para_el_diseno_de_ambientes.md
  07_orientaciones_para_la_organizacion_de_la_rutina.md
  08_orientaciones_para_la_planificacion_docente.md
  09_orientaciones_para_la_evaluacion_y_el_seguimiento.md
  10_bibliografia.md
```

Chapter 04 (the largest, ~100KB) contains all 15 N&uacute;cleos Pedag&oacute;gicos across 5 &Aacute;mbitos de Experiencia, with their development processes and progression descriptors structured as:

```markdown
### N&uacute;cleo pedag&oacute;gico: Identidad y autonom&iacute;a

**Inicial lactantes**

Proceso de desarrollo y aprendizaje: Reconocerse como una persona diferente a...

Descriptores de progresi&oacute;n:
- Atiende cuando lo llaman por su nombre.
- Reconoce su imagen en el espejo...
- Expresa preferencia por algunos de sus juguetes...

**Inicial 1**

Proceso de desarrollo y aprendizaje: Manifestar progresivamente el reconocimiento de...

Descriptores de progresi&oacute;n:
- Identifica sus juguetes y elementos...
- Hace uso de expresiones como "yo", "mi" y "m&iacute;o"...
- Reconoce a las personas que integran su grupo familiar...
```
