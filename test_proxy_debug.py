#!/usr/bin/env python3
"""
Test script to verify proxy and comment functionality on a specific URL.
Usage: python test_proxy_debug.py
"""
from __future__ import annotations
import os
import sys
import time
import logging

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.driver_factory import get_driver
from src.config import HEADLESS, PAGE_LOAD_TIMEOUT, FIND_TIMEOUT, AFTER_SUBMIT_PAUSE
from src.commenter import process_job

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('test_proxy_debug.log', mode='w')
    ]
)
logger = logging.getLogger(__name__)


def parse_proxy(proxy_str: str) -> str:
    """
    Parse proxy string in format IP:PORT:USER:PASS and return HTTP proxy URL.
    Example: 14.224.225.146:29087:ue56:ue56 -> http://ue56:ue56@14.224.225.146:29087
    """
    parts = proxy_str.split(':')
    if len(parts) != 4:
        raise ValueError(f"Invalid proxy format: {proxy_str}. Expected IP:PORT:USER:PASS")
    
    ip, port, user, password = parts
    return f"http://{user}:{password}@{ip}:{port}"


def test_proxy_connection():
    """Test if proxy is working by connecting to a URL."""
    PROXY = "14.224.225.146:29087:ue56:ue56"
    TARGET_URL = "https://flowlinevalve.com/2022/09/ptfe-lined-ball-globe-valves-manufacturer-in-ahmedabad-gujarat-india/"
    
    logger.info(f"Testing proxy: {PROXY}")
    logger.info(f"Target URL: {TARGET_URL}")
    
    try:
        proxy_url = parse_proxy(PROXY)
        logger.info(f"Parsed proxy URL: {proxy_url}")
    except ValueError as e:
        logger.error(f"Failed to parse proxy: {e}")
        return False
    
    driver = None
    try:
        logger.info("Creating Chrome driver with proxy...")
        os.environ["HEADLESS"] = str(HEADLESS)
        driver = get_driver(proxy=proxy_url)
        
        logger.info(f"Setting page load timeout to {PAGE_LOAD_TIMEOUT}s...")
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        
        logger.info(f"Navigating to {TARGET_URL}...")
        start_time = time.time()
        driver.get(TARGET_URL)
        load_time = time.time() - start_time
        logger.info(f"Page loaded in {load_time:.2f}s")
        
        # Check page title
        title = driver.title
        logger.info(f"Page title: {title}")
        
        # Take screenshot for debugging
        try:
            screenshot_path = "test_page_screenshot.png"
            driver.save_screenshot(screenshot_path)
            logger.info(f"Screenshot saved to {screenshot_path}")
        except Exception as screenshot_err:
            logger.warning(f"Could not save screenshot: {screenshot_err}")
        
        # Check for comment form
        html_text = driver.page_source
        logger.info(f"Page source length: {len(html_text)} chars")
        
        # Look for common comment form indicators
        comment_indicators = ['comment', 'textarea', 'submit', 'name', 'email']
        found_indicators = [ind for ind in comment_indicators if ind.lower() in html_text.lower()]
        logger.info(f"Comment form indicators found: {found_indicators}")
        
        # Detect comment platform
        from src.commenter import _detect_platform
        platform = _detect_platform(html_text)
        logger.info(f"Detected platform: {platform}")
        
        # Debug: Find all textareas
        try:
            textareas = driver.find_elements("tag name", "textarea")
            logger.info(f"Found {len(textareas)} textarea elements")
            for i, ta in enumerate(textareas):
                try:
                    ta_name = ta.get_attribute('name') or ta.get_attribute('id') or ''
                    ta_class = ta.get_attribute('class') or ''
                    ta_visible = ta.is_displayed() if hasattr(ta, 'is_displayed') else 'N/A'
                    logger.info(f"  Textarea {i}: name/id='{ta_name}', class='{ta_class}', visible={ta_visible}")
                except Exception:
                    logger.info(f"  Textarea {i}: could not get details")
        except Exception as e:
            logger.warning(f"Could not enumerate textareas: {e}")
        
        # Debug: Find potential comment buttons
        try:
            from selenium.webdriver.common.by import By
            all_buttons = driver.find_elements(By.TAG_NAME, "button")
            logger.info(f"Found {len(all_buttons)} button elements")
            for i, btn in enumerate(all_buttons):
                try:
                    btn_text = btn.text or btn.get_attribute('innerText') or ''
                    btn_class = btn.get_attribute('class') or ''
                    if btn_text or 'comment' in btn_class.lower():
                        logger.info(f"  Button {i}: text='{btn_text[:50]}', class='{btn_class}'")
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Could not enumerate buttons: {e}")
        
        # Scroll and wait for lazy-loaded content
        logger.info("Scrolling to bottom to trigger lazy-loaded comments...")
        for i in range(3):
            driver.execute_script(f"window.scrollTo(0, {1000 * (i+1)});")
            time.sleep(1)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        
        # Try to find and click any "show comments" or "leave comment" buttons
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            
            # Common patterns for comment buttons
            comment_btn_selectors = [
                "a[href*='comment']",
                "button[class*='comment']",
                ".show-comments",
                ".load-comments",
                "#comments .reply",
                ".comment-reply-link",
                "a[class*='comment']",
                ".btn-comment",
                ".comments-toggle"
            ]
            
            for selector in comment_btn_selectors:
                try:
                    btns = driver.find_elements(By.CSS_SELECTOR, selector)
                    for btn in btns:
                        if btn.is_displayed():
                            btn_text = btn.text or btn.get_attribute('innerText') or ''
                            logger.info(f"Found comment-related button: selector={selector}, text='{btn_text[:30]}'")
                            # Try clicking it
                            try:
                                btn.click()
                                logger.info(f"Clicked button: {btn_text[:30]}")
                                time.sleep(2)
                                break
                            except Exception as click_err:
                                logger.warning(f"Could not click button: {click_err}")
                    else:
                        continue
                    break
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Error looking for comment buttons: {e}")
        
        # Re-check for textareas after scrolling/clicking
        try:
            textareas = driver.find_elements("tag name", "textarea")
            logger.info(f"After scrolling - Found {len(textareas)} textarea elements")
        except Exception:
            pass
        
        # Test commenting
        job = {
            "url": TARGET_URL,
            "anchor": "Test Anchor",
            "content": "This is a test comment from automated testing.",
            "name": "Test User",
            "email": "test@example.com",
            "website": "https://example.com"
        }
        
        logger.info("Attempting to post a test comment...")
        ok, reason, link = process_job(driver, job)
        
        if ok:
            logger.info(f"SUCCESS: Comment posted! Reason: {reason}")
            if link:
                logger.info(f"Comment link: {link}")
            return True
        else:
            logger.warning(f"FAILED: Could not post comment. Reason: {reason}")
            return False
            
    except Exception as e:
        logger.error(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if driver:
            logger.info("Closing browser...")
            try:
                driver.quit()
            except Exception:
                pass


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("PROXY TEST SCRIPT")
    logger.info("=" * 60)
    
    success = test_proxy_connection()
    
    logger.info("=" * 60)
    if success:
        logger.info("TEST PASSED: Proxy is working and comment was posted!")
    else:
        logger.info("TEST FAILED: Please check the logs for details.")
    logger.info("=" * 60)
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

