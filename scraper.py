from playwright.sync_api import sync_playwright
from datetime import datetime
import pandas as pd

URL = "https://www.facebook.com/marketplace/lisbon/vehicles?exact=0&sortBy=creation_time_descend"
NUM_VEHICLES = 5 # Number of vehicle listings to scrape

MIN_DESC_LENGTH = 20  # Minimum characters for description to be captured
X_POSITION_THRESHOLD = 500  # X position to identify main content area
EXPAND_DESC_TEXT = "Ver mais"  # Text for "expand description" button
CURRENCY_SYMBOL = "€"  # Currency symbol to identify price


def dismiss_cookies(page):
    try:
        page.wait_for_timeout(3000)
        page.evaluate("""
            () => {
                const els = document.querySelectorAll('button, div[role="button"], span[role="button"], a[role="button"]');
                for (const el of els) {
                    const text = el.textContent.trim();
                    if (text.includes('Recusar') || text.includes('Decline optional')) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        page.wait_for_timeout(1000)
    except Exception:
        pass


def dismiss_overlay(page):
    try:
        close_btn = page.query_selector("div[aria-label='Close'], div[aria-label='Fechar']")
        if close_btn:
            close_btn.click()
            page.wait_for_timeout(1000)
    except Exception:
        pass


def extract_vehicle(page):
    # Title
    title_el = page.query_selector("h1 span")
    title = title_el.inner_text() if title_el else "Title not found"

    # Price/Value
    value = page.evaluate("""
        () => {
            const elements = document.querySelectorAll('*');
            for (const el of elements) {
                const text = el.innerText;
                if (text && text.includes('""" + CURRENCY_SYMBOL + """') && text.length < 50) {
                    return text.trim();
                }
            }
            return '';
        }
    """)

    # Expand description
    page.evaluate("""
        () => {
            const els = document.querySelectorAll('span');
            for (const el of els) {
                if (el.children.length === 0 && el.textContent.trim() === '""" + EXPAND_DESC_TEXT + """') {
                    const rect = el.getBoundingClientRect();
                    if (rect.x > """ + str(X_POSITION_THRESHOLD) + """) {
                        el.parentElement.click();
                        return true;
                    }
                }
            }
            return false;
        }
    """)
    page.wait_for_timeout(2000)

    # Read expanded description
    desc = page.evaluate("""
        () => {
            const spans = document.querySelectorAll('span');
            for (const span of spans) {
                const rect = span.getBoundingClientRect();
                if (rect.x > """ + str(X_POSITION_THRESHOLD) + """ && span.innerText.length >= """ + str(MIN_DESC_LENGTH) + """ && !span.innerText.includes('""" + EXPAND_DESC_TEXT + """')) {
                    return span.innerText;
                }
            }
            return '';
        }
    """)

    return {"title": title, "description": desc or "No description found", "value": value or "Price not found"}


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(
        geolocation={"latitude": 38.7223, "longitude": -9.1393},
        permissions=["geolocation"],
        locale="pt-PT",
    )
    page = context.new_page()
    page.goto(URL, wait_until="domcontentloaded")

    dismiss_cookies(page)
    dismiss_overlay(page)

    # Wait for listings
    page.wait_for_selector("a[href*='/marketplace/item/']", timeout=30000)

    # Collect listing URLs
    links = page.query_selector_all("a[href*='/marketplace/item/']")
    hrefs = []
    for link in links:
        href = link.get_attribute("href")
        if href and href not in hrefs:
            hrefs.append(href)
        if len(hrefs) >= NUM_VEHICLES:
            break

    print(f"Found {len(hrefs)} vehicle links\n")

    # Visit each listing and extract data
    vehicles = []
    for i, href in enumerate(hrefs):
        full_url = f"https://www.facebook.com{href}" if href.startswith("/") else href
        print(f"[{i+1}/{len(hrefs)}] Visiting: {full_url[:80]}...")

        page.goto(full_url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        dismiss_overlay(page)

        vehicle = extract_vehicle(page)
        vehicle["url"] = full_url
        vehicles.append(vehicle)

        print(f"  Title: {vehicle['title']}")
        print()

    # Save to CSV
    df = pd.DataFrame(vehicles, columns=["title", "value", "description", "url"])
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"vehicles_{timestamp}.csv"
    df.to_csv(filename, index=False, encoding="utf-8")



    print(df.to_string(index=False))
    print(f"\nSaved {len(vehicles)} vehicles to {filename}")
    browser.close()
