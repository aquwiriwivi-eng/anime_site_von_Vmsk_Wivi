import os  # БЕРЕМ ПАРОЛИ ИЗ ОКРУЖЕНИЯ BASH
import psycopg  # ЧТОБЫ ОБЩАТЬСЯ С POSTGRES
import httpx  # Чтобы общаться с Shikimori_api

from fastapi import FastAPI, HTTPException  # Чтобы писать api
from pydantic import BaseModel

# Правильный импорт твоей функции (проверь название файла: shikimori или shikimori_2)
from shikimori import fetch_anime_from_shikimori

app = FastAPI()


def get_conn():
  return psycopg.connect(
      host="postgre_sql",
      port=5432,
      dbname="Anime_Wivi",
      user="Vmsk_Wivi",
      password=os.environ["DB_PASSWORD"],
  )


@app.get("/api/random")
def get_random_anime():
  with get_conn() as conn:
    anime_rows = conn.execute(
        "SELECT id, shikimori_id, name, russian, japanese, date, originalurl,"
        " mainurl FROM anime_list ORDER BY RANDOM() LIMIT 6"
    ).fetchall()

  return [
      {
          "id": r[0],
          "shikimori_id": r[1],
          "name": r[2],
          "russian": r[3],
          "japanese": r[4],
          "date": str(r[5]) if r[5] else None,
          "originalurl": r[6],
          "mainurl": r[7],
      }
      for r in anime_rows
  ]


@app.get("/api/search/local")
def anime_search_local(q: str):
  search_pattern = f"%{q}%"
  with get_conn() as conn:
    anime_rows = conn.execute(
        "SELECT id, shikimori_id, name, russian, japanese, date, originalurl, mainurl, description "
        "FROM anime_list "
        "WHERE name ILIKE %s OR russian ILIKE %s OR japanese ILIKE %s",
        (search_pattern, search_pattern, search_pattern),
    ).fetchall()

  return [
      {
          "id": r[0],
          "shikimori_id": r[1],
          "name": r[2],
          "russian": r[3],
          "japanese": r[4],
          "date": str(r[5]) if r[5] else None,
          "originalurl": r[6],
          "mainurl": r[7],
          "description": r[8]
      }
      for r in anime_rows
  ]


@app.get("/api/search/sync")
async def anime_search_sync(q: str):
  search_pattern = f"%{q}%"
  
  # 1. Сначала собираем то, что уже есть в локальной базе
  with get_conn() as conn:
    anime_rows = conn.execute(
        "SELECT id, shikimori_id, name, russian, japanese, date, originalurl, mainurl, description "
        "FROM anime_list "
        "WHERE name ILIKE %s OR russian ILIKE %s OR japanese ILIKE %s",
        (search_pattern, search_pattern, search_pattern),
    ).fetchall()

  local_results = [
      {
          "id": r[0],
          "shikimori_id": r[1],
          "name": r[2],
          "russian": r[3],
          "japanese": r[4],
          "date": str(r[5]) if r[5] else None,
          "originalurl": r[6],
          "mainurl": r[7],
          "description": r[8]
      }
      for r in anime_rows
  ]
  
  existing_shikimori_ids = {str(item["shikimori_id"]) for item in local_results if item["shikimori_id"]}
  combined_results = list(local_results)

  # 2. Запрашиваем Шикимори
  try:
    shikimori_data = await fetch_anime_from_shikimori(q)
    shikimori_animes = shikimori_data.get("data", {}).get("animes", [])
  except Exception as e:
    return {"results": combined_results, "api_status": str(e)}

  # 3. Сохраняем новые аниме и сразу забираем их реальный Postgres ID через RETURNING id
  with get_conn() as conn:
    with conn.cursor() as cur:
      for anime in shikimori_animes:
        shikimori_id = str(anime.get("id"))
        name = anime.get("name")
        russian = anime.get("russian")
        japanese = anime.get("japanese")
        aired_date = anime.get("airedOn", {}).get("date")
        description = anime.get("description")
        poster = anime.get("poster", {})
        original_url = poster.get("originalUrl")
        main_url = poster.get("mainUrl")

        if shikimori_id not in existing_shikimori_ids:
          cur.execute(
              """
              INSERT INTO anime_list (shikimori_id, name, russian, japanese, date, originalurl, mainurl, description)
              VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
              ON CONFLICT (shikimori_id) DO UPDATE SET name = EXCLUDED.name
              RETURNING id
              """,
              (shikimori_id, name, russian, japanese, aired_date, original_url, main_url, description)
          )
          row = cur.fetchone()
          conn.commit()
          row_id = row[0] if row else None

          combined_results.append({
              "id": row_id,  # <--- Теперь здесь реальный ID из Postgres!
              "shikimori_id": shikimori_id,
              "name": name,
              "russian": russian,
              "japanese": japanese,
              "date": aired_date,
              "originalurl": original_url,
              "mainurl": main_url,
              "description": description
          })

  return combined_results


  # Забириаем из POSTGRES подробные данные про одно аниме по id этого аниме
#Больше данных добавлю позже.
@app.get("/api/anime/{anime_id}")
async def anime_search_by_id(anime_id: int):
  with get_conn() as conn:
    anime_all_desc = conn.execute(
        "SELECT id, shikimori_id, name, russian, japanese, date, description, originalurl, mainurl "
        "FROM anime_list "
        "WHERE id = %s ",
        (anime_id,),
    ).fetchone()
    
    if not anime_all_desc:
        raise HTTPException(status_code=404, detail="Аниме не найдено в базе данных")
    
    # Превращаем ответ postgres в JSON-совместимый массив как в app.get search
  return{
          "id": anime_all_desc[0],
          "shikimori_id": anime_all_desc[1],
          "name": anime_all_desc[2],
          "russian": anime_all_desc[3],
          "japanese": anime_all_desc[4],
          "date": str(anime_all_desc[5]) if anime_all_desc[5] else None,
          "description": anime_all_desc[6],
          "originalurl": anime_all_desc[7],
          "mainurl": anime_all_desc[8],
    }