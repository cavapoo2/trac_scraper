"""Quick test - should work now"""
import asyncio
from trac_change_history import TracChangeHistoryScraper

async def test():
    # EDIT THESE
    BASE_URL = "YOUR_TRAC_URL"
    TICKET_ID = 1
    
    scraper = TracChangeHistoryScraper(base_url=BASE_URL, output_dir="test_output")
    events = await scraper.scrape(TICKET_ID)
    
    if events:
        print(f"\n✅ SUCCESS! Captured {len(events)} events")
        e = events[0]
        print(f"\nFirst event:")
        print(f"  Comment #: {e['comment_num']}")
        print(f"  Timestamp: {e['timestamp']}")
        print(f"  Author: {e['author']}")
        print(f"  Field changes: {len(e['field_changes'])}")
        if e['field_changes']:
            fc = e['field_changes'][0]
            print(f"    Example: {fc['field']} {fc['action']} from '{fc['old_value']}' to '{fc['new_value']}'")
    else:
        print("\n❌ Still no events captured")

asyncio.run(test())
