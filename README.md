# AutoSieve 🚗

![Status](https://img.shields.io/badge/Status-Work%20In%20Progress-orange)
![License](https://img.shields.io/badge/License-MIT-blue)
![Tech](https://img.shields.io/badge/Made%20with-TypeScript-blue)

**AutoSieve** is a specialized AI-driven program designed to identify "Value Arbitrage" vehicle deals on Facebook Marketplace Portugal. By bridging the gap between unstructured social media listings and structured market benchmarks (Standvirtual), AutoSieve acts as an automated "Personal Car Scout."

---

## 🎯 The Mission
The objective is to find high-value deals by identifying listings where the **Price < Market Average**, specifically targeting **Private Sellers** with **Low Mileage** vehicles.

### The "Value Arbitrage" Formula
AutoSieve calculates a **Deal Score ($S$)** using the following logic:

$$S = \frac{\text{Market Average (Standvirtual)}}{\text{Listing Price}} \times \text{Condition Multiplier}$$

---

## 🛠️ Key Engineering Features

### 1. Semantic Data Extraction (LLM Powered)
* **The Problem:** Marketplace listings often hide critical data (KMs, IUC status, real seller type) inside messy, unstructured text.
* **The Solution:** Uses a lightweight LLM (GPT-4o-mini or local Llama 3) to parse descriptions into structured JSON:
    * `is_dealer`: Detects "hidden" dealers using keywords like *IVA dedutível* or *Garantia de 18 meses*.
    * `kms`: Extracts true mileage.
    * `maintenance`: Identifies mentions of timing belt changes or *IPO em dia*.

### 2. Market Benchmarking
* Integrates a Portuguese market baseline using data derived from **Standvirtual’s "Avaliador."**
* Computes real-time price comparisons to flag listings priced significantly below the localized market average.

### 3. Smart Filtering & UI Injection
* **Dealer Shield:** Automatically deprioritizes listings identified as commercial entities to focus on private deals.
* **Visual Overlays:** Injects a "Deal Meter" (Green/Yellow/Red) directly onto the Facebook Marketplace interface for immediate decision-making.

---

## 🏗️ Technical Stack
* **Frontend:** React + Vite
* **Language:** TypeScript
* **Manifest:** Version 3 (Service Workers + Content Scripts)
* **Intelligence:** OpenAI API / Ollama (Local)
* **DOM Monitoring:** `MutationObserver` for handling dynamic infinite-scroll loading.

---

## 🚀 Development Roadmap (WIP)

- [x] **Phase 1: Project Architecture & Roadmap Definition**
- [ ] **Phase 2: DOM Scraper Engine** - Extract titles and prices from Marketplace cards.
- [ ] **Phase 3: LLM Parsing Layer** - Implement the "Private vs. Dealer" classifier.
- [ ] **Phase 4: Benchmarking Engine** - Integrate Standvirtual price averages for top Portuguese models.
- [ ] **Phase 5: UI Overlay** - Inject "Deal Score" badges into the browser.

---

## 👨‍💻 Author
**João Pedro Cardoso**
*CS Intern & Aspiring AI/LLM Engineer*

---

*This project is a work-in-progress focused on applying NLP and Semantic Analysis to solve real-world data fragmentation in the automotive market.*