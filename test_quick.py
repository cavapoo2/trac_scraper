"""
Quick test of the updated Trac 0.11 scraper
"""

import asyncio
from trac_change_history import TracChangeHistoryScraper


async def test():
    # Configure for your Trac instance
    BASE_URL = "YOUR_TRAC_URL_HERE"  # e.g., "https://trac.example.com/projects/pcbtaskregister"
    TICKET_ID = 1  # Change to your test ticket
    
    scraper = TracChangeHistoryScraper(
        base_url=BASE_URL,
        output_dir="test_output"
    )
    
    print("Testing updated Trac 0.11.2.1 scraper...\n")
    events = await scraper.scrape(TICKET_ID)
    
    if events:
        print(f"\n✅ SUCCESS! Captured {len(events)} events\n")
        print("First event details:")
        print(f"  Comment #: {events[0]['comment_num']}")
        print(f"  Timestamp: {events[0]['timestamp']}")
        print(f"  Author: {events[0]['author']}")
        print(f"  Field changes: {len(events[0]['field_changes'])}")
        if events[0]['field_changes']:
            fc = events[0]['field_changes'][0]
            print(f"    - {fc['field']}: {fc['old_value']} → {fc['new_value']}")
        print(f"  Comment length: {len(events[0]['comment'])} chars")
        
        if events[0]['comment']:
            print(f"  Comment preview: {events[0]['comment'][:100]}...")
    else:
        print("\n❌ No events captured")
        print("Check that:")
        print("  1. The URL is correct")
        print("  2. The ticket has change history")
        print("  3. You can access the ticket without auth errors")


if __name__ == "__main__":
    asyncio.run(test())
