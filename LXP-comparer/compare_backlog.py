#!/usr/bin/env python3
"""
Compares the "ideal" LXP backlog (from xlsx) against actual Jira tickets (from .doc exports)
using Gemini Flash via Vertex AI for semantic matching.

Produces:
  - comparison-report.md  — Full coverage report with per-module stats and mapping table
  - comparison-report.csv — Machine-readable mapping for further analysis

Usage:
    uv run python3 compare_backlog.py
"""

import csv
import json
import time
from pathlib import Path

from google import genai

SCRIPT_DIR = Path(__file__).parent
STORIES_DIR = SCRIPT_DIR / "stories"
LXP_DIR = SCRIPT_DIR / "lxp-backlog"
REPORT_MD = SCRIPT_DIR / "comparison-report.md"
REPORT_CSV = SCRIPT_DIR / "comparison-report.csv"

PROJECT = "g-ai-agent-edu-dev-prj-f184"
LOCATION = "us-central1"
MODEL = "gemini-2.0-flash"

# Rate limiting: Gemini Flash allows 60 RPM on free tier
DELAY_BETWEEN_CALLS = 1.5  # seconds


def load_stories() -> list[dict]:
    """Load all Jira tickets as {key, title, filename, content}."""
    stories = []
    for md_file in sorted(STORIES_DIR.glob("EI-*.md")):
        content = md_file.read_text(encoding="utf-8")
        first_line = content.split("\n")[0]
        # Extract key and title from "# [EI-XXX] Title"
        key = md_file.stem  # e.g. EI-299
        title = first_line.replace(f"# [{key}] ", "").strip()
        stories.append({
            "key": key,
            "title": title,
            "filename": md_file.name,
            "content": content,
        })
    return stories


def load_lxp_items() -> list[dict]:
    """Load all LXP functionalities as {name, module, sub_module, priority, filename, content}."""
    items = []
    for md_file in sorted(LXP_DIR.rglob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        rel_path = md_file.relative_to(LXP_DIR)
        parts = list(rel_path.parts)

        module = parts[0] if len(parts) > 1 else "uncategorized"
        sub_module = parts[1] if len(parts) > 2 else ""
        first_line = content.split("\n")[0]
        name = first_line.lstrip("# ").strip()

        # Extract priority from metadata table
        priority = ""
        for line in content.split("\n"):
            if line.startswith("| Priority"):
                priority = line.split("|")[2].strip()
                break

        items.append({
            "name": name,
            "module": module,
            "sub_module": sub_module,
            "priority": priority,
            "filename": str(rel_path),
            "content": content,
        })
    return items


def build_ticket_index(stories: list[dict]) -> str:
    """Build a compact text index of all Jira tickets for the LLM prompt."""
    lines = []
    for s in stories:
        # Extract status and type from content
        status = ""
        ticket_type = ""
        for line in s["content"].split("\n"):
            if line.startswith("| Status"):
                status = line.split("|")[2].strip()
            elif line.startswith("| Type"):
                ticket_type = line.split("|")[2].strip()
        lines.append(f"- {s['key']}: [{ticket_type}] [{status}] {s['title']}")
    return "\n".join(lines)


def match_functionality(
    client: genai.Client,
    lxp_item: dict,
    ticket_index: str,
) -> dict:
    """Ask Gemini to find Jira tickets that match an LXP functionality."""
    prompt = f"""You are analyzing a software project backlog.

## Task
Given an "ideal" LXP platform functionality description and a list of actual Jira tickets, identify which tickets are related to this functionality.

## LXP Functionality
**Name:** {lxp_item['name']}
**Module:** {lxp_item['module']}
**Priority:** {lxp_item['priority']}

**Description:**
{lxp_item['content']}

## Jira Tickets
{ticket_index}

## Instructions
1. Identify which Jira tickets (by key, e.g. EI-123) relate to this functionality. A ticket relates if it implements, tests, fixes bugs in, or otherwise contributes to this functionality. List only the most relevant tickets (max 20).
2. Rate the overall coverage: "none", "partial", or "full".
3. Briefly explain your assessment (1-2 sentences).

Respond ONLY with valid JSON in this exact format, no markdown fences:
{{"matched_tickets": ["EI-XXX", "EI-YYY"], "coverage": "none|partial|full", "explanation": "Brief explanation"}}
"""

    resp = client.models.generate_content(model=MODEL, contents=prompt)
    text = resp.text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[: text.rfind("```")]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "matched_tickets": [],
            "coverage": "error",
            "explanation": f"Failed to parse LLM response: {text[:200]}",
        }


