from playwright.sync_api import sync_playwright
from datetime import datetime

URL = "https://www.facebook.com/marketplace/lisbon/vehicles?exact=0"
NUM_VEHICLES = 5


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

    # Expand description
    page.evaluate("""
        () => {
            const els = document.querySelectorAll('span');
            for (const el of els) {
                if (el.children.length === 0 && el.textContent.trim() === 'Ver mais') {
                    const rect = el.getBoundingClientRect();
                    if (rect.x > 500) {
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
                if (rect.x > 500 && span.innerText.length > 100 && !span.innerText.includes('Ver mais')) {
                    return span.innerText;
                }
            }
            return '';
        }
    """)

    return {"title": title, "description": desc or "No description found"}


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

    # Save to file
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"vehicles_{timestamp}.txt"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"Facebook Marketplace - Vehicles near Lisbon\n")
        f.write(f"Scraped: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total: {len(vehicles)} vehicles\n")
        f.write("=" * 60 + "\n\n")

        for i, v in enumerate(vehicles, 1):
            f.write(f"Vehicle #{i}\n")
            f.write("-" * 40 + "\n")
            f.write(f"Title: {v['title']}\n")
            f.write(f"URL: {v['url']}\n")
            f.write(f"\nDescription:\n{v['description']}\n")
            f.write("\n" + "=" * 60 + "\n\n")

    print(f"Saved {len(vehicles)} vehicles to {filename}")
    browser.close()
