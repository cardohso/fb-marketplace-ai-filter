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
    """Click 'Ver mais' / 'See more' near the listing description area."""
    page.evaluate("""
        () => {
            const allSpans = document.querySelectorAll('span');
            let inDetailArea = false;
            for (const span of allSpans) {
                const t = span.textContent.trim();
                // Start looking after "Detalhes" or "Descrição do vendedor"
                if (t === 'Detalhes' || t === 'Descrição do vendedor') {
                    inDetailArea = true;
                    continue;
                }
                if (inDetailArea && span.children.length === 0
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

    # Description — try two strategies:
    # 1. Find "Descrição do vendedor" heading and grab the text after it
    # 2. Fallback: find the longest span near the listing details area
    desc = ""
    all_spans = soup.find_all("span")

    # Strategy 1: explicit heading
    for i, span in enumerate(all_spans):
        if span.get_text(strip=True) == "Descrição do vendedor":
            parent = span.find_parent("div")
            if parent:
                desc = parent.get_text(separator=" ", strip=True)
                # Remove the heading itself and UI buttons
                for remove in ["Descrição do vendedor", "Ver mais", "Ver menos",
                               "See more", "See less"]:
                    desc = desc.replace(remove, "").strip()
            break

    # Strategy 2: find description text after "Detalhes" section
    if not desc:
        in_details = False
        skip_keywords = {"cookie", "facebook", "publicidade", "anúncio",
                         "condomínio", "casas expansíveis", "centro de contas",
                         "publicado", "localização", "enviar mensagem",
                         "saiba mais", "seleções de hoje"}
        best = ""
        for span in all_spans:
            text = span.get_text(strip=True)
            if text == "Detalhes":
                in_details = True
                continue
            if not in_details:
                continue
            if len(text) > len(best) and len(text) < 3000:
                lower = text.lower()
                if any(k in lower for k in skip_keywords):
                    continue
                # Skip short UI elements and condition labels
                if text in {"Condição", "Estado", "Ver mais", "Ver menos",
                            "See more", "See less"}:
                    continue
                # Skip spans that start with condition text
                if text.startswith("Usado") or text.startswith("Novo"):
                    continue
                # Strip trailing UI text
                for suffix in ["Ver mais", "Ver menos", "See more", "See less"]:
                    if text.endswith(suffix):
                        text = text[:-len(suffix)].strip()
                if len(text) > 30:
                    best = text
        desc = best

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
