"""Utilities for crawling Moodle pages and extracting date-based class events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from html import unescape
from html.parser import HTMLParser
import http.cookiejar
import re
import time
from typing import Dict, List, Optional, Sequence, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse, urlunparse
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
        super().__init__()
        self._parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, _attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
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
        super().__init__()
        self.links: List[str] = []

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "a":
            return
        attrs_map = {key.lower(): value for key, value in attrs if key and value is not None}
        href = attrs_map.get("href", "").strip()
        if href:
            self.links.append(href)


class _LoginFormParser(HTMLParser):
    """Finds login forms and captures hidden fields needed for submission."""

    def __init__(self) -> None:
        super().__init__()
        self.forms: List[Dict[str, object]] = []
        self._current_form: Optional[Dict[str, object]] = None

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
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
    _MAX_PAST_DAYS = 365
    _MAX_FUTURE_DAYS = 730

    def __init__(self, max_pages: int = 18, timeout_seconds: int = 15) -> None:
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
        events: List[MoodleEvent] = []
        for page_url, html in pages:
            events.extend(self._extract_events_from_page(page_url, html))

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
        for page_url, html in pages:
            events.extend(self._extract_events_from_page(page_url, html))
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
        """Starts an Edge or Chrome webdriver using Selenium Manager auto-driver discovery."""
        webdriver = selenium_bundle["webdriver"]
        WebDriverException = selenium_bundle["WebDriverException"]
        EdgeOptions = selenium_bundle["EdgeOptions"]
        ChromeOptions = selenium_bundle["ChromeOptions"]

        errors: List[str] = []
        try:
            edge_options = EdgeOptions()
            edge_options.add_argument("--disable-gpu")
            edge_options.add_argument("--window-size=1380,980")
            edge_options.add_argument("--inprivate")
            edge_driver = webdriver.Edge(options=edge_options)
            return edge_driver, "Edge", ""
        except WebDriverException as exc:
            errors.append(f"Edge: {exc}")

        try:
            chrome_options = ChromeOptions()
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1380,980")
            chrome_options.add_argument("--incognito")
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
            username_input = wait.until(
                lambda d: d.find_elements(By.ID, "i0116") or d.find_elements(By.NAME, "loginfmt")
            )[0]
            username_input.clear()
            username_input.send_keys(username)
            self._click_first_if_present(driver, By, ("idSIButton9",))

            password_input = wait.until(
                lambda d: d.find_elements(By.ID, "i0118") or d.find_elements(By.NAME, "passwd")
            )[0]
            password_input.clear()
            password_input.send_keys(password)
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
                        element.click()
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
        queue: List[str] = self._extract_candidate_links(current_url, first_html, start_url)

        while queue and len(pages) < self.max_pages:
            next_url = queue.pop(0)
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
        queue: List[str] = self._extract_candidate_links(start_url, start_html, start_url)

        while queue and len(pages) < self.max_pages:
            next_url = queue.pop(0)
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

        return pages

    def _extract_candidate_links(self, base_url: str, html: str, root_url: str) -> List[str]:
        """Returns same-site links that likely lead to relevant Moodle content."""
        parser = _LinkParser()
        parser.feed(html)
        links: List[str] = []
        root_host = urlparse(root_url).netloc.lower()

        for href in parser.links:
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

        # Preserve order while removing duplicates.
        unique_links: List[str] = []
        seen: Set[str] = set()
        for link in links:
            canonical = self._canonical_url(link)
            if canonical in seen:
                continue
            seen.add(canonical)
            unique_links.append(link)
        return unique_links

    def _extract_events_from_page(self, page_url: str, html: str) -> List[MoodleEvent]:
        """Parses one Moodle page into structured date-based events."""
        plain_text = self._html_to_plain_text(html)
        lines = [self._normalize_whitespace(line) for line in plain_text.splitlines()]
        lines = [line for line in lines if line]

        events: List[MoodleEvent] = []
        seen_page_keys: Set[Tuple[str, str, str, str]] = set()
        for index, line in enumerate(lines):
            category = self._detect_category(line, page_url)
            if category is None:
                local_context = " ".join(lines[max(0, index - 1) : min(len(lines), index + 2)])
                category = self._detect_category(local_context, page_url)
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

            title = self._derive_title(lines, index, category)
            if not title:
                title = f"{category} item"

            event_key = (
                event_date.isoformat(),
                category.lower(),
                title.lower(),
                time_label.lower(),
            )
            if event_key in seen_page_keys:
                continue
            seen_page_keys.add(event_key)

            details = f"{parsed_context}\nSource: {page_url}"
            events.append(
                MoodleEvent(
                    title=title,
                    category=category,
                    event_date=event_date,
                    time_label=time_label,
                    details=details,
                    source_url=page_url,
                )
            )

        return events

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
        """Removes duplicate parsed events while keeping deterministic ordering."""
        sorted_events = sorted(
            events,
            key=lambda item: (
                item.event_date.isoformat(),
                item.category.lower(),
                item.title.lower(),
                item.time_label.lower(),
            ),
        )
        deduped: List[MoodleEvent] = []
        seen: Set[Tuple[str, str, str, str]] = set()
        for event in sorted_events:
            key = (
                event.event_date.isoformat(),
                event.category.lower(),
                event.title.lower(),
                event.time_label.lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(event)
        return deduped

    def _filter_event_date_window(self, events: List[MoodleEvent]) -> List[MoodleEvent]:
        """Drops events far outside the active academic window to reduce false positives."""
        today = date.today()
        min_date = today - timedelta(days=self._MAX_PAST_DAYS)
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
