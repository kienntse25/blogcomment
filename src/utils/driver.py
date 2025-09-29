from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from ..config import PAGE_LOAD_STRATEGY, DISABLE_IMAGES, HEADLESS, USER_AGENT

def build_driver(headless: bool = HEADLESS) -> webdriver.Chrome:
    opts = Options()
    if PAGE_LOAD_STRATEGY in {"eager", "none", "normal"}:
        opts.page_load_strategy = PAGE_LOAD_STRATEGY

    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--window-size=1440,2200")
    opts.add_argument("--lang=en-US")
    opts.add_argument(f"--user-agent={USER_AGENT}")

    # giảm dấu vết automation
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument("--disable-blink-features=AutomationControlled")

    if DISABLE_IMAGES:
        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.default_content_setting_values.notifications": 2,
            "profile.managed_default_content_settings.geolocation": 2,
        }
        opts.add_experimental_option("prefs", prefs)
        opts.add_argument("--blink-settings=imagesEnabled=false")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)

    # ẩn navigator.webdriver
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
                               {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"})
        driver.execute_cdp_cmd("Network.setUserAgentOverride", {"userAgent": USER_AGENT})
    except Exception:
        pass

    driver.set_page_load_timeout(30)
    driver.set_script_timeout(30)
    return driver
