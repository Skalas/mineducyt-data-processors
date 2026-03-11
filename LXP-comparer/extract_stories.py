#!/usr/bin/env python3
"""
Extracts individual user stories/tickets from Jira-exported .doc files (HTML format)
and saves each one as a separate Markdown file.

Usage:
    python3 extract_stories.py

Output:
    stories/EI-XXX.md  (one file per ticket)
"""

import os
import re
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "stories"

DOC_FILES = [
    SCRIPT_DIR / "Backlog IHFB - Bugs and Defects.doc",
    SCRIPT_DIR / "Backlog IHFB - Otros Tickets.doc",
]

# Matches lines like: [EI-299] Some title Created: 05/Mar/26  Updated: 10/Mar/26
TICKET_HEADER_RE = re.compile(r"^\s*\[EI-(\d+)\]\s+(.+?)\s+Created:\s+(.+)")

# Matches metadata fields like "Status:\nDone" or "Type:\nBug"
FIELD_RE = re.compile(
    r"^(Status|Project|Components|Affects versions|Fix versions|Parent|Type|Priority|"
    r"Reporter|Assignee|Resolution|Votes|Labels|Remaining Estimate|Time Spent|"
    r"Original estimate|Epic Link|Sprint|QA Assignee|Start Date|Due Date|"
    r"Σ Remaining Estimate|Σ Time Spent|Σ Original Estimate|Issue links|"
    r"Sub-tasks|Attachments|Priority):$",
    re.MULTILINE,
)


def doc_to_text(doc_path: Path) -> str:
    """Convert a .doc file to plain text using macOS textutil."""
    result = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", str(doc_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def parse_metadata(block: str) -> dict:
    """Extract key metadata fields from the raw text block."""
    metadata = {}
    fields_of_interest = [
        "Status", "Type", "Priority", "Reporter", "Assignee",
        "Resolution", "Sprint", "Parent", "Epic Link",
    ]
    for field in fields_of_interest:
        pattern = re.compile(rf"^{re.escape(field)}:\n(.+)$", re.MULTILINE)
        match = pattern.search(block)
        if match:
            metadata[field] = match.group(1).strip()
    return metadata


def parse_dates(header_line: str) -> dict:
    """Extract Created/Updated/Resolved/Due dates from the header line."""
    dates = {}
    for label in ["Created", "Updated", "Resolved", "Due"]:
        match = re.search(rf"{label}:\s+([\d{{2}}/\w{{3}}/\d{{2}}]+)", header_line)
        if match:
            dates[label] = match.group(1)
    return dates


def extract_section(text: str, section_name: str) -> str:
    """Extract content between ' Section ' markers."""
    pattern = re.compile(
        rf"^\s*{re.escape(section_name)}\s*$\n(.*?)(?=^\s*(?:Comments|Sub-tasks|Attachments)\s*$|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    return ""


def extract_description(text: str) -> str:
    """Extract the Description section."""
    marker = " Description \n"
    idx = text.find(marker)
    if idx == -1:
        marker = " Description\n"
        idx = text.find(marker)
    if idx == -1:
        return ""

    start = idx + len(marker)
    # Description ends at " Comments " or end of text
    end_markers = ["\n Comments \n", "\n Comments\n"]
    end = len(text)
    for em in end_markers:
        pos = text.find(em, start)
        if pos != -1:
            end = min(end, pos)
    return text[start:end].strip()


def extract_comments(text: str) -> list[dict]:
    """Extract comments as a list of {author, date, body}."""
    marker = " Comments \n"
    idx = text.find(marker)
    if idx == -1:
        marker = " Comments\n"
        idx = text.find(marker)
    if idx == -1:
        return []

    comments_text = text[idx + len(marker):]
    # Pattern: Comment by Author Name [ DD/Mon/YY ]
    comment_re = re.compile(
        r"Comment by (.+?)\s*\[\s*(\d{2}/\w{3}/\d{2})\s*\]"
    )
    parts = comment_re.split(comments_text)
    # parts: [preamble, author1, date1, body1, author2, date2, body2, ...]
    comments = []
    for i in range(1, len(parts) - 2, 3):
        author = parts[i].strip()
        date = parts[i + 1].strip()
        body = parts[i + 2].strip()
        comments.append({"author": author, "date": date, "body": body})
    return comments


def split_tickets(text: str) -> list[tuple[str, str, str]]:
    """Split text into individual tickets. Returns list of (key, title, raw_block)."""
    lines = text.split("\n")
    tickets = []
    current_key = None
    current_title = None
    current_lines = []

    for line in lines:
        match = TICKET_HEADER_RE.match(line)
        if match:
            if current_key is not None:
                tickets.append((current_key, current_title, "\n".join(current_lines)))
            current_key = f"EI-{match.group(1)}"
            current_title = match.group(2).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_key is not None:
        tickets.append((current_key, current_title, "\n".join(current_lines)))

    return tickets


def ticket_to_markdown(key: str, title: str, raw_block: str) -> str:
    """Convert a raw ticket block into a clean Markdown document."""
    metadata = parse_metadata(raw_block)
    header_match = TICKET_HEADER_RE.match(raw_block.split("\n")[0])
    dates = parse_dates(raw_block.split("\n")[0]) if header_match else {}
    description = extract_description(raw_block)
    comments = extract_comments(raw_block)

    lines = [f"# [{key}] {title}", ""]

    # Metadata table
    meta_fields = [
        ("Status", metadata.get("Status")),
        ("Type", metadata.get("Type")),
        ("Priority", metadata.get("Priority")),
        ("Reporter", metadata.get("Reporter")),
        ("Assignee", metadata.get("Assignee")),
        ("Resolution", metadata.get("Resolution")),
        ("Sprint", metadata.get("Sprint")),
        ("Parent", metadata.get("Parent")),
        ("Epic Link", metadata.get("Epic Link")),
        ("Created", dates.get("Created")),
        ("Updated", dates.get("Updated")),
        ("Resolved", dates.get("Resolved")),
        ("Due", dates.get("Due")),
    ]
    active_fields = [(k, v) for k, v in meta_fields if v]
    if active_fields:
        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        for field, value in active_fields:
            lines.append(f"| {field} | {value} |")
        lines.append("")

    # Description
    if description:
        lines.append("## Description")
        lines.append("")
        lines.append(description)
        lines.append("")

    # Comments
    if comments:
        lines.append("## Comments")
        lines.append("")
        for c in comments:
            lines.append(f"**{c['author']}** ({c['date']}):")
            lines.append("")
            lines.append(c["body"])
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    seen_keys = set()
    total = 0

    for doc_file in DOC_FILES:
        if not doc_file.exists():
            print(f"Warning: {doc_file.name} not found, skipping.")
            continue

        print(f"Processing: {doc_file.name}")
        text = doc_to_text(doc_file)
        tickets = split_tickets(text)
        print(f"  Found {len(tickets)} tickets")

        for key, title, raw_block in tickets:
            if key in seen_keys:
                print(f"  Skipping duplicate: {key}")
                continue
            seen_keys.add(key)

            md_content = ticket_to_markdown(key, title, raw_block)
            output_path = OUTPUT_DIR / f"{key}.md"
            output_path.write_text(md_content, encoding="utf-8")
            total += 1

    print(f"\nDone! Extracted {total} unique tickets to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
