from playwright.sync_api import sync_playwright

URL = "https://www.facebook.com/marketplace/lisbon/vehicles?exact=0"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(
        geolocation={"latitude": 38.7223, "longitude": -9.1393},
        permissions=["geolocation"],
        locale="pt-PT",
    )
    page = context.new_page()
    page.goto(URL, wait_until="domcontentloaded")

    # Dismiss cookie consent popup
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

    # Close the "Log in" / "See more on Facebook" overlay if present
    try:
        close_btn = page.query_selector("div[aria-label='Close'], div[aria-label='Fechar']")
        if close_btn:
            close_btn.click()
            page.wait_for_timeout(1000)
    except Exception:
        pass

    # Wait for listings to appear
    page.wait_for_selector("a[href*='/marketplace/item/']", timeout=30000)

    # Get first vehicle listing link and navigate directly
    first_link = page.query_selector("a[href*='/marketplace/item/']")
    if not first_link:
        print("No listings found")
        browser.close()
        exit()

    href = first_link.get_attribute("href")
    page.goto(f"https://www.facebook.com{href}", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Dismiss popups again on the listing page
    try:
        close_btn = page.query_selector("div[aria-label='Close'], div[aria-label='Fechar']")
        if close_btn:
            close_btn.click()
            page.wait_for_timeout(1000)
    except Exception:
        pass

    # Extract title
    title_el = page.query_selector("h1 span")
    title = title_el.inner_text() if title_el else "Title not found"

    # Click the "Ver mais" in the description (the one with x > 500, on the right side)
    desc = ""
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

    # Now read the expanded description
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

    print(f"Title: {title}")
    print(f"\nDescription: {desc if desc else 'No description found'}")

    browser.close()
