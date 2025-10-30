# src/commenter.py
from __future__ import annotations
import time
import socket
import html
import re
from typing import Dict, Any, Tuple, Optional
from urllib.parse import urlparse

from langdetect import detect, DetectorFactory
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
    ElementClickInterceptedException,
    InvalidSessionIdException,
)
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .config import FIND_TIMEOUT, AFTER_SUBMIT_PAUSE, PAGE_LOAD_TIMEOUT, LANG_DETECT_MIN_CHARS

DetectorFactory.seed = 0
_TAG_RE = re.compile(r"<[^>]+>")

# ---------------- Helpers ----------------

def _dns_ok(u: str, timeout=5) -> Tuple[bool, str]:
    try:
        host = urlparse(u).hostname
        if not host:
            return False, "Invalid URL"
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo(host, None)
        return True, ""
    except Exception as e:
        return False, f"DNS error: {e}"

def _wait_body(driver):
    try:
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
    except InvalidSessionIdException:
        raise
    except Exception:
        pass


def _progressive_scroll(driver, steps: int = 6, pause: float = 0.35):
    try:
        height = driver.execute_script(
            "return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);"
        )
    except InvalidSessionIdException:
        raise
    except Exception:
        return
    if not height:
        return
    for i in range(1, max(1, steps) + 1):
        try:
            driver.execute_script("window.scrollTo(0, arguments[0]);", height * i / steps)
        except InvalidSessionIdException:
            raise
        except Exception:
            break
        time.sleep(pause)


def _reveal_hidden_textarea(driver):
    js = """
    const candidates = Array.from(document.querySelectorAll('textarea'));
    for (const el of candidates) {
        let node = el;
        while (node && node instanceof HTMLElement) {
            const style = window.getComputedStyle(node);
            if (style.display === 'none') node.style.display = 'block';
            if (style.visibility === 'hidden') node.style.visibility = 'visible';
            node.classList?.remove('hidden', 'collapsed', 'is-hidden');
            node = node.parentElement;
        }
        if (el.offsetParent !== null) return el;
    }
    return candidates.length ? candidates[0] : null;
    """
    try:
        el = driver.execute_script(js)
        return el if el else None
    except InvalidSessionIdException:
        raise
    except Exception:
        return None

def _scroll_into_view(driver, el):
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center', inline:'center'});", el
        )
        time.sleep(0.1)
    except Exception:
        pass

def _safe_click(driver, el, label="button") -> Tuple[bool, str]:
    try:
        _scroll_into_view(driver, el)
        el.click()
        return True, f"clicked {label}"
    except ElementClickInterceptedException:
        try:
            ActionChains(driver).move_to_element(el).click().perform()
            return True, f"actions-click {label}"
        except Exception:
            pass
        try:
            driver.execute_script("arguments[0].click();", el)
            return True, f"js-click {label}"
        except Exception as e3:
            return False, f"click-failed: {e3}"
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", el)
            return True, f"js-click {label}"
        except Exception as e2:
            return False, f"click-failed: {e2}"

def _set_val(driver, el, text: str):
    try:
        driver.execute_script(
            "arguments[0].value = arguments[1];"
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
            "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
            el,
            text,
        )
    except Exception:
        try:
            el.clear()
        except Exception:
            pass
        try:
            el.send_keys(text)
        except Exception:
            pass

def _qsa_first(driver, selectors) -> Optional[object]:
    # JS tìm phần tử đầu tiên hiển thị theo danh sách selector
    js = """
    const sels = arguments[0];
    for (const s of sels) {
      try {
        const el = document.querySelector(s);
        if (el && el.offsetParent !== null) return el;
      } catch(e) {}
    }
    return null;
    """
    try:
        el = driver.execute_script(js, list(selectors))
        if el:
            return el
    except InvalidSessionIdException:
        raise
    except Exception:
        pass
    # Fallback vòng lặp Python
    for s in selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, s)
            if el.is_displayed():
                return el
        except InvalidSessionIdException:
            raise
        except Exception:
            continue
    return None

