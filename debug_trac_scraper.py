"""
Debug version of Trac Change History Scraper
Prints out the HTML structure to help diagnose parsing issues
"""

import asyncio
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


async def debug_trac_html(base_url: str, ticket_id: int, output_file: str = "debug_html.txt"):
    """
    Fetch a ticket page and dump the relevant HTML for debugging.
    """
    url = f"{base_url}/ticket/{ticket_id}"
    
    print(f"🔍 Fetching: {url}\n")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()
        
        response = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
        if response.status != 200:
            print(f"❌ HTTP {response.status}")
            await browser.close()
            return
        
        html = await page.content()
        await browser.close()
    
    soup = BeautifulSoup(html, "html.parser")
    
    # Write full HTML to file
    Path(output_file).write_text(html, encoding="utf-8")
    print(f"✓ Full HTML saved to: {output_file}\n")
    
    # Debug output
    print("="*70)
    print("DEBUG ANALYSIS")
    print("="*70)
    
    # 1. Check for #changelog
    changelog = soup.find(id="changelog")
    print(f"\n1. #changelog div exists? {changelog is not None}")
    
    if changelog:
        print(f"   - Tag: {changelog.name}")
        print(f"   - Classes: {changelog.get('class')}")
    else:
        # Look for alternative IDs/classes used for change history
        print("\n   Checking for alternative change history containers...")
        alternatives = [
            soup.find(id="history"),
            soup.find(id="changes"),
            soup.find(class_="changelog"),
            soup.find(class_="history"),
        ]
        for alt in alternatives:
            if alt:
                print(f"   - Found: <{alt.name}> id='{alt.get('id')}' class='{alt.get('class')}'")
    
    # 2. Look for change blocks with various patterns
    print(f"\n2. Looking for change blocks with different patterns...")
    
    # Try different selectors
    change_divs = soup.find_all("div", class_="change")
    print(f"   - <div class='change'>: {len(change_divs)} found")
    
    change_lis = soup.find_all("li", class_="change")
    print(f"   - <li class='change'>: {len(change_lis)} found")
    
    # Check for divs with "change" in the class list
    change_any = soup.find_all(lambda tag: tag.name in ["div", "li"] and 
                                "change" in " ".join(tag.get("class", [])))
    print(f"   - Elements with 'change' in class: {len(change_any)} found")
    
    # Look for h3 tags with specific text patterns
    h3_changes = soup.find_all("h3", string=lambda s: s and ("Changed" in s or "comment" in s))
    print(f"   - <h3> tags with 'Changed' or 'comment': {len(h3_changes)} found")
    
    # Combined
    all_changes = change_divs + change_lis
    
    if not all_changes and h3_changes:
        # Try to find the parent div of these h3 tags
        print("\n   ⚠️  No <div class='change'> found, but found <h3> tags with 'Changed'")
        print("   Checking parent structures...")
        for h3 in h3_changes[:3]:
            parent = h3.parent
            print(f"     • <h3> parent: <{parent.name}> class='{parent.get('class')}' id='{parent.get('id')}'")
            all_changes.append(parent)
    
    if not all_changes:
        print("\n   ⚠️  No change blocks found with standard patterns!")
        print("   Searching for ANY div/ul containing 'changes' class...")
        
        # Very broad search
        ul_changes = soup.find_all("ul", class_="changes")
        print(f"   - <ul class='changes'>: {len(ul_changes)} found")
        
        div_comment = soup.find_all("div", class_="comment")
        print(f"   - <div class='comment'>: {len(div_comment)} found")
        
        if ul_changes:
            print("\n   Found <ul class='changes'> - showing parent structure:")
            parent = ul_changes[0].parent
            print(f"     Parent: <{parent.name}> class='{parent.get('class')}' id='{parent.get('id')}'")
            all_changes.append(parent)
        
        # Check for h3 tags that might indicate changes
        h3_tags = soup.find_all("h3")
        print(f"\n   - Found {len(h3_tags)} <h3> tags total")
        for h3 in h3_tags[:10]:  # Show first 10
            text = h3.get_text(' ', strip=True)[:80]
            if "changed" in text.lower() or "comment" in text.lower() or "by" in text.lower():
                print(f"     • {h3.get('class')} — {text}")
    
    # 3. Analyze first change block
    if all_changes:
        print(f"\n3. First change block analysis:")
        first = all_changes[0]
        
        print(f"   - Tag: <{first.name}>")
        print(f"   - Classes: {first.get('class')}")
        print(f"   - ID: {first.get('id')}")
        
        # h3
        h3 = first.find("h3")
        if h3:
            print(f"\n   - Has <h3>: Yes")
            print(f"     Text: {h3.get_text(' ', strip=True)[:80]}")
        else:
            print(f"\n   - Has <h3>: No")
        
        # ul.changes
        ul = first.find("ul", class_="changes")
        if ul:
            print(f"\n   - Has <ul class='changes'>: Yes")
            lis = ul.find_all("li", recursive=False)
            print(f"     <li> items: {len(lis)}")
            if lis:
                first_li = lis[0]
                print(f"     First <li> text: {first_li.get_text(' ', strip=True)[:80]}")
                strong = first_li.find("strong")
                if strong:
                    print(f"     Field name: {strong.get_text(strip=True)}")
                ems = first_li.find_all("em")
                print(f"     <em> tags: {len(ems)}")
        else:
            print(f"\n   - Has <ul class='changes'>: No")
        
        # div.comment
        comment_div = first.find("div", class_="comment")
        if comment_div:
            print(f"\n   - Has <div class='comment'>: Yes")
            comment_text = comment_div.get_text(strip=True)[:100]
            print(f"     Text preview: {comment_text}...")
        else:
            print(f"\n   - Has <div class='comment'>: No")
        
        # Show raw HTML of first change
        print(f"\n4. Raw HTML of first change block (first 500 chars):")
        print("-" * 70)
        print(str(first)[:500])
        print("-" * 70)
    
    print(f"\n5. Full HTML saved to: {output_file}")
    print(f"   You can inspect the complete structure there.\n")
    
    # 6. Extra checks for Trac 0.11 specific patterns
    print(f"\n6. Trac 0.11.x specific checks:")
    
    # Look for text that indicates change history
    if "Changed" in html or "comment:" in html:
        print(f"   ✓ Found 'Changed' or 'comment:' in HTML")
    
    # Check for common Trac 0.11 structures
    form = soup.find("form", id="propertyform")
    if form:
        print(f"   ✓ Found #propertyform (ticket edit form)")
    
    # Look for the ticket box
    ticket_box = soup.find(id="ticket")
    if ticket_box:
        print(f"   ✓ Found #ticket box")
    
    # Check for fieldset (Trac 0.11 often uses this)
    fieldsets = soup.find_all("fieldset")
    print(f"   - Found {len(fieldsets)} <fieldset> tags")
    for fs in fieldsets[:3]:
        legend = fs.find("legend")
        if legend:
            print(f"     • Legend: {legend.get_text(strip=True)}")
    
    # Look for any div that contains both "Changed" and a date pattern
    import re
    date_pattern = re.compile(r'\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}')
    potential_changes = soup.find_all("div", string=lambda s: s and "Changed" in s and date_pattern.search(s or ""))
    print(f"   - Divs with 'Changed' + date pattern: {len(potential_changes)}")
    
    print(f"\n{'='*70}")
    print("Please share this output or the trac_debug.html file!")
    print(f"{'='*70}\n")


async def main():
    # Configure
    BASE_URL = "https://trac.ffmpeg.org"
    TICKET_ID = 1  # Change this to your test ticket
    
    await debug_trac_html(BASE_URL, TICKET_ID, "trac_debug.html")
    
    print("\n" + "="*70)
    print("NEXT STEPS:")
    print("="*70)
    print("1. Review the output above")
    print("2. Check trac_debug.html for the full page source")
    print("3. Look for the change history section in your browser")
    print("4. Share the findings so we can fix the parser\n")


if __name__ == "__main__":
    asyncio.run(main())
