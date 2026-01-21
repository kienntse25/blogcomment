#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
from src.commenter import process_job
from src.registry import was_seen, mark_seen

TEST_URL = "https://flowlinevalve.com/2022/09/ptfe-lined-ball-globe-valves-manufacturer-in-ahmedabad-gujarat-india/"

test_job = {
    "url": TEST_URL,
    "anchor": "PTFE Lined Ball Globe Valves",
    "content": "Great article about PTFE-lined valves! Very informative.",
    "name": "Test User",
    "email": "test@example.com",
    "website": "https://example.com"
}

def test_url():
    print(f"Testing URL: {TEST_URL}")
    print("-" * 60)
    url, content, name, email = test_job["url"], test_job["content"], test_job["name"], test_job["email"]
    if was_seen(url, content, name, email):
        print("Already processed, skipping...")
        return
    print("Proceeding with test...")
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        print("Starting browser test...")
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        driver = webdriver.Chrome(options=chrome_options)
        print("Processing job...")
        ok, reason, link = process_job(driver, test_job)
        print("\n" + "=" * 60)
        print("RESULT:")
        print(f"  Status: {'SUCCESS' if ok else 'FAILED'}")
        print(f"  Reason: {reason}")
        print(f"  Comment Link: {link or 'N/A'}")
        meta = {"status": "OK", "reason": reason, "comment_link": link, "language": "en"} if ok else {"status": "FAILED", "reason": reason}
        mark_seen(url, content, name, email, meta)
        driver.quit()
        print("\nTest completed!")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_url()
