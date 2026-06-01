import re
import logging

logger = logging.getLogger(__name__)

def clean_articles(text):
    logger.debug(f"Оригінальний текст для очищення: '{text}'")
    
    cyrillic = "АВЕКМНОРСТХІУуавекмнорстхі"
    latin    = "ABEKMHOPCTXIYyabekmhopctxi"
    layout_map = str.maketrans(cyrillic, latin)
    
    fixed_text = text.translate(layout_map).upper()
    fixed_text = fixed_text.replace('"', '').replace("'", "").replace("`", "")
    logger.debug(f"Текст після транслітерації та видалення лапок: '{fixed_text}'")
    
    raw_articles = re.split(r'[,\n/.;|]', fixed_text)
    articles = []
    
    for art in raw_articles:
        clean_art = art.strip()
        if clean_art and len(clean_art) <= 25 and clean_art.count(" ") <= 1:
            articles.append(clean_art)
            
    logger.debug(f"Фінальний список артикулів для пошуку: {articles}")
    return articles

def format_dict_results(data_dict):
    logger.debug(f"Форматування результатів (кількість груп: {len(data_dict)})")
    lines = []
    for brand_art, offers in data_dict.items():
        lines.append(brand_art)
        lines.extend(offers)
        lines.append("") 
    return "\n".join(lines).strip()

def build_store_reply(store_name, result_data):
    logger.debug(f"Побудова відповіді для магазину: {store_name}")
    reply = f"🛒 {store_name}\n\n"
    if result_data["exact"]:
        reply += format_dict_results(result_data["exact"])
    else:
        reply += "❌ Деталь не знайдена."
    if result_data["analogs"]:
        reply += "\n\n♻️ *Є АНАЛОГИ*"
    return reply