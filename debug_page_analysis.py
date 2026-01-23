#!/usr/bin/env python3
"""
Deep debug script to analyze page structure and comment forms.
"""
from __future__ import annotations
import os
import sys
import time
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.driver_factory import get_driver

PROXY = "14.224.225.146:29087:ue56:ue56"
TARGET_URL = "https://flowlinevalve.com/2022/09/ptfe-lined-ball-globe-valves-manufacturer-in-ahmedabad-gujarat-india/"

def parse_proxy(proxy_str):
    parts = proxy_str.split(':')
    if len(parts) != 4:
        raise ValueError(f"Invalid proxy format: {proxy_str}")
    ip, port, user, password = parts
    return f"http://{user}:{password}@{ip}:{port}"

def main():
    print("=" * 60)
    print("DEEP PAGE ANALYSIS")
    print("=" * 60)
    
    driver = None
    try:
        proxy_url = parse_proxy(PROXY)
        driver = get_driver(proxy=proxy_url)
        driver.set_page_load_timeout(25)
        
        print(f"\n1. Loading page: {TARGET_URL}")
        driver.get(TARGET_URL)
        time.sleep(2)
        
        print(f"\n2. Page title: {driver.title}")
        
        # Get page source
        html = driver.page_source
        print(f"\n3. Page source length: {len(html)} chars")
        
        # Save full HTML for analysis
        with open("debug_page_source.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("4. Saved full HTML to debug_page_source.html")
        
        # Check for specific comment-related patterns
        print("\n5. Searching for comment-related patterns:")
        
        patterns = [
            ("commentform", "WordPress comment form"),
            ("comment-form", "WordPress comment form (lowercase)"),
            ("wpdiscuz", "wpDiscuz comments"),
            ("disqus", "Disqus comments"),
            ("fb-comments", "Facebook comments"),
            ("textarea", "All textareas"),
            ("class=\"comment\"", "Comment class"),
            ("id=\"comment\"", "Comment ID"),
            ("name=\"comment\"", "Comment name"),
            ("submit", "Submit buttons"),
            ("Leave a reply", "Leave reply text"),
            ("post a comment", "Post comment text"),
        ]
        
        html_lower = html.lower()
        for pattern, description in patterns:
            count = html_lower.count(pattern.lower())
            print(f"   - {description}: {count} occurrences")
        
        # Look for forms
        print("\n6. Analyzing forms:")
        try:
            forms = driver.find_elements("tag name", "form")
            print(f"   Found {len(forms)} form elements")
            for i, form in enumerate(forms):
                form_action = form.get_attribute('action') or ''
                form_id = form.get_attribute('id') or ''
                form_class = form.get_attribute('class') or ''
                print(f"   Form {i}: action='{form_action[:50]}', id='{form_id}', class='{form_class}'")
                
                # Get inputs in this form
                inputs = form.find_elements("tag name", "input")
                textareas = form.find_elements("tag name", "textarea")
                print(f"     Inputs: {len(inputs)}, Textareas: {len(textareas)}")
        except Exception as e:
            print(f"   Error analyzing forms: {e}")
        
        # Look for comment-specific sections
        print("\n7. Searching for comment sections:")
        try:
            # Look for div with comment-related IDs/classes
            comment_containers = driver.find_elements("css selector", "[id*='comment'], [class*='comment']")
            print(f"   Found {len(comment_containers)} comment-related containers")
            
            # Get more details about the page structure
            print("\n8. Page structure analysis:")
            print(f"   - Total divs: {len(driver.find_elements('tag name', 'div'))}")
            print(f"   - Total forms: {len(driver.find_elements('tag name', 'form'))}")
            print(f"   - Total textareas: {len(driver.find_elements('tag name', 'textarea'))}")
            print(f"   - Total inputs: {len(driver.find_elements('tag name', 'input'))}")
            print(f"   - Total buttons: {len(driver.find_elements('tag name', 'button'))}")
            print(f"   - Total anchors: {len(driver.find_elements('tag name', 'a'))}")
            
            # Scroll and check for lazy-loaded content
            print("\n9. Scrolling to trigger lazy loading...")
            for i in range(5):
                driver.execute_script(f"window.scrollTo(0, {1000 * (i+1)});")
                time.sleep(1)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)
            
            print(f"   After scrolling:")
            print(f"   - Total textareas: {len(driver.find_elements('tag name', 'textarea'))}")
            print(f"   - Total forms: {len(driver.find_elements('tag name', 'form'))}")
            
        except Exception as e:
            print(f"   Error: {e}")
        
        # Get JavaScript-rendered content
        print("\n10. JavaScript content analysis:")
        try:
            # Check if there are any hidden elements
            hidden_elements = driver.execute_script("""
                var hidden = [];
                var all = document.getElementsByTagName('*');
                for (var i = 0; i < all.length; i++) {
                    var el = all[i];
                    var style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') {
                        if (el.id || el.className || el.tagName) {
                            hidden.push({
                                tag: el.tagName,
                                id: el.id || '',
                                class: el.className || '',
                                display: style.display,
                                visibility: style.visibility
                            });
                        }
                    }
                }
                return hidden.slice(0, 20);  // Limit to 20
            """)
            
            if hidden_elements:
                print(f"    Found {len(hidden_elements)} hidden elements:")
                for el in hidden_elements[:10]:
                    print(f"    - {el['tag']} id='{el['id'][:30]}' class='{el['class'][:30]}' display={el['display']} visibility={el['visibility']}")
            else:
                print("    No hidden elements found")
                
        except Exception as e:
            print(f"    Error: {e}")
        
        print("\n" + "=" * 60)
        print("ANALYSIS COMPLETE")
        print("=" * 60)
        
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

if __name__ == "__main__":
    main()

