"""Utilities for crawling Moodle pages and extracting date-based class events."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date, timedelta
from html import unescape
from html.parser import HTMLParser
import http.cookiejar
import platform
import re
import time
from typing import Dict, List, Optional, Sequence, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


@dataclass
class MoodleEvent:
    """Represents one dated event parsed from Moodle content."""

    title: str
    category: str
    event_date: date
    time_label: str = ""
    details: str = ""
    source_url: str = ""


@dataclass
class _AnchorLink:
    """Represents one parsed anchor with href and visible text."""

    href: str
    text: str


@dataclass
class _AssignmentPageInfo:
    """Represents key metadata parsed from one assignment page."""

    url: str
    title: str
    due_date: Optional[date]
    due_time: str
    class_label: str


class _VisibleTextParser(HTMLParser):
    """Extracts readable text while skipping scripts/styles."""

    _BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "dt",
        "dd",
        "figcaption",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "p",
        "section",
        "table",
        "tr",
        "td",
        "th",
        "ul",
        "ol",
    }

    def __init__(self) -> None:
        """Initializes parser state for collecting visible text fragments."""
        super().__init__()
        self._parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, _attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        """Tracks block boundaries and enter/exit script/style skip sections."""
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        """Closes skip sections and emits line breaks for block-level end tags."""
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        """Collects visible text content while discarding pure whitespace."""
        if self._skip_depth:
            return
        if data.strip():
            self._parts.append(data)

    def get_text(self) -> str:
        """Returns the concatenated visible text."""
        return unescape("".join(self._parts))


class _LinkParser(HTMLParser):
    """Extracts links from anchor tags."""

    def __init__(self) -> None:
        """Initializes parser state for anchor href/text capture."""
        super().__init__()
        self.links: List[_AnchorLink] = []
        self._current_href: str = ""
        self._current_text_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        """Starts collecting text for each anchor tag that has an href."""
        if tag.lower() != "a":
            return
        attrs_map = {key.lower(): value for key, value in attrs if key and value is not None}
        href = attrs_map.get("href", "").strip()
        self._current_href = href
        self._current_text_parts = []

    def handle_data(self, data: str) -> None:
        """Accumulates visible text for the currently open anchor."""
        if not self._current_href:
            return
        if data.strip():
            self._current_text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        """Finalizes one anchor record with normalized visible text."""
        if tag.lower() != "a" or not self._current_href:
            return
        text = re.sub(r"\s+", " ", "".join(self._current_text_parts)).strip()
        self.links.append(_AnchorLink(href=self._current_href, text=text))
        self._current_href = ""
        self._current_text_parts = []


class _LoginFormParser(HTMLParser):
    """Finds login forms and captures hidden fields needed for submission."""

    def __init__(self) -> None:
        """Initializes parser state used while scanning form/input tags."""
        super().__init__()
        self.forms: List[Dict[str, object]] = []
        self._current_form: Optional[Dict[str, object]] = None

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        """Captures form actions plus username/password and hidden input metadata."""
        attrs_map = {key.lower(): value for key, value in attrs if key and value is not None}
        lowered_tag = tag.lower()

        if lowered_tag == "form":
            self._current_form = {
                "action": attrs_map.get("action", ""),
                "hidden_inputs": {},
                "has_username": False,
                "has_password": False,
            }
            return

        if lowered_tag != "input" or self._current_form is None:
            return

        input_name = (attrs_map.get("name") or "").strip()
        if not input_name:
            return
        input_type = (attrs_map.get("type") or "text").strip().lower()
        input_value = attrs_map.get("value", "") or ""

        if input_name.lower() == "username":
            self._current_form["has_username"] = True
        if input_name.lower() == "password" or input_type == "password":
            self._current_form["has_password"] = True
        if input_type == "hidden":
            hidden_inputs = self._current_form["hidden_inputs"]
            if isinstance(hidden_inputs, dict):
                hidden_inputs[input_name] = input_value

    def handle_endtag(self, tag: str) -> None:
        """Stores completed login-capable forms once closing tag is reached."""
        if tag.lower() != "form" or self._current_form is None:
            return
        if self._current_form.get("has_username") and self._current_form.get("has_password"):
            self.forms.append(self._current_form)
        self._current_form = None


class MoodleCrawler:
    """Crawls Moodle pages and extracts homework, quiz, and test dates."""

    _TIME_PATTERN = re.compile(r"\b(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm))\b")
    _TIME_ONLY_PATTERN = re.compile(r"^(?:\d{1,2}(?::\d{2})?\s*(?:AM|PM)|\d{1,2}\s*(?:AM|PM))$", re.IGNORECASE)
    _MONTH_PATTERN = (
        r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
        r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
    )
    _WEEKDAY_PREFIX = r"(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
    _MONTH_FIRST_PATTERN = re.compile(
        rf"\b(?:{_WEEKDAY_PREFIX},?\s+)?(?P<month>{_MONTH_PATTERN})\s+"
        rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:,)?\s+(?P<year>\d{{2,4}})\b",
        re.IGNORECASE,
    )
    _DAY_FIRST_PATTERN = re.compile(
        rf"\b(?:{_WEEKDAY_PREFIX},?\s+)?(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+"
        rf"(?P<month>{_MONTH_PATTERN})(?:,)?\s+(?P<year>\d{{2,4}})\b",
        re.IGNORECASE,
    )
    _SLASH_PATTERN = re.compile(r"\b(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{2,4})\b")
    _CATEGORY_KEYWORDS = {
        "Homework": ("homework", "assignment", "assign"),
        "Quiz": ("quiz",),
        "Test": ("test", "exam", "midterm", "final"),
    }
    _MOODLE_PATH_HINTS = (
        "/course/view.php",
        "/mod/assign/",
        "/mod/quiz/",
        "/mod/page/",
        "/calendar/view.php",
        "/my/",
    )
    _MONTH_NAME_TO_NUMBER = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    _GENERIC_TITLE_PREFIXES = (
        "due",
        "due date",
        "opens",
        "open",
        "closes",
        "available",
        "date",
    )
    _TITLE_STOP_WORDS = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "assignment",
        "homework",
        "quiz",
        "test",
        "exam",
        "done",
        "mark",
        "as",
        "view",
        "receive",
        "grade",
        "make",
        "submission",
        "feedback",
        "is",
        "are",
        "to",
        "a",
        "an",
    }
    _SSO_HOST_HINTS = (
        "microsoftonline.com",
        "okta.com",
        "duosecurity.com",
        "auth0.com",
    )
    _SSO_PATH_HINTS = ("saml", "oauth", "signin", "login", "authorize")
    _SELENIUM_WAIT_SECONDS = 25
    _MANUAL_CREDENTIAL_WAIT_SECONDS = 60
    _MANUAL_PASSWORD_WAIT_SECONDS = 60
    _MFA_WAIT_SECONDS = 60
    _MAX_FUTURE_DAYS = 730
    _EXTRA_ASSIGNMENT_PAGE_BUDGET = 120

    def __init__(self, max_pages: int = 60, timeout_seconds: int = 15) -> None:
        """Configures crawl depth and HTTP timeout behavior."""
        self.max_pages = max_pages
        self.timeout_seconds = timeout_seconds

    def crawl(
        self,
        start_url: str,
        username: str = "",
        password: str = "",
    ) -> Tuple[List[MoodleEvent], bool, str]:
        """Returns extracted Moodle events plus login requirement/message metadata."""
        normalized_url = self._normalize_input_url(start_url)
        if not normalized_url:
            return [], False, "Enter a valid Moodle URL before importing."

        opener = self._build_opener()
        try:
            first_html, first_final_url = self._fetch_html(opener, normalized_url)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            return [], False, f"Could not read Moodle page: {exc}"

        if self._requires_login(first_html, first_final_url, normalized_url):
            if self._is_external_sso_url(first_final_url, normalized_url):
                if not username or not password:
                    return (
                        [],
                        True,
                        "External SSO detected. Enter Moodle username and password so browser login can run.",
                    )
                return self._crawl_through_external_sso(normalized_url, username, password)
            if not username or not password:
                return [], True, "Login required. Enter Moodle username and password, then import again."
            login_ok, login_message = self._attempt_login(opener, normalized_url, first_html, username, password)
            if not login_ok:
                return [], True, login_message
            try:
                first_html, first_final_url = self._fetch_html(opener, normalized_url)
            except (HTTPError, URLError, TimeoutError, ValueError) as exc:
                return [], True, f"Logged in, but could not re-open Moodle page: {exc}"
            if self._requires_login(first_html, first_final_url, normalized_url):
                return [], True, "Login did not succeed. Verify credentials and Moodle URL."

        pages = self._collect_pages(opener, normalized_url, first_html)
        assignment_index = self._build_assignment_index(pages)
        events: List[MoodleEvent] = []
        for page_url, html in pages:
            events.extend(self._extract_events_from_page(page_url, html, assignment_index))

        deduped = self._dedupe_events(events)
        deduped = self._filter_event_date_window(deduped)
        if not deduped:
            return [], False, "No homework/quiz/test dates were detected on the scanned Moodle pages."
        return deduped, False, f"Detected {len(deduped)} dated Moodle items."

    def _crawl_through_external_sso(
        self,
        start_url: str,
        username: str,
        password: str,
    ) -> Tuple[List[MoodleEvent], bool, str]:
        """Uses browser automation for SSO sites, then parses Moodle pages from that session."""
        selenium_bundle = self._import_selenium()
        if selenium_bundle is None:
            return (
                [],
                True,
                "External SSO detected. Install selenium (`py -3 -m pip install selenium`) to enable automated sign-in.",
            )

        driver, browser_name, start_error = self._create_webdriver(selenium_bundle)
        if driver is None:
            return [], True, f"Could not start browser automation for SSO login: {start_error}"

        try:
            logged_in, message = self._perform_sso_login(driver, selenium_bundle, start_url, username, password)
            if not logged_in:
                return [], True, message

            pages = self._collect_pages_with_driver(driver, start_url)
        finally:
            try:
                driver.quit()
            except Exception:
                pass

        events: List[MoodleEvent] = []
        assignment_index = self._build_assignment_index(pages)
        for page_url, html in pages:
            events.extend(self._extract_events_from_page(page_url, html, assignment_index))
        deduped = self._dedupe_events(events)
        deduped = self._filter_event_date_window(deduped)
        if not deduped:
            return [], False, f"Signed in via {browser_name}, but no homework/quiz/test dates were detected."
        return deduped, False, f"Detected {len(deduped)} dated Moodle items via {browser_name} SSO session."

    def _import_selenium(self) -> Optional[Dict[str, object]]:
        """Loads selenium modules lazily so non-SSO use works without extra dependency."""
        try:
            from selenium import webdriver  # type: ignore
            from selenium.common.exceptions import TimeoutException, WebDriverException  # type: ignore
            from selenium.webdriver.chrome.options import Options as ChromeOptions  # type: ignore
            from selenium.webdriver.common.by import By  # type: ignore
            from selenium.webdriver.edge.options import Options as EdgeOptions  # type: ignore
            from selenium.webdriver.support import expected_conditions as EC  # type: ignore
            from selenium.webdriver.support.ui import WebDriverWait  # type: ignore
        except Exception:
            return None

        return {
            "webdriver": webdriver,
            "TimeoutException": TimeoutException,
            "WebDriverException": WebDriverException,
            "ChromeOptions": ChromeOptions,
            "EdgeOptions": EdgeOptions,
            "By": By,
            "EC": EC,
            "WebDriverWait": WebDriverWait,
        }

    def _create_webdriver(self, selenium_bundle: Dict[str, object]):
        """Starts a platform-appropriate webdriver for SSO automation."""
        webdriver = selenium_bundle["webdriver"]
        WebDriverException = selenium_bundle["WebDriverException"]
        EdgeOptions = selenium_bundle["EdgeOptions"]
        ChromeOptions = selenium_bundle["ChromeOptions"]

        errors: List[str] = []
        is_macos = platform.system().lower() == "darwin"

        if is_macos:
            try:
                safari_driver = webdriver.Safari()
                return safari_driver, "Safari", ""
            except WebDriverException as exc:
                errors.append(f"Safari: {exc}")

        if not is_macos:
            try:
                edge_options = EdgeOptions()
                edge_options.add_argument("--disable-gpu")
                edge_options.add_argument("--window-size=1380,980")
                edge_driver = webdriver.Edge(options=edge_options)
                return edge_driver, "Edge", ""
            except WebDriverException as exc:
                errors.append(f"Edge: {exc}")

        try:
            chrome_options = ChromeOptions()
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1380,980")
            chrome_driver = webdriver.Chrome(options=chrome_options)
            return chrome_driver, "Chrome", ""
        except WebDriverException as exc:
            errors.append(f"Chrome: {exc}")

        return None, "", "; ".join(errors) if errors else "No supported browser found."

    def _perform_sso_login(
        self,
        driver,
        selenium_bundle: Dict[str, object],
        start_url: str,
        username: str,
        password: str,
    ) -> Tuple[bool, str]:
        """Performs Microsoft-style SSO using username/password and waits for Moodle redirect."""
        By = selenium_bundle["By"]
        WebDriverWait = selenium_bundle["WebDriverWait"]
        TimeoutException = selenium_bundle["TimeoutException"]

        moodle_host = urlparse(start_url).netloc.lower()
        wait = WebDriverWait(driver, self._SELENIUM_WAIT_SECONDS)

        try:
            driver.get(start_url)
            self._wait_for_document_ready(driver)
        except Exception as exc:
            return False, f"Could not open Moodle URL in browser automation: {exc}"

        if urlparse(driver.current_url).netloc.lower() == moodle_host:
            return True, "Already authenticated."

        try:
            username_input = self._wait_for_editable_input(
                driver,
                wait,
                ((By.ID, "i0116"), (By.NAME, "loginfmt")),
            )
            if username_input is None or not self._enter_text_into_input(driver, username_input, username):
                return False, "SSO login failed: could not enter username in the Microsoft login form."
            self._click_first_if_present(driver, By, ("idSIButton9",))

            password_input = self._wait_for_editable_input(
                driver,
                wait,
                ((By.ID, "i0118"), (By.NAME, "passwd")),
            )
            if password_input is None or not self._enter_text_into_input(driver, password_input, password):
                return False, "SSO login failed: could not enter password in the Microsoft login form."
            self._click_first_if_present(driver, By, ("idSIButton9",))

            # Decline "Stay signed in?" to avoid changing account persistence.
            self._click_first_if_present(driver, By, ("idBtn_Back",))
            self._click_first_if_present(driver, By, ("idSIButton9",))
            self._wait_for_document_ready(driver)

            if self._wait_for_redirect_to_host(driver, moodle_host, self._SELENIUM_WAIT_SECONDS):
                return True, "SSO login successful."

            # Always leave the browser open for credential correction after automated submit.
            if self._wait_for_redirect_to_host(driver, moodle_host, self._MANUAL_CREDENTIAL_WAIT_SECONDS):
                return True, "SSO login successful after manual credential correction."

            # Also leave a separate window for manual password correction.
            if self._wait_for_redirect_to_host(driver, moodle_host, self._MANUAL_PASSWORD_WAIT_SECONDS):
                return True, "SSO login successful after manual password correction."

            # Then leave the browser open for phone-based MFA approval.
            if self._wait_for_redirect_to_host(driver, moodle_host, self._MFA_WAIT_SECONDS):
                return True, "SSO login successful after manual phone verification."
        except TimeoutException:
            return (
                False,
                "SSO login timed out. The provider may require MFA/extra verification that automation cannot complete.",
            )
        except Exception as exc:
            return False, f"Browser SSO login failed: {exc}"

        if self._looks_like_credential_failure(driver):
            return (
                False,
                "SSO login failed after waiting 60 seconds for username correction, 60 seconds for password correction, and 60 seconds for phone verification.",
            )
        if self._looks_like_mfa_challenge(driver):
            return False, "SSO login timed out waiting for Microsoft phone verification."
        return False, "SSO login timed out before returning to Moodle."

    def _wait_for_editable_input(self, driver, wait, locators: Sequence[Tuple[object, str]]):
        """Returns the first visible editable input among candidate locators."""
        def _find_input(d):
            """Returns the first interactable text-like input from candidate locators."""
            for by, selector in locators:
                try:
                    candidates = d.find_elements(by, selector)
                except Exception:
                    continue
                for candidate in candidates:
                    try:
                        if not candidate.is_displayed() or not candidate.is_enabled():
                            continue
                        input_type = (candidate.get_attribute("type") or "").strip().lower()
                        readonly = (candidate.get_attribute("readonly") or "").strip().lower()
                        disabled = (candidate.get_attribute("disabled") or "").strip().lower()
                        if input_type in {"hidden", "button", "submit"}:
                            continue
                        if readonly in {"readonly", "true"} or disabled in {"disabled", "true"}:
                            continue
                        return candidate
                    except Exception:
                        continue
            return None

        try:
            return wait.until(_find_input)
        except Exception:
            return None

    def _enter_text_into_input(self, driver, input_element, value: str) -> bool:
        """Enters text into an input with JS fallback for strict Edge element-state checks."""
        try:
            input_element.click()
        except Exception:
            pass

        try:
            input_element.clear()
        except Exception:
            # Some SSO pages disallow clear() temporarily; JS fallback handles this path.
            pass

        try:
            input_element.send_keys(value)
        except Exception:
            try:
                driver.execute_script(
                    "arguments[0].focus();"
                    "arguments[0].value='';"
                    "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));"
                    "arguments[0].value=arguments[1];"
                    "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));"
                    "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                    input_element,
                    value,
                )
            except Exception:
                return False

        try:
            entered_value = (input_element.get_attribute("value") or "").strip()
            return bool(entered_value)
        except Exception:
            return True

    def _click_first_if_present(self, driver, by, element_ids: Sequence[str]) -> bool:
        """Clicks the first visible+enabled element from a list of candidate IDs."""
        for element_id in element_ids:
            try:
                candidates = driver.find_elements(by.ID, element_id)
            except Exception:
                continue
            for element in candidates:
                try:
                    if element.is_displayed() and element.is_enabled():
                        try:
                            element.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", element)
                        return True
                except Exception:
                    continue
        return False

    def _wait_for_document_ready(self, driver, timeout_seconds: int = 12) -> None:
        """Waits for browser document readiness where possible."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                ready_state = driver.execute_script("return document.readyState")
            except Exception:
                return
            if str(ready_state).lower() == "complete":
                return
            time.sleep(0.2)

    def _wait_for_redirect_to_host(self, driver, expected_host: str, timeout_seconds: int) -> bool:
        """Waits until the browser is redirected to the expected host."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            current_host = urlparse(str(getattr(driver, "current_url", ""))).netloc.lower()
            if current_host == expected_host:
                return True
            time.sleep(0.4)
        current_host = urlparse(str(getattr(driver, "current_url", ""))).netloc.lower()
        return current_host == expected_host

    def _looks_like_credential_failure(self, driver) -> bool:
        """Detects common Microsoft SSO credential failure messages."""
        page = (driver.page_source or "").lower()
        url_hint = (driver.current_url or "").lower()
        return any(
            token in page or token in url_hint
            for token in (
                "your account or password is incorrect",
                "incorrect password",
                "incorrect username",
                "that microsoft account doesn't exist",
                "we couldn't find an account with that username",
                "enter a valid email address",
                "invalid username",
                "invalid password",
                "try again",
            )
        )

    def _looks_like_mfa_challenge(self, driver) -> bool:
        """Detects common Microsoft SSO two-factor challenge pages."""
        page = (driver.page_source or "").lower()
        url_hint = (driver.current_url or "").lower()
        return any(
            token in page or token in url_hint
            for token in (
                "approve sign in request",
                "check your phone",
                "microsoft authenticator",
                "verify your identity",
                "verification code",
                "two-step verification",
                "security info",
                "additional security verification",
                "enter code",
                "multi-factor authentication",
                "mfa",
            )
        )

    def _collect_pages_with_driver(self, driver, start_url: str) -> List[Tuple[str, str]]:
        """Collects Moodle pages by following candidate links in an authenticated browser session."""
        root_host = urlparse(start_url).netloc.lower()
        current_url = driver.current_url or start_url
        first_html = driver.page_source or ""

        pages: List[Tuple[str, str]] = [(current_url, first_html)]
        visited: Set[str] = {self._canonical_url(current_url)}
        queue = deque(self._extract_candidate_links(current_url, first_html, start_url))

        while queue and len(pages) < self.max_pages:
            next_url = queue.popleft()
            canonical = self._canonical_url(next_url)
            if canonical in visited:
                continue
            visited.add(canonical)

            try:
                driver.get(next_url)
                self._wait_for_document_ready(driver)
            except Exception:
                continue

            final_url = driver.current_url
            final_host = urlparse(final_url).netloc.lower()
            if final_host != root_host:
                continue

            html = driver.page_source or ""
            if self._requires_login(html, final_url, start_url):
                continue

            pages.append((final_url, html))
            for link in self._extract_candidate_links(final_url, html, start_url):
                if self._canonical_url(link) not in visited:
                    queue.append(link)

        self._expand_with_assignment_pages_driver(
            driver=driver,
            root_url=start_url,
            root_host=root_host,
            pages=pages,
            visited=visited,
            max_extra_pages=self._EXTRA_ASSIGNMENT_PAGE_BUDGET,
        )
        return pages

    def _build_opener(self):
        """Creates an opener with cookie persistence for session authentication."""
        cookie_jar = http.cookiejar.CookieJar()
        return build_opener(HTTPCookieProcessor(cookie_jar))

    def _fetch_html(self, opener, url: str) -> Tuple[str, str]:
        """Fetches one HTML page and returns its body plus final resolved URL."""
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 MoodleCalendarBot/1.0",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with opener.open(request, timeout=self.timeout_seconds) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(charset, errors="replace")
            return html, response.geturl()

    def _requires_login(self, html: str, final_url: str, root_url: str) -> bool:
        """Checks whether page content appears to be a login or SSO gateway page."""
        if self._is_external_sso_url(final_url, root_url):
            return True

        lower = html.lower()
        has_username_field = 'name="username"' in lower or "name='username'" in lower
        has_password_field = 'name="password"' in lower or "name='password'" in lower
        has_common_login_inputs = any(
            token in lower
            for token in (
                'type="password"',
                "type='password'",
                'id="i0116"',  # Microsoft login username input
                "sign in to your account",
            )
        )
        has_login_indicator = any(
            token in lower
            for token in (
                "/login/index.php",
                "log in",
                "login",
                "sign in",
                "authentication",
                "single sign-on",
                "sso",
                "microsoft",
            )
        )
        parsed_final = urlparse(final_url)
        path_hint = f"{parsed_final.path}?{parsed_final.query}".lower()
        path_looks_like_login = any(token in path_hint for token in self._SSO_PATH_HINTS)
        if parsed_final.netloc.lower() != urlparse(root_url).netloc.lower() and path_looks_like_login:
            return True

        return (has_username_field and has_password_field) or (
            has_login_indicator and ("you are not logged in" in lower or has_common_login_inputs or path_looks_like_login)
        )

    def _is_external_sso_url(self, final_url: str, root_url: str) -> bool:
        """Returns True when redirected from Moodle host to a known external SSO host."""
        final_parsed = urlparse(final_url)
        root_parsed = urlparse(root_url)
        final_host = final_parsed.netloc.lower()
        root_host = root_parsed.netloc.lower()
        if not final_host or final_host == root_host:
            return False
        return any(host_hint in final_host for host_hint in self._SSO_HOST_HINTS)

    def _attempt_login(
        self,
        opener,
        start_url: str,
        html: str,
        username: str,
        password: str,
    ) -> Tuple[bool, str]:
        """Attempts Moodle form login using discovered hidden tokens."""
        form_parser = _LoginFormParser()
        form_parser.feed(html)
        form = form_parser.forms[0] if form_parser.forms else None

        login_url = urljoin(start_url, "/login/index.php")
        payload: Dict[str, str] = {}
        if form is not None:
            action = str(form.get("action") or "").strip()
            if action:
                login_url = urljoin(start_url, action)
            hidden_inputs = form.get("hidden_inputs", {})
            if isinstance(hidden_inputs, dict):
                payload.update({str(key): str(value) for key, value in hidden_inputs.items()})

        payload["username"] = username
        payload["password"] = password
        request = Request(
            login_url,
            data=urlencode(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Mozilla/5.0 MoodleCalendarBot/1.0",
            },
        )
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                _ = response.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            return False, f"Could not submit Moodle login form: {exc}"

        return True, "Login successful."

    def _collect_pages(self, opener, start_url: str, start_html: str) -> List[Tuple[str, str]]:
        """Crawls a limited set of Moodle pages likely to contain assignment dates."""
        pages: List[Tuple[str, str]] = [(start_url, start_html)]
        visited: Set[str] = {self._canonical_url(start_url)}
        queue = deque(self._extract_candidate_links(start_url, start_html, start_url))

        while queue and len(pages) < self.max_pages:
            next_url = queue.popleft()
            canonical = self._canonical_url(next_url)
            if canonical in visited:
                continue
            visited.add(canonical)

            try:
                html, final_url = self._fetch_html(opener, next_url)
            except (HTTPError, URLError, TimeoutError, ValueError):
                continue
            if self._requires_login(html, final_url, start_url):
                continue

            pages.append((final_url, html))
            for link in self._extract_candidate_links(final_url, html, start_url):
                if self._canonical_url(link) not in visited:
                    queue.append(link)

        self._expand_with_assignment_pages(
            opener=opener,
            root_url=start_url,
            root_host=urlparse(start_url).netloc.lower(),
            pages=pages,
            visited=visited,
            max_extra_pages=self._EXTRA_ASSIGNMENT_PAGE_BUDGET,
        )
        return pages

    def _expand_with_assignment_pages(
        self,
        opener,
        root_url: str,
        root_host: str,
        pages: List[Tuple[str, str]],
        visited: Set[str],
        max_extra_pages: int,
    ) -> None:
        """Fetches assignment pages discovered from crawled pages to improve coverage."""
        remaining_budget = max_extra_pages
        while remaining_budget > 0:
            targets = self._collect_assignment_targets_from_pages(pages, root_url, visited)
            if not targets:
                return

            fetched_any = False
            for target_url in targets:
                if remaining_budget <= 0:
                    break
                canonical_target = self._canonical_url(target_url)
                if canonical_target in visited:
                    continue
                visited.add(canonical_target)

                try:
                    html, final_url = self._fetch_html(opener, target_url)
                except (HTTPError, URLError, TimeoutError, ValueError):
                    continue
                if urlparse(final_url).netloc.lower() != root_host:
                    continue
                if self._requires_login(html, final_url, root_url):
                    continue

                pages.append((final_url, html))
                visited.add(self._canonical_url(final_url))
                remaining_budget -= 1
                fetched_any = True

            if not fetched_any:
                return

    def _expand_with_assignment_pages_driver(
        self,
        driver,
        root_url: str,
        root_host: str,
        pages: List[Tuple[str, str]],
        visited: Set[str],
        max_extra_pages: int,
    ) -> None:
        """Visits discovered assignment pages in an authenticated webdriver session."""
        remaining_budget = max_extra_pages
        while remaining_budget > 0:
            targets = self._collect_assignment_targets_from_pages(pages, root_url, visited)
            if not targets:
                return

            fetched_any = False
            for target_url in targets:
                if remaining_budget <= 0:
                    break
                canonical_target = self._canonical_url(target_url)
                if canonical_target in visited:
                    continue
                visited.add(canonical_target)

                try:
                    driver.get(target_url)
                    self._wait_for_document_ready(driver)
                except Exception:
                    continue

                final_url = driver.current_url
                if urlparse(final_url).netloc.lower() != root_host:
                    continue
                html = driver.page_source or ""
                if self._requires_login(html, final_url, root_url):
                    continue

                pages.append((final_url, html))
                visited.add(self._canonical_url(final_url))
                remaining_budget -= 1
                fetched_any = True

            if not fetched_any:
                return

    def _collect_assignment_targets_from_pages(
        self,
        pages: List[Tuple[str, str]],
        root_url: str,
        visited: Set[str],
    ) -> List[str]:
        """Collects unseen assignment URLs from crawled page content."""
        root_host = urlparse(root_url).netloc.lower()
        targets: List[str] = []
        seen_targets: Set[str] = set()

        for page_url, html in pages:
            anchors = self._extract_anchor_links(page_url, html)
            for anchor in anchors:
                if not self._is_assignment_page_url(anchor.href):
                    continue
                normalized = self._to_submission_page_url(anchor.href)
                parsed = urlparse(normalized)
                if parsed.netloc.lower() != root_host:
                    continue
                canonical = self._canonical_url(normalized)
                if canonical in visited or canonical in seen_targets:
                    continue
                seen_targets.add(canonical)
                targets.append(normalized)

            for submission_link in self._extract_submission_action_links_from_html(page_url, html, root_host):
                if not self._is_assignment_page_url(submission_link):
                    continue
                normalized = self._to_submission_page_url(submission_link)
                canonical = self._canonical_url(normalized)
                if canonical in visited or canonical in seen_targets:
                    continue
                seen_targets.add(canonical)
                targets.append(normalized)

        targets.sort(key=self._crawl_link_priority)
        return targets

    def _extract_candidate_links(self, base_url: str, html: str, root_url: str) -> List[str]:
        """Returns same-site links that likely lead to relevant Moodle content."""
        parser = _LinkParser()
        parser.feed(html)
        links: List[str] = []
        root_host = urlparse(root_url).netloc.lower()

        for anchor in parser.links:
            href = anchor.href
            if href.startswith("#") or href.lower().startswith(("mailto:", "javascript:")):
                continue
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            if parsed.netloc.lower() != root_host:
                continue

            path_hint = f"{parsed.path}?{parsed.query}".lower()
            if not any(token in path_hint for token in self._MOODLE_PATH_HINTS):
                continue
            links.append(absolute)

        # Moodle "Add submission" buttons may be rendered outside anchor tags.
        links.extend(self._extract_submission_action_links_from_html(base_url, html, root_host))

        # Preserve order while removing duplicates.
        unique_links: List[str] = []
        seen: Set[str] = set()
        for link in links:
            canonical = self._canonical_url(link)
            if canonical in seen:
                continue
            seen.add(canonical)
            unique_links.append(link)
        unique_links.sort(key=self._crawl_link_priority)
        return unique_links

    def _extract_submission_action_links_from_html(
        self,
        base_url: str,
        html: str,
        root_host: str = "",
    ) -> List[str]:
        """Extracts assignment submission URLs from raw Moodle HTML/button/script content."""
        pattern = re.compile(
            r"(?P<url>(?:https?://[^\"'<>\s]+)?/mod/assign/view\.php\?[^\"'<>\s]*"
            r"(?:action=editsubmission|action=submit)[^\"'<>\s]*)",
            re.IGNORECASE,
        )

        links: List[str] = []
        seen: Set[str] = set()
        for match in pattern.finditer(html):
            raw_url = unescape(match.group("url")).strip()
            raw_url = raw_url.strip("\"'<>")
            raw_url = raw_url.rstrip(");,")
            absolute = urljoin(base_url, raw_url)
            parsed = urlparse(absolute)
            if root_host and parsed.netloc.lower() != root_host.lower():
                continue
            canonical = self._canonical_url(absolute)
            if canonical in seen:
                continue
            seen.add(canonical)
            links.append(absolute)
        return links

    def _crawl_link_priority(self, link: str) -> Tuple[int, str]:
        """Sort key to discover course coverage first, then activity detail pages."""
        lowered = link.lower()
        if "/course/view.php" in lowered:
            return (0, lowered)
        if "/calendar/view.php" in lowered:
            return (1, lowered)
        if "/my/" in lowered:
            return (2, lowered)
        if "/mod/assign/" in lowered:
            return (3, lowered)
        if "/mod/quiz/" in lowered:
            return (4, lowered)
        return (5, lowered)

    def _extract_events_from_page(
        self,
        page_url: str,
        html: str,
        assignment_index: Optional[Dict[str, _AssignmentPageInfo]] = None,
    ) -> List[MoodleEvent]:
        """Parses one Moodle page into structured date-based events."""
        plain_text = self._html_to_plain_text(html)
        lines = [self._normalize_whitespace(line) for line in plain_text.splitlines()]
        lines = [line for line in lines if line]
        page_links = self._extract_anchor_links(page_url, html)
        page_has_assignment_links = any(self._is_assignment_page_url(anchor.href) for anchor in page_links)
        if not page_has_assignment_links:
            page_has_assignment_links = bool(self._extract_submission_action_links_from_html(page_url, html))
        class_label = self._extract_class_label(page_url, page_links, lines)
        assignment_index = assignment_index or {}

        if self._is_assignment_page_url(page_url):
            assignment_event = self._extract_assignment_page_event(
                page_url,
                lines,
                class_label,
                assignment_index,
            )
            return [assignment_event] if assignment_event is not None else []

        events: List[MoodleEvent] = []
        seen_page_keys: Set[Tuple[str, str, str, str]] = set()
        for index, line in enumerate(lines):
            category = self._detect_category(line, page_url)
            if category is None:
                local_context = " ".join(lines[max(0, index - 1) : min(len(lines), index + 2)])
                category = self._detect_category(local_context, page_url)
            if category is None and page_has_assignment_links:
                local_context = " ".join(lines[max(0, index - 1) : min(len(lines), index + 2)])
                if self._looks_date_related(local_context.lower()):
                    category = "Homework"
            if category is None:
                continue

            parsed_context = ""
            parsed_date: Optional[Tuple[date, str]] = None
            context_candidates = [
                line,
                " ".join(lines[index : min(len(lines), index + 2)]),
                " ".join(lines[max(0, index - 1) : index + 1]),
            ]
            for candidate in context_candidates:
                parsed_date = self._extract_first_date(candidate)
                if parsed_date is not None:
                    parsed_context = candidate
                    break
            if parsed_date is None:
                continue
            event_date, time_label = parsed_date

            if not self._is_relevant_schedule_context(category, parsed_context):
                continue

            raw_title = self._derive_title(lines, index, category)
            if not raw_title:
                raw_title = f"{category} item"

            source_url = page_url
            if category == "Homework":
                source_url = self._resolve_homework_submission_url(
                    page_url,
                    page_links,
                    raw_title,
                    event_date,
                    time_label,
                    class_label,
                    assignment_index,
                )
            elif category in {"Quiz", "Test"}:
                source_url = self._resolve_quiz_test_url(
                    page_url,
                    page_links,
                    raw_title,
                    category,
                    event_date,
                    time_label,
                    class_label,
                    assignment_index,
                )

            title = raw_title
            if category == "Homework":
                low_confidence_title = self._is_low_confidence_homework_title(raw_title)
                if low_confidence_title and source_url == page_url:
                    # Skip generic homework rows unless they were confidently mapped to an assignment page.
                    continue

                resolved_class_label = class_label
                info = assignment_index.get(self._canonical_url(self._to_submission_page_url(source_url)))
                if info is not None and info.class_label:
                    resolved_class_label = info.class_label

                base_title = raw_title
                if self._is_low_confidence_homework_title(base_title) and info is not None:
                    indexed_title = self._clean_assignment_title(info.title, resolved_class_label)
                    if indexed_title and not self._is_low_confidence_homework_title(indexed_title):
                        base_title = indexed_title

                if self._is_low_confidence_homework_title(base_title):
                    base_title = "Homework item"
                title = self._with_class_label(base_title, resolved_class_label)

            event_key = (
                event_date.isoformat(),
                category.lower(),
                title.lower(),
                time_label.lower(),
            )
            if event_key in seen_page_keys:
                continue
            seen_page_keys.add(event_key)

            details = f"{parsed_context}\nSource: {source_url}"
            events.append(
                MoodleEvent(
                    title=title,
                    category=category,
                    event_date=event_date,
                    time_label=time_label,
                    details=details,
                    source_url=source_url,
                )
            )

        return events

    def _extract_anchor_links(self, base_url: str, html: str) -> List[_AnchorLink]:
        """Returns absolute in-page links with visible text."""
        parser = _LinkParser()
        parser.feed(html)
        anchors: List[_AnchorLink] = []
        for anchor in parser.links:
            href = anchor.href.strip()
            if not href or href.startswith("#") or href.lower().startswith(("mailto:", "javascript:")):
                continue
            absolute = urljoin(base_url, href)
            anchors.append(_AnchorLink(href=absolute, text=self._normalize_whitespace(anchor.text)))
        return anchors

    def _build_assignment_index(self, pages: List[Tuple[str, str]]) -> Dict[str, _AssignmentPageInfo]:
        """Builds an index of assignment pages keyed by canonical submission URL."""
        index: Dict[str, _AssignmentPageInfo] = {}
        for page_url, html in pages:
            plain_text = self._html_to_plain_text(html)
            lines = [self._normalize_whitespace(line) for line in plain_text.splitlines()]
            lines = [line for line in lines if line]
            anchors = self._extract_anchor_links(page_url, html)
            class_label = self._extract_class_label(page_url, anchors, lines)

            # Seed metadata from assignment links even when assignment pages are not crawled.
            for anchor in anchors:
                if not self._is_assignment_page_url(anchor.href):
                    continue
                normalized_anchor_url = self._to_submission_page_url(anchor.href)
                key = self._canonical_url(normalized_anchor_url)
                anchor_title = self._normalize_whitespace(anchor.text) or "Homework item"
                existing = index.get(key)
                if existing is None:
                    index[key] = _AssignmentPageInfo(
                        url=normalized_anchor_url,
                        title=anchor_title,
                        due_date=None,
                        due_time="",
                        class_label=class_label,
                    )
                else:
                    if not existing.class_label and class_label:
                        existing.class_label = class_label
                    if (not existing.title or existing.title.lower().endswith("item")) and anchor_title:
                        existing.title = anchor_title
            for submission_link in self._extract_submission_action_links_from_html(page_url, html):
                if not self._is_assignment_page_url(submission_link):
                    continue
                normalized_link = self._to_submission_page_url(submission_link)
                key = self._canonical_url(normalized_link)
                existing = index.get(key)
                if existing is None:
                    index[key] = _AssignmentPageInfo(
                        url=normalized_link,
                        title="Homework item",
                        due_date=None,
                        due_time="",
                        class_label=class_label,
                    )
                elif not existing.class_label and class_label:
                    existing.class_label = class_label

            if not self._is_assignment_page_url(page_url):
                continue

            due_date, due_time = self._extract_due_datetime_from_lines(lines)

            title = ""
            for line in lines:
                if not line:
                    continue
                if self._looks_generic(line):
                    continue
                lowered = line.lower()
                if any(token in lowered for token in ("dashboard", "my courses", "assignment", "submission status")):
                    # Allow assignment headings like "Assignment 2", but avoid global navigation labels.
                    if lowered.startswith("assignment "):
                        title = line
                        break
                    continue
                title = line
                break
            if not title:
                title = "Homework item"

            normalized_url = self._to_submission_page_url(page_url)
            key = self._canonical_url(normalized_url)
            existing = index.get(key)
            if existing is None:
                index[key] = _AssignmentPageInfo(
                    url=normalized_url,
                    title=title,
                    due_date=due_date,
                    due_time=due_time,
                    class_label=class_label,
                )
            else:
                existing.url = normalized_url
                if title:
                    existing.title = title
                if due_date is not None:
                    existing.due_date = due_date
                if due_time:
                    existing.due_time = due_time
                if class_label:
                    existing.class_label = class_label
        return index

    def _extract_due_datetime_from_lines(self, lines: List[str]) -> Tuple[Optional[date], str]:
        """Finds the most likely due date/time from plain-text page lines."""
        for idx, line in enumerate(lines):
            lowered = line.lower()
            if "due" not in lowered:
                continue
            parsed = self._extract_first_date(line)
            if parsed is not None:
                return parsed
            if idx + 1 < len(lines):
                parsed = self._extract_first_date(f"{line} {lines[idx + 1]}")
                if parsed is not None:
                    return parsed
                parsed = self._extract_first_date(lines[idx + 1])
                if parsed is not None:
                    return parsed

        for idx, line in enumerate(lines):
            lowered = line.lower()
            if "close" not in lowered and "deadline" not in lowered:
                continue
            parsed = self._extract_first_date(line)
            if parsed is not None:
                return parsed
            if idx + 1 < len(lines):
                parsed = self._extract_first_date(f"{line} {lines[idx + 1]}")
                if parsed is not None:
                    return parsed

        for line in lines:
            parsed = self._extract_first_date(line)
            if parsed is not None:
                return parsed
        return None, ""

    def _extract_class_label(self, page_url: str, anchors: List[_AnchorLink], lines: List[str]) -> str:
        """Extracts a class/course label from breadcrumbs or course links."""
        parsed_page = urlparse(page_url)
        page_query = {key.lower(): value for key, value in parse_qsl(parsed_page.query, keep_blank_values=True)}
        page_course_id = page_query.get("id", "").strip()
        if page_course_id and "/course/view.php" in parsed_page.path.lower():
            for anchor in anchors:
                parsed_anchor = urlparse(anchor.href)
                if "/course/view.php" not in parsed_anchor.path.lower():
                    continue
                anchor_query = {key.lower(): value for key, value in parse_qsl(parsed_anchor.query, keep_blank_values=True)}
                if anchor_query.get("id", "").strip() != page_course_id:
                    continue
                text = self._normalize_whitespace(anchor.text)
                lowered = text.lower()
                if text and lowered not in {"dashboard", "home", "my courses", "courses", "course"}:
                    return text

        label_candidates: List[str] = []
        for anchor in anchors:
            if "/course/view.php" not in anchor.href.lower():
                continue
            text = self._normalize_whitespace(anchor.text)
            lowered = text.lower()
            if not text or lowered in {"dashboard", "home", "my courses", "courses", "course"}:
                continue
            label_candidates.append(text)

        unique_labels = list(dict.fromkeys(label_candidates))
        if len(unique_labels) == 1:
            # Breadcrumb links are generally ordered from general to specific; use the most specific course label.
            return unique_labels[0]
        if len(unique_labels) > 1:
            # Multiple course links on one page (e.g., dashboard) are ambiguous for per-event class labelling.
            return ""

        for line in lines[:20]:
            match = re.search(r"\b[A-Z]{3,5}\s*[- ]\s*\d{3,4}\b", line)
            if match:
                return self._normalize_whitespace(match.group(0))
            compact_match = re.search(r"\b[A-Z]{2,6}\d{3,4}(?:-\d{3})?(?:-\d{6})?\b", line)
            if compact_match:
                return self._normalize_whitespace(compact_match.group(0))

        parsed = urlparse(page_url)
        query_map = {key.lower(): value for key, value in parse_qsl(parsed.query, keep_blank_values=True)}
        course_id = query_map.get("id", "").strip()
        if course_id and "/course/view.php" in parsed.path.lower():
            return f"Course {course_id}"
        return ""

    def _with_class_label(self, title: str, class_label: str) -> str:
        """Prefixes the title with class context when not already present."""
        if not class_label:
            return title
        lowered_title = title.lower()
        lowered_label = class_label.lower()
        if lowered_label in lowered_title:
            return title
        return f"[{class_label}] {title}"

    def _extract_assignment_page_event(
        self,
        page_url: str,
        lines: List[str],
        page_class_label: str,
        assignment_index: Dict[str, _AssignmentPageInfo],
    ) -> Optional[MoodleEvent]:
        """Parses one assignment page into a single due-date homework event."""
        source_url = self._to_submission_page_url(page_url)
        info = assignment_index.get(self._canonical_url(source_url))

        due_context, parsed_due = self._extract_due_context_from_lines(lines)
        due_date: Optional[date] = None
        due_time = ""
        if parsed_due is not None:
            due_date, due_time = parsed_due
        elif info is not None and info.due_date is not None:
            due_date, due_time = info.due_date, info.due_time

        if due_date is None:
            return None

        class_label = page_class_label
        if info is not None and info.class_label:
            class_label = info.class_label

        base_title = ""
        if info is not None:
            base_title = info.title
        base_title = self._clean_assignment_title(base_title, class_label)
        if not base_title:
            base_title = self._derive_title(lines, 0, "Homework")
            base_title = self._clean_assignment_title(base_title, class_label)
        if not base_title:
            base_title = "Homework item"

        if not class_label and info is not None:
            class_label = self._infer_class_label_from_text(info.title)

        title = self._with_class_label(base_title, class_label)
        details_line = due_context or f"Due: {due_date.isoformat()} {due_time}".strip()
        details = f"{details_line}\nSource: {source_url}"
        return MoodleEvent(
            title=title,
            category="Homework",
            event_date=due_date,
            time_label=due_time,
            details=details,
            source_url=source_url,
        )

    def _extract_due_context_from_lines(self, lines: List[str]) -> Tuple[str, Optional[Tuple[date, str]]]:
        """Returns the most relevant due/close context line and parsed date/time."""
        for idx, line in enumerate(lines):
            lowered = line.lower()
            if not any(token in lowered for token in ("due", "closes", "closed", "deadline", "close:")):
                continue
            parsed = self._extract_first_date(line)
            if parsed is not None:
                return line, parsed
            if idx + 1 < len(lines):
                combined = f"{line} {lines[idx + 1]}".strip()
                parsed = self._extract_first_date(combined)
                if parsed is not None:
                    return combined, parsed
                parsed = self._extract_first_date(lines[idx + 1])
                if parsed is not None:
                    return lines[idx + 1], parsed
        return "", None

    def _clean_assignment_title(self, title: str, class_label: str) -> str:
        """Normalizes assignment titles extracted from noisy page text."""
        cleaned = self._normalize_whitespace(title)
        if not cleaned:
            return ""
        cleaned = re.sub(r"(?i)^skip to main content\s*", "", cleaned).strip()
        cleaned = re.sub(r"\s*\|\s*home.*$", "", cleaned, flags=re.IGNORECASE).strip()
        if class_label and cleaned.lower().startswith(class_label.lower() + ":"):
            cleaned = cleaned[len(class_label) + 1 :].strip()

        if cleaned.lower() in {"overview", "completion requirements", "home"}:
            return ""
        return cleaned

    def _infer_class_label_from_text(self, text: str) -> str:
        """Infers course code from heading text when explicit class labels are unavailable."""
        normalized = self._normalize_whitespace(text)
        if not normalized:
            return ""
        match = re.match(r"^([A-Z]{2,6}\d{3,4}(?:-\d{3})?(?:-\d{6})?)", normalized)
        if match:
            return match.group(1)
        return ""

    def _is_relevant_schedule_context(self, category: str, text: str) -> bool:
        """Keeps only date lines relevant to due/test/quiz scheduling."""
        lowered = text.lower()
        if category == "Homework":
            return any(token in lowered for token in ("due", "closes", "closed", "deadline", "close:"))
        if category == "Quiz":
            return any(token in lowered for token in ("quiz", "due", "closes", "deadline", "exam", "test", "date"))
        if category == "Test":
            return any(token in lowered for token in ("test", "exam", "midterm", "final", "due", "date", "deadline"))
        return True

    def _is_low_confidence_homework_title(self, title: str) -> bool:
        """Returns True when homework title text is too generic for reliable link matching."""
        lowered = title.lower()
        if self._looks_generic(title):
            return True
        return any(
            token in lowered
            for token in (
                "mark as done",
                "feedback",
                "completion requirements",
                "overview",
                "done:view",
            )
        )

    def _resolve_homework_submission_url(
        self,
        page_url: str,
        anchors: List[_AnchorLink],
        event_title: str,
        event_date: date,
        event_time_label: str,
        class_label: str,
        assignment_index: Dict[str, _AssignmentPageInfo],
    ) -> str:
        """Chooses the best Moodle assignment submission URL for a homework event."""
        if self._is_assignment_page_url(page_url):
            direct_link = self._find_submission_action_link(anchors)
            if direct_link:
                return self._to_submission_page_url(direct_link)
            return self._to_submission_page_url(page_url)

        candidates: List[_AnchorLink] = []
        for anchor in anchors:
            if self._is_assignment_page_url(anchor.href):
                candidates.append(anchor)
        if not candidates:
            return page_url

        title_tokens = self._tokenize_title(event_title)

        best_score = -10_000
        best_url = candidates[0].href
        best_info: Optional[_AssignmentPageInfo] = None
        best_has_due_mismatch = False
        best_due_match_score = -10_000
        best_due_match_url = ""
        low_confidence_title = self._is_low_confidence_homework_title(event_title)
        for candidate in candidates:
            normalized_candidate = self._to_submission_page_url(candidate.href)
            score = 0
            has_due_mismatch = False

            link_tokens = self._tokenize_title(candidate.text)
            score += len(title_tokens.intersection(link_tokens)) * 4

            info = assignment_index.get(self._canonical_url(normalized_candidate))
            if info is not None:
                if info.due_date == event_date:
                    score += 220
                    if score > best_due_match_score:
                        best_due_match_score = score
                        best_due_match_url = normalized_candidate
                elif info.due_date is not None:
                    score -= 240
                    has_due_mismatch = True
                if event_time_label and info.due_time and info.due_time.lower() == event_time_label.lower():
                    score += 25
                elif event_time_label and info.due_time:
                    score -= 20
                info_tokens = self._tokenize_title(info.title)
                score += len(title_tokens.intersection(info_tokens)) * 6
                if class_label and info.class_label and class_label.lower() == info.class_label.lower():
                    score += 20
                elif class_label and info.class_label:
                    score -= 30
            elif "/mod/assign/view.php" in normalized_candidate.lower():
                score += 2

            if score > best_score:
                best_score = score
                best_url = normalized_candidate
                best_info = info
                best_has_due_mismatch = has_due_mismatch
        if best_due_match_url:
            return self._to_submission_page_url(best_due_match_url)
        if low_confidence_title:
            return page_url
        if best_has_due_mismatch and best_info is not None and best_info.due_date is not None:
            return page_url
        if best_score >= 32:
            return self._to_submission_page_url(best_url)

        # Low-confidence generic rows should not be force-mapped to a random assignment.
        return page_url

    def _is_assignment_page_url(self, url: str) -> bool:
        """Returns True for Moodle assignment URLs."""
        parsed = urlparse(url)
        return "/mod/assign/view.php" in parsed.path.lower() or "/mod/assign/" in parsed.path.lower()

    def _find_submission_action_link(self, anchors: List[_AnchorLink]) -> str:
        """Finds explicit assignment submission links from available anchors."""
        for anchor in anchors:
            parsed = urlparse(anchor.href)
            if not self._is_assignment_page_url(anchor.href):
                continue
            query_map = {key.lower(): value for key, value in parse_qsl(parsed.query, keep_blank_values=True)}
            action = query_map.get("action", "").strip().lower()
            text = anchor.text.lower()
            if action in {"editsubmission", "submit"}:
                return anchor.href
            if "add submission" in text or "edit submission" in text or "submission" in text:
                return anchor.href
        return ""

    def _to_submission_page_url(self, assignment_url: str) -> str:
        """Normalizes assignment URLs to submission-page variants."""
        if not self._is_assignment_page_url(assignment_url):
            return assignment_url

        parsed = urlparse(assignment_url)
        existing_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        query_pairs: List[Tuple[str, str]] = []
        has_action = False
        for key, value in existing_pairs:
            if key.lower() == "action":
                has_action = True
                if value.strip().lower() in {"editsubmission", "submit"}:
                    query_pairs.append((key, value))
                continue
            query_pairs.append((key, value))

        if not has_action:
            query_pairs.append(("action", "editsubmission"))
        elif not any(k.lower() == "action" for k, _ in query_pairs):
            query_pairs.append(("action", "editsubmission"))

        normalized_query = urlencode(query_pairs, doseq=True)
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                normalized_query,
                parsed.fragment,
            )
        )

    def _tokenize_title(self, value: str) -> Set[str]:
        """Normalizes a title into informative tokens for fuzzy matching."""
        raw_tokens = re.findall(r"[a-z0-9]+", value.lower())
        return {
            token
            for token in raw_tokens
            if len(token) >= 2 and token not in self._TITLE_STOP_WORDS
        }

    def _resolve_quiz_test_url(
        self,
        page_url: str,
        anchors: List[_AnchorLink],
        event_title: str,
        category: str,
        event_date: date,
        event_time_label: str,
        class_label: str,
        assignment_index: Dict[str, _AssignmentPageInfo],
    ) -> str:
        """Chooses the best quiz/test module URL for quiz or test events."""
        if self._is_quiz_page_url(page_url):
            return self._to_quiz_page_url(page_url)

        candidates: List[_AnchorLink] = []
        for anchor in anchors:
            if self._is_quiz_page_url(anchor.href):
                candidates.append(anchor)
        if not candidates:
            if category == "Test":
                return self._resolve_homework_submission_url(
                    page_url,
                    anchors,
                    event_title,
                    event_date,
                    event_time_label,
                    class_label,
                    assignment_index,
                )
            return page_url

        title_tokens = self._tokenize_title(event_title)
        if not title_tokens:
            return self._to_quiz_page_url(candidates[0].href)

        best_score = -1
        best_url = candidates[0].href
        for candidate in candidates:
            link_tokens = self._tokenize_title(candidate.text)
            score = len(title_tokens.intersection(link_tokens))
            if score > best_score:
                best_score = score
                best_url = candidate.href
        resolved_quiz_url = self._to_quiz_page_url(best_url)

        if category == "Test" and "/course/view.php" in resolved_quiz_url.lower():
            return self._resolve_homework_submission_url(
                page_url,
                anchors,
                event_title,
                event_date,
                event_time_label,
                class_label,
                assignment_index,
            )
        return resolved_quiz_url

    def _is_quiz_page_url(self, url: str) -> bool:
        """Returns True for Moodle quiz module URLs."""
        parsed = urlparse(url)
        return "/mod/quiz/" in parsed.path.lower()

    def _to_quiz_page_url(self, quiz_url: str) -> str:
        """Normalizes quiz URLs to a stable quiz-view destination."""
        if not self._is_quiz_page_url(quiz_url):
            return quiz_url

        parsed = urlparse(quiz_url)
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        query_map = {key.lower(): value for key, value in query_pairs}

        quiz_id = query_map.get("id", "").strip() or query_map.get("cmid", "").strip()
        if quiz_id:
            normalized_query = urlencode([("id", quiz_id)], doseq=True)
            return urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    "/mod/quiz/view.php",
                    parsed.params,
                    normalized_query,
                    parsed.fragment,
                )
            )
        return quiz_url

    def _html_to_plain_text(self, html: str) -> str:
        """Converts HTML markup to plain text."""
        parser = _VisibleTextParser()
        parser.feed(html)
        return parser.get_text()

    def _detect_category(self, text: str, source_url: str) -> Optional[str]:
        """Classifies one text segment as Homework, Quiz, or Test."""
        lowered = text.lower()
        for category, keywords in self._CATEGORY_KEYWORDS.items():
            if any(keyword in lowered for keyword in keywords):
                return category

        source_hint = source_url.lower()
        if "/mod/assign/" in source_hint and self._looks_date_related(lowered):
            return "Homework"
        if "/mod/quiz/" in source_hint and self._looks_date_related(lowered):
            return "Quiz"
        return None

    def _extract_first_date(self, text: str) -> Optional[Tuple[date, str]]:
        """Extracts the first parseable date and optional time from text."""
        for pattern_name, pattern in (
            ("month_first", self._MONTH_FIRST_PATTERN),
            ("day_first", self._DAY_FIRST_PATTERN),
            ("slash", self._SLASH_PATTERN),
        ):
            for match in pattern.finditer(text):
                maybe_date = self._build_date_from_match(match.groupdict(), pattern_name)
                if maybe_date is None:
                    continue
                time_label = self._extract_time(text)
                return maybe_date, time_label
        return None

    def _build_date_from_match(self, groups: Dict[str, str], pattern_name: str) -> Optional[date]:
        """Builds a date object from regex group captures."""
        try:
            raw_year = int(groups["year"])
            year = raw_year if raw_year >= 100 else 2000 + raw_year
            if pattern_name == "slash":
                month = int(groups["month"])
                day_value = int(groups["day"])
            else:
                month_token = groups["month"].lower()[:3]
                month = self._MONTH_NAME_TO_NUMBER[month_token]
                day_value = int(groups["day"])
            return date(year, month, day_value)
        except (KeyError, ValueError):
            return None

    def _extract_time(self, text: str) -> str:
        """Returns the first time token found in text."""
        match = self._TIME_PATTERN.search(text)
        if not match:
            return ""
        return self._normalize_whitespace(match.group(1)).upper()

    def _looks_date_related(self, text: str) -> bool:
        """Checks whether text has date cues used by Moodle due-date lines."""
        if any(token in text for token in ("due", "date", "open", "close", "deadline")):
            return True
        return self._extract_first_date(text) is not None

    def _derive_title(self, lines: List[str], index: int, category: str) -> str:
        """Builds a concise, user-facing title from nearby text."""
        candidate = self._normalize_whitespace(lines[index])
        if self._looks_generic(candidate):
            for offset in range(1, 4):
                previous_index = index - offset
                if previous_index < 0:
                    break
                previous_line = self._normalize_whitespace(lines[previous_index])
                if previous_line and not self._looks_generic(previous_line):
                    candidate = previous_line
                    break

        cleaned = self._strip_date_like_chunks(candidate)
        cleaned = cleaned[:120].strip(" -:\t")
        if not cleaned or self._looks_generic(cleaned):
            return f"{category} item"
        return cleaned

    def _looks_generic(self, text: str) -> bool:
        """Checks whether text is too generic to be a good event title."""
        lowered = text.lower()
        if len(lowered) <= 4:
            return True
        if self._TIME_ONLY_PATTERN.match(text.strip()):
            return True
        return any(lowered.startswith(prefix) for prefix in self._GENERIC_TITLE_PREFIXES)

    def _strip_date_like_chunks(self, text: str) -> str:
        """Removes noisy date labels from title candidates."""
        cleaned = self._MONTH_FIRST_PATTERN.sub("", text)
        cleaned = self._DAY_FIRST_PATTERN.sub("", cleaned)
        cleaned = self._SLASH_PATTERN.sub("", cleaned)
        cleaned = re.sub(r"\b(?:due|date|opens|open|closes|available)\b[:\-]?", "", cleaned, flags=re.IGNORECASE)
        return self._normalize_whitespace(cleaned)

    def _dedupe_events(self, events: List[MoodleEvent]) -> List[MoodleEvent]:
        """Removes duplicate parsed events while preferring higher-quality source URLs."""
        best_by_key: Dict[Tuple[str, str, str, str], MoodleEvent] = {}
        for event in events:
            key = (
                event.event_date.isoformat(),
                event.category.lower(),
                event.title.lower(),
                event.time_label.lower(),
            )
            current = best_by_key.get(key)
            if current is None:
                best_by_key[key] = event
                continue
            best_by_key[key] = self._pick_preferred_event(current, event)
        primary_deduped = list(best_by_key.values())

        # Second pass: collapse same source/date/time rows where only the extracted title differs.
        best_by_source_key: Dict[Tuple[str, str, str, str], MoodleEvent] = {}
        for event in primary_deduped:
            source_key = self._canonical_url(event.source_url) if event.source_url else ""
            key2 = (
                event.event_date.isoformat(),
                event.category.lower(),
                event.time_label.lower(),
                source_key,
            )
            current = best_by_source_key.get(key2)
            if current is None:
                best_by_source_key[key2] = event
                continue
            best_by_source_key[key2] = self._pick_preferred_event(current, event)

        return sorted(
            best_by_source_key.values(),
            key=lambda item: (
                item.event_date.isoformat(),
                item.category.lower(),
                item.title.lower(),
                item.time_label.lower(),
            ),
        )

    def _pick_preferred_event(self, left: MoodleEvent, right: MoodleEvent) -> MoodleEvent:
        """Returns the preferred event between two duplicate keys."""
        left_score = self._source_quality_score(left.source_url)
        right_score = self._source_quality_score(right.source_url)
        if right_score > left_score:
            return right
        if left_score > right_score:
            return left

        left_title_generic = left.title.lower().endswith(" item")
        right_title_generic = right.title.lower().endswith(" item")
        if left_title_generic != right_title_generic:
            return right if not right_title_generic else left

        if len(right.details) > len(left.details):
            return right
        return left

    def _source_quality_score(self, source_url: str) -> int:
        """Scores source URLs so module pages beat generic course pages."""
        lowered = source_url.lower()
        score = 0
        if "/course/view.php" in lowered:
            score -= 20
        if "/mod/assign/view.php" in lowered:
            score += 40
        if "action=editsubmission" in lowered or "action=submit" in lowered:
            score += 15
        if "/mod/quiz/view.php" in lowered:
            score += 35
        elif "/mod/quiz/" in lowered:
            score += 20
        return score

    def _filter_event_date_window(self, events: List[MoodleEvent]) -> List[MoodleEvent]:
        """Keeps only events from today onward and within the forward import window."""
        today = date.today()
        min_date = today
        max_date = today + timedelta(days=self._MAX_FUTURE_DAYS)
        return [event for event in events if min_date <= event.event_date <= max_date]

    def _canonical_url(self, url: str) -> str:
        """Normalizes URL comparison keys by dropping fragments and defaulting path."""
        parsed = urlparse(url)
        path = parsed.path or "/"
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))

    def _normalize_input_url(self, raw_url: str) -> str:
        """Adds a scheme if missing and validates URL shape."""
        candidate = raw_url.strip()
        if not candidate:
            return ""
        if not candidate.lower().startswith(("http://", "https://")):
            candidate = f"https://{candidate}"
        parsed = urlparse(candidate)
        if not parsed.scheme or not parsed.netloc:
            return ""
        return candidate

    def _normalize_whitespace(self, value: str) -> str:
        """Collapses repeated whitespace for consistent parsing/storage."""
        return re.sub(r"\s+", " ", value).strip()
