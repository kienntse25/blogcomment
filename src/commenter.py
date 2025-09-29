from __future__ import annotations
import time, socket
from typing import Optional, Tuple, Dict, Any
from urllib.parse import urlparse

from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    NoSuchElementException, TimeoutException,
    ElementClickInterceptedException, WebDriverException,
)
from .config import FIND_TIMEOUT, AFTER_SUBMIT_PAUSE
from .form_selectors import COMMENT_TEXTAREAS, NAME_INPUTS, EMAIL_INPUTS, SUBMIT_BUTTONS
from .utils.throttle import human_pause

def _dns_ok(u: str) -> bool:
    try:
        host = urlparse(u.strip()).hostname
        if not host: return False
        socket.getaddrinfo(host, None); return True
    except Exception: return False

def _qsa_first_js(driver, selectors):
    js = """
    const sels = arguments[0];
    for (let s of sels) {
      try {
        const el = document.querySelector(s);
        if (el && el.offsetParent !== null) return el;
      } catch(e) {}
    }
    return null;
    """
    return driver.execute_script(js, list(selectors))

def _find_here(driver, selectors, timeout=FIND_TIMEOUT):
    end = time.time() + timeout; el = None
    while time.time() < end and not el:
        el = _qsa_first_js(driver, selectors)
        if el: break
        time.sleep(0.12)
    if not el:
        for s in selectors:
            try:
                e = driver.find_element(By.CSS_SELECTOR, s)
                if e.is_displayed() and e.is_enabled(): return e
            except NoSuchElementException: pass
    return el

def _find_any_frame(driver, selectors, timeout=FIND_TIMEOUT) -> Tuple[Optional[object], Optional[int]]:
    driver.switch_to.default_content()
    el = _find_here(driver, selectors, timeout=max(1, timeout*0.6))
    if el: return el, None
    for idx, fr in enumerate(driver.find_elements(By.TAG_NAME, "iframe")):
        try:
            driver.switch_to.default_content(); driver.switch_to.frame(fr)
            el = _find_here(driver, selectors, timeout=1.0)
            if el: return el, idx
        except Exception: pass
    driver.switch_to.default_content()
    return None, None

def _dismiss_overlays(driver):
    driver.switch_to.default_content()
    for sel in [
        "#onetrust-accept-btn-handler", "button#onetrust-accept-btn-handler",
        "button[aria-label*='accept' i]",
    ]:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, sel)
            if btn.is_displayed(): btn.click(); time.sleep(0.1); break
        except NoSuchElementException:
            pass
    for xp in [
        "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'accept')]",
        "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'agree')]",
        "//button[contains(., 'Chấp nhận') or contains(., 'Tôi đồng ý')]",
    ]:
        try:
            btn = driver.find_element(By.XPATH, xp)
            if btn.is_displayed(): btn.click(); time.sleep(0.1); break
        except NoSuchElementException:
            pass
    for sel in ["[aria-label='Close']", "button[aria-label*='close' i]", ".mfp-close", ".modal-close", ".popup-close", ".close"]:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, sel)
            if btn.is_displayed(): btn.click(); time.sleep(0.1); break
        except NoSuchElementException:
            pass

def _scroll_center(driver, el):
    driver.execute_script("try{arguments[0].scrollIntoView({block:'center',inline:'center'});}catch(e){}", el)
    time.sleep(0.05)

def _point_on_el(driver, el) -> bool:
    return bool(driver.execute_script("""
    const el = arguments[0];
    const r = el.getBoundingClientRect();
    const cx = Math.floor(r.left + r.width/2);
    const cy = Math.floor(r.top + r.height/2);
    const e = document.elementFromPoint(cx, cy);
    return e === el || el.contains(e);
    """, el))

def _safe_click(driver, el, label="submit"):
    driver.switch_to.default_content()
    _scroll_center(driver, el)
    if not _point_on_el(driver, el):
        _dismiss_overlays(driver); _scroll_center(driver, el)
    try:
        el.click(); return True, f"Clicked {label}"
    except ElementClickInterceptedException:
        pass
    except Exception as e:
        last = f"click: {e}"
    else:
        last = ""
    try:
        ActionChains(driver).move_to_element(el).pause(0.05).click().perform(); return True, f"Actions clicked {label}"
    except ElementClickInterceptedException:
        pass
    except Exception as e:
        last = f"Actions: {e}"
    try:
        driver.execute_script("arguments[0].click();", el); return True, f"JS clicked {label}"
    except Exception as e:
        last = f"JS: {e}"
    return False, f"Click failed {label} -> {last or 'intercepted'}"

def _set_value_fast(driver, el, text: str):
    try:
        driver.execute_script("""
        const el = arguments[0], val = arguments[1];
        if ('value' in el) el.value = val;
        el.dispatchEvent(new Event('input', {bubbles:true}));
        el.dispatchEvent(new Event('change', {bubbles:true}));
        """, el, text)
        time.sleep(0.02)
    except Exception:
        try: el.clear()
        except Exception: pass
        el.send_keys(text)

