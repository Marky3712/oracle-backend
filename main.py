from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import uvicorn
import httpx
import base64
import uuid
import os
import re
from datetime import datetime, timedelta

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== GIGACHAT КЛИЕНТ ====================
class GigaChatClient:
    def __init__(self):
        self.client_id = os.environ.get("GIGACHAT_CLIENT_ID")
        self.client_secret = os.environ.get("GIGACHAT_CLIENT_SECRET")
        self._token = None
        self._token_expires = None

    async def _get_token(self):
        if self._token is not None and self._token_expires is not None and self._token_expires > datetime.now():
            return self._token
        
        credentials = f"{self.client_id}:{self.client_secret}"
        auth_key = base64.b64encode(credentials.encode()).decode()
        
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.post(
                "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
                headers={
                    "Authorization": f"Basic {auth_key}",
                    "RqUID": str(uuid.uuid4()),
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data={"scope": "GIGACHAT_API_PERS"}
            )
            if response.status_code != 200:
                raise Exception(f"Ошибка получения токена: {response.text}")
            
            result = response.json()
            if "access_token" not in result:
                raise Exception(f"Токен не получен: {result}")
            
            self._token = result["access_token"]
            # Если expires_in нет — ставим 1 час (3600 секунд)
            expires_in = result.get("expires_in", 3600)
            self._token_expires = datetime.now() + timedelta(seconds=expires_in)
            return self._token

    async def chat(self, messages, temperature=0.8):
        token = await self._get_token()
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.post(
                "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "GigaChat-Pro",
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": 1000
                },
                timeout=30.0
            )
            return response.json()["choices"][0]["message"]["content"]

gigachat = GigaChatClient()

# ==================== ПРОМПТЫ ====================
SYSTEM_PROMPT = """Ты — Оракул, мистический предсказатель на картах Таро.
Твои ответы должны быть таинственными, в готическом стиле.
Никогда не пиши, что ты ИИ. Ты — Оракул, древний дух."""

def get_daily_prompt():
    return "Вытяни одну карту Таро и дай предсказание на сегодня."

def get_yesno_prompt(question):
    return f"Вопрос: '{question}'. Ответь ДА или НЕТ, затем объясни."

def get_three_prompt(question):
    return f"Сделай расклад Три карты на вопрос: '{question}'."

def get_celtic_prompt(question):
    return f"Сделай расклад Кельтский крест на вопрос: '{question}'."

# ==================== МОДЕЛИ ====================
class PredictRequest(BaseModel):
    spread_type: str
    question: Optional[str] = None
    cards: Optional[List[dict]] = None

class OracleAskRequest(BaseModel):
    question: str

# ==================== ЭНДПОИНТЫ ====================
@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.post("/api/predict")
async def make_prediction(request: PredictRequest):
    try:
        if request.spread_type == "daily":
            user_prompt = get_daily_prompt()
        elif request.spread_type == "yesno":
            if not request.question:
                raise HTTPException(status_code=400, detail="Вопрос обязателен")
            user_prompt = get_yesno_prompt(request.question)
        elif request.spread_type == "three":
            if not request.question:
                raise HTTPException(status_code=400, detail="Вопрос обязателен")
            user_prompt = get_three_prompt(request.question)
        elif request.spread_type == "celtic":
            if not request.question:
                raise HTTPException(status_code=400, detail="Вопрос обязателен")
            user_prompt = get_celtic_prompt(request.question)
        else:
            raise HTTPException(status_code=400, detail="Неизвестный тип расклада")

        if request.cards:
            cards_info = "\n".join([f"- {card.get('name')}: {card.get('meaning')}" for card in request.cards])
            user_prompt += f"\n\nВыпавшие карты:\n{cards_info}\n\nСделай предсказание, основываясь на этих картах."

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
        prediction = await gigachat.chat(messages)
        return {"success": True, "prediction": prediction}
    except Exception as e:
        return {"success": False, "error": str(e), "prediction": "Оракул временно молчит. Попробуй позже."}

@app.post("/api/oracle/ask")
async def oracle_ask(request: OracleAskRequest):
    """Всевидящий Оракул — отвечает на любые вопросы"""
    try:
        messages = [
            {"role": "system", "content": """Ты — Всевидящий Оракул, древний дух, хранитель тайн и судеб.
Твои ответы должны быть таинственными и мудрыми, в готическом стиле.
Никогда не пиши, что ты ИИ. Ты — Оракул."""},
            {"role": "user", "content": request.question}
        ]
        answer = await gigachat.chat(messages, temperature=0.8)
        return {"success": True, "answer": answer}
    except Exception as e:
        return {"success": False, "error": str(e), "answer": "Оракул временно молчит. Попробуй позже."}

