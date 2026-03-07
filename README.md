This repository is dedicated to a Chrome Extension designed to bring order to the unstructured data of Facebook Marketplace's vehicle listings in Portugal. By leveraging Small Language Models (SLMs) and Semantic Analysis, AutoSieve filters through the "noise"—identifying dealers posing as private sellers, extracting hidden maintenance history, and verifying tax (IUC) status.

🌟 The Problem
Facebook Marketplace is a goldmine for vehicle deals, but it suffers from:

Misleading Metadata: Dealers tagging listings as "Individual."

Hidden Costs: No dedicated fields for IUC (Imposto Único de Circulação) or IPO (Inspecção) status.

Unstructured Descriptions: Critical data (mileage, number of owners, timing belt changes) is buried in messy text.

🛠️ Key Features (Planned & In-Progress)
[ ] Semantic Filter Engine: Move beyond keyword matching to understand intent (e.g., distinguishing "IUC paid" from "IUC due").

[ ] Dealer Detection AI: Analysis of listing patterns and descriptions to flag commercial entities.

[ ] Automated Data Structuring: Extracting mileage, fuel type, and maintenance history into a clean UI overlay.

[ ] Market Value Benchmarking: Comparing live listings against the Portuguese market average.

🏗️ Technical Stack
Frontend: React + Vite (Manifest V3)

Language: TypeScript

Intelligence: * Local: Ollama (Llama 3 / Phi-3) for privacy-conscious parsing.

Cloud: OpenAI / Anthropic API (Experimental).

DOM Interaction: MutationObserver for handling dynamic content loading.

🚀 Getting Started (Dev Mode)
Note: This project is currently in early development.

Clone the repository:

Bash
git clone https://github.com/yourusername/autosieve.git
Install dependencies:

Bash
npm install
Build the extension:

Bash
npm run build
Load in Chrome:

Open chrome://extensions/

Enable "Developer mode" (top right).

Click "Load unpacked" and select the dist folder.

📈 Roadmap
Phase 1: Basic DOM extraction and keyword-based filtering.

Phase 2: Local LLM integration for description summarization.

Phase 3: Integration with Portuguese automotive data APIs.

👨‍💻 Author
[Your Name] Computer Science Intern & Aspiring AI Engineer

This project is part of a personal portfolio focused on applying LLMs to solve real-world data extraction challenges.