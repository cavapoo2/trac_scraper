"""
Trac Ticket Change History Scraper
Scrapes a single ticket page and captures the full change history:
  - Field changes  (component, available_date, status, priority, etc.)
  - Comment text   (the free-text comment posted alongside those changes)

Both are captured together as a single "change event" per timestamp/author.

HTML structure Trac renders:
  <div id="changelog">
    <div class="change" id="trac-change-1">
      <h3 class="change">
        <span class="cnum"><a href="#comment:1">comment:1</a></span>
        Changed <a ...>2024-01-15</a> by <span class="trac-author">alice</span>
      </h3>

      <!-- Field changes (may be absent if comment-only) -->
      <ul class="changes">
        <li class="trac-field-component">
          <strong>Component</strong> changed from <em>libavcodec</em> to <em>libavformat</em>
        </li>
        <li class="trac-field-available_date">
          <strong>Available_date</strong> set to <em>2024-02-01</em>
        </li>
      </ul>

      <!-- Comment text (may be absent if field-change-only) -->
      <div class="comment searchable">
        <p>This is the comment body text.</p>
      </div>
    </div>
    ...
  </div>
"""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup, Tag
from playwright.async_api import async_playwright

from symbols import sym


class TracChangeHistoryScraper:
    """
    Scrapes the full change history of a single Trac ticket,
    capturing field changes (component, available_date, etc.)
    AND comment text for every change event.
    """

    def __init__(self, base_url: str, output_dir: str = "trac_history"):
        self.base_url = base_url.rstrip("/")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    # ── HTML parsing ──────────────────────────────────────────────────────────

    def _parse_change_header(self, h3: Tag) -> dict:
        """
        Extract comment number, timestamp and author from an <h3 class="change">.

        Handles two common Trac layouts:
          Layout A: "Changed <a title='...iso...'> by <span class='trac-author'>name"
          Layout B: plain text "Changed 2024-01-15T10:00:00Z by alice"
        """
        result = {"comment_num": None, "timestamp": None, "author": None, "raw": ""}

        result["raw"] = h3.get_text(" ", strip=True)

        # Comment number  e.g. comment:3
        cnum_tag = h3.find("span", class_="cnum") or h3.find("a", href=re.compile(r"#comment:\d+"))
        if cnum_tag:
            m = re.search(r"comment:(\d+)", cnum_tag.get_text())
            if m:
                result["comment_num"] = int(m.group(1))

        # Timestamp — prefer the title attribute on an <a> tag (ISO 8601)
        time_tag = h3.find("a", title=re.compile(r"\d{4}-\d{2}-\d{2}"))
        if time_tag:
            result["timestamp"] = time_tag["title"].strip()
        else:
            # Fall back: find anything that looks like a date/time in the text
            m = re.search(
                r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)",
                result["raw"],
            )
            if m:
                result["timestamp"] = m.group(1)

        # Author — <span class="trac-author"> or text after "by "
        author_tag = h3.find("span", class_=re.compile(r"trac-author"))
        if author_tag:
            result["author"] = author_tag.get_text(strip=True)
        else:
            m = re.search(r"\bby\s+(\S+)", result["raw"])
            if m:
                result["author"] = m.group(1)

        return result

    def _parse_field_changes(self, ul: Tag) -> list[dict]:
        """
        Parse <ul class="changes"> into a list of field-change dicts.

        Each <li> looks like one of:
          <strong>Field</strong> changed from <em>old</em> to <em>new</em>
          <strong>Field</strong> set to <em>value</em>
          <strong>Field</strong> deleted
        """
        changes = []
        for li in ul.find_all("li", recursive=False):
            entry = {"field": None, "action": None, "old_value": None, "new_value": None}

            strong = li.find("strong")
            if strong:
                entry["field"] = strong.get_text(strip=True)

            ems = li.find_all("em")
            li_text = li.get_text(" ", strip=True)

            if "changed from" in li_text and len(ems) >= 2:
                entry["action"] = "changed"
                entry["old_value"] = ems[0].get_text(strip=True)
                entry["new_value"] = ems[1].get_text(strip=True)
            elif "set to" in li_text and ems:
                entry["action"] = "set"
                entry["new_value"] = ems[0].get_text(strip=True)
            elif "deleted" in li_text:
                entry["action"] = "deleted"
                if ems:
                    entry["old_value"] = ems[0].get_text(strip=True)
            elif ems:
                # Generic fallback
                entry["action"] = "modified"
                entry["new_value"] = ems[-1].get_text(strip=True)
                if len(ems) > 1:
                    entry["old_value"] = ems[0].get_text(strip=True)

            if entry["field"]:
                changes.append(entry)

        return changes

    def _parse_comment_text(self, comment_div: Tag) -> str:
        """Extract plain text from <div class="comment searchable">."""
        if not comment_div:
            return ""
        return comment_div.get_text("\n", strip=True)

    def _parse_changelog(self, soup: BeautifulSoup) -> list[dict]:
        """
        Walk every change block in #changelog and return a list of events.

        Each event dict:
          {
            "comment_num": int | None,
            "timestamp":   str | None,
            "author":      str | None,
            "field_changes": [
              {"field": str, "action": str, "old_value": str|None, "new_value": str|None},
              ...
            ],
            "comment": str   # "" when no free-text comment was posted
          }
        """
        events = []

        # Trac wraps the whole history in <div id="changelog"> …
        # Individual change blocks are <div class="change"> children.
        changelog = soup.find(id="changelog") or soup

        # Support both old Trac (<div class="change">) and newer Bootstrap Trac
        # (<li class="… user-comment …"> or <li class="… ticket-state …">)
        change_blocks = changelog.find_all(
            lambda tag: (
                tag.name in ("div", "li")
                and "change" in tag.get("class", [])
                and tag.get("id", "").startswith("trac-change")
            )
        )

        for block in change_blocks:
            event = {
                "comment_num": None,
                "timestamp": None,
                "author": None,
                "field_changes": [],
                "comment": "",
            }

            # ── Header ────────────────────────────────────────────────────
            h3 = block.find("h3", class_="change")
            if h3:
                header = self._parse_change_header(h3)
                event.update(
                    {k: header[k] for k in ("comment_num", "timestamp", "author")}
                )

            # ── Field changes ─────────────────────────────────────────────
            ul = block.find("ul", class_="changes")
            if ul:
                event["field_changes"] = self._parse_field_changes(ul)

            # ── Comment text ──────────────────────────────────────────────
            comment_div = block.find("div", class_=re.compile(r"\bcomment\b"))
            if comment_div:
                event["comment"] = self._parse_comment_text(comment_div)

            # Only add if there's actually something to record
            if event["field_changes"] or event["comment"]:
                events.append(event)

        return events

    # ── Output formatters ─────────────────────────────────────────────────────

    def _to_markdown(self, ticket_id: str, events: list[dict]) -> str:
        """Render change history as a readable Markdown document."""
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"# Change History — Ticket #{ticket_id}",
            f"",
            f"**Source:** {self.base_url}/ticket/{ticket_id}  ",
            f"**Exported:** {now}  ",
            f"**Total change events:** {len(events)}",
            f"",
            "---",
            "",
        ]

        for ev in events:
            cnum = f"comment:{ev['comment_num']}" if ev["comment_num"] else "change"
            ts = ev["timestamp"] or "unknown time"
            author = ev["author"] or "unknown"

            lines.append(f"## [{cnum}] — {ts} by **{author}**")
            lines.append("")

            if ev["field_changes"]:
                lines.append("**Field changes:**")
                lines.append("")
                for fc in ev["field_changes"]:
                    field = fc["field"]
                    action = fc["action"]
                    old = fc["old_value"]
                    new = fc["new_value"]

                    if action == "changed":
                        lines.append(f"- **{field}**: `{old}` → `{new}`")
                    elif action == "set":
                        lines.append(f"- **{field}**: set to `{new}`")
                    elif action == "deleted":
                        lines.append(f"- **{field}**: deleted (was `{old}`)")
                    else:
                        parts = []
                        if old:
                            parts.append(f"was `{old}`")
                        if new:
                            parts.append(f"now `{new}`")
                        lines.append(f"- **{field}**: {', '.join(parts) or action}")
                lines.append("")

            if ev["comment"]:
                lines.append("**Comment:**")
                lines.append("")
                for para in ev["comment"].split("\n"):
                    lines.append(f"> {para}" if para else ">")
                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    def _save(self, ticket_id: str, events: list[dict]):
        """Save JSON and Markdown outputs."""
        stem = f"ticket_{ticket_id}_history"

        json_path = self.output_dir / f"{stem}.json"
        json_path.write_text(
            json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  {sym.tick} JSON:     {json_path}")

        md_path = self.output_dir / f"{stem}.md"
        md_path.write_text(self._to_markdown(ticket_id, events), encoding="utf-8")
        print(f"  {sym.tick} Markdown: {md_path}")

    def _print_summary(self, ticket_id: str, events: list[dict]):
        """Console summary."""
        total_field_changes = sum(len(e["field_changes"]) for e in events)
        total_comments = sum(1 for e in events if e["comment"])
        field_names = sorted(
            {fc["field"] for e in events for fc in e["field_changes"]}
        )

        print(f"\n  {'─'*52}")
        print(f"  {sym.ticket} Ticket #{ticket_id} — Change History")
        print(f"  {'─'*52}")
        print(f"  {sym.info} Change events:   {len(events)}")
        print(f"  {sym.info} Field changes:   {total_field_changes}")
        print(f"  {sym.info} Events w/comment:{total_comments}")
        if field_names:
            print(f"  {sym.info} Fields changed:  {', '.join(field_names)}")
        print(f"  {'─'*52}\n")

        print(f"  {'#':<6} {'Author':<18} {'Fields changed':<30} {'Comment?'}")
        print(f"  {'-'*6} {'-'*18} {'-'*30} {'-'*8}")
        for ev in events:
            cnum = str(ev["comment_num"]) if ev["comment_num"] else "-"
            author = (ev["author"] or "?")[:18]
            fields = ", ".join(fc["field"] for fc in ev["field_changes"])[:30]
            has_comment = sym.tick if ev["comment"] else sym.cross
            print(f"  {cnum:<6} {author:<18} {fields:<30} {has_comment}")

    # ── Main entry point ──────────────────────────────────────────────────────

    async def scrape(self, ticket_id: str | int):
        """Fetch and parse the change history for a single ticket."""
        ticket_id = str(ticket_id)
        url = f"{self.base_url}/ticket/{ticket_id}"

        print(f"\n{sym.rocket} Trac Change History Scraper")
        print(f"{sym.link}  {url}")
        print(f"{sym.folder} Output: {self.output_dir.absolute()}\n")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                extra_http_headers={
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            page = await context.new_page()
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            print(f"{sym.hourglass} Loading ticket page...")
            response = await page.goto(url, wait_until="domcontentloaded", timeout=60000)

            if response.status == 403:
                print(f"{sym.cross} Access denied (403). Try adding authentication.")
                await browser.close()
                return []
            if response.status != 200:
                print(f"{sym.cross} HTTP {response.status} — cannot fetch ticket.")
                await browser.close()
                return []

            # Wait for the changelog to render
            try:
                await page.wait_for_selector("#changelog", timeout=10000)
            except Exception:
                print(f"{sym.warning} #changelog not found — page may have no history yet.")

            html = await page.content()
            await browser.close()

        print(f"{sym.tick} Page loaded. Parsing change history...")
        soup = BeautifulSoup(html, "html.parser")
        events = self._parse_changelog(soup)

        self._print_summary(ticket_id, events)

        print(f"\n{sym.file} Saving output...")
        self._save(ticket_id, events)

        print(f"\n{sym.party} Done!")
        return events


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    # ── Configuration ─────────────────────────────────────────────────────────
    BASE_URL   = "https://trac.ffmpeg.org"
    TICKET_ID  = 1234        # ← change to the ticket you want
    OUTPUT_DIR = "ffmpeg_ticket_history"
    # ─────────────────────────────────────────────────────────────────────────

    scraper = TracChangeHistoryScraper(base_url=BASE_URL, output_dir=OUTPUT_DIR)
    await scraper.scrape(TICKET_ID)


if __name__ == "__main__":
    asyncio.run(main())
