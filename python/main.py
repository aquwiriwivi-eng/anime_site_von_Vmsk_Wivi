import os #БЕРЕМ ПАРОЛИ ИЗ ОКРУЖЕНИЯ BASH
import psycopg #ЧТОБЫ ОБЩАТЬСЯ С POSTGRESS
import httpx #Чтобы общаться с Shikimori_api и использовать http-протокол

from fastapi import FastAPI, HTTPException #Чтобы писать api
from pydantic import BaseModel #чтобы писать api и задавать классы - хз что значит, но это надо, без этого никак!

import python.shikimori import fetch_anime_from_shikimori

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
def anime_search(q: str):
    search_pattern = f"%{q}%"
    with get_conn() as conn:
        anime_rows = conn.execute(
            "SELECT id, shikimori_id, name, russian, japanese, date, mainurl FROM anime_list "
            "WHERE name ILIKE %s "
            "OR russian ILIKE %s "
            "OR japanese ILIKE %s",
            (search_pattern, search_pattern, search_pattern),
        ).fetchall()

        #Превращаем ответ postgress в json массив и отправляем в фронтенд
        search_results = [
        {
            "id": r[0],
            "shikimori_id": r[1],
            "name": r[2],
            "russian": r[3],
            "japanese": r[4],
            "date": str(r[5]) if r[5] else None,
            "mainurl": r[6]
        }
        for r in anime_rows
    ]

    return search_results
