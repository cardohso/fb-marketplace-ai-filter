from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from datetime import datetime
import pandas as pd
from config import MARKETPLACE_URL, NUM_VEHICLES, CURRENCY_SYMBOL, HEADLESS


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


def expand_see_more(page):
    """Click 'Ver mais' only inside the seller description section."""
    page.evaluate("""
        () => {
            const allSpans = document.querySelectorAll('span');
            let inDescSection = false;
            for (const span of allSpans) {
                const t = span.textContent.trim();
                if (t === 'Descrição do vendedor') {
                    inDescSection = true;
                    continue;
                }
                if (inDescSection && span.children.length === 0
                    && (t === 'Ver mais' || t === 'See more')) {
                    span.parentElement.click();
                    return;
                }
            }
        }
    """)
    page.wait_for_timeout(2000)


def extract_vehicle(page):
    # Wait for listing content to render
    page.wait_for_selector("h1 span", timeout=10000)
    page.wait_for_timeout(2000)
    expand_see_more(page)
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    # Title
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else "Title not found"

    # Price — first short text containing €
    value = ""
    for el in soup.find_all("span"):
        text = el.get_text(strip=True)
        if CURRENCY_SYMBOL in text and len(text) < 50:
            value = text
            break

    # Description — find "Descrição do vendedor" heading, then grab the next
    # span that contains the actual description text
    desc = ""
    all_spans = soup.find_all("span")
    for i, span in enumerate(all_spans):
        if span.get_text(strip=True) == "Descrição do vendedor":
            for j in range(i + 1, min(i + 5, len(all_spans))):
                text = all_spans[j].get_text(strip=True)
                skip = {"Ver mais", "See more", "Ver menos", "See less",
                        "Descrição do vendedor"}
                if text and text not in skip and len(text) > 10:
                    # Strip trailing "Ver mais"/"Ver menos" embedded in the text
                    for suffix in ["Ver mais", "Ver menos", "See more", "See less"]:
                        if text.endswith(suffix):
                            text = text[:-len(suffix)].strip()
                    desc = text
                    break
            break

    # Images — collect listing product photos (alt starts with "Foto de produto")
    image_urls = []
    seen = set()
    for img in soup.find_all("img"):
        alt = img.get("alt", "")
        src = img.get("src", "")
        if src and "Foto de produto" in alt and src not in seen:
            seen.add(src)
            image_urls.append(src)

    return {
        "title": title,
        "description": desc or "No description found",
        "value": value or "Price not found",
        "image_urls": "|".join(image_urls),
    }


with sync_playwright() as p:
    browser = p.chromium.launch(headless=HEADLESS)
    context = browser.new_context(
        geolocation={"latitude": 38.7223, "longitude": -9.1393},
        permissions=["geolocation"],
        locale="pt-PT",
    )
    page = context.new_page()
    page.goto(MARKETPLACE_URL, wait_until="domcontentloaded")

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
        print(f"  Description: {vehicle['description'][:100]}...")
        print()

    # Save to CSV
    df = pd.DataFrame(vehicles, columns=["title", "value", "description", "image_urls", "url"])
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"vehicles_{timestamp}.csv"
    df.to_csv(filename, index=False, encoding="utf-8")

    print(df.to_string(index=False))
    print(f"\nSaved {len(vehicles)} vehicles to {filename}")
    browser.close()
