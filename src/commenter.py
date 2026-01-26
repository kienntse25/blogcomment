# src/commenter.py
from __future__ import annotations
import time
import html
import re
import os
import random
from typing import Dict, Any, Tuple, Optional
from urllib.parse import urlparse

from langdetect import detect, DetectorFactory
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
    ElementClickInterceptedException,
    InvalidSessionIdException,
    UnexpectedAlertPresentException,
)
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .config import (
    FIND_TIMEOUT,
    AFTER_SUBMIT_PAUSE,
    PAGE_LOAD_TIMEOUT,
    LANG_DETECT_MIN_CHARS,
    COMMENT_FORM_WAIT_SEC,
    FAST_SCROLL_TO_BOTTOM,
)
from .form_selectors import COMMENT_TEXTAREAS, NAME_INPUTS, EMAIL_INPUTS, SUBMIT_BUTTONS

DetectorFactory.seed = 0
_TAG_RE = re.compile(r"<[^>]+>")

# ---------------- Helpers ----------------

def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()

def _is_rate_limit_message(msg: str) -> bool:
    m = (msg or "").strip().lower()
    if not m:
        return False
    # Common WP/anti-spam "posting too quickly" messages in multiple languages.
    tokens = (
        "too quickly",
        "posting comments too quickly",
        "please slow down",
        "slow down",
        "zu schnell",          # DE
        "bitte etwas langsamer",  # DE
        "trop vite",           # FR
        "trop rapidement",     # FR
        "demasiado rápido",    # ES
        "muy rápido",          # ES
        "quá nhanh",           # VI
        "hãy chậm lại",        # VI
    )
    return any(t in m for t in tokens)

def _is_privacy_or_block_page(driver) -> Optional[str]:
    """
    Fast-fail for obvious browser interstitials that will never contain a comment form.
    Keeps worker from wasting COMMENT_FORM_WAIT_SEC on pages like:
      - "Privacy error" / cert errors
      - chrome-error://chromewebdata
    """
    try:
        title = (driver.title or "").strip().lower()
    except Exception:
        title = ""
    try:
        cur = (driver.current_url or "").strip().lower()
    except Exception:
        cur = ""

    if cur.startswith("chrome-error://") or "chromewebdata" in cur:
        return "TLS/privacy error"
    if any(
        tok in title
        for tok in (
            "privacy error",
            "your connection is not private",
            "net::err_cert",
            "this site can’t be reached",
            "this site can't be reached",
        )
    ):
        return "TLS/privacy error"
    if any(tok in title for tok in ("access denied", "attention required", "just a moment")):
        return "Blocked/interstitial"
    return None

def _wait_body(driver):
    try:
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
    except InvalidSessionIdException:
        raise
    except Exception:
        pass


