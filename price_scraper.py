import asyncio
import re
import json
import aiohttp
from bs4 import BeautifulSoup
import logging
from logging.handlers import RotatingFileHandler

import config

logger = logging.getLogger(__name__)

# НАЛАШТУВАННЯ ЛОГУВАННЯ З РОТАЦІЄЮ (10 MB)
api_logger = logging.getLogger("api_scraper")
api_logger.setLevel(logging.DEBUG)

if not api_logger.handlers:
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] (Line: %(lineno)d) -> %(message)s')
    file_handler = RotatingFileHandler("api_scraper.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    api_logger.addHandler(file_handler)
    api_logger.propagate = False

class PriceScraperService:
    def __init__(self):
        self.preferred_brands = ["POLCAR", "VAG", "VW", "SIGNEDA", "DPA", "FPS"]
        self.session_data = config.load_sessions()
        
        # Асинхронний замок для безпечного запису сесій з різних тасок
        self.db_lock = asyncio.Lock()
        # Семафор для обмеження одночасних запитів до сайтів (макс. 2 паралельно)
        self.rate_limiter = asyncio.Semaphore(2)
        
        self.sessions = {
            "autonova": {"http": None, "auth": self.session_data.get("autonova_token")},
            "forma": {"http": None, "auth": self.session_data.get("forma_token")},
            "fourcars": {"http": None, "auth": bool(self.session_data.get("fourcars_cookies"))},
            "inside": {"http": None, "auth": bool(self.session_data.get("inside_cookies"))}
        }
        api_logger.info("✅ PriceScraperService ініціалізовано. Лок та Семафор активні.")

    async def _get_session(self, site):
        if self.sessions[site]["http"] is None or self.sessions[site]["http"].closed:
            api_logger.debug(f"[{site.upper()}] Відкриття нової HTTP-сесії.")
            cookies = self.session_data.get(f"{site}_cookies", {})
            self.sessions[site]["http"] = aiohttp.ClientSession(cookies=cookies)
        return self.sessions[site]["http"]

    async def _universal_login(self, site, url, method="post", payload=None, headers=None, auth_type="token"):
        api_logger.debug(f"🔑 [{site.upper()}] Спроба авторизації на {url}")
        session = await self._get_session(site)
        try:
            req_kwargs = {"json": payload} if auth_type == "token" else {"data": payload}
            async with getattr(session, method)(url, headers=headers, **req_kwargs) as res:
                api_logger.debug(f"[{site.upper()}] Статус відповіді авторизації: {res.status}")
                
                if auth_type == "token" and res.status == 200:
                    self.sessions[site]["auth"] = (await res.json()).get("token")
                    async with self.db_lock:
                        self.session_data[f"{site}_token"] = self.sessions[site]["auth"]
                elif auth_type == "cookie":
                    body = (await res.text()).lower()
                    self.sessions[site]["auth"] = any(w in body for w in ["logout", "выход", "вихід", "кабінет"]) or res.status == 302
                    
                if self.sessions[site]["auth"]:
                    if session.cookie_jar:
                        async with self.db_lock:
                            self.session_data[f"{site}_cookies"] = {c.key: c.value for c in session.cookie_jar}
                    async with self.db_lock:
                        config.save_sessions(self.session_data)
                    api_logger.info(f"✅ [{site.upper()}] Авторизація УСПІШНА.")
                    return True
                
                api_logger.warning(f"❌ [{site.upper()}] ПОМИЛКА АВТОРИЗАЦІЇ. Статус: {res.status}")
                return False
        except Exception as e:
            api_logger.error(f"💥 [{site.upper()}] Критична помилка авторизації: {e}", exc_info=True)
            return False

    async def _login_autonova(self):
        return await self._universal_login("autonova", "https://ucb-ext.prod.cp.autonovad.ua/api/login", 
            payload={"login": config.AUTONOVA_LOGIN, "password": config.AUTONOVA_PASSWORD},
            headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "Mozilla/5.0"}
        )

    async def _login_forma(self):
        return await self._universal_login("forma", "https://ecom.ad.ua/api/user/login",
            payload={"comId": 19, "login": config.FORMA_LOGIN, "pwd": config.FORMA_PASSWORD},
            headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
        )

    async def _login_fourcars(self):
        return await self._universal_login("fourcars", "https://4cars.com.ua/?action=user_login",
            payload={"login": config.FOURCARS_LOGIN, "password": config.FOURCARS_PASSWORD, "remember_me": "1", "auth": "Вход", "action": "user_do_login"},
            headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"}, auth_type="cookie"
        )

    async def _login_inside(self):
        return await self._universal_login("inside", "https://inside-auto.com/customer/login",
            payload={"phone": "", "email": config.INSIDE_EMAIL, "password": config.INSIDE_PASSWORD},
            headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"}, auth_type="cookie"
        )

    async def search_autonova(self, article):
        async with self.rate_limiter:
            api_logger.info(f"🔍 [AUTONOVA] Пошук: '{article}'")
            res_dict = {"exact": {}, "analogs": {}}
            session = await self._get_session("autonova")
            if not self.sessions["autonova"]["auth"] and not await self._login_autonova(): 
                api_logger.error("[AUTONOVA] Переривання пошуку: немає доступу (auth = False).")
                return res_dict

            headers = {"User-Agent": "Mozilla/5.0", "Authorization": f"Bearer {self.sessions['autonova']['auth']}"}
            url = f"https://catalogue-api.autonovad.ua/api/search-redirect?query={article}"
            
            try:
                api_logger.debug(f"[AUTONOVA] GET запит: {url}")
                async with session.get(url, headers=headers) as res:
                    if res.status == 401:
                        api_logger.warning("[AUTONOVA] Токен протерміновано (401). Оновлення...")
                        if await self._login_autonova():
                            headers["Authorization"] = f"Bearer {self.sessions['autonova']['auth']}"
                            res = await session.get(url, headers=headers)
                    if res.status != 200: 
                        api_logger.warning(f"⚠️ [AUTONOVA] Поганий статус відповіді: {res.status}")
                        return res_dict
                    data = await res.json()

                match = re.search(r'query=([\w_]+)', data.get("redirect", ""))
                if not match or "brands" in data.get("redirect", ""): 
                    api_logger.info("ℹ️ [AUTONOVA] Знайдено кілька брендів або артикул відсутній.")
                    return res_dict

                product_id = match.group(1)
                endpoints = [f"https://catalogue-api.autonovad.ua/api/products/{product_id}/offers", f"https://catalogue-api.autonovad.ua/api/products/{product_id}/external-offers"]
                cat_map = {"offers": "Залишки", "branchOffers": "Залишки на філіалах", "supplierOffers": "Залишки постачальників"}
                seen_ids, search_clean = set(), re.sub(r'[\W_]+', '', str(article)).upper()

                for ep in endpoints:
                    api_logger.debug(f"[AUTONOVA] Запит залишків: {ep}")
                    async with session.get(ep, headers=headers) as r:
                        if r.status != 200: 
                            api_logger.warning(f"[AUTONOVA] Помилка залишків (статус {r.status}): {ep}")
                            continue
                        
                        ep_data = await r.json()
                        for arr_key, cat_name in cat_map.items():
                            for item in ep_data.get(arr_key, []):
                                if item['id'] in seen_ids: continue
                                seen_ids.add(item['id'])
                                
                                brand, code = item.get("brand", {}).get("name", "Unknown"), str(item.get("code", ""))
                                price, qty = int(float(item.get("price", {}).get("current", 0))), int(item.get("quantity", 0))
                                days = item.get("delivery", {}).get("days", 0)
                                
                                clean_code = re.sub(r'[\W_]+', '', code).upper()
                                term_str = "⏱ сьогодні" if days == 0 else "⏳ завтра" if days == 1 else f"⏳ {int(days)} дн."
                                
                                t_type = "exact" if search_clean in clean_code or clean_code in search_clean else "analogs"
                                cat_key, b_key = f"📂 *{cat_name}*", f"🔹 *{brand} {code}*"
                                
                                res_dict[t_type].setdefault(cat_key, {}).setdefault(b_key, []).append(f"{term_str} | 📦 {qty} | 💰 {price} грн.")

                formatted_res = self._format_autonova_dict(res_dict)
                api_logger.info(f"🏁 [AUTONOVA] Завершено. Точних: {len(formatted_res['exact'])}, Аналогів: {len(formatted_res['analogs'])}")
                return formatted_res
                
            except Exception as e: 
                api_logger.error(f"❌ [AUTONOVA] Помилка: {e}", exc_info=True)
                return {"exact": {}, "analogs": {}}

    def _format_autonova_dict(self, res_dict):
        formatted = {"exact": {}, "analogs": {}}
        for t_type in ["exact", "analogs"]:
            for cat, items in res_dict[t_type].items():
                formatted[t_type][cat] = []
                for b_key, offers in items.items():
                    formatted[t_type][cat].extend([b_key] + offers + [""])
                if formatted[t_type][cat]: formatted[t_type][cat].pop()
        return formatted

    async def search_fps(self, article):
        async with self.rate_limiter:
            api_logger.info(f"🔍 [FORMA] Пошук: '{article}'")
            res_dict = {"exact": {}, "analogs": {}}
            session = await self._get_session("forma")
            if not self.sessions["forma"]["auth"] and not await self._login_forma(): 
                api_logger.error("[FORMA] Переривання пошуку: немає доступу.")
                return res_dict

            headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json", "Authorization": f"Bearer {self.sessions['forma']['auth']}"}
            url, payload = "https://ecom.ad.ua/api/items/ByCode", article.replace(" ", "")

            try:
                api_logger.debug(f"[FORMA] POST запит: {url}")
                async with session.post(url, json=payload, headers=headers) as res:
                    if res.status == 401:
                        api_logger.warning("[FORMA] Токен протерміновано (401). Оновлення...")
                        if await self._login_forma():
                            headers["Authorization"] = f"Bearer {self.sessions['forma']['auth']}"
                            res = await session.post(url, json=payload, headers=headers)
                    if res.status != 200: 
                        api_logger.warning(f"⚠️ [FORMA] Поганий статус: {res.status}")
                        return res_dict
                    data = await res.json()

                if not data: 
                    api_logger.info("ℹ️ [FORMA] Порожня відповідь (нічого не знайдено).")
                    return res_dict
                    
                search_clean = re.sub(r'[^A-Z0-9]', '', article.upper())

                for item in data:
                    brand, art = item.get("brand", "Н/Д"), item.get("itemNo", "Н/Д")
                    price = f"{item.get('price', 0)} грн." if item.get("price") else "Немає ціни"
                    
                    try:
                        stocks = json.loads(item.get("stock", "{}")).get("Stock", [])
                        avail = " | ".join([f"📦 {s.get('L')}: {s.get('Q', '0')}" for s in stocks]) or "📦 Немає даних"
                    except: avail = "📦 Помилка читання"

                    parsed_clean = re.sub(r'[^A-Z0-9]', '', art.upper())
                    t_type = "exact" if parsed_clean != "НД" and (search_clean in parsed_clean or parsed_clean in search_clean) else "analogs"
                    
                    res_dict[t_type].setdefault(f"🔹 *{brand} {art}*", []).append(f"{avail} | 💰 {price}")
                
                api_logger.info(f"🏁 [FORMA] Завершено. Точних: {len(res_dict['exact'])}, Аналогів: {len(res_dict['analogs'])}")
            except Exception as e: 
                api_logger.error(f"❌ [FORMA] Помилка: {e}", exc_info=True)
                
            return res_dict

    async def search_fourcars(self, article):
        async with self.rate_limiter:
            api_logger.info(f"🔍 [4CARS] Пошук: '{article}'")
            res_dict = {"exact": {}, "analogs": {}}
            session = await self._get_session("fourcars")
            if not self.sessions["fourcars"]["auth"] and not await self._login_fourcars(): 
                api_logger.error("[4CARS] Переривання пошуку: немає доступу.")
                return res_dict

            url = f"https://4cars.com.ua/?action=catalog_price&code={article}"
            try:
                api_logger.debug(f"[4CARS] GET запит: {url}")
                async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as res:
                    html = await res.text()

                if "action=user_login" in html.lower() and "action=user_logout" not in html.lower():
                    api_logger.debug("🔄 [4CARS] Сесія застаріла, перелогінююсь...")
                    if not await self._login_fourcars(): return res_dict
                    async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as res:
                        html = await res.text()

                table = BeautifulSoup(html, "html.parser").find("table", class_="datatable")
                if not table: 
                    api_logger.info("ℹ️ [4CARS] Таблиця з результатами відсутня.")
                    return res_dict

                parsing_analogs = False
                for row in table.find_all("tr"):
                    if row.find("td", class_="separator") and "замены" in row.text.lower():
                        parsing_analogs = True
                        continue

                    cols = row.find_all("td")
                    if len(cols) < 6: continue
                    strings = list(cols[0].stripped_strings)
                    if len(strings) < 2: continue
                    
                    brand, art = strings[0], strings[1]
                    avail, term = cols[2].text.strip(), cols[3].text.strip()
                    price_div = cols[5].find("div", class_="table_price")
                    price = price_div.text.strip() if price_div else cols[5].text.strip()

                    if "---" in avail or "---" in term or "---" in price: continue

                    term_c = re.sub(r'днів|дні|день', 'дн.', term, flags=re.IGNORECASE)
                    res_dict["analogs" if parsing_analogs else "exact"].setdefault(f"🔹 *{brand} {art}*", []).append(
                        f"{'⏳' if term_c.isdigit() and int(term_c) > 0 else '⏱'} {term_c + ' дн.' if term_c.isdigit() else term_c} | 📦 {avail.replace('шт.', '').strip()} | 💰 {price}"
                    )
                
                api_logger.info(f"🏁 [4CARS] Завершено. Точних: {len(res_dict['exact'])}, Аналогів: {len(res_dict['analogs'])}")
            except Exception as e: 
                api_logger.error(f"❌ [4CARS] Помилка: {e}", exc_info=True)
                
            return res_dict

    async def search_inside(self, article):
        async with self.rate_limiter:
            api_logger.info(f"🔍 [INSIDE] Пошук: '{article}'")
            res_dict = {"exact": {}, "analogs": {}}
            session = await self._get_session("inside")
            if not self.sessions["inside"]["auth"] and not await self._login_inside(): 
                api_logger.error("[INSIDE] Переривання пошуку: немає доступу.")
                return res_dict

            url = f"https://inside-auto.com/search/pre_search?search={article}"
            try:
                api_logger.debug(f"[INSIDE] GET запит: {url}")
                async with session.get(url) as res: html = await res.text()

                if "вход" in html.lower() and "выход" not in html.lower():
                    api_logger.debug("🔄 [INSIDE] Сесія застаріла, перелогінююсь...")
                    if not await self._login_inside(): return res_dict
                    async with session.get(url) as res: html = await res.text()

                soup = BeautifulSoup(html, 'html.parser')
                brand_items = soup.select('ul.list-group li.list-group-item a')
                
                if brand_items:
                    api_logger.debug("[INSIDE] Знайдено кілька брендів. Вибір найкращого...")
                    av_brands = {item.find('b').text.strip().upper(): item.get('href') for item in brand_items if item.find('b')}
                    sel_url = next((av_brands[pb] for pb in self.preferred_brands if pb in av_brands), list(av_brands.values())[0] if av_brands else None)
                    if sel_url:
                        async with session.get(f"https://inside-auto.com{sel_url}") as r: soup = BeautifulSoup(await r.text(), 'html.parser')

                items = soup.select('.row.item')
                if not items:
                    api_logger.info("ℹ️ [INSIDE] Нічого не знайдено.")
                    return res_dict

                for item in items:
                    b_tag, a_tag = item.select_one('.col-md-3 b'), item.select_one('.col-md-3 a')
                    if not b_tag or not a_tag: continue
                    
                    brand, art = b_tag.text.strip(), a_tag.text.strip()
                    t_type = "exact" if item.select_one('.label-success') else "analogs"
                    b_key = f"🔹 *{brand} {art}*"

                    for offer in item.select('tr[class*="product-"]'):
                        term = offer.select_one('.search-product-term').text.strip().replace('\n', '').replace("в наличии", "в наявності").replace("ч.", "год.") if offer.select_one('.search-product-term') else ""
                        qty = offer.select_one('.search-product-quantity').text.replace('шт.', '').strip() if offer.select_one('.search-product-quantity') else ""
                        price = offer.select_one('.search-product-price').text.replace(' ', '').replace('\n', '').replace('грн.', '').strip() if offer.select_one('.search-product-price') else ""
                        
                        is_fast = 'в наявності' in term.lower() or 'год.' in term.lower() or term.strip() in ['0', '1']
                        res_dict[t_type].setdefault(b_key, []).append(f"{'⏱' if is_fast else '⏳'} {term} | 📦 {qty} | 💰 {price} грн.")

                api_logger.info(f"🏁 [INSIDE] Завершено. Точних: {len(res_dict['exact'])}, Аналогів: {len(res_dict['analogs'])}")
            except Exception as e: 
                api_logger.error(f"❌ [INSIDE] Помилка: {e}", exc_info=True)
                
            return res_dict

    async def close(self):
        api_logger.info("🔌 Закриття HTTP сесій...")
        for data in self.sessions.values():
            if data["http"] and not data["http"].closed:
                await data["http"].close()