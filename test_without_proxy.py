#!/usr/bin/env python3
"""
Test if website is accessible without proxy.
"""
from __future__ import annotations
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.driver_factory import get_driver

TARGET_URL = "https://flowlinevalve.com/2022/09/ptfe-lined-ball-globe-valves-manufacturer-in-ahmedabad-gujarat-india/"

def main():
    print("=" * 60)
    print("TESTING WITHOUT PROXY")
    print("=" * 60)
    
    driver = None
    try:
        print(f"\n1. Loading page WITHOUT proxy: {TARGET_URL}")
        driver = get_driver(proxy=None)  # NO PROXY
        driver.set_page_load_timeout(25)
        
        driver.get(TARGET_URL)
        time.sleep(3)
        
        print(f"\n2. Page title: {driver.title}")
        
        html = driver.page_source
        print(f"\n3. Page source length: {len(html)} chars")
        
        # Check if this is an error page
        if "chromium" in html.lower() or "error" in html.lower():
            print("\n⚠️  WARNING: This appears to be an error page!")
        else:
            print("\n✓ Page content looks real")
            
        # Check for forms and textareas
        forms = driver.find_elements("tag name", "form")
        textareas = driver.find_elements("tag name", "textarea")
        print(f"\n4. Forms: {len(forms)}, Textareas: {len(textareas)}")
        
        if forms > 0 or textareas > 0:
            print("✓ Page has interactive elements")
        else:
            print("⚠️  No interactive elements found")
        
        # Save screenshot
        driver.save_screenshot("test_no_proxy_screenshot.png")
        print("\n5. Screenshot saved to test_no_proxy_screenshot.png")
        
    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

if __name__ == "__main__":
    main()