# ==================== ТЕСТОВЫЙ ЭНДПОИНТ ====================
@app.get("/api/test-gigachat")
async def test_gigachat():
    result = {
        "has_client_id": bool(os.environ.get("GIGACHAT_CLIENT_ID")),
        "has_client_secret": bool(os.environ.get("GIGACHAT_CLIENT_SECRET")),
        "token_response": None,
        "error": None
    }
    
    try:
        credentials = f"{os.environ.get('GIGACHAT_CLIENT_ID')}:{os.environ.get('GIGACHAT_CLIENT_SECRET')}"
        auth_key = base64.b64encode(credentials.encode()).decode()
        
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.post(
                "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
                headers={
                    "Authorization": f"Basic {auth_key}",
                    "RqUID": str(uuid.uuid4()),
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data={"scope": "GIGACHAT_API_PERS"}
            )
            result["token_response"] = response.status_code
            if response.status_code == 200:
                data = response.json()
                result["has_access_token"] = bool(data.get("access_token"))
            else:
                result["error"] = response.text
    except Exception as e:
        result["error"] = str(e)
    
    return result

# ==================== ДЕБАГ-ЭНДПОИНТ ====================
@app.post("/api/oracle/debug")
async def oracle_debug(request: OracleAskRequest):
    import traceback
    try:
        messages = [
            {"role": "system", "content": "Ты — Оракул. Отвечай кратко, максимум 2 предложения."},
            {"role": "user", "content": request.question}
        ]
        answer = await gigachat.chat(messages, temperature=0.8)
        return {"success": True, "answer": answer}
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
# ==================== ГОРОСКОП ПО ЗНАКАМ ЗОДИАКА ====================
ZODIAC_SIGNS = [
    "Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева",
    "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы"
]

ZODIAC_EMOJIS = {
    "Овен": "♈️", "Телец": "♉️", "Близнецы": "♊️", "Рак": "♋️",
    "Лев": "♌️", "Дева": "♍️", "Весы": "♎️", "Скорпион": "♏️",
    "Стрелец": "♐️", "Козерог": "♑️", "Водолей": "♒️", "Рыбы": "♓️"
}

async def generate_daily_horoscope(sign: str) -> dict:
    """Генерирует гороскоп и карту дня для одного знака через GigaChat"""
    try:
        today = datetime.now().strftime("%d.%m.%Y")
        messages = [
            {"role": "system", "content": f"""Ты — Оракул. Напиши предсказание для знака {sign} на сегодня.
Формат ответа (строго):
ГОРОСКОП: 3-4 предложения, таинственно, но с добрым посылом.
КАРТА ДНЯ: название карты Таро (из старших арканов).
ОПИСАНИЕ КАРТЫ: 1 предложение, что эта карта значит для {sign} сегодня.

Никаких лишних слов, только факты."""},
            {"role": "user", "content": f"Сделай предсказание для {sign} на {today}"}
        ]
        response = await gigachat.chat(messages, temperature=0.8)
        
        # Парсим ответ
        import re
        horoscope_match = re.search(r"ГОРОСКОП:\s*(.+?)(?=КАРТА ДНЯ:|$)", response, re.DOTALL)
        card_match = re.search(r"КАРТА ДНЯ:\s*(.+)", response)
        desc_match = re.search(r"ОПИСАНИЕ КАРТЫ:\s*(.+)", response)
        
        return {
            "success": True,
            "horoscope": horoscope_match.group(1).strip() if horoscope_match else "Туман будущего неясен...",
            "card": card_match.group(1).strip() if card_match else "Шут",
            "card_desc": desc_match.group(1).strip() if desc_match else "Новое начало"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/send-daily-horoscope")
async def send_daily_horoscope():
    """Отправляет гороскоп для всех знаков зодиака в Telegram группу"""
    import httpx
    
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        return {"success": False, "error": "Не настроены TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID"}
    
    today = datetime.now().strftime("%d.%m.%Y")
    results = []
    
    for sign in ZODIAC_SIGNS:
        # Генерируем гороскоп для знака
        horo_data = await generate_daily_horoscope(sign)
        if not horo_data["success"]:
            results.append({"sign": sign, "success": False, "error": horo_data.get("error")})
            continue
        
        emoji = ZODIAC_EMOJIS.get(sign, "🔮")
        
        # Формируем сообщение
        message = f"""{emoji} *{sign}* {emoji}

📜 *Гороскоп на {today}:*
{horo_data['horoscope']}

🃏 *Карта дня:* {horo_data['card']}
{horo_data['card_desc']}

✨ *Совет дня:* Доверься своей интуиции.

#{sign.lower()} #оракул #гороскоп #картадня"""
        
        # Отправляем в Telegram
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "Markdown"
                }
            )
            results.append({"sign": sign, "success": response.status_code == 200})
        
        # Небольшая задержка, чтобы не забанили
        await asyncio.sleep(0.5)
    
    return {"success": True, "results": results}

# ==================== ПЛАНИРОВЩИК ЕЖЕДНЕВНОЙ РАССЫЛКИ ====================
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

async def daily_horoscope_job():
    """Отправляет гороскоп каждый день в 8:00"""
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{os.environ.get('RENDER_EXTERNAL_URL', 'http://localhost:10000')}/api/send-daily-horoscope"
        )

# Запускаем планировщик при старте
@app.on_event("startup")
async def start_scheduler():
    scheduler.add_job(daily_horoscope_job, "cron", hour=8, minute=0)
    scheduler.start()

# Ручной запуск (для тестирования)
@app.post("/api/test-horoscope")
async def test_horoscope():
    """Тестовый запуск для одного знака"""
    test_result = await generate_daily_horoscope("Козерог")
    return test_result
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
