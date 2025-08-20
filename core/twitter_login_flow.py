import logging
import threading
import time
import uuid
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext

logger = logging.getLogger(__name__)


class _LoginAttempt:
    def __init__(self, username: str, email: str, password: str, playwright, browser: Browser, context: BrowserContext, page: Page):
        self.username = username
        self.email = email
        self.password = password
        self.playwright = playwright
        self.browser = browser
        self.context = context
        self.page = page
        self.created_at = datetime.now()
        self.expires_at = self.created_at + timedelta(minutes=5)

    def close(self):
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass


_lock = threading.RLock()
_attempts: dict[str, _LoginAttempt] = {}


def _dismiss_consent(page):
    """Best-effort dismissal of cookie/consent dialogs that can block inputs."""
    try:
        selectors = [
            'button:has-text("Accept all")',
            'button:has-text("Accept all cookies")',
            'button:has-text("Allow all cookies")',
            'button:has-text("Accept")',
            'div[role="button"]:has-text("Accept")',
            'div[role="button"]:has-text("Allow all cookies")',
            '[data-testid="confirmationSheetConfirm"]',
        ]
        for sel in selectors:
            el = page.query_selector(sel)
            if el:
                el.click()
                page.wait_for_timeout(500)
                break
    except Exception:
        pass


def _infer_identifier_required(page, input_element) -> str:
    """Return one of: 'email', 'username_or_phone', or '' (unknown)."""
    try:
        text = input_element.get_attribute('placeholder') or ''
        aria = input_element.get_attribute('aria-label') or ''
        # Try to read a nearby label text (simple heuristic)
        label_text = page.evaluate(
            "el => (el.closest('label')?.innerText) || (el.parentElement?.querySelector('label')?.innerText) || ''",
            input_element
        ) or ''
        combined = f"{text} {aria} {label_text}".lower()
        if 'email' in combined and ('username' not in combined and 'phone' not in combined):
            return 'email'
        if 'phone' in combined or 'username' in combined:
            return 'username_or_phone'
    except Exception:
        pass
    return ''

def _cleanup_expired_attempts():
    with _lock:
        to_delete = []
        now = datetime.now()
        for token, attempt in _attempts.items():
            if attempt.expires_at <= now:
                try:
                    attempt.close()
                finally:
                    to_delete.append(token)
        for token in to_delete:
            _attempts.pop(token, None)