def _find_any_frame(driver, selectors, timeout=FIND_TIMEOUT) -> Tuple[Optional[object], Optional[int]]:
    """
    Tìm phần tử theo selectors trong main document, nếu không thấy thì duyệt qua iframes.
    Trả về (element, index_iframe or None)
    """
    end = time.time() + timeout
    while time.time() < end:
        try:
            driver.switch_to.default_content()
            el = _qsa_first(driver, selectors)
            if el:
                return el, None

            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for idx, fr in enumerate(iframes):
                try:
                    driver.switch_to.default_content()
                    driver.switch_to.frame(fr)
                    el2 = _qsa_first(driver, selectors)
                    if el2:
                        return el2, idx
                except Exception:
                    continue
        except InvalidSessionIdException:
            raise
        except Exception:
            pass
        time.sleep(0.2)

    try:
        driver.switch_to.default_content()
    except InvalidSessionIdException:
        raise
    except Exception:
        pass
    return None, None


def _coerce_iframe_index(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _switch_to_frame(driver, index: Optional[int]) -> bool:
    try:
        driver.switch_to.default_content()
    except InvalidSessionIdException:
        raise
    except Exception:
        pass
    if index is None:
        return True
    try:
        frames = driver.find_elements(By.TAG_NAME, "iframe")
    except InvalidSessionIdException:
        raise
    except Exception:
        return False
    if index < 0 or index >= len(frames):
        return False
    try:
        driver.switch_to.frame(frames[index])
        return True
    except InvalidSessionIdException:
        raise
    except Exception:
        return False


def _find_with_selector(driver, selector: Optional[str], iframe_hint=None) -> Tuple[Optional[object], Optional[int]]:
    if not selector:
        return None, None
    idx = _coerce_iframe_index(iframe_hint)
    try:
        driver.switch_to.default_content()
    except InvalidSessionIdException:
        raise
    except Exception:
        pass
    try:
        if idx is not None:
            frames = driver.find_elements(By.TAG_NAME, "iframe")
            if idx < 0 or idx >= len(frames):
                return None, None
            try:
                driver.switch_to.frame(frames[idx])
            except InvalidSessionIdException:
                raise
            except Exception:
                return None, None
        el = driver.find_element(By.CSS_SELECTOR, selector)
        if el.is_displayed():
            return el, idx
    except InvalidSessionIdException:
        raise
    except Exception:
        return None, None
    finally:
        try:
            driver.switch_to.default_content()
        except InvalidSessionIdException:
            raise
        except Exception:
            pass
    return None, None


def _try_open_comment_form(driver) -> bool:
    js = """
    const keywords = [
      "comment", "reply", "leave a comment", "add comment", "add a comment",
      "коммент", "комментар", "ответить", "оставить комментарий",
      "написать комментарий", "добавить комментарий", "оставить ответ", "добавить ответ"
    ];
    const nodes = [];
    ["button","a","summary","div","span"].forEach(tag => {
      document.querySelectorAll(tag).forEach(el => nodes.push(el));
    });
    for (const el of nodes) {
      if (!el) continue;
      const txt = (el.innerText || el.textContent || "").trim().toLowerCase();
      if (!txt) continue;
      if (!keywords.some(kw => txt.includes(kw))) continue;
      try {
        el.click();
        return true;
      } catch(e) {}
      try {
        el.dispatchEvent(new MouseEvent("click", {bubbles:true, cancelable:true}));
        return true;
      } catch(e) {}
    }
    return false;
    """
    try:
        return bool(driver.execute_script(js))
    except InvalidSessionIdException:
        raise
    except Exception:
        return False


def detect_language(driver, fallback: str = "unknown") -> str:
    """
    Cố gắng phát hiện ngôn ngữ trang hiện tại. Trả về mã ISO-639-1 hoặc fallback.
    """
    try:
        source = driver.page_source or ""
    except InvalidSessionIdException:
        raise
    except Exception:
        source = ""
    if not source:
        return fallback
    text = _TAG_RE.sub(" ", source)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < LANG_DETECT_MIN_CHARS:
        return fallback
    try:
        lang = detect(text)
        return lang or fallback
    except Exception:
        return fallback

def _detect_platform(html_text: str) -> str:
    t = (html_text or "").lower()
    if any(
        token in t
        for token in (
            'id="disqus_thread"',
            "data-disqus",
            "disqus.com/embed.js",
            "disqus.com/count.js",
        )
    ):
        return "disqus"
    if "blogger.com" in t or 'name="blogger' in t or "g:plusone" in t:
        return "blogger"
    if "commento" in t or "commento.io" in t:
        return "commento"
    if "hyvor" in t or "hyvor-talk" in t or "talk.hyvor.com" in t:
        return "hyvor"
    if "facebook.com/plugins/comments" in t or "fb-comments" in t:
        return "fbcomments"
    if "wpdiscuz" in t:
        return "wpdiscuz"
    if "g-recaptcha" in t or "hcaptcha" in t:
        return "captcha"
    if "you must be logged in to post a comment" in t:
        return "login"
    if "must be logged in to comment" in t:
        return "login"

    if "comment-form" in t or 'id="commentform"' in t or 'name="comment"' in t:
        return "wordpress"
    return "unknown"

def _build_comment_text(base_text: str, anchor: str, website: str) -> str:
    base = (base_text or "").strip()
    atext = (anchor or "").strip()
    site = (website or "").strip()
    if atext and site:
        # Thay lần xuất hiện đầu tiên của anchor bằng thẻ a; nếu không có thì thêm cuối
        if atext in base:
            return base.replace(
                atext,
                f'<a href="{html.escape(site, quote=True)}">{html.escape(atext)}</a>',
                1,
            )
        return f'{base} <a href="{html.escape(site, quote=True)}">{html.escape(atext)}</a>'
    return base or "Thank you for the article!"

# ---------------- Main entry ----------------

def process_job(
    driver,
    job: Dict[str, Any],
    selectors: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, str]:
    """
    job dict: {'url','anchor','content','name','email','website'}
    selectors: {'ta_sel','name_sel','email_sel','btn_sel','ta_iframe','btn_iframe'}
    return: (ok:bool, reason:str, comment_link:str)
    """
    url = str(job.get("url", "")).strip()
    anchor = str(job.get("anchor", "")) if job.get("anchor") is not None else ""
    content = str(job.get("content", "")) if job.get("content") is not None else ""
    name = str(job.get("name", "")) or "Guest"
    email = str(job.get("email", "")) or ""
    website = str(job.get("website", "")) or ""
    selectors = selectors or job.get("selectors") or None
    if selectors is not None and not isinstance(selectors, dict):
        selectors = None

    if not url:
        return False, "Empty URL", ""

    okdns, why = _dns_ok(url)
    if not okdns:
        return False, why or "DNS not resolved", ""

    try:
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    except Exception:
        pass

    # Load page
    try:
        driver.get(url)
    except TimeoutException:
        return False, "Page load timeout", ""
    except WebDriverException as e:
        msg = str(e)
        if "ERR_NAME_NOT_RESOLVED" in msg:
            return False, "DNS not resolved", ""
        return False, f"WebDriver: {e.__class__.__name__}", ""

    _wait_body(driver)
    _progressive_scroll(driver, steps=5, pause=0.3)

    # Detect platform
    html_text = ""
    try:
        html_text = driver.page_source or ""
    except Exception:
        pass
    platform = _detect_platform(html_text)

    login_hint = platform == "login"
    platform_reasons = {
        "disqus": "Disqus requires login",
        "blogger": "Blogger requires login",
        "commento": "Commento requires login",
        "hyvor": "Hyvor requires login",
        "fbcomments": "Facebook comments require login",
        "wpdiscuz": "wpDiscuz (captcha/login)",
        "captcha": "Captcha present",
    }

    # Tìm field
    textarea_selectors = [
        "textarea#comment", "textarea[name='comment']", "form#commentform textarea",
        "textarea.comment-form-textarea", "form.comment-form textarea", "textarea"
    ]
    name_selectors  = ["input#author", "input[name='author']", "input[name='name']", "input[name='author-name']"]
    email_selectors = ["input#email",  "input[name='email']"]
    url_selectors   = ["input#url",    "input[name='url']", "input[name='website']"]
    submit_selectors = [
        "input[type='submit']", "button[type='submit']",
        "input.submit", "button.submit", "input#submit", "button#submit",
        "form#commentform input[type='submit']"
    ]

    ta = None
    ta_ifr = None
    if selectors:
        ta, ta_ifr = _find_with_selector(driver, selectors.get("ta_sel"), selectors.get("ta_iframe"))
    if not ta:
        ta, ta_ifr = _find_any_frame(driver, textarea_selectors, timeout=FIND_TIMEOUT)
    if not ta:
        toggled = _try_open_comment_form(driver)
        _progressive_scroll(driver, steps=3, pause=0.4)
        ta, ta_ifr = _find_any_frame(driver, textarea_selectors, timeout=FIND_TIMEOUT)
        if not ta:
            candidate = _reveal_hidden_textarea(driver)
            if candidate:
                ta = candidate
                ta_ifr = None
    if not ta:
        if login_hint:
            return False, "Login required", ""
        if platform in platform_reasons:
            return False, platform_reasons.get(platform, "Comment box not found"), ""
        return False, "Comment box not found", ""

    # Switch frame nếu textarea nằm trong iframe
    if not _switch_to_frame(driver, ta_ifr):
        return False, "Cannot enter textarea iframe", ""

    # Điền nội dung
    text_to_send = _build_comment_text(content, anchor, website)
    _set_val(driver, ta, text_to_send)

    # Điền các field tùy chọn
    # Name
    nm = None
    if selectors and selectors.get("name_sel"):
        try:
            nm = driver.find_element(By.CSS_SELECTOR, selectors["name_sel"])
        except Exception:
            nm = None
    if not nm:
        for s in name_selectors:
            try:
                nm = driver.find_element(By.CSS_SELECTOR, s)
                break
            except NoSuchElementException:
                continue
    if nm:
        _set_val(driver, nm, name)

    # Email
    em = None
    if selectors and selectors.get("email_sel"):
        try:
            em = driver.find_element(By.CSS_SELECTOR, selectors["email_sel"])
        except Exception:
            em = None
    if not em:
        for s in email_selectors:
            try:
                em = driver.find_element(By.CSS_SELECTOR, s)
                break
            except NoSuchElementException:
                continue
    if em and email:
        _set_val(driver, em, email)

    # Website
    urlf = None
    for s in url_selectors:
        try:
            urlf = driver.find_element(By.CSS_SELECTOR, s)
            break
        except NoSuchElementException:
            continue
    if urlf and website:
        _set_val(driver, urlf, website)

    # Submit
    driver.switch_to.default_content()
    btn = None
    btn_ifr = None
    if selectors:
        btn, btn_ifr = _find_with_selector(driver, selectors.get("btn_sel"), selectors.get("btn_iframe"))
    if not btn:
        btn, btn_ifr = _find_any_frame(driver, submit_selectors, timeout=FIND_TIMEOUT)
    if btn:
        if not _switch_to_frame(driver, btn_ifr):
            return False, "Cannot enter submit iframe", ""
        ok, why = _safe_click(driver, btn, "submit")
        if not ok:
            return False, why, ""
        time.sleep(AFTER_SUBMIT_PAUSE)
    else:
        # Không thấy nút submit, thử submit form bao quanh textarea
        try:
            if not _switch_to_frame(driver, ta_ifr):
                return False, "Cannot enter textarea iframe", ""
            driver.execute_script("""
                var el = arguments[0];
                var f = el.form || el.closest('form');
                if (f) { f.submit(); return true; } else { return false; }
            """, ta)
            time.sleep(AFTER_SUBMIT_PAUSE)
        except Exception:
            return False, "No submit button/form", ""

    # Kiểm tra dấu hiệu thành công
    driver.switch_to.default_content()
    try:
        html_after = (driver.page_source or "").lower()
    except Exception:
        html_after = ""

    success_hints = [
        "comment submitted", "awaiting moderation", "awaiting approval",
        "your comment is awaiting", "bình luận của bạn", "đã gửi bình luận",
        "thank you for your comment", "comment was posted", "held for moderation"
    ]
    if any(h in html_after for h in success_hints):
        # cố gắng lấy permalink comment (best-effort)
        link = ""
        try:
            anchors = driver.find_elements(By.CSS_SELECTOR, "a.comment-permalink, a[rel='bookmark'], a.permalink")
            if anchors:
                link = anchors[-1].get_attribute("href") or ""
        except Exception:
            pass
        return True, "Submitted (maybe pending moderation)", link

    # Nhiều site WP sẽ reload và chưa render thông báo → vẫn coi là submitted
    return True, "Submitted", ""


def post_comment(
    driver,
    url: str,
    name: str,
    email: str,
    comment: str,
    selectors: Optional[Dict[str, Any]] = None,
    anchor: str = "",
    website: str = "",
) -> Tuple[bool, str]:
    """
    Giữ API cũ cho pipeline legacy: trả (ok, reason).
    """
    job = {
        "url": url,
        "anchor": anchor,
        "content": comment,
        "name": name,
        "email": email,
        "website": website,
    }
    ok, reason, _ = process_job(driver, job, selectors=selectors)
    return ok, reason
