import logging
import time
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from bs4 import BeautifulSoup

from config import URL_TEMPLATES, BASE_URL

logger = logging.getLogger(__name__)


class WebScraper:
    def __init__(self):
        self._playwright = None
        self._browser = None
        self._page = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _start(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        self._page = context.new_page()
        self._page.set_default_timeout(30_000)
        logger.info("Playwright browser started")

    def close(self):
        try:
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            logger.warning(f"Error closing Playwright: {e}")
        finally:
            self._browser = None
            self._playwright = None
            self._page = None

    # ------------------------------------------------------------------
    # Scraping helpers
    # ------------------------------------------------------------------

    def _scrape_current_page(self) -> list[list[str]]:
        """Parse the table on the current page and return rows."""
        html = self._page.content()
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("table tr")
        data = []
        for row in rows[1:]:           # skip header
            cells = [td.get_text(strip=True) for td in row.select("td")]
            if cells and len(cells) > 1 and cells[0] != "Page1of2018":
                data.append(cells)
        logger.debug(f"Scraped {len(data)} rows from current page")
        return data

    def _get_page_info(self) -> tuple[int, int]:
        """
        Return (current_page, total_pages) by parsing the page-navigation
        text that ESPN Cricinfo renders (e.g. "Page 3 of 47").
        Returns (0, 0) if the text cannot be found.
        """
        try:
            html = self._page.content()
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup.find_all(string=lambda t: t and "Page" in t and "of" in t):
                text = tag.strip().replace("\xa0", " ")
                # e.g. "Page 3 of 47"
                parts = text.split()
                if len(parts) >= 4 and parts[0] == "Page" and parts[2] == "of":
                    return int(parts[1]), int(parts[3])
        except Exception:
            pass
        return 0, 0

    def _find_next_button(self):
        """
        Return the first visible 'Next' anchor element, or None.
        Tries multiple selector strategies so layout changes don't break it.
        """
        page = self._page
        strategies = [
            lambda: page.get_by_role("link", name="Next"),
            lambda: page.locator("a", has_text="Next"),
            lambda: page.locator("//a[normalize-space(text())='Next']"),
            lambda: page.locator("//a[contains(@class,'next')]"),
        ]
        for strategy in strategies:
            try:
                candidate = strategy()
                if candidate.count() > 0 and candidate.first.is_visible():
                    return candidate.first
            except Exception:
                continue
        return None

    def _click_next(self, current_page: int) -> bool:
        """
        Click the Next button and wait for the page number to increment.
        Returns True if navigation succeeded, False if on the last page.

        Using the page-number indicator (rather than first-row text) is
        more reliable: two adjacent pages can share a first-row value
        (same player, same score), which would incorrectly halt scraping.
        """
        next_link = self._find_next_button()
        if next_link is None:
            logger.info("No 'Next' button visible – last page reached")
            return False

        try:
            next_link.scroll_into_view_if_needed()
            next_link.click()
        except Exception as e:
            logger.error(f"Click on 'Next' failed: {e}")
            return False

        # Wait up to 30 s for the page number to advance
        deadline = time.time() + 30
        while time.time() < deadline:
            time.sleep(1.5)
            new_page, total = self._get_page_info()
            if new_page == current_page + 1:
                logger.debug(f"  Navigated to page {new_page} of {total}")
                return True
            # Fallback: if we can't read page numbers, verify Next button is
            # still present and has changed (avoids infinite loop on edge cases)
            if new_page == 0:
                # Can't read page numbers; fall back to checking Next is clickable
                if self._find_next_button() is not None:
                    logger.debug("Page numbers unreadable – assuming navigation OK")
                    return True

        logger.warning(
            f"Timed out waiting for page {current_page + 1} to load"
        )
        return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrape_dataset(self, dataset_type: str, start_date: str) -> list[list[str]]:
        """
        Scrape all pages for a given dataset type starting from start_date.
        Opens and closes the browser automatically.

        Progress is logged at INFO level so you can follow along:
          • Page N/T – M rows on this page (running total: R)
        """
        url = self._build_url(dataset_type, start_date)
        logger.info(f"[{dataset_type}] Starting scrape from: {url}")

        self._start()
        try:
            self._page.goto(url, wait_until="domcontentloaded")
            try:
                self._page.wait_for_selector("table", timeout=20_000)
            except PlaywrightTimeout:
                logger.error("Timed out waiting for table – page may not have loaded")
                return []

            all_data: list[list[str]] = []
            page_num = 1
            max_pages = 500  # safety ceiling

            while page_num <= max_pages:
                # Read page-counter from the page itself where possible
                _, total_pages = self._get_page_info()
                page_label = f"{page_num}/{total_pages}" if total_pages else str(page_num)

                time.sleep(2)   # polite crawl delay
                page_data = self._scrape_current_page()
                all_data.extend(page_data)

                logger.info(
                    f"[{dataset_type}] Page {page_label} – "
                    f"{len(page_data)} rows scraped  |  running total: {len(all_data)}"
                )

                if not page_data:
                    logger.warning(f"  Empty page {page_num} – stopping")
                    break

                if not self._click_next(page_num):
                    break

                page_num += 1

            logger.info(
                f"[{dataset_type}] Scrape complete – "
                f"{page_num} page(s) processed, {len(all_data)} total rows"
            )
            return all_data

        finally:
            self.close()

    @staticmethod
    def _build_url(dataset_type: str, start_date: str) -> str:
        template = URL_TEMPLATES.get(dataset_type)
        if not template:
            raise ValueError(f"Unknown dataset type: {dataset_type}")
        return BASE_URL + template.format(start_date=start_date)

    @staticmethod
    def format_date_for_url(date_str: str) -> str:
        date = datetime.strptime(date_str.split()[0], "%Y-%m-%d")
        return date.strftime("%d+%b+%Y")