import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright
from datetime import datetime
import re


async def scrape_trac_ticket(url: str, output_dir: str = "ticket_data", headless: bool = True):
    """
    Scrape a Trac ticket and save all information to JSON with attachments.
    Supports both old (0.11, 0.12) and new Trac versions.
    
    Args:
        url: URL of the Trac ticket
        output_dir: Directory to save output files
        headless: Whether to run browser in headless mode
    """
    # Create output directory structure
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    attachments_dir = output_path / "attachments"
    attachments_dir.mkdir(exist_ok=True)
    
    async with async_playwright() as p:
        # Launch browser with stealth settings
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process'
            ]
        )
        
        # Create context with realistic settings
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York',
            permissions=['geolocation'],
            color_scheme='light',
            extra_http_headers={
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
        )
        
        page = await context.new_page()
        
        # Set default timeout to 60 seconds
        page.set_default_timeout(60000)
        
        # Add stealth JavaScript to hide automation
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            
            window.chrome = {
                runtime: {}
            };
            
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """)
        
        print(f"Loading ticket: {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            # Wait a bit for any dynamic content
            await page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Error loading page: {e}")
            print("Trying with a longer timeout...")
            await page.goto(url, timeout=90000)
            await page.wait_for_timeout(3000)
        
        # Extract ticket number from URL
        ticket_match = re.search(r'/ticket/(\d+)', url)
        ticket_number = ticket_match.group(1) if ticket_match else "unknown"
        
        ticket_data = {
            "url": url,
            "ticket_number": ticket_number,
            "scraped_at": datetime.now().isoformat(),
            "fields": {},
            "description": "",
            "comments": [],
            "attachments": []
        }
        
        # Detect Trac version
        print("Detecting Trac version...")
        trac_version = "unknown"
        try:
            footer_text = await page.locator("#footer").text_content(timeout=5000)
            if footer_text:
                version_match = re.search(r'Trac\s+([\d.]+)', footer_text)
                if version_match:
                    trac_version = version_match.group(1)
                    print(f"  Detected Trac version: {trac_version}")
                    ticket_data["trac_version"] = trac_version
        except:
            pass
        
        # Take a screenshot for debugging
        await page.screenshot(path=str(output_path / f"screenshot_{ticket_number}.png"))
        print(f"Screenshot saved for debugging")
        
        # Extract ticket fields from the property table
        print("Extracting ticket fields...")
        
        async def extract_fields_from_row(row):
            """Extract field-value pairs from a table row, getting selected values from dropdowns."""
            fields = {}
            try:
                # Get all direct children of the row in order
                children = await row.locator("> *").all()
                
                if not children:
                    return fields
                
                # Process children sequentially, looking for th-td pairs
                i = 0
                while i < len(children):
                    try:
                        current_tag = await children[i].evaluate("el => el.tagName.toLowerCase()")
                        
                        if current_tag == "th":
                            header_text = await children[i].text_content()
                            header_clean = header_text.strip().rstrip(':').lower()
                            
                            # Look for the corresponding td
                            if i + 1 < len(children):
                                next_tag = await children[i+1].evaluate("el => el.tagName.toLowerCase()")
                                
                                if next_tag == "td":
                                    td_elem = children[i+1]
                                    
                                    # Check what type of content this td has
                                    has_select = await td_elem.locator("select").count() > 0
                                    has_input = await td_elem.locator("input[type='text']").count() > 0
                                    has_textarea = await td_elem.locator("textarea").count() > 0
                                    
                                    value_clean = None
                                    
                                    if has_select:
                                        # Extract the SELECTED option from the dropdown
                                        try:
                                            selected_option = await td_elem.locator("select option[selected]").first.text_content(timeout=1000)
                                            if selected_option:
                                                value_clean = selected_option.strip()
                                            else:
                                                # If no option is marked as selected, get the first one (default)
                                                first_option = await td_elem.locator("select option").first.text_content(timeout=1000)
                                                if first_option:
                                                    value_clean = first_option.strip()
                                        except:
                                            # Fallback: try to get the selected value via JavaScript
                                            try:
                                                value_clean = await td_elem.locator("select").first.evaluate("el => el.options[el.selectedIndex]?.text")
                                                if value_clean:
                                                    value_clean = value_clean.strip()
                                            except:
                                                pass
                                    
                                    elif has_input:
                                        # Extract value from input field
                                        try:
                                            input_value = await td_elem.locator("input[type='text']").first.get_attribute("value")
                                            if input_value:
                                                value_clean = input_value.strip()
                                        except:
                                            pass
                                    
                                    elif has_textarea:
                                        # Extract value from textarea
                                        try:
                                            textarea_value = await td_elem.locator("textarea").first.text_content()
                                            if textarea_value:
                                                value_clean = textarea_value.strip()
                                        except:
                                            pass
                                    
                                    else:
                                        # Plain text cell (display value)
                                        value_text = await td_elem.text_content()
                                        value_clean = value_text.strip()
                                    
                                    if header_clean and value_clean:
                                        fields[header_clean] = value_clean
                                    
                                    i += 2  # Skip both th and td
                                    continue
                        
                        i += 1
                        
                    except:
                        i += 1
                        continue
            except:
                pass
            
            return fields
        
        try:
            # Wait for the properties table to be visible
            await page.wait_for_selector("#properties", timeout=10000)
            
            # Try multiple selector patterns for properties
            property_selectors = [
                "#properties table.properties tr",
                "#properties table tr",
                "#properties tr"
            ]
            
            property_rows = []
            for selector in property_selectors:
                property_rows = await page.locator(selector).all()
                if property_rows:
                    print(f"  Found {len(property_rows)} property rows using: {selector}")
                    break
            
            # Extract fields from each row
            for row in property_rows:
                row_fields = await extract_fields_from_row(row)
                for field_name, field_value in row_fields.items():
                    ticket_data["fields"][field_name] = field_value
                    print(f"    {field_name}: {field_value}")
                    
            print(f"  Total fields extracted: {len(ticket_data['fields'])}")
            
            # Also try to extract fields that might be elsewhere
            # Some Trac versions have fields in different locations
            if len(ticket_data["fields"]) < 5:  # Only if we didn't get many fields
                print("  Looking for additional fields outside main table...")
                
                additional_field_patterns = [
                    (".trac-field-reporter", "reporter"),
                    (".reporter", "reporter"),
                    (".trac-field-owner", "owner"),
                    (".owner", "owner"),
                    (".trac-field-status", "status"),
                    (".status", "status"),
                    (".trac-field-priority", "priority"),
                    (".trac-field-component", "component"),
                    (".trac-field-version", "version"),
                    (".trac-field-milestone", "milestone"),
                    (".trac-field-keywords", "keywords"),
                    (".trac-field-cc", "cc"),
                ]
                
                for selector, field_name in additional_field_patterns:
                    try:
                        elem = await page.locator(selector).first.text_content(timeout=2000)
                        if elem and elem.strip():
                            if field_name not in ticket_data["fields"]:
                                ticket_data["fields"][field_name] = elem.strip()
                                print(f"    Found additional field: {field_name}: {elem.strip()}")
                    except:
                        continue
                    
        except Exception as e:
            print(f"Error extracting fields: {e}")
        except Exception as e:
            print(f"Error extracting fields: {e}")
        
        # Extract summary (title)
        try:
            selectors = [
                "#ticket h1.summary",
                "h1.summary",
                "#content h1",
                "h1",
                "#ticket .summary"
            ]
            
            for selector in selectors:
                try:
                    summary = await page.locator(selector).first.text_content(timeout=5000)
                    if summary:
                        ticket_data["fields"]["summary"] = summary.strip()
                        print(f"Found summary using: {selector}")
                        break
                except:
                    continue
        except Exception as e:
            print(f"Error extracting summary: {e}")
        
        # Extract description
        print("Extracting description...")
        try:
            selectors = [
                "#ticket .description .searchable",
                ".description .searchable",
                "#ticket .description",
                ".description",
                "div.description"
            ]
            
            for selector in selectors:
                try:
                    await page.wait_for_selector(selector, timeout=5000)
                    description = await page.locator(selector).first.text_content()
                    if description:
                        ticket_data["description"] = description.strip()
                        print(f"  Found description ({len(description)} chars) using: {selector}")
                        break
                except:
                    continue
        except Exception as e:
            print(f"Error extracting description: {e}")
        
        # Extract comments - THIS IS THE IMPROVED PART
        print("Extracting comments...")
        try:
            # First, check if changelog exists at all
            changelog_exists = await page.locator("#changelog").count() > 0
            
            if not changelog_exists:
                print("  No #changelog element found on page")
            else:
                print("  Found #changelog element")
                
                # Try multiple patterns for comment extraction
                comment_patterns = [
                    {
                        "name": "Modern Trac (.change divs)",
                        "container": "#changelog .change",
                        "author": [".trac-field-author", "h3.change a", ".author"],
                        "timestamp": [".trac-field-time", "a.timeline", ".date"],
                        "text": [".comment.searchable", ".comment", "div.searchable"]
                    },
                    {
                        "name": "Old Trac (h3.change headers)",
                        "container": "#changelog h3.change",
                        "author": ["a", "span"],
                        "timestamp": ["a.timeline", ".date"],
                        "text": ["following-sibling::div[1]", "+ div"]
                    },
                    {
                        "name": "Alternative (div with class containing 'change')",
                        "container": "#changelog div[class*='change']",
                        "author": ["h3 a", ".author", "a"],
                        "timestamp": ["a.timeline", ".date", "h3 a"],
                        "text": [".comment", "div.searchable", "p"]
                    }
                ]
                
                comments_found = False
                
                for pattern in comment_patterns:
                    print(f"  Trying pattern: {pattern['name']}")
                    comment_elements = await page.locator(pattern["container"]).all()
                    
                    if comment_elements:
                        print(f"    Found {len(comment_elements)} potential comments")
                        comments_found = True
                        
                        for idx, comment_elem in enumerate(comment_elements):
                            comment_data = {
                                "comment_number": len(ticket_data["comments"]) + 1,
                                "author": "",
                                "timestamp": "",
                                "text": ""
                            }
                            
                            # Try to get author
                            for author_sel in pattern["author"]:
                                try:
                                    author = await comment_elem.locator(author_sel).first.text_content(timeout=2000)
                                    if author:
                                        comment_data["author"] = author.strip()
                                        break
                                except:
                                    continue
                            
                            # Try to get timestamp
                            for time_sel in pattern["timestamp"]:
                                try:
                                    timestamp = await comment_elem.locator(time_sel).first.text_content(timeout=2000)
                                    if timestamp:
                                        comment_data["timestamp"] = timestamp.strip()
                                        break
                                except:
                                    continue
                            
                            # Try to get comment text
                            for text_sel in pattern["text"]:
                                try:
                                    # Handle XPath-style selectors differently
                                    if "following-sibling" in text_sel or text_sel.startswith("+"):
                                        # Need to find next sibling
                                        comment_text = await comment_elem.evaluate("""
                                            el => el.nextElementSibling ? el.nextElementSibling.textContent : ''
                                        """)
                                    else:
                                        comment_text = await comment_elem.locator(text_sel).first.text_content(timeout=2000)
                                    
                                    if comment_text:
                                        comment_data["text"] = comment_text.strip()
                                        break
                                except:
                                    continue
                            
                            # If we got at least author or text, add it
                            if comment_data["author"] or comment_data["text"]:
                                ticket_data["comments"].append(comment_data)
                                print(f"    Comment {comment_data['comment_number']}: author='{comment_data['author'][:30]}...' text={len(comment_data['text'])} chars")
                        
                        if ticket_data["comments"]:
                            break  # Found comments, stop trying other patterns
                
                if not comments_found:
                    print("  No comments found with any pattern")
                    
                    # Last resort: dump the changelog HTML for manual inspection
                    try:
                        changelog_html = await page.locator("#changelog").inner_html()
                        debug_file = output_path / f"changelog_debug_{ticket_number}.html"
                        with open(debug_file, "w", encoding="utf-8") as f:
                            f.write(changelog_html)
                        print(f"  Saved changelog HTML to: {debug_file}")
                    except:
                        pass
                        
        except Exception as e:
            print(f"Error extracting comments: {e}")
        
        print(f"Total comments extracted: {len(ticket_data['comments'])}")
        
        # Extract and download attachments
        print("Extracting attachments...")
        try:
            await page.wait_for_selector("#attachments", timeout=5000)
            
            # Try multiple attachment selectors
            attachment_selectors = [
                "#attachments dt a",
                "#attachments a",
                "dl#attachments dt a"
            ]
            
            attachments = []
            for selector in attachment_selectors:
                attachments = await page.locator(selector).all()
                if attachments:
                    print(f"  Found {len(attachments)} attachments using: {selector}")
                    break
            
            for attachment in attachments:
                filename = await attachment.text_content()
                href = await attachment.get_attribute("href")
                
                if filename and href:
                    filename = filename.strip()
                    
                    # Construct full URL if href is relative
                    if href.startswith('/'):
                        base_url = '/'.join(url.split('/')[:3])
                        attachment_page_url = base_url + href
                    else:
                        attachment_page_url = href
                    
                    print(f"  Processing attachment: {filename}")
                    print(f"    Attachment page: {attachment_page_url}")
                    
                    # Download the attachment
                    try:
                        download_page = await context.new_page()
                        download_page.set_default_timeout(60000)
                        
                        # Navigate to the attachment page
                        print(f"    Loading attachment page...")
                        await download_page.goto(attachment_page_url, wait_until="domcontentloaded")
                        await download_page.wait_for_timeout(1000)
                        
                        # Look for download links on the attachment page
                        # Trac typically has links like:
                        # - "Original Format" or "Download" 
                        # - URL format: /raw-attachment/ticket/XXXX/filename
                        # - Or direct format: /attachment/ticket/XXXX/filename?format=raw
                        
                        download_url = None
                        
                        # Try multiple strategies to find the download link
                        download_link_patterns = [
                            # Pattern 1: Look for raw-attachment link
                            "a[href*='raw-attachment']",
                            # Pattern 2: Look for format=raw parameter
                            "a[href*='format=raw']",
                            # Pattern 3: Look for "Download" or "Original Format" text
                            "a:has-text('Download')",
                            "a:has-text('Original Format')",
                            "a:has-text('download')",
                            # Pattern 4: Look in the attachment info div
                            "#content .attachment a",
                            ".attachment a"
                        ]
                        
                        for pattern in download_link_patterns:
                            try:
                                links = await download_page.locator(pattern).all()
                                for link in links:
                                    link_href = await link.get_attribute("href")
                                    if link_href and (
                                        'raw-attachment' in link_href or 
                                        'format=raw' in link_href or
                                        link_href.endswith(filename)
                                    ):
                                        if link_href.startswith('/'):
                                            download_url = base_url + link_href
                                        else:
                                            download_url = link_href
                                        print(f"    Found download link using pattern: {pattern}")
                                        break
                                if download_url:
                                    break
                            except:
                                continue
                        
                        # If no direct download link found, try adding format=raw to current URL
                        if not download_url:
                            print(f"    No direct download link found, trying format=raw parameter")
                            if '?' in attachment_page_url:
                                download_url = attachment_page_url + '&format=raw'
                            else:
                                download_url = attachment_page_url + '?format=raw'
                        
                        print(f"    Download URL: {download_url}")
                        
                        # Now actually download the file
                        async with download_page.expect_download(timeout=60000) as download_info:
                            await download_page.goto(download_url)
                        
                        download = await download_info.value
                        
                        # Save the file
                        save_path = attachments_dir / filename
                        await download.save_as(str(save_path))
                        
                        await download_page.close()
                        
                        ticket_data["attachments"].append({
                            "filename": filename,
                            "attachment_page_url": attachment_page_url,
                            "download_url": download_url,
                            "local_path": str(save_path.relative_to(output_path))
                        })
                        print(f"    ✓ Saved to: {save_path}")
                        
                    except Exception as e:
                        print(f"    ✗ Error downloading {filename}: {e}")
                        
                        # Try alternative method: direct HTTP download
                        try:
                            print(f"    Trying alternative download method...")
                            response = await download_page.request.get(download_url if download_url else attachment_page_url + '?format=raw')
                            
                            if response.ok:
                                content = await response.body()
                                save_path = attachments_dir / filename
                                with open(save_path, 'wb') as f:
                                    f.write(content)
                                
                                ticket_data["attachments"].append({
                                    "filename": filename,
                                    "attachment_page_url": attachment_page_url,
                                    "download_url": download_url,
                                    "local_path": str(save_path.relative_to(output_path)),
                                    "method": "http_request"
                                })
                                print(f"    ✓ Saved via HTTP request to: {save_path}")
                            else:
                                raise Exception(f"HTTP {response.status}")
                        except Exception as e2:
                            print(f"    ✗ Alternative method also failed: {e2}")
                            ticket_data["attachments"].append({
                                "filename": filename,
                                "attachment_page_url": attachment_page_url,
                                "download_url": download_url if download_url else "not_found",
                                "error": str(e)
                            })
                        
                        try:
                            await download_page.close()
                        except:
                            pass
                            
        except Exception as e:
            print(f"No attachments found or error: {e}")
        
        await browser.close()
        
        # Save ticket data to JSON
        json_path = output_path / f"ticket_{ticket_number}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(ticket_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n✓ Ticket data saved to: {json_path}")
        print(f"✓ Total fields extracted: {len(ticket_data['fields'])}")
        print(f"✓ Total comments extracted: {len(ticket_data['comments'])}")
        print(f"✓ Total attachments: {len(ticket_data['attachments'])}")
        
        return ticket_data


async def main():
    # Example usage
    ticket_url = input("Enter Trac ticket URL (or press Enter for default): ").strip()
    if not ticket_url:
        ticket_url = "https://trac.ffmpeg.org/ticket/10735"
        print(f"Using default: {ticket_url}")
    
    print("="*60)
    print("Trac Ticket Scraper (Multi-Version Support)")
    print("="*60)
    print()
    
    # Set headless=False to see the browser (useful for debugging)
    # Set headless=True for production use
    ticket_data = await scrape_trac_ticket(ticket_url, headless=False)
    
    print("\n" + "="*60)
    print("Extraction Complete!")
    print("="*60)
    print("\nTicket Summary:")
    print(f"  Number: {ticket_data['ticket_number']}")
    if 'summary' in ticket_data['fields']:
        print(f"  Summary: {ticket_data['fields']['summary']}")
    print(f"\nKey Fields:")
    for key in ['reported by', 'priority', 'component', 'version', 'status', 'resolution']:
        if key in ticket_data['fields']:
            print(f"  {key.title()}: {ticket_data['fields'][key]}")


if __name__ == "__main__":
    asyncio.run(main())