def _progressive_scroll(driver, steps: int = 6, pause: float = 0.15):
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
    function isVisible(el) {
      try {
        const r = el.getBoundingClientRect();
        if (!r || r.width < 2 || r.height < 2) return false;
        const style = window.getComputedStyle(el);
        if (!style) return false;
        if (style.display === 'none') return false;
        if (style.visibility === 'hidden') return false;
        if (style.opacity === '0') return false;
        return true;
      } catch(e) { return false; }
    }
    for (const s of sels) {
      try {
        const el = document.querySelector(s);
        if (el && isVisible(el)) return el;
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

def _try_accept_cookies(driver) -> bool:
    """
    Best-effort cookie consent clicker (no-op if nothing found).
    Keeps it short to avoid slowing down runs.
    """
    js = r"""
    // IMPORTANT: keep tokens specific. Do NOT include generic "ok" because it matches normal links (e.g. "Okfun").
    const ACCEPT = [
      "accept", "agree", "got it", "consent",
      "accetta", "accetto", "consenti", "va bene", "ho capito",
      "aceptar", "acepto",
      "j'accepte", "accepter",
      "zulassen", "akzeptieren",
      "aceitar",
      "รับ", "同意", "允许"
    ];
    const COOKIE_CTX = ["cookie", "consent", "gdpr", "privacy", "cmp"];
    function norm(s){ return (s||"").trim().toLowerCase(); }
    function isVisible(el){
      if (!el) return false;
      const r = el.getBoundingClientRect();
      if (!r || r.width < 2 || r.height < 2) return false;
      const style = window.getComputedStyle(el);
      if (!style) return false;
      if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return false;
      return true;
    }
    function inCookieContext(el) {
      if (!el) return false;
      // Prefer restricting to cookie/consent containers to avoid clicking normal page links.
      const container = el.closest(
        "[id*='cookie' i], [class*='cookie' i], [id*='consent' i], [class*='consent' i], " +
        "[id*='gdpr' i], [class*='gdpr' i], [id*='privacy' i], [class*='privacy' i], " +
        "[role='dialog'], [aria-modal='true']"
      );
      if (!container) return false;
      const ctx = norm((container.id||"") + " " + (container.className||"") + " " + (container.getAttribute("aria-label")||""));
      return COOKIE_CTX.some(t => ctx.includes(t));
    }

    // Search only inside likely cookie/consent contexts first.
    let candidates = [];
    document.querySelectorAll(
      "[id*='cookie' i], [class*='cookie' i], [id*='consent' i], [class*='consent' i], " +
      "[id*='gdpr' i], [class*='gdpr' i], [id*='privacy' i], [class*='privacy' i], " +
      "[role='dialog'][aria-modal='true']"
    ).forEach(container => {
      container.querySelectorAll("button, a, input[type='button'], input[type='submit']").forEach(el => candidates.push(el));
    });
    // If none found, do not click anything (safer than guessing).
    if (!candidates.length) return false;

    for (const el of candidates) {
      if (!isVisible(el)) continue;
      const txt = norm(el.innerText || el.textContent || el.value || "");
      if (!txt) continue;
      if (!ACCEPT.some(t => txt === t || txt.includes(t))) continue;
      if (!inCookieContext(el)) continue;
      try { el.click(); return true; } catch(e) {}
      try { el.dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true})); return true; } catch(e) {}
    }
    return false;
    """
    try:
        return bool(driver.execute_script(js))
    except InvalidSessionIdException:
        raise
    except Exception:
        return False

def _jump_to_comment_anchors(driver) -> None:
    """
    Some WP themes lazy-render the comment form only when scrolled near #comments/#respond.
    This function tries fast hash jumps to trigger that logic.
    """
    for h in ("#comments", "#respond", "#commentform"):
        try:
            driver.execute_script("location.hash = arguments[0];", h)
            driver.execute_script("window.dispatchEvent(new Event('hashchange'));")
            time.sleep(0.05)
        except Exception:
            continue

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

def _strict_comment_selectors() -> list[str]:
    # Avoid ultra-generic selectors that cause false positives (contact forms, etc.).
    bad = {"textarea", "button"}
    out: list[str] = []
    for s in COMMENT_TEXTAREAS:
        if s in bad:
            continue
        # Contact-form-7 textarea is not a website comment box.
        if "wpcf7" in s:
            continue
        out.append(s)
    return out or list(COMMENT_TEXTAREAS)

def _strict_submit_selectors() -> list[str]:
    # Avoid clicking random buttons (cookie banners, newsletter, etc.).
    out: list[str] = []
    for s in SUBMIT_BUTTONS:
        if s.strip().lower() == "button":
            continue
        out.append(s)
    return out or list(SUBMIT_BUTTONS)

def _best_comment_textarea_in_context(driver) -> Optional[object]:
    """
    Heuristic finder to avoid:
      - picking contact/newsletter textareas
      - missing comment textareas that don't match strict CSS selectors
    Returns a visible textarea WebElement or None.
    """
    js = r"""
    const COMMENT_TOKENS = [
      "comment", "reply", "leave a reply", "leave a comment", "add a comment",
      "bình luận", "nhận xét", "góp ý",
      "коммент", "комментар", "ответ",
      "تعليق", "coment", "comentar", "comentario", "yorum"
    ];
    const NEGATIVE_TOKENS = [
      "contact", "message", "newsletter", "subscribe", "search", "login", "sign in"
    ];
    function textOf(el) {
      const a = [
        el.getAttribute("id") || "",
        el.getAttribute("name") || "",
        el.getAttribute("aria-label") || "",
        el.getAttribute("placeholder") || "",
        el.className || ""
      ].join(" ").toLowerCase();
      return a;
    }
    function hasToken(hay, tokens) { return tokens.some(t => hay.includes(t)); }
    function isVisible(el) {
      if (!el) return false;
      const r = el.getBoundingClientRect();
      if (!r || r.width < 2 || r.height < 2) return false;
      const style = window.getComputedStyle(el);
      if (!style) return false;
      if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return false;
      return true;
    }
    function scoreTextarea(ta) {
      let score = 0;
      const t = textOf(ta);
      if (hasToken(t, COMMENT_TOKENS)) score += 6;
      if (ta.closest("#respond, #commentform, .comment-respond, .comments-area, #comments, .comment-form, section#comments")) score += 4;
      const f = ta.form || ta.closest("form");
      if (f) {
        const action = (f.getAttribute("action") || "").toLowerCase();
        if (action.includes("wp-comments-post") || action.includes("comment")) score += 4;
        const ftxt = (f.className || "").toLowerCase() + " " + (f.id || "").toLowerCase();
        if (hasToken(ftxt, COMMENT_TOKENS)) score += 2;
        if (hasToken(ftxt, NEGATIVE_TOKENS)) score -= 6;
      }
      const anc = ta.closest("form, section, div");
      if (anc) {
        const a = (anc.className || "").toLowerCase() + " " + (anc.id || "").toLowerCase();
        if (hasToken(a, COMMENT_TOKENS)) score += 2;
        if (hasToken(a, NEGATIVE_TOKENS)) score -= 4;
      }
      // Downscore obvious contact-form-7 fields
      if (ta.closest(".wpcf7, form.wpcf7-form")) score -= 8;
      return score;
    }

    const textareas = Array.from(document.querySelectorAll("textarea"));
    let best = null;
    let bestScore = -9999;
    for (const ta of textareas) {
      if (!isVisible(ta)) continue;
      const sc = scoreTextarea(ta);
      if (sc > bestScore) { bestScore = sc; best = ta; }
    }
    if (best && bestScore >= 4) return best;
    return null;
    """
    try:
        el = driver.execute_script(js)
        return el if el else None
    except InvalidSessionIdException:
        raise
    except Exception:
        return None

def _find_best_comment_textarea(driver, timeout_sec: float) -> Tuple[Optional[object], Optional[int]]:
    """
    Try strict selectors first, then heuristic scoring (main doc + iframes).
    Returns (textarea, iframe_index)
    """
    strict = _strict_comment_selectors()
    end = time.time() + max(0.0, float(timeout_sec))
    while True:
        driver.switch_to.default_content()
        ta = _qsa_first(driver, strict)
        if not ta:
            ta = _best_comment_textarea_in_context(driver)
        if ta:
            return ta, None
        iframes = []
        try:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
        except Exception:
            iframes = []
        for idx, fr in enumerate(iframes):
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(fr)
                ta2 = _qsa_first(driver, strict)
                if not ta2:
                    ta2 = _best_comment_textarea_in_context(driver)
                if ta2:
                    return ta2, idx
            except InvalidSessionIdException:
                raise
            except Exception:
                continue
        if time.time() >= end:
            break
        time.sleep(0.25)
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return None, None

def _closest_form(driver, el) -> Optional[object]:
    try:
        form = driver.execute_script("return arguments[0].form || arguments[0].closest('form');", el)
        return form if form else None
    except InvalidSessionIdException:
        raise
    except Exception:
        return None

def _find_in_form(form_el, selectors: list[str]):
    for s in selectors:
        try:
            el = form_el.find_element(By.CSS_SELECTOR, s)
            if el.is_displayed():
                return el
        except Exception:
            continue
    return None

def _find_submit_in_form(driver, form_el) -> Optional[object]:
    # Prefer submit button inside the same form as textarea.
    try:
        el = driver.execute_script(
            """
            const f = arguments[0];
            if (!f) return null;
            return f.querySelector("input[type='submit'], button[type='submit'], button[name='submit'], input[name='submit']");
            """,
            form_el,
        )
        return el if el else None
    except InvalidSessionIdException:
        raise
    except Exception:
        return None

def _verify_posted_comment(driver, name: str, comment_text: str) -> str:
    """
    Best-effort verification: try to find the posted comment in the DOM.
    Returns a permalink (or empty string if not found).
    """
    name_norm = _norm_ws(name).lower()
    content_norm = _norm_ws(comment_text)
    if not name_norm or not content_norm:
        return ""
    snippet = _norm_ws(content_norm[:80]).lower()
    if len(snippet) < 12:
        return ""

    js = r"""
    const name = (arguments[0] || "").toLowerCase();
    const snippet = (arguments[1] || "").toLowerCase();
    function norm(s){ return (s||"").replace(/\s+/g," ").trim(); }
    function txt(el){ return norm(el ? (el.innerText || el.textContent || "") : ""); }
    function has(h, needle){ return h && needle && h.toLowerCase().includes(needle.toLowerCase()); }
    function inForm(el){
      return !!(el && el.closest && el.closest("#respond, #commentform, form.comment-form, form#commentform, .comment-respond"));
    }
    const selectors = [
      "#comments .comment",
      ".comments-area .comment",
      "ol.commentlist > li",
      ".comment-list > li",
      "article.comment",
      "li.comment"
    ];
    let nodes = [];
    for (const sel of selectors) {
      try { nodes.push(...document.querySelectorAll(sel)); } catch(e) {}
    }
    // de-dup
    nodes = Array.from(new Set(nodes));
    if (!nodes.length) return "";
    const tail = nodes.slice(-20);
    for (let i = tail.length - 1; i >= 0; i--) {
      const el = tail[i];
      if (!el || inForm(el)) continue;
      const t = txt(el);
      if (!t) continue;
      if (!has(t, name)) continue;
      if (!has(t, snippet)) continue;
      const id = (el.getAttribute("id") || "");
      if (id && id.toLowerCase().startsWith("comment-")) {
        return "#" + id;
      }
      // Some themes put the ID on an inner wrapper
      const inner = el.querySelector?.("[id^='comment-']");
      if (inner) {
        const iid = inner.getAttribute("id") || "";
        if (iid) return "#" + iid;
      }
      return "#comments";
    }
    return "";
    """
    try:
        frag = driver.execute_script(js, name_norm, snippet)
        frag = str(frag or "").strip()
    except Exception:
        frag = ""
    if not frag:
        return ""
    try:
        base = (driver.current_url or "").split("#", 1)[0]
    except Exception:
        base = ""
    if base:
        return base + frag
    return frag

def _verify_posted_comment_http(driver, url: str, name: str, comment_text: str) -> str:
    """
    Verify by fetching the page HTML directly (no JS rendering).
    Only intended as a fallback when Selenium DOM doesn't show the new comment.
    Uses cookies from Selenium session to reduce false negatives.
    Returns a permalink (or empty string if not found).
    """
    try:
        enabled = os.getenv("VERIFY_HTTP_ON_FAIL", "true").strip().lower() in {"1", "true", "yes", "on"}
    except Exception:
        enabled = True
    if not enabled:
        return ""

    name_norm = _norm_ws(name).lower()
    content_norm = _norm_ws(comment_text)
    snippet = _norm_ws(content_norm[:120]).lower()
    if not name_norm or len(snippet) < 12:
        return ""

    sess = requests.Session()
    try:
        for c in (driver.get_cookies() or []):
            n = c.get("name")
            v = c.get("value")
            if not n:
                continue
            sess.cookies.set(n, v)
    except Exception:
        pass

    headers = {}
    try:
        ua = os.getenv("USER_AGENT", "").strip()
        if ua:
            headers["User-Agent"] = ua
    except Exception:
        pass

    timeout = float(os.getenv("VERIFY_HTTP_TIMEOUT", "6"))
    try:
        r = sess.get(url, headers=headers or None, timeout=timeout, allow_redirects=True)
    except Exception:
        return ""

    try:
        html_txt = r.text or ""
    except Exception:
        return ""
    low = html_txt.lower()
    pos = low.rfind(snippet)
    if pos < 0:
        return ""
    window = low[max(0, pos - 1200): pos + 1200]
    if name_norm not in window:
        return ""

    # Try to extract comment id near the match for a stable permalink.
    chunk = html_txt[max(0, pos - 2500): pos + 2500]
    m = re.search(r"""id\s*=\s*["']comment-(\d+)["']""", chunk, flags=re.IGNORECASE)
    base = (r.url or url).split("#", 1)[0]
    if m:
        return f"{base}#comment-{m.group(1)}"
    return f"{base}#comments"

def _is_rating_required_alert(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    tokens = (
        "select a rating",
        "please select a rating",
        "rating is required",
        "seleziona",  # IT
        "valutazione",  # IT
        "bewertung",  # DE
        "評価",  # JA
    )
    return any(tok in t for tok in tokens)

def _try_set_required_ratings(driver, form_el) -> bool:
    """
    Some WP plugins (e.g. WP Recipe Maker) require a rating before submit and will
    show a JS alert like "Please select a rating".
    This tries to set a non-zero rating inside the same comment form.
    """
    if form_el is None:
        return False
    js = r"""
    const form = arguments[0];
    if (!form) return false;
    let changed = false;
    function click(el){
      try { el.click(); } catch(e) {}
      try { el.dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true})); } catch(e) {}
      try { el.dispatchEvent(new Event("change",{bubbles:true})); } catch(e) {}
    }
    // Radio-based ratings
    const radios = Array.from(form.querySelectorAll("input[type='radio'][name]"));
    const groups = new Map();
    for (const r of radios) {
      const n = (r.name || "").toLowerCase();
      if (!n) continue;
      if (!(n.includes("rating") || n.includes("rate"))) continue;
      if (!groups.has(r.name)) groups.set(r.name, []);
      groups.get(r.name).push(r);
    }
    for (const [name, items] of groups.entries()) {
      // pick highest numeric value > 0
      let best = null;
      let bestV = -1;
      for (const it of items) {
        const v = parseInt(it.value || "0", 10);
        if (Number.isFinite(v) && v > bestV) { bestV = v; best = it; }
      }
      if (best && bestV > 0) {
        if (!best.checked) {
          best.checked = true;
          click(best);
          changed = true;
        }
      }
    }
    // Select-based ratings
    const selects = Array.from(form.querySelectorAll("select[name]"));
    for (const s of selects) {
      const n = (s.name || "").toLowerCase();
      if (!(n.includes("rating") || n.includes("rate"))) continue;
      const opts = Array.from(s.options || []);
      let bestIdx = -1;
      let bestV = -1;
      for (let i = 0; i < opts.length; i++) {
        const ov = parseInt(opts[i].value || "0", 10);
        if (Number.isFinite(ov) && ov > bestV) { bestV = ov; bestIdx = i; }
      }
      if (bestIdx >= 0 && bestV > 0 && s.selectedIndex !== bestIdx) {
        s.selectedIndex = bestIdx;
        try { s.dispatchEvent(new Event("change",{bubbles:true})); } catch(e) {}
        changed = true;
      }
    }
    return changed;
    """
    try:
        return bool(driver.execute_script(js, form_el))
    except InvalidSessionIdException:
        raise
    except Exception:
        return False


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
      "написать комментарий", "добавить комментарий", "оставить ответ", "добавить ответ", "تعليق"
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
    
    # IMPORTANT: Check WordPress FIRST to avoid false positives from comment spam
    # WordPress indicators are more specific and should be checked first
    if "comment-form" in t or 'id="commentform"' in t or 'name="comment"' in t:
        return "wordpress"
    if "wpdiscuz" in t:
        return "wpdiscuz"
    
    # Check Disqus (external comment system)
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
    
    # Blogger detection - use regex to avoid matching blog URLs in spam comments
    # Only match if it's actual Blogger platform markup
    # Blogger detection should be strict; many pages contain blogspot.com links in content.
    if any(
        tok in t
        for tok in (
            "www.blogger.com/comment.g",
            "blogger-iframe-colorize",
            "data-blogger",
            "blogger-comment",
        )
    ):
        return "blogger"
    
    # Check other platforms
    if "commento" in t or "commento.io" in t:
        return "commento"
    if "hyvor" in t or "hyvor-talk" in t or "talk.hyvor.com" in t:
        return "hyvor"
    if "facebook.com/plugins/comments" in t or "fb-comments" in t:
        return "fbcomments"
    if "g-recaptcha" in t or "hcaptcha" in t:
        return "captcha"
    if "you must be logged in to post a comment" in t:
        return "login"
    if "must be logged in to comment" in t:
        return "login"

    return "unknown"

def _extract_submit_error_message(html_text: str) -> str:
    """
    Best-effort extraction for common WordPress error pages/messages.
    Returns a short, human-readable message or empty string.
    """
    t = html_text or ""
    patterns = [
        # wp_die error page
        r'(?is)<div[^>]+id=["\']error-page["\'][^>]*>.*?<p[^>]*>(.*?)</p>',
        r'(?is)<div[^>]+class=["\']wp-die-message["\'][^>]*>(.*?)</div>',
        # classic WP comment error
        r'(?is)<p[^>]*>\s*<strong>\s*error\s*</strong>\s*:\s*(.*?)</p>',
        r'(?is)<p[^>]*>\s*<strong>\s*error\s*</strong>\s*([^<]+)</p>',
        # generic notices
        r'(?is)<div[^>]+class=["\'][^"\']*(?:error|notice|alert)[^"\']*["\'][^>]*>(.*?)</div>',
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if not m:
            continue
        msg = m.group(1) if m.lastindex else ""
        msg = html.unescape(_TAG_RE.sub(" ", msg))
        msg = re.sub(r"\s+", " ", msg).strip()
        if msg:
            return msg[:240]
    return ""

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
    attach_anchor = bool(job.get("attach_anchor", True))
    selectors = selectors or job.get("selectors") or None
    if selectors is not None and not isinstance(selectors, dict):
        selectors = None

    if not url:
        return False, "Empty URL", ""
    if not attach_anchor:
        anchor = ""
        website = ""

    nav_started_at = time.time()
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
    # Best-effort: dismiss cookie banners early (can hide comment form).
    _try_accept_cookies(driver)
    _jump_to_comment_anchors(driver)

    # If we got redirected to a different domain, do not attempt to comment there.
    # This commonly happens on compromised sites or anti-bot redirects.
    try:
        cur_url = str(getattr(driver, "current_url", "") or "").strip()
    except Exception:
        cur_url = ""
    try:
        orig_host = (urlparse(url).netloc or "").split("@")[-1].lower()
        cur_host = (urlparse(cur_url).netloc or "").split("@")[-1].lower()
    except Exception:
        orig_host, cur_host = "", ""
    def _same_host_or_www(a: str, b: str) -> bool:
        if not a or not b:
            return False
        if a == b:
            return True
        if a == f"www.{b}" or b == f"www.{a}":
            return True
        return False
    allow_cross = os.getenv("ALLOW_CROSS_DOMAIN_REDIRECT", "false").strip().lower() in {"1", "true", "yes", "on"}
    if cur_url and orig_host and cur_host and (not _same_host_or_www(orig_host, cur_host)) and not allow_cross:
        return False, f"Redirected to different domain: {cur_host}", cur_url

    interstitial = _is_privacy_or_block_page(driver)
    if interstitial:
        return False, interstitial, ""
    # Fast scroll to bottom - jump directly to bottom for lazy-loaded comments
    if FAST_SCROLL_TO_BOTTOM:
        try:
            driver.execute_script(
                "window.scrollTo(0, Math.max(document.body.scrollHeight, document.documentElement.scrollHeight));"
                "window.dispatchEvent(new Event('scroll'));"
            )
            time.sleep(0.1)
        except Exception:
            pass

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

    # Find comment textarea (2-phase):
    #  - fast path: strict selectors, short wait
    #  - slow path: scroll/expand + heuristic scoring, up to COMMENT_FORM_WAIT_SEC
    ta = None
    ta_ifr = None
    if selectors:
        ta, ta_ifr = _find_with_selector(driver, selectors.get("ta_sel"), selectors.get("ta_iframe"))
    if not ta:
        ta, ta_ifr = _find_best_comment_textarea(driver, timeout_sec=min(2.0, float(FIND_TIMEOUT)))
    if not ta:
        # Trigger lazy-load / expand reply areas once, then wait a bit longer.
        _try_accept_cookies(driver)
        _try_open_comment_form(driver)
        _jump_to_comment_anchors(driver)
        if FAST_SCROLL_TO_BOTTOM:
            try:
                driver.execute_script(
                    "window.scrollTo(0, Math.max(document.body.scrollHeight, document.documentElement.scrollHeight));"
                    "window.dispatchEvent(new Event('scroll'));"
                )
            except Exception:
                pass
        _progressive_scroll(driver, steps=3, pause=0.25)
        ta, ta_ifr = _find_best_comment_textarea(driver, timeout_sec=float(COMMENT_FORM_WAIT_SEC))
        if not ta:
            candidate = _reveal_hidden_textarea(driver)
            if candidate:
                ta = candidate
                ta_ifr = None
    if not ta:
        if login_hint:
            # Only return "Login required" if we genuinely can't locate any comment form.
            return False, "Login required (no comment form)", ""
        if platform in platform_reasons:
            return False, platform_reasons.get(platform, "Comment box not found"), ""
        return False, "Comment box not found", ""

    # Switch frame nếu textarea nằm trong iframe
    if not _switch_to_frame(driver, ta_ifr):
        return False, "Cannot enter textarea iframe", ""

    form_el = _closest_form(driver, ta)

    # Điền nội dung
    text_to_send = _build_comment_text(content, anchor, website)
    _set_val(driver, ta, text_to_send)

    # Some plugins require rating selection; set it before submit to avoid alerts.
    try:
        if _try_set_required_ratings(driver, form_el):
            time.sleep(0.1)
    except Exception:
        pass

    # Điền các field tùy chọn
    # Name - sử dụng comprehensive selectors từ form_selectors.py
    nm = None
    if selectors and selectors.get("name_sel"):
        try:
            nm = driver.find_element(By.CSS_SELECTOR, selectors["name_sel"])
        except Exception:
            nm = None
    if not nm and form_el is not None:
        nm = _find_in_form(form_el, NAME_INPUTS)
    if not nm:
        for s in NAME_INPUTS:
            try:
                nm = driver.find_element(By.CSS_SELECTOR, s)
                break
            except NoSuchElementException:
                continue
    if nm:
        _set_val(driver, nm, name)

    # Email - sử dụng comprehensive selectors từ form_selectors.py
    em = None
    if selectors and selectors.get("email_sel"):
        try:
            em = driver.find_element(By.CSS_SELECTOR, selectors["email_sel"])
        except Exception:
            em = None
    if not em and form_el is not None:
        em = _find_in_form(form_el, EMAIL_INPUTS)
    if not em:
        for s in EMAIL_INPUTS:
            try:
                em = driver.find_element(By.CSS_SELECTOR, s)
                break
            except NoSuchElementException:
                continue
    if em and email:
        _set_val(driver, em, email)

    # Website URL - comprehensive selectors
    url_selectors = ["input#url", "input[name='url']", "input[name='website']", "input[placeholder*='Website' i]", "input[placeholder*='URL' i]"]
    urlf = None
    if form_el is not None:
        urlf = _find_in_form(form_el, url_selectors)
    if not urlf:
        for s in url_selectors:
            try:
                urlf = driver.find_element(By.CSS_SELECTOR, s)
                break
            except NoSuchElementException:
                continue
    if urlf and website:
        _set_val(driver, urlf, website)

    # Submit: prefer submit inside the same form as textarea (avoid random buttons)
    # Optional anti-spam: many sites reject comments submitted "too quickly" after page load.
    try:
        min_delay = float(os.getenv("MIN_SUBMIT_DELAY_SEC", "0") or "0")
    except Exception:
        min_delay = 0.0
    if min_delay > 0:
        try:
            now = time.time()
            jitter = 0.0
            try:
                jitter = float(os.getenv("SUBMIT_DELAY_JITTER_SEC", "0.4") or "0.4")
            except Exception:
                jitter = 0.4
            waited = max(0.0, now - nav_started_at)
            remain = max(0.0, min_delay - waited)
            if remain > 0:
                time.sleep(remain + (random.random() * max(0.0, jitter)))
        except Exception:
            pass

    btn = None
    if form_el is not None:
        btn = _find_submit_in_form(driver, form_el)
    if btn:
        try:
            ok, why = _safe_click(driver, btn, "submit")
            if not ok:
                return False, why, ""
            time.sleep(AFTER_SUBMIT_PAUSE)
        except UnexpectedAlertPresentException:
            # Try to resolve common rating-required alerts quickly.
            try:
                alert = driver.switch_to.alert
                atxt = alert.text or ""
                alert.accept()
            except Exception:
                atxt = ""
            if _is_rating_required_alert(atxt):
                try:
                    if not _switch_to_frame(driver, ta_ifr):
                        return False, "Rating required (cannot access form)", ""
                    form_el2 = _closest_form(driver, ta)
                    _try_set_required_ratings(driver, form_el2)
                    btn_retry = _find_submit_in_form(driver, form_el2) if form_el2 is not None else None
                    if btn_retry:
                        ok2, why2 = _safe_click(driver, btn_retry, "submit")
                        if not ok2:
                            return False, why2, ""
                        time.sleep(AFTER_SUBMIT_PAUSE)
                    else:
                        return False, "Rating required (no submit after setting)", ""
                except Exception:
                    return False, "Rating required", ""
            else:
                return False, f"Unexpected alert: {atxt}".strip(), ""
    else:
        # Fallback: try strict submit selectors (global) or form.submit()
        driver.switch_to.default_content()
        btn2 = None
        btn2_ifr = None
        if selectors:
            btn2, btn2_ifr = _find_with_selector(driver, selectors.get("btn_sel"), selectors.get("btn_iframe"))
        if not btn2:
            btn2, btn2_ifr = _find_any_frame(driver, _strict_submit_selectors(), timeout=float(FIND_TIMEOUT))
        if btn2:
            if not _switch_to_frame(driver, btn2_ifr):
                return False, "Cannot enter submit iframe", ""
            ok, why = _safe_click(driver, btn2, "submit")
            if not ok:
                return False, why, ""
            time.sleep(AFTER_SUBMIT_PAUSE)
        else:
            try:
                if not _switch_to_frame(driver, ta_ifr):
                    return False, "Cannot enter textarea iframe", ""
                driver.execute_script(
                    "var el = arguments[0]; var f = el.form || el.closest('form'); if (f) { f.submit(); return true; } return false;",
                    ta,
                )
                time.sleep(AFTER_SUBMIT_PAUSE)
            except Exception:
                return False, "No submit button/form", ""

    # Kiểm tra dấu hiệu thành công / lỗi sau submit
    try:
        driver.switch_to.default_content()
    except UnexpectedAlertPresentException:
        try:
            alert = driver.switch_to.alert
            atxt = alert.text or ""
            alert.accept()
        except Exception:
            atxt = ""
        if _is_rating_required_alert(atxt):
            return False, "Rating required", ""
        return False, f"Unexpected alert: {atxt}".strip(), ""
    try:
        full_html = driver.page_source or ""
    except Exception:
        full_html = ""
    html_after = full_html.lower()
    cur_after = ""
    try:
        cur_after = (driver.current_url or "").strip()
    except Exception:
        cur_after = ""
    try:
        title_after = (driver.title or "").strip()
    except Exception:
        title_after = ""

    # Explicit HTTP block pages (common on wp-comments-post.php)
    title_low = title_after.lower()
    if "403" in title_low or "forbidden" in title_low:
        if "wp-comments-post.php" in (cur_after or "").lower():
            return False, "403 Forbidden (submit blocked)", ""
        if "403" in title_low:
            return False, "403 Forbidden", ""
    if "wp-comments-post.php" in (cur_after or "").lower():
        # Some servers return a minimal 403 page without setting a descriptive title.
        if "403 forbidden" in html_after or "access is forbidden" in html_after:
            return False, "403 Forbidden (submit blocked)", ""

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

    # Verify actual posted comment (when the page doesn't show a clear success message).
    verified_link = _verify_posted_comment(driver, name=name, comment_text=text_to_send)
    if verified_link:
        return True, "Submitted (verified)", verified_link

    # WordPress/common failure hints (must be specific; do not match normal form text like "Required fields are marked").
    if "duplicate comment" in html_after:
        return False, "Duplicate comment", ""
    if "comments are closed" in html_after:
        return False, "Comments are closed", ""
    if "you are posting comments too quickly" in html_after:
        return False, "Rate limited (posting too quickly)", ""
    if "must be logged in" in html_after:
        return False, "Login required", ""
    if "captcha" in html_after or "recaptcha" in html_after or "hcaptcha" in html_after:
        return False, "Captcha present", ""

    # Extract explicit WP error pages/messages (wp_die / ERROR: ...)
    msg = _extract_submit_error_message(full_html)
    if msg:
        if _is_rate_limit_message(msg):
            # Some sites still accept the comment but show a "too quickly" warning.
            verified_http = _verify_posted_comment_http(
                driver,
                url=cur_after or url,
                name=name,
                comment_text=text_to_send,
            )
            if verified_http:
                return True, "Submitted (verified-http)", verified_http
            return False, "Rate limited (posting too quickly)", ""
        # Common WP message for missing required fields:
        if "please fill the required fields" in msg.lower() or "please enter your" in msg.lower():
            return False, "Missing required fields", ""
        return False, msg, ""

    # Generic error hints (keep conservative)
    error_hints = [
        "error:", "there was an error", "could not be posted", "cannot be posted",
        "forbidden", "access denied",
    ]
    if any(h in html_after for h in error_hints):
        verified_http = _verify_posted_comment_http(
            driver,
            url=cur_after or url,
            name=name,
            comment_text=text_to_send,
        )
        if verified_http:
            return True, "Submitted (verified-http)", verified_http
        return False, "Submit error", ""

    # Best-effort: some sites redirect without rendering a success message.
    if cur_after and cur_after != url:
        return True, "Submitted (unverified)", cur_after
    return True, "Submitted (unverified)", ""


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
