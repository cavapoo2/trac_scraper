"""
Diagnostic version - shows exactly what's happening at each step
"""

import asyncio
import re
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


async def diagnose_scraping(base_url: str, ticket_id: int):
    """
    Step-by-step diagnostic of what the scraper sees.
    """
    url = f"{base_url}/ticket/{ticket_id}"
    
    print(f"🔍 Diagnosing: {url}\n")
    print("="*70)
    
    # Fetch the page
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()
        
        print("STEP 1: Fetching page...")
        response = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        print(f"  Status: {response.status}")
        
        if response.status != 200:
            print("  ❌ Failed to fetch page")
            await browser.close()
            return
        
        html = await page.content()
        await browser.close()
    
    print(f"  ✓ Page fetched ({len(html)} bytes)\n")
    
    soup = BeautifulSoup(html, "html.parser")
    
    # Step 2: Find #changelog
    print("="*70)
    print("STEP 2: Looking for #changelog...")
    changelog = soup.find(id="changelog")
    
    if changelog:
        print(f"  ✓ Found #changelog")
        print(f"    Tag: <{changelog.name}>")
        print(f"    Classes: {changelog.get('class')}")
        print(f"    Children: {len(list(changelog.children))} elements")
    else:
        print("  ⚠️  #changelog not found")
        print("  Trying fallback (full document)...")
        changelog = soup
    
    # Step 3: Find change blocks
    print("\n" + "="*70)
    print("STEP 3: Looking for <div class='change'> blocks...")
    
    change_divs = changelog.find_all("div", class_="change")
    print(f"  Found: {len(change_divs)} blocks")
    
    if not change_divs:
        print("\n  ⚠️  No <div class='change'> found!")
        print("  Let me check what IS in the changelog...")
        
        # Show what's actually there
        if changelog != soup:
            print(f"\n  Direct children of #changelog:")
            for i, child in enumerate(list(changelog.children)[:10]):
                if hasattr(child, 'name') and child.name:
                    classes = child.get('class', [])
                    print(f"    {i+1}. <{child.name}> class={classes}")
        
        return
    
    # Step 4: Parse first change block
    print("\n" + "="*70)
    print(f"STEP 4: Analyzing first change block...")
    
    first_block = change_divs[0]
    print(f"  Tag: <{first_block.name}>")
    print(f"  Classes: {first_block.get('class')}")
    print(f"  ID: {first_block.get('id')}")
    
    # 4a: Find h3
    print(f"\n  4a. Looking for <h3>...")
    h3 = first_block.find("h3", class_="change") or first_block.find("h3")
    
    if h3:
        print(f"    ✓ Found <h3>")
        print(f"      Classes: {h3.get('class')}")
        print(f"      ID: {h3.get('id')}")
        print(f"      Text: {h3.get_text(' ', strip=True)[:100]}")
        
        # Parse comment number
        m = re.search(r"comment:(\d+)", h3.get_text())
        if m:
            print(f"      Comment #: {m.group(1)}")
        else:
            print(f"      Comment #: NOT FOUND")
        
        # Parse timestamp
        time_tag = h3.find("a", title=re.compile(r"\d{4}-\d{2}-\d{2}"))
        if time_tag:
            print(f"      Timestamp: {time_tag['title']}")
        else:
            print(f"      Timestamp: NOT FOUND (no <a> with title containing date)")
        
        # Parse author
        author_label = h3.find("label", id=re.compile(r"changeLabel", re.I))
        author_span = h3.find("span", class_=re.compile(r"trac-author"))
        
        if author_label:
            print(f"      Author (label): {author_label.get_text(strip=True)}")
        elif author_span:
            print(f"      Author (span): {author_span.get_text(strip=True)}")
        else:
            # Try text pattern
            m = re.search(r"\bby\s+(\S+)", h3.get_text())
            if m:
                print(f"      Author (text): {m.group(1)}")
            else:
                print(f"      Author: NOT FOUND")
    else:
        print(f"    ❌ No <h3> found in first change block")
    
    # 4b: Find <ul class="changes">
    print(f"\n  4b. Looking for <ul class='changes'>...")
    ul = first_block.find("ul", class_="changes")
    
    if ul:
        print(f"    ✓ Found <ul class='changes'>")
        lis = ul.find_all("li", recursive=False)
        print(f"      <li> count: {len(lis)}")
        
        if lis:
            first_li = lis[0]
            print(f"\n      First <li>:")
            print(f"        Text: {first_li.get_text(' ', strip=True)[:100]}")
            
            strong = first_li.find("strong")
            if strong:
                print(f"        Field: {strong.get_text(strip=True)}")
            else:
                print(f"        Field: NO <strong> FOUND")
            
            ems = first_li.find_all("em")
            print(f"        <em> count: {len(ems)}")
            if ems:
                for i, em in enumerate(ems):
                    print(f"          em[{i}]: {em.get_text(strip=True)}")
    else:
        print(f"    ❌ No <ul class='changes'> found")
    
    # 4c: Find <div class="comment">
    print(f"\n  4c. Looking for <div class='comment'>...")
    comment_div = first_block.find("div", class_=re.compile(r"\bcomment\b"))
    
    if comment_div:
        print(f"    ✓ Found <div class='comment'>")
        comment_text = comment_div.get_text(strip=True)
        print(f"      Length: {len(comment_text)} chars")
        print(f"      Preview: {comment_text[:100]}")
    else:
        print(f"    ❌ No <div class='comment'> found")
    
    # Step 5: Summary
    print("\n" + "="*70)
    print("STEP 5: Summary")
    print("="*70)
    
    has_h3 = first_block.find("h3") is not None
    has_ul = first_block.find("ul", class_="changes") is not None
    has_comment = first_block.find("div", class_=re.compile(r"\bcomment\b")) is not None
    
    print(f"  Has <h3>: {has_h3}")
    print(f"  Has <ul class='changes'>: {has_ul}")
    print(f"  Has <div class='comment'>: {has_comment}")
    
    if has_h3 and (has_ul or has_comment):
        print(f"\n  ✅ Structure looks correct - scraper should work!")
        print(f"  If it's not working, the issue is in the parsing logic.")
    else:
        print(f"\n  ⚠️  Missing expected elements")
        print(f"  This explains why the scraper isn't capturing anything.")
    
    # Show raw HTML
    print("\n" + "="*70)
    print("STEP 6: Raw HTML of first change block")
    print("="*70)
    print(str(first_block)[:1000])
    print("\n... (truncated)")
    print("="*70)


async def main():
    # CONFIGURE HERE
    BASE_URL = "YOUR_TRAC_URL"  # e.g., "https://trac.example.com/projects/pcbtaskregister"
    TICKET_ID = 1
    
    await diagnose_scraping(BASE_URL, TICKET_ID)


if __name__ == "__main__":
    asyncio.run(main())
