# AutoSieve 🚗

![Status](https://img.shields.io/badge/Status-Work%20In%20Progress-orange)
![License](https://img.shields.io/badge/License-MIT-blue)
![Tech](https://img.shields.io/badge/Made%20with-Python-blue)

**AutoSieve** is a specialized AI-driven program designed to identify "Value Arbitrage" vehicle deals on Facebook Marketplace Portugal. By bridging the gap between unstructured social media listings and structured market benchmarks (Standvirtual), AutoSieve acts as an automated "Personal Car Scout."

---

## 🎯 The Mission
The objective is to find high-value deals by identifying listings where the **Price < Market Average**, specifically targeting **Private Sellers** with **Low Mileage** vehicles.

### The "Value Arbitrage" Formula
AutoSieve calculates a **Deal Score ($S$)** using the following logic:

$$S = \frac{\text{Market Average (Standvirtual)}}{\text{Listing Price}} \times \text{Condition Multiplier}$$

---

## 🛠️ Key Engineering Features

### 1. DOM Scraper Engine (`scraper.py`)
* Uses **Playwright** to navigate Facebook Marketplace and collect vehicle listing URLs.
* Parses each listing's HTML with **BeautifulSoup** to extract:
    * **Title** from the `<h1>` tag.
    * **Price** by matching the `€` currency symbol.
    * **Seller description** from the "Descrição do vendedor" section, automatically expanding truncated text via "Ver mais".
    * **Listing images** — product photo URLs for vision-based analysis.
* Handles cookie consent banners and login overlays automatically.
* Outputs a timestamped CSV (`vehicles_YYYY-MM-DD_HH-MM-SS.csv`).

### 2. LLM Parsing Layer (`llm_parser.py`)
* Enriches scraped CSVs with structured data extracted by a local **Llama 3.1** model via **Ollama**.
* Each listing description is analysed and parsed into structured JSON:
    * `is_dealer`: Detects "hidden" dealers using keywords like *IVA dedutível*, *stand*, *garantia*.
    * `kms`: Extracts mileage as a plain integer.
    * `maintenance`: Identifies timing belt replacement and *IPO* (vehicle inspection) status.
    * `iuc_status`: IUC tax status (`ok`, `pending`, `unknown`).
    * `condition`: Flags accident history and paint issues.
    * `notes`: One-sentence summary of standout aspects.
* **Vision fallback:** When mileage is not found in the description text, listing images are sent to **LLaVA 13B** (vision model) to read the odometer/dashboard display. Includes confidence checks and sanity validation (rejects readings outside 100–999,999 km).
* Outputs an enriched CSV (`vehicles_..._enriched.csv`) with `llm_` prefixed columns.

### 3. Market Benchmarking (Planned)
* Will integrate a Portuguese market baseline using data derived from **Standvirtual's "Avaliador."**
* Will compute real-time price comparisons to flag listings priced significantly below the localized market average.

### 4. Smart Filtering & UI (Planned)
* **Dealer Shield:** Automatically deprioritize listings identified as commercial entities to focus on private deals.
* **Visual Overlays:** Inject a "Deal Meter" (Green/Yellow/Red) directly onto the Facebook Marketplace interface.

---

## 🏗️ Technical Stack
* **Language:** Python
* **Scraping:** Playwright + BeautifulSoup
* **LLM:** Ollama (Llama 3.1 for text, LLaVA 13B for vision)
* **Data:** Pandas

---

## 🚀 Usage

### Prerequisites
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install playwright pandas beautifulsoup4 requests

# Install Playwright browsers
playwright install chromium

# Install and start Ollama with required models
ollama pull llama3.1
ollama pull llava:13b
ollama serve
```

### 1. Scrape listings
```bash
python3 scraper.py
```
Outputs: `vehicles_YYYY-MM-DD_HH-MM-SS.csv`

### 2. Enrich with LLM analysis
```bash
python3 llm_parser.py vehicles_YYYY-MM-DD_HH-MM-SS.csv
```
Outputs: `vehicles_YYYY-MM-DD_HH-MM-SS_enriched.csv`

---

## 🚀 Development Roadmap (WIP)

- [x] **Phase 1: Project Architecture & Roadmap Definition**
- [x] **Phase 2: DOM Scraper Engine** - Extract titles, prices, and descriptions from Marketplace listings.
- [x] **Phase 3: LLM Parsing Layer** - Enrich listings with structured data via Ollama/Llama 3.1.
- [ ] **Phase 4: Benchmarking Engine** - Integrate Standvirtual price averages for top Portuguese models.
- [ ] **Phase 5: UI Overlay** - Inject "Deal Score" badges into the browser.

---

## 👨‍💻 Author
**João Pedro Cardoso**
*CS Intern & Aspiring AI/LLM Engineer*

---

*This project is a work-in-progress focused on applying NLP and Semantic Analysis to solve real-world data fragmentation in the automotive market.*
