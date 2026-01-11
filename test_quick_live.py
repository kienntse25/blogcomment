est_quick_live.py</path>
<parameter name="content">#!/usr/bin/env python3
"""
Quick live test for form detection - Run with: python3 test_quick_live.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.driver_factory import make_selenium_driver
from src.discover import discover_form

# URL test nhanh - WordPress blog
TEST_URL = "https://onepowerbenin.com/en/on-a-mission-in-northern-benin/"

print("🧪 Live Test: Form Detection")
print(f"URL: {TEST_URL}\n")

driver = None
try:
    print("🔄 Starting driver...")
    driver = make_selenium_driver(headless=False)  # Visible để xem
    print("✅ Driver started!\n")
    
    print("🔍 Discovering form...")
    result = discover_form(driver, TEST_URL)
    
    print("\n" + "="*60)
    print("📊 KẾT QUẢ")
    print("="*60)
    
    if result:
        print("✅ TÌM THẤY FORM!")
        for k, v in result.items():
            print(f"   {k}: {v}")
    else:
        print("❌ KHÔNG TÌM THẤY FORM")
        
except Exception as e:
    print(f"❌ LỖI: {e}")
    import traceback
    traceback.print_exc()
finally:
    if driver:
        print("\n🔄 Đóng driver...")
        driver.quit()
        print("✅ Done!")