def start_login_flow(username: str, email: str, password: str) -> dict:
    """Begin Twitter/X login; stops at verification code prompt if required.

    Returns a dict with keys: success, token, verification_required, error
    """
    _cleanup_expired_attempts()
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True, args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ])
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 1600},
        )
        page = context.new_page()

        logger.info("[Twitter] Navigating to mobile login page")
        # Try the simpler mobile login flow first
        uname = (email or username).strip()
        mobile_ok = False
        try:
            page.goto("https://mobile.twitter.com/login?hide_message=1", timeout=90000)
            _dismiss_consent(page)
            page.wait_for_selector('input[name="session[username_or_email]"]', timeout=30000, state="visible")
            page.fill('input[name="session[username_or_email]"]', uname)
            page.wait_for_selector('input[name="session[password]"]', timeout=30000, state="visible")
            page.fill('input[name="session[password]"]', password)
            btn = page.query_selector('div[data-testid="LoginForm_Login_Button"]') or page.query_selector('button[type="submit"]')
            if btn:
                btn.click()
            else:
                page.keyboard.press("Enter")
            mobile_ok = True
            logger.info("[Twitter] Submitted mobile login form for %s", uname)
        except Exception:
            mobile_ok = False

        if not mobile_ok:
            logger.info("[Twitter] Mobile login unavailable; falling back to desktop flow")
            # Fallback to desktop login flow
            page.goto("https://x.com/i/flow/login", timeout=90000)
            _dismiss_consent(page)
            page.wait_for_selector('input[autocomplete="username"], input[name="text"]', timeout=40000, state="visible")
            target_input = page.query_selector('input[autocomplete="username"]') or page.query_selector('input[name="text"]')
            if target_input is None:
                raise RuntimeError("Login username/email input not found")
            # Determine which identifier is being requested on this step
            kind = _infer_identifier_required(page, target_input)
            value_to_fill = uname
            if kind == 'username_or_phone' and username:
                value_to_fill = username
            target_input.fill(value_to_fill)
            # Next
            # Try multiple variants of Next (data-testid and text)
            btn = (
                page.query_selector('div[data-testid="ocfEnterTextNextButton"]')
                or page.get_by_role("button", name="Next")
                or page.query_selector('div[role="button"]:has-text("Next")')
            )
            if btn:
                btn.click()
            else:
                target_input.press("Enter")
            # Optional extra identifier step
            try:
                page.wait_for_selector('input[name="password"], input[type="password"], input[name="text"]', timeout=40000, state="visible")
            except Exception:
                pass
            extra_identifier = page.query_selector('input[name="text"]')
            if extra_identifier and not page.query_selector('input[type="password"], input[name="password"]'):
                kind2 = _infer_identifier_required(page, extra_identifier)
                value2 = uname
                if kind2 == 'username_or_phone' and username:
                    value2 = username
                extra_identifier.fill(value2)
                btn2 = (
                    page.query_selector('div[data-testid="ocfEnterTextNextButton"]')
                    or page.get_by_role("button", name="Next")
                    or page.query_selector('div[role="button"]:has-text("Next")')
                )
                if btn2:
                    btn2.click()
                else:
                    extra_identifier.press("Enter")
            # Password field can have data-testid as well; try both
            page.wait_for_selector('input[name="password"], input[type="password"], input[data-testid="ocfEnterPasswordTextInput"]', timeout=40000, state="visible")
            pwd_input = page.query_selector('input[name="password"]') or page.query_selector('input[type="password"]') or page.query_selector('input[data-testid="ocfEnterPasswordTextInput"]')
            if pwd_input is None:
                raise RuntimeError("Password input not found")
            pwd_input.fill(password)
            login_button = (
                page.query_selector('div[data-testid="LoginForm_Login_Button"]')
                or page.get_by_role("button", name="Log in")
                or page.query_selector('div[role="button"]:has-text("Log in")')
            )
            if login_button:
                login_button.click()
            else:
                pwd_input.press("Enter")

        # Determine if verification required
        # Wait briefly; either we land in home/user or see verification input
        page.wait_for_timeout(2500)

        # Check for code input presence (mobile and desktop patterns)
        verification_input = (
            page.query_selector('input[name="challenge_response"]') or
            page.query_selector('input[autocomplete="one-time-code"]') or
            page.query_selector('input[name="text"]')
        )
        if verification_input is not None or "Enter verification code" in page.content():
            token = uuid.uuid4().hex
            with _lock:
                _attempts[token] = _LoginAttempt(username, email, password, pw, browser, context, page)
            return {"success": True, "verification_required": True, "token": token}

        # Else assume success; capture storage state
        storage_state = context.storage_state()
        cookies = context.cookies()
        try:
            context.close()
        finally:
            try:
                browser.close()
            finally:
                pw.stop()
        return {"success": True, "verification_required": False, "storage_state": storage_state, "cookies": cookies}

    except Exception as e:
        logger.error(f"Twitter login start failed: {e}")
        try:
            # Save debug artifacts
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            if 'page' in locals() and page:
                page.screenshot(path=f"/tmp/twitter_login_{ts}.png", full_page=True)
                html = page.content()
                with open(f"/tmp/twitter_login_{ts}.html", 'w', encoding='utf-8') as f:
                    f.write(html)
                logger.info("[Twitter] saved debug artifacts to /tmp/twitter_login_%s.(png|html)", ts)
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass
        return {"success": False, "error": str(e)}


def complete_login_with_code(token: str, code: str) -> dict:
    """Complete login by entering verification code; returns storage_state and cookies."""
    _cleanup_expired_attempts()
    with _lock:
        attempt = _attempts.get(token)
    if attempt is None:
        return {"success": False, "error": "Login attempt expired or not found"}

    try:
        page = attempt.page
        # Fill code; handle single or multi-input cases
        # Try a single input first
        input_box = page.query_selector('input[name="text"], input[autocomplete="one-time-code"]')
        if input_box:
            input_box.fill(code)
        else:
            # Try multiple one-char inputs
            inputs = page.query_selector_all('input[autocomplete="one-time-code"], input[type="text"]')
            if inputs and len(inputs) > 1:
                for i, ch in enumerate(code.strip()):
                    if i < len(inputs):
                        inputs[i].fill(ch)
        # Click Next/Submit
        cont = page.get_by_role("button", name="Next") or page.query_selector('div[role="button"]:has-text("Next")')
        if cont:
            cont.click()
        else:
            page.keyboard.press("Enter")

        # Wait a bit for login to finish
        page.wait_for_timeout(3000)

        storage_state = attempt.context.storage_state()
        cookies = attempt.context.cookies()

        # Cleanup and drop token
        attempt.close()
        with _lock:
            _attempts.pop(token, None)

        return {"success": True, "storage_state": storage_state, "cookies": cookies}

    except Exception as e:
        logger.error(f"Twitter login verification failed: {e}")
        try:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            if 'page' in locals() and page:
                page.screenshot(path=f"/tmp/twitter_verify_{ts}.png", full_page=True)
                with open(f"/tmp/twitter_verify_{ts}.html", 'w', encoding='utf-8') as f:
                    f.write(page.content())
                logger.info("[Twitter] saved verification debug artifacts to /tmp/twitter_verify_%s.(png|html)", ts)
        except Exception:
            pass
        try:
            attempt.close()
        finally:
            with _lock:
                _attempts.pop(token, None)
        return {"success": False, "error": str(e)}


