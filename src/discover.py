from __future__ import annotations
import time, socket
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlparse

from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from selenium.webdriver.common.keys import Keys

from .form_selectors import COMMENT_TEXTAREAS, NAME_INPUTS, EMAIL_INPUTS, SUBMIT_BUTTONS
from .config import FIND_TIMEOUT, PAGE_LOAD_TIMEOUT

def _dns_ok(u: str) -> bool:
    try:
        host = urlparse(u).hostname
        if not host: return False
        socket.getaddrinfo(host, None); return True
    except Exception: return False

def _qsa_first_js(driver, sels):
    js = """
    const s = arguments[0];
    for (let c of s) { try {
        const el = document.querySelector(c);
        if (el && el.offsetParent !== null) return el;
    } catch(e){} }
    return null;
    """
    return driver.execute_script(js, list(sels))

def _find_here(driver, sels, timeout=FIND_TIMEOUT):
    end = time.time() + timeout; el = None
    while time.time() < end and not el:
        el = _qsa_first_js(driver, sels)
        if el: break
        time.sleep(0.12)
    if not el:
        for s in sels:
            try:
                e = driver.find_element(By.CSS_SELECTOR, s)
                if e.is_displayed() and e.is_enabled(): return e
            except NoSuchElementException: pass
    return el

def _find_any_frame(driver, sels, timeout=FIND_TIMEOUT) -> Tuple[Optional[object], Optional[int]]:
    driver.switch_to.default_content()
    el = _find_here(driver, sels, timeout=max(1, timeout*0.6))
    if el: return el, None
    
    # Search inside iframes
    for idx, fr in enumerate(driver.find_elements(By.TAG_NAME, "iframe")):
        try:
            driver.switch_to.default_content(); driver.switch_to.frame(fr)
            el = _find_here(driver, sels, timeout=1.0)
            if el: return el, idx
        except Exception: pass
    driver.switch_to.default_content()
    return None, None

def _scroll_to_comment_area(driver):
    """Scroll to common comment area locations."""
    try:
        # Try to find and scroll to comment containers
        selectors = [
            "#respond", "#commentform", "#comments", 
            ".comment-respond", ".comments-area", 
            ".comment-area", ".post-comments",
            ".tf-comment-section", "#disqus_thread"
        ]
        for sel in selectors:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", el)
                    return True
            except NoSuchElementException:
                continue
    except Exception:
        pass
    return False

def _click_leave_comment_button(driver):
    """Click on 'Leave a comment' or similar buttons."""
    try:
        # Keywords for comment buttons in multiple languages
        keywords = [
            # English
            "leave a comment", "add comment", "add a comment", 
            "post a comment", "write a comment",
            # Spanish/Portuguese
            "dejar un comentario", "deixe um comentário", "comentar",
            # Vietnamese
            "viết bình luận", "đăng bình luận", "gửi bình luận",
            # Russian
            "оставить комментарий", "написать комментарий",
            # Arabic
            "تعليق", "أضف تعليق",
        ]
        
        # Find all clickable elements
        for tag in ["a", "button"]:
            try:
                elements = driver.find_elements(By.TAG_NAME, tag)
                for el in elements:
                    try:
                        text = (el.text or "").strip().lower()
                        if any(kw in text for kw in keywords):
                            # Scroll to element
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                            time.sleep(0.3)
                            el.click()
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
        
        # Also try by aria-label or title
        for kw in keywords:
            try:
                el = driver.find_element(By.CSS_SELECTOR, f"[aria-label*='{kw}' i], [title*='{kw}' i]")
                if el.is_displayed():
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                    time.sleep(0.3)
                    el.click()
                    return True
            except NoSuchElementException:
                continue
                
    except Exception:
        pass
    return False

def _scroll_page_slowly(driver, scrolls=3):
    """Scroll page slowly to trigger lazy loading."""
    try:
        total_height = driver.execute_script("return document.body.scrollHeight")
        viewport = driver.execute_script("return window.innerHeight")
        
        for i in range(scrolls):
            driver.execute_script(f"window.scrollTo(0, {viewport * (i + 1)});")
            time.sleep(0.5)
        
        # Scroll back to top
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.2)
    except Exception:
        pass

def discover_form(driver, url: str) -> Optional[Dict[str, Any]]:
    u = url if url.lower().startswith(("http://","https://")) else "https://" + url
    if not _dns_ok(u): return None
    
    try: 
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        driver.get(u)
    except (TimeoutException, WebDriverException): 
        return None
    
    # Wait for page to stabilize
    time.sleep(1)
    
    # Try to click "Leave a comment" button first
    _click_leave_comment_button(driver)
    
    # Scroll to comment area
    _scroll_to_comment_area(driver)
    
    # Scroll slowly to trigger lazy loading
    _scroll_page_slowly(driver, scrolls=3)
    
    # Try to find textarea
    ta, ta_ifr = _find_any_frame(driver, COMMENT_TEXTAREAS, timeout=FIND_TIMEOUT*1.5)
    if not ta:
        # Additional search attempts
        _scroll_page_slowly(driver, scrolls=2)
        ta, ta_ifr = _find_any_frame(driver, COMMENT_TEXTAREAS, timeout=FIND_TIMEOUT)
    
    if not ta: return None

    driver.switch_to.default_content()
    if ta_ifr is not None:
        try: 
            driver.switch_to.frame(driver.find_elements(By.TAG_NAME, "iframe")[ta_ifr])
        except Exception: 
            return None

    name_el = _find_here(driver, NAME_INPUTS, timeout=max(1, FIND_TIMEOUT*0.5))
    email_el = _find_here(driver, EMAIL_INPUTS, timeout=max(1, FIND_TIMEOUT*0.5))

    driver.switch_to.default_content()
    btn, btn_ifr = _find_any_frame(driver, SUBMIT_BUTTONS, timeout=max(1, FIND_TIMEOUT*0.7))

    def _css(el):
        try:
            tag = el.tag_name.lower()
            el_id = el.get_attribute("id")
            nm = el.get_attribute("name")
            ty = el.get_attribute("type")
            if el_id: return f"{tag}#{el_id}"
            if nm:    return f"{tag}[name='{nm}']"
            if ty:    return f"{tag}[type='{ty}']"
            cls = (el.get_attribute("class") or "").split()
            if cls:   return f"{tag}.{'.'.join(cls[:2])}"
            return tag
        except Exception:
            return None

    sel = {
        "ta_sel": _css(ta),
        "name_sel": _css(name_el) if name_el else None,
        "email_sel": _css(email_el) if email_el else None,
        "btn_sel": _css(btn) if btn else None,
        "ta_iframe": ta_ifr,
        "btn_iframe": btn_ifr,
        "source": "discover",
    }
    return sel if sel["ta_sel"] else None