def _hard_blocked(page_lower: str) -> Optional[str]:
    flags = [
        ("disqus.com", "Third-party comments (Disqus)"),
        ("data-disqus", "Third-party comments (Disqus)"),
        ("facebook.com/plugins/comments", "Third-party comments (Facebook)"),
        ("fb-comments", "Third-party comments (Facebook)"),
        ("intensedebate", "Third-party comments (IntenseDebate)"),
        ("utteranc.es", "Third-party comments (Utterances/GitHub)"),
        ("giscus.app", "Third-party comments (Giscus/GitHub)"),
        ("talk.hyvor.com", "Third-party comments (Hyvor Talk)"),
        ("remark42", "Third-party comments (Remark42)"),
        ("commento.io", "Third-party comments (Commento)"),
        ("data-hypercomments", "Third-party comments (HyperComments)"),
        ("g-recaptcha", "Captcha required"),
        ("hcaptcha", "Captcha required"),
        ("must be logged in to post a comment", "Login required"),
        ("you must be logged in", "Login required"),
        ("wpdiscuz", "Captcha or anti-spam (wpDiscuz)"),
    ]
    for key, why in flags:
        if key in page_lower: return why
    return None

def post_comment(driver, url: str, name: str, email: str, comment: str,
                 selectors: Optional[Dict[str, Any]] = None) -> tuple[bool, str]:
    u = url if url.lower().startswith(("http://","https://")) else "https://" + url
    if not _dns_ok(u): return False, "DNS not resolved"

    try:
        driver.get(u)
    except TimeoutException:
        return False, "Timeout loading page"
    except WebDriverException as e:
        msg = str(e)
        if "ERR_NAME_NOT_RESOLVED" in msg: return False, "DNS not resolved"
        if "ERR_CONNECTION_TIMED_OUT" in msg or "ERR_TIMED_OUT" in msg: return False, "Connection timed out"
        if "ERR_INTERNET_DISCONNECTED" in msg: return False, "No internet"
        return False, f"WebDriver error: {e.__class__.__name__}"

    time.sleep(0.15); _dismiss_overlays(driver)

    blocked = _hard_blocked(driver.page_source.lower())
    if blocked: return False, blocked

    def _by_cached(sel: Optional[str], iframe_idx: Optional[int]) -> Optional[object]:
        if not sel: return None
        driver.switch_to.default_content()
        if iframe_idx is not None:
            frames = driver.find_elements(By.TAG_NAME, "iframe")
            try: driver.switch_to.frame(frames[iframe_idx])
            except Exception: return None
        try: return driver.find_element(By.CSS_SELECTOR, sel)
        except Exception: return None

    ta = name_el = email_el = btn = None
    ta_ifr = btn_ifr = None

    if selectors:
        ta_ifr  = selectors.get("ta_iframe")
        btn_ifr = selectors.get("btn_iframe")
        ta      = _by_cached(selectors.get("ta_sel"), ta_ifr)
        if ta:
            name_el  = _by_cached(selectors.get("name_sel"), ta_ifr)
            email_el = _by_cached(selectors.get("email_sel"), ta_ifr)
            btn      = _by_cached(selectors.get("btn_sel"), btn_ifr)

    if not ta:
        ta, ta_ifr = _find_any_frame(driver, COMMENT_TEXTAREAS)
        if not ta: return False, "Comment box not found"

    driver.switch_to.default_content()
    if ta_ifr is not None:
        try:
            driver.switch_to.frame(driver.find_elements(By.TAG_NAME, "iframe")[ta_ifr])
        except Exception:
            return False, "Failed to switch into iframe for textarea"

    if not name_el:
        name_el = _find_here(driver, NAME_INPUTS, timeout=max(1, FIND_TIMEOUT*0.5))
    if not email_el:
        email_el = _find_here(driver, EMAIL_INPUTS, timeout=max(1, FIND_TIMEOUT*0.5))

    _scroll_center(driver, ta)
    _set_value_fast(driver, ta, comment)
    if name_el:  _set_value_fast(driver, name_el, name)
    if email_el: _set_value_fast(driver, email_el, email)

    driver.switch_to.default_content()
    if not btn:
        btn, btn_ifr = _find_any_frame(driver, SUBMIT_BUTTONS, timeout=max(1, FIND_TIMEOUT*0.7))

    if not btn:
        try:
            driver.switch_to.default_content()
            if ta_ifr is not None:
                driver.switch_to.frame(driver.find_elements(By.TAG_NAME, "iframe")[ta_ifr])
            driver.execute_script("""
                const el = arguments[0];
                const f = el.closest('form');
                if (f) { f.submit(); return true; } else { el.submit && el.submit(); return true; }
            """, ta)
            human_pause(AFTER_SUBMIT_PAUSE, AFTER_SUBMIT_PAUSE + 0.2)
        except Exception:
            return False, "Submit button not found"
    else:
        driver.switch_to.default_content()
        if btn_ifr is not None:
            try: driver.switch_to.frame(driver.find_elements(By.TAG_NAME, "iframe")[btn_ifr])
            except Exception: return False, "Failed to switch into iframe for submit"
        ok, why = _safe_click(driver, btn, label="submit")
        if not ok: return False, why
        human_pause(AFTER_SUBMIT_PAUSE, AFTER_SUBMIT_PAUSE + 0.2)

    driver.switch_to.default_content()
    html = driver.page_source.lower()
    hints = [
        "awaiting moderation", "chờ duyệt", "thank you for your comment",
        "bình luận của bạn", "your comment is awaiting", "đã gửi bình luận",
        "awaiting approval", "comment submitted",
    ]
    if any(h in html for h in hints):
        return True, "Submitted (possibly in moderation)"
    return True, "Submitted"
