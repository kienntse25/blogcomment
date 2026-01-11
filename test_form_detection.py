#!/usr/bin/env python3
"""
Test script for improved form detection
Tests multiple URLs to verify selector improvements
"""
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.driver_factory import make_selenium_driver
from src.discover import discover_form
from src.config import HEADLESS

# Test URLs covering different platforms
TEST_URLS = [
    # WordPress (most common)
    "https://www.wpbeginner.com/beginners-guide/how-to-install-wordpress/",
    "https://kinsta.com/blog/wordpress-seo/",
    
    # Different WP themes
    "https://www.elegantthemes.com/blog/wordpress/best-wordpress-plugins",
    
    # Vietnamese sites
    "https://vnexpress.net/",
    "https://dantri.com.vn/",
    
    # News sites (might have Arabic)
    "https://www.aljazeera.com/",
]

def test_url(driver, url: str, index: int, total: int):
    """Test form detection on a single URL"""
    print(f"\n{'='*80}")
    print(f"[{index}/{total}] Testing: {url}")
    print('='*80)
    
    try:
        start = time.time()
        result = discover_form(driver, url)
        duration = time.time() - start
        
        if result:
            print(f"✅ SUCCESS ({duration:.1f}s)")
            print(f"   Textarea: {result.get('ta_sel', 'N/A')}")
            print(f"   Name: {result.get('name_sel', 'N/A')}")
            print(f"   Email: {result.get('email_sel', 'N/A')}")
            print(f"   Submit: {result.get('btn_sel', 'N/A')}")
            if result.get('ta_iframe') is not None:
                print(f"   Iframe: {result.get('ta_iframe')}")
            return True
        else:
            print(f"❌ FAILED ({duration:.1f}s) - No form found")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False

def main():
    print("🧪 THOROUGH FORM DETECTION TEST")
    print(f"Testing {len(TEST_URLS)} URLs...")
    print(f"Headless mode: {HEADLESS}")
    
    driver = None
    results = []
    
    try:
        driver = make_selenium_driver()
        print("✅ Driver created successfully")
        
        for i, url in enumerate(TEST_URLS, 1):
            success = test_url(driver, url, i, len(TEST_URLS))
            results.append((url, success))
            
            # Small pause between tests
            time.sleep(2)
        
        # Summary
        print(f"\n{'='*80}")
        print("📊 TEST SUMMARY")
        print('='*80)
        
        success_count = sum(1 for _, s in results if s)
        total = len(results)
        success_rate = (success_count / total * 100) if total > 0 else 0
        
        print(f"Total: {total}")
        print(f"Success: {success_count}")
        print(f"Failed: {total - success_count}")
        print(f"Success Rate: {success_rate:.1f}%")
        
        print("\nDetailed Results:")
        for url, success in results:
            status = "✅" if success else "❌"
            print(f"{status} {url}")
        
        if success_rate >= 70:
            print(f"\n🎉 EXCELLENT! {success_rate:.1f}% success rate")
        elif success_rate >= 50:
            print(f"\n⚠️  GOOD but needs improvement: {success_rate:.1f}%")
        else:
            print(f"\n❌ POOR: {success_rate:.1f}% - needs more work")
        
        return 0 if success_rate >= 50 else 1
        
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
        
    finally:
        if driver:
            try:
                driver.quit()
                print("\n✅ Driver closed")
            except:
                pass

if __name__ == "__main__":
    sys.exit(main())
