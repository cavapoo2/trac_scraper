"""
Trac 0.11.2.1 Compatibility Test
Quick test to verify the change history scraper works with older Trac.
"""

import asyncio
from trac_change_history import TracChangeHistoryScraper
from symbols import sym


async def test_trac_011_compatibility(base_url: str, test_ticket_id: int):
    """
    Test scraper against a Trac 0.11.2.1 instance.
    """
    print(f"\n{sym.test} Testing Trac 0.11.2.1 Compatibility")
    print(f"{sym.info} Target: {base_url}")
    print(f"{sym.ticket} Test ticket: #{test_ticket_id}\n")
    
    scraper = TracChangeHistoryScraper(
        base_url=base_url,
        output_dir="trac_011_test"
    )
    
    try:
        events = await scraper.scrape(test_ticket_id)
        
        print(f"\n{sym.party} SUCCESS! Scraper works with Trac 0.11.2.1")
        print(f"\n{sym.info} What was captured:")
        print(f"  - Change events: {len(events)}")
        
        if events:
            event = events[0]
            print(f"  - First event has {len(event['field_changes'])} field changes")
            if event['field_changes']:
                fc = event['field_changes'][0]
                print(f"    Example: {fc['field']} {fc['action']}")
            print(f"  - Comment length: {len(event.get('comment', ''))}")
        
        print(f"\n{sym.tick} Trac 0.11.2.1 is fully supported!")
        return True
        
    except Exception as e:
        print(f"\n{sym.cross} Error: {e}")
        print(f"\n{sym.warning} Please check:")
        print(f"  1. Is the URL correct? {base_url}")
        print(f"  2. Does ticket #{test_ticket_id} exist?")
        print(f"  3. Does it have change history?")
        print(f"  4. Any 403 errors? (try stealth scraper)")
        return False


async def main():
    # ═══════════════════════════════════════════════════════════════════
    # CONFIGURE YOUR TRAC 0.11.2.1 INSTANCE HERE
    # ═══════════════════════════════════════════════════════════════════
    
    BASE_URL = "https://trac.ffmpeg.org"  # ← Your Trac 0.11.2.1 URL
    TEST_TICKET = 1                        # ← A ticket with change history
    
    # ═══════════════════════════════════════════════════════════════════
    
    await test_trac_011_compatibility(BASE_URL, TEST_TICKET)


if __name__ == "__main__":
    print(f"""
    ╔═══════════════════════════════════════════════════════════════╗
    ║  Trac 0.11.2.1 Change History Scraper - Compatibility Test   ║
    ╚═══════════════════════════════════════════════════════════════╝
    """)
    
    asyncio.run(main())
