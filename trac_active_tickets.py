"""
Trac Active Ticket Scraper
Fetches all active tickets excluding rejected ones.
Uses Trac's built-in CSV export for reliable data extraction,
with Playwright to handle any bot-detection/auth issues.
"""

import asyncio
import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright


class TracTicketScraper:
    def __init__(self, base_url, output_dir="trac_tickets"):
        """
        Args:
            base_url: Base URL of the Trac instance e.g. "https://trac.ffmpeg.org"
            output_dir: Directory to save output files
        """
        self.base_url = base_url.rstrip('/')
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def _build_query_url(self, fmt="csv", max_tickets=0):
        """
        Build the Trac query URL for active tickets excluding rejected.

        Trac standard active statuses: new, assigned, reopened, accepted
        We also exclude resolution=rejected and resolution=wontfix.
        max_tickets=0 means no limit (Trac default cap is usually 100,
        so we use max=0 to try to get all).
        """
        params = [
            # Include all open/active statuses
            "status=new",
            "status=assigned",
            "status=reopened",
            "status=accepted",
            # Exclude rejected resolution (covers closed-as-rejected too)
            "resolution=!rejected",
            "resolution=!wontfix",
            # Columns to include in CSV
            "col=id",
            "col=summary",
            "col=status",
            "col=type",
            "col=priority",
            "col=component",
            "col=owner",
            "col=reporter",
            "col=created",
            "col=modified",
            "col=resolution",
            "col=keywords",
            # Sort by ticket ID descending (newest first)
            "order=id",
            "desc=1",
            f"max={max_tickets}",
            f"format={fmt}",
        ]
        return f"{self.base_url}/query?" + "&".join(params)

    async def _fetch_csv(self, page, url):
        """Fetch the CSV export from Trac."""
        print(f"  📥 Fetching: {url}")
        response = await page.request.get(url)

        if response.status == 403:
            raise PermissionError(
                "Access denied (403). The site may require authentication.\n"
                "Try logging in manually in the browser first, or provide cookies."
            )
        if response.status != 200:
            raise RuntimeError(f"Unexpected HTTP status: {response.status}")

        return await response.text()

    def _parse_csv(self, csv_text):
        """Parse the CSV response into a list of dicts."""
        reader = csv.DictReader(io.StringIO(csv_text))
        tickets = []
        for row in reader:
            # Strip whitespace from all values
            tickets.append({k.strip(): v.strip() for k, v in row.items()})
        return tickets

    def _save_csv(self, csv_text, filename="tickets.csv"):
        """Save raw CSV to disk."""
        path = self.output_dir / filename
        path.write_text(csv_text, encoding="utf-8")
        print(f"  ✓ CSV saved:  {path}")
        return path

    def _save_json(self, tickets, filename="tickets.json"):
        """Save tickets as JSON."""
        path = self.output_dir / filename
        path.write_text(
            json.dumps(tickets, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  ✓ JSON saved: {path}")
        return path

    def _save_markdown(self, tickets, filename="tickets.md"):
        """Save tickets as a readable Markdown table."""
        path = self.output_dir / filename

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"# Active Tickets (excluding Rejected)",
            f"",
            f"**Source:** {self.base_url}  ",
            f"**Generated:** {now}  ",
            f"**Total tickets:** {len(tickets)}",
            f"",
        ]

        if not tickets:
            lines.append("_No tickets found._")
        else:
            # Determine columns present in the data
            all_keys = list(tickets[0].keys()) if tickets else []

            # Choose which columns to show in the table (keep it readable)
            preferred = ["id", "summary", "status", "type", "priority",
                         "component", "owner", "reporter"]
            cols = [k for k in preferred if k in all_keys]
            # Add any remaining columns not in the preferred list
            cols += [k for k in all_keys if k not in cols and k not in
                     ("description", "keywords")]

            # Header row
            header = "| " + " | ".join(cols) + " |"
            separator = "| " + " | ".join(["---"] * len(cols)) + " |"
            lines += [header, separator]

            for t in tickets:
                ticket_id = t.get("id", "").strip("#")
                row_values = []
                for col in cols:
                    val = t.get(col, "").replace("|", "\\|")
                    # Make ticket IDs into links
                    if col == "id":
                        val = f"[#{ticket_id}]({self.base_url}/ticket/{ticket_id})"
                    row_values.append(val)
                lines.append("| " + " | ".join(row_values) + " |")

        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  ✓ Markdown saved: {path}")
        return path

    def _print_summary(self, tickets):
        """Print a quick summary to the console."""
        print(f"\n{'='*60}")
        print(f"  TICKETS FOUND: {len(tickets)}")
        print(f"{'='*60}")

        if not tickets:
            print("  (none)")
            return

        # Count by status
        from collections import Counter
        status_counts = Counter(t.get("status", "unknown") for t in tickets)
        print("\n  By Status:")
        for status, count in sorted(status_counts.items()):
            print(f"    {status:<20} {count}")

        # Count by type if present
        if "type" in tickets[0]:
            type_counts = Counter(t.get("type", "unknown") for t in tickets)
            print("\n  By Type:")
            for ttype, count in sorted(type_counts.items()):
                print(f"    {ttype:<20} {count}")

        # Count by priority if present
        if "priority" in tickets[0]:
            priority_counts = Counter(t.get("priority", "unknown") for t in tickets)
            print("\n  By Priority:")
            for priority, count in sorted(priority_counts.items()):
                print(f"    {priority:<20} {count}")

        print(f"\n  First 10 tickets:")
        print(f"  {'ID':<8} {'Status':<12} {'Summary'}")
        print(f"  {'-'*8} {'-'*12} {'-'*40}")
        for t in tickets[:10]:
            tid = t.get("id", "?").strip("#")
            status = t.get("status", "?")
            summary = t.get("summary", "?")[:60]
            print(f"  #{tid:<7} {status:<12} {summary}")

        if len(tickets) > 10:
            print(f"  ... and {len(tickets) - 10} more")

    async def fetch_tickets(self, max_tickets=0):
        """
        Main entry point - fetch all active non-rejected tickets.
        Saves CSV, JSON and Markdown files.
        """
        print(f"\n🎫 Trac Active Ticket Scraper")
        print(f"🔗 Source: {self.base_url}")
        print(f"📂 Output: {self.output_dir.absolute()}\n")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
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
                }
            )
            page = await context.new_page()

            # Remove webdriver fingerprint
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            # --- Step 1: Visit the base site first to get cookies/session ---
            print("⏳ Establishing session...")
            await page.goto(self.base_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # --- Step 2: Fetch the CSV export ---
            print("⏳ Fetching ticket data (CSV)...")
            csv_url = self._build_query_url(fmt="csv", max_tickets=max_tickets)
            csv_text = await self._fetch_csv(page, csv_url)

            await browser.close()

        # --- Step 3: Parse & save ---
        print("\n💾 Saving results...")
        tickets = self._parse_csv(csv_text)

        # Remove any tickets that slipped through with rejected resolution
        tickets = [
            t for t in tickets
            if t.get("resolution", "").lower() not in ("rejected", "wontfix")
        ]

        self._save_csv(csv_text, "tickets.csv")
        self._save_json(tickets, "tickets.json")
        self._save_markdown(tickets, "tickets.md")

        self._print_summary(tickets)

        print(f"\n✅ Done! Output saved to: {self.output_dir.absolute()}")
        return tickets


async def main():
    # -------------------------------------------------------
    # Configuration — edit these for your Trac instance
    # -------------------------------------------------------
    BASE_URL = "https://trac.ffmpeg.org"
    OUTPUT_DIR = "ffmpeg_tickets"

    # Set to a number (e.g. 500) to cap results, or 0 for no limit
    MAX_TICKETS = 0
    # -------------------------------------------------------

    scraper = TracTicketScraper(base_url=BASE_URL, output_dir=OUTPUT_DIR)
    await scraper.fetch_tickets(max_tickets=MAX_TICKETS)


if __name__ == "__main__":
    asyncio.run(main())
