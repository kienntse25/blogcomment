#!/usr/bin/env python3
"""
Script đơn giản để test 1 URL cụ thể
"""
import os
os.environ["HEADLESS"] = "false"
os.environ["PAGELOAD_TIMEOUT"] = "60"
os.environ["FIND_TIMEOUT"] = "12"
os.environ["COMMENT_FORM_WAIT_SEC"] = "30"
os.environ["FAST_SCROLL_TO_BOTTOM"] = "true"
os.environ["SEARCH_IFRAMES"] = "true"
os.environ["SCREENSHOT_ON_FAIL"] = "true"
os.environ["FAILSHOT_DIR"] = "logs/failshots"

from src.driver_factory import make_selenium_driver
from src.commenter import process_job, detect_language

# URL cần test
URL = "https://ipb.edu.tl/ada-ipb-realiza-kompetisaun-lima-5-hodi-komemora-loron-falintil/"

job = {
    "url": URL,
    "anchor": "test anchor",
    "website": "https://example.com",
    "content": "Thanks for sharing this information!",
    "name": "Test User",
    "email": "test@example.com",
    "attach_anchor": True,
}

print(f"\n{'='*60}")
print(f"Testing URL: {URL}")
print(f"{'='*60}\n")

driver = make_selenium_driver()
try:
    print("Loading page and trying to post comment...")
    ok, reason, link = process_job(driver, job)
    lang = detect_language(driver)
    
    print(f"\n{'='*60}")
    print(f"RESULT:")
    print(f"  Success: {ok}")
    print(f"  Reason: {reason}")
    print(f"  Comment Link: {link}")
    print(f"  Language: {lang}")
    print(f"{'='*60}\n")
    
    if not ok:
        print("Check logs/failshots/ for HTML and screenshot")
        
finally:
    driver.quit()
