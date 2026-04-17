# AutoPrice B2B Aggregator Bot

AutoPrice B2B Aggregator is a professional Telegram bot designed for real-time price and availability monitoring across four major auto parts B2B platforms: **Autonova-D**, **Forma Parts**, **4cars**, and **Inside-Auto**.

## 🛠 Tech Stack
* **Python 3.x**
* **Aiogram 3.x** — Asynchronous Telegram Bot API framework.
* **Selenium & undetected-chromedriver** — Bypassing anti-bot protections on JavaScript-heavy platforms.
* **Asyncio & ThreadPoolExecutor** — Managing concurrent scraping tasks without blocking the main event loop.
* **Cachetools (TTLCache)** — Optimizing performance by storing analog data lookups.

## 🚀 Key Features
* **Asynchronous Processing:** Handles multiple user requests simultaneously with high efficiency.
* **Anti-Fraud Protection Bypass:** Simulates human behavior to circumvent detection and IP bans.
* **Parallel Scraping:** Queries all 4 providers concurrently, significantly reducing response time.
* **Performance Optimization:** Implements TTL caching for 60 minutes to eliminate redundant browser queries.
* **Memory Management:** Includes a scheduled task to restart the browser instance every 48 hours for 24/7 stability.

## 📦 Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/telpelton/autoprice-b2b-bot.git](https://github.com/telpelton/autoprice-b2b-bot.git)
   cd autoprice-b2b-bot
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables:**
* Create a .env file in the root directory and add your credentials:
   ```bash
   BOT_TOKEN=
   ALLOWED_USERS=
   INSIDE_EMAIL=
   INSIDE_PASSWORD=
   FORMA_LOGIN=
   FORMA_PASSWORD=
   FOURCARS_LOGIN=
   FOURCARS_PASSWORD=
   AUTONOVAD_LOGIN=
   AUTONOVAD_PASSWORD=
   ```

4. **Run the bot:**
   ```bash
   python main.py
   ```