def generate_report(
    lxp_items: list[dict],
    results: list[dict],
    stories: list[dict],
) -> str:
    """Generate the full Markdown coverage report."""
    total = len(lxp_items)
    full = sum(1 for r in results if r["coverage"] == "full")
    partial = sum(1 for r in results if r["coverage"] == "partial")
    none_ = sum(1 for r in results if r["coverage"] == "none")
    errors = sum(1 for r in results if r["coverage"] == "error")

    # All matched ticket keys
    all_matched = set()
    for r in results:
        all_matched.update(r.get("matched_tickets", []))
    all_story_keys = {s["key"] for s in stories}
    unmatched_tickets = all_story_keys - all_matched

    lines = [
        "# LXP Backlog Coverage Report",
        "",
        "## Summary",
        "",
        f"- **Total LXP functionalities:** {total}",
        f"- **Full coverage:** {full} ({full*100//total}%)",
        f"- **Partial coverage:** {partial} ({partial*100//total}%)",
        f"- **No coverage:** {none_} ({none_*100//total}%)",
        f"- **Errors:** {errors}",
        "",
        f"- **Total Jira tickets:** {len(stories)}",
        f"- **Tickets matched to at least one functionality:** {len(all_matched)}",
        f"- **Unmatched tickets:** {len(unmatched_tickets)}",
        "",
    ]

    # Per-module breakdown
    modules = {}
    for item, result in zip(lxp_items, results):
        mod = item["module"]
        if mod not in modules:
            modules[mod] = {"full": 0, "partial": 0, "none": 0, "error": 0, "total": 0}
        modules[mod]["total"] += 1
        modules[mod][result["coverage"]] += 1

    lines.append("## Coverage by Module")
    lines.append("")
    lines.append("| Module | Total | Full | Partial | None |")
    lines.append("|--------|-------|------|---------|------|")
    for mod, counts in sorted(modules.items()):
        lines.append(
            f"| {mod} | {counts['total']} | {counts['full']} | {counts['partial']} | {counts['none']} |"
        )
    lines.append("")

    # Detailed mapping
    lines.append("## Detailed Mapping")
    lines.append("")
    current_module = ""
    for item, result in zip(lxp_items, results):
        if item["module"] != current_module:
            current_module = item["module"]
            lines.append(f"### {current_module}")
            lines.append("")

        coverage_icon = {
            "full": "[FULL]",
            "partial": "[PARTIAL]",
            "none": "[NONE]",
            "error": "[ERROR]",
        }.get(result["coverage"], "[?]")

        tickets_str = ", ".join(result.get("matched_tickets", [])) or "—"
        lines.append(f"**{coverage_icon} {item['name']}** (Priority: {item['priority']})")
        lines.append(f"- Matched tickets: {tickets_str}")
        lines.append(f"- {result.get('explanation', '')}")
        lines.append("")

    # Unmatched tickets
    if unmatched_tickets:
        lines.append("## Unmatched Jira Tickets")
        lines.append("")
        lines.append("These tickets were not matched to any LXP functionality:")
        lines.append("")
        story_map = {s["key"]: s for s in stories}
        for key in sorted(unmatched_tickets):
            s = story_map.get(key, {})
            lines.append(f"- **{key}**: {s.get('title', 'Unknown')}")
        lines.append("")

    return "\n".join(lines)


def write_csv(
    lxp_items: list[dict],
    results: list[dict],
):
    """Write machine-readable CSV mapping."""
    with open(REPORT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Module", "Sub-Module", "Functionality", "Priority",
            "Coverage", "Matched Tickets", "Explanation",
        ])
        for item, result in zip(lxp_items, results):
            writer.writerow([
                item["module"],
                item["sub_module"],
                item["name"],
                item["priority"],
                result["coverage"],
                "; ".join(result.get("matched_tickets", [])),
                result.get("explanation", ""),
            ])


def main():
    print("Loading data...")
    stories = load_stories()
    lxp_items = load_lxp_items()
    print(f"  {len(stories)} Jira tickets")
    print(f"  {len(lxp_items)} LXP functionalities")

    ticket_index = build_ticket_index(stories)
    print(f"  Ticket index: {len(ticket_index)} chars")

    client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)

    results = []
    print(f"\nComparing {len(lxp_items)} functionalities (using {MODEL})...")
    for i, item in enumerate(lxp_items, 1):
        print(f"  [{i}/{len(lxp_items)}] {item['name'][:60]}...", end=" ", flush=True)
        try:
            result = match_functionality(client, item, ticket_index)
            print(f"→ {result['coverage']} ({len(result.get('matched_tickets', []))} tickets)")
        except Exception as e:
            result = {
                "matched_tickets": [],
                "coverage": "error",
                "explanation": str(e)[:200],
            }
            print(f"→ ERROR: {e}")
        results.append(result)
        time.sleep(DELAY_BETWEEN_CALLS)

    print("\nGenerating reports...")
    report = generate_report(lxp_items, results, stories)
    REPORT_MD.write_text(report, encoding="utf-8")
    print(f"  → {REPORT_MD}")

    write_csv(lxp_items, results)
    print(f"  → {REPORT_CSV}")

    # Print summary
    full = sum(1 for r in results if r["coverage"] == "full")
    partial = sum(1 for r in results if r["coverage"] == "partial")
    none_ = sum(1 for r in results if r["coverage"] == "none")
    print(f"\nDone! Coverage: {full} full, {partial} partial, {none_} none (of {len(lxp_items)} total)")


if __name__ == "__main__":
    main()
