import os #БЕРЕМ ПАРОЛИ ИЗ ОКРУЖЕНИЯ BASH
import psycopg #ЧТОБЫ ОБЩАТЬСЯ С POSTGRESS
import httpx #Чтобы общаться с Shikimori_api и использовать http-протокол

from fastapi import FastAPI, HTTPException #Чтобы писать api
from pydantic import BaseModel #чтобы писать api и задавать классы - хз что значит, но это надо, без этого никак!

app = FastAPI()

def get_conn():
    return psycopg.connect(
        host="postgre_sql",
        port=5432,
        dbname="Anime_Wivi",
        user="Vmsk_Wivi",
        password=os.environ["DB_PASSWORD"],
    )

@app.get("/api/search") # Чекай // Обработчик отправки поисковой формы (AJAX/Fetch) там в строке  // Отправляем GET-запрос на бэкенд
# const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
#есть кусочек /api/search?q=
# а дальше после $() являеться нашим текстом запроса, например "Атака Титанов"
def anime_search(search_query, str):
    with get_conn() as conn:
        anime_search = conn.execute(
            "SELECT id, shikimori_id, name, russian, japanese, date, mainurl FROM anime_list "
            "WHERE name ILIKE %s "
            "OR russian ILIKE %s "
            "OR japanese ILIKE %s",
            (search_query, search_query, search_query),
        ).fetchall()
