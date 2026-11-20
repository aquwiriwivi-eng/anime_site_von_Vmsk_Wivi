import os  # БЕРЕМ ПАРОЛИ ИЗ ОКРУЖЕНИЯ BASH
import asyncio
import psycopg  # ЧТОБЫ ОБЩАТЬСЯ С POSTGRES
import httpx  # Чтобы общаться с Shikimori_api

from fastapi.staticfiles import StaticFiles  # Чтобы отдавать картинки фронтенду
from pydantic import BaseModel

# Правильный импорт твоей функции (проверь название файла: shikimori или shikimori_2)
from shikimori import fetch_anime_from_shikimori
from images import download_anime_images, PHOTO_DIR

import secrets
from datetime import date
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, Query, Depends, Request, Response
from PIL import Image
from psycopg.errors import UniqueViolation

#--------------------------------------------------

app = FastAPI()

# Картинки будут доступны по адресу /anime_photo/mainurl_folder/<файл>
# Это совпадает с относительным путём, который лежит в БД
app.mount("/anime_photo", StaticFiles(directory=PHOTO_DIR), name="anime_photo")

from prometheus_fastapi_instrumentator import Instrumentator #Added Prometheus to collect metrics
Instrumentator().instrument(app).expose(app) #Added Prometheus to collect metrics


def get_conn():
  return psycopg.connect(
      host="postgre_sql",
      port=5432,
      dbname=os.environ["POSTGRES_DB"],
      user=os.environ["POSTGRES_USER"],
      password=os.environ["DB_PASSWORD"],
  )

# Если токен не задан, админ-эндпоинт просто выключен, а сайт всё равно стартует
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")
BANNER_DIR = Path(PHOTO_DIR) / "week"
BANNER_DB_PREFIX = "anime_photo/week"   # так же, как в БД лежат mainurl/originalurl
MAX_BANNER_BYTES = 10 * 1024 * 1024
BANNER_SIZE = (1920, 1080)

WEEK_SELECT = """
SELECT w.position, a.id, a.shikimori_id, a.name, a.russian, a.mainurl,
       w.banner_path, w.tagline, w.week_start
FROM anime_of_the_week w
JOIN anime_list a ON a.id = w.anime_id
"""


def week_row_to_dict(r):
  return {
      "position": r[0],
      "anime_id": r[1],
      "shikimori_id": r[2],
      "name": r[3],
      "russian": r[4],
      "mainurl": r[5],
      "banner_path": r[6],
      "tagline": r[7],
      "week_start": str(r[8]),
  }


def check_admin(token: str | None):
  if not ADMIN_TOKEN:
    raise HTTPException(status_code=503, detail="ADMIN_TOKEN не настроен")
  if not token or not secrets.compare_digest(token, ADMIN_TOKEN):
    raise HTTPException(status_code=401, detail="Unauthorized")


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

  # 3. Берем только те аниме, которых ещё нет в нашей базе
  new_animes = [a for a in shikimori_animes if str(a.get("id")) not in existing_shikimori_ids]

  # 4. Скачиваем картинки ДО работы с БД (все аниме параллельно).
  #    Для каждого аниме получаем (путь_original, путь_main)
  posters = [a.get("poster") or {} for a in new_animes]
  photo_paths = await asyncio.gather(*(
      download_anime_images(str(a.get("id")), p.get("originalUrl"), p.get("mainUrl"))
      for a, p in zip(new_animes, posters)
  ))

  # 5. Сохраняем новые аниме: в БД идёт ПУТЬ к файлу, а не ссылка Shikimori
  with get_conn() as conn:
    with conn.cursor() as cur:
      for anime, poster, (original_path, main_path) in zip(new_animes, posters, photo_paths):
        shikimori_id = str(anime.get("id"))
        name = anime.get("name")
        russian = anime.get("russian")
        japanese = anime.get("japanese")
        aired_date = (anime.get("airedOn") or {}).get("date")
        description = anime.get("description")

        # Если скачать не удалось (path = None) - временно оставляем ссылку Shikimori,
        # чтобы фронтенд не остался совсем без картинки
        original_url = original_path or poster.get("originalUrl")
        main_url = main_path or poster.get("mainUrl")

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
            "id": row_id,  # Реальный ID из Postgres
            "shikimori_id": shikimori_id,
            "name": name,
            "russian": russian,
            "japanese": japanese,
            "date": aired_date,
            "originalurl": original_url,  # теперь это путь вида anime_photo/originalurl_folder/...
            "mainurl": main_url,          # а это anime_photo/mainurl_folder/...
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

# ---------- Аниме недели ----------

@app.get("/api/anime-of-the-week")
def get_anime_of_the_week():
  """Слоты (до 3) последней начавшейся недели."""
  with get_conn() as conn:
    rows = conn.execute(
        WEEK_SELECT + """
        WHERE w.is_published
          AND w.week_start = (
              SELECT MAX(week_start) FROM anime_of_the_week
              WHERE is_published AND week_start <= CURRENT_DATE
          )
        ORDER BY w.position
        """
    ).fetchall()
  return [week_row_to_dict(r) for r in rows]


@app.get("/api/anime-of-the-week/archive")
def get_week_archive(
    year: int | None = Query(default=None, ge=2000, le=2100),
    shikimori_id: str | None = None,
):
  """Архив. Фильтры необязательные: ?year=2025 и/или ?shikimori_id=16498"""
  conditions = ["w.is_published", "w.week_start <= CURRENT_DATE"]
  params: list = []

  if year:
    conditions.append("w.week_start >= %s AND w.week_start < %s")
    params += [date(year, 1, 1), date(year + 1, 1, 1)]
  if shikimori_id:
    conditions.append("a.shikimori_id = %s")
    params.append(shikimori_id)

  query = (
      WEEK_SELECT
      + " WHERE " + " AND ".join(conditions)
      + " ORDER BY w.week_start DESC, w.position"
  )
  with get_conn() as conn:
    rows = conn.execute(query, params).fetchall()
  return [week_row_to_dict(r) for r in rows]


@app.post("/api/admin/anime-of-the-week")
def admin_set_anime_of_the_week(
    shikimori_id: str = Form(...),
    week_start: date = Form(...),
    position: int = Form(..., ge=1, le=3),
    tagline: str = Form(...),
    banner: UploadFile = File(...),
    x_admin_token: str | None = Header(default=None),
):
  check_admin(x_admin_token)

  if week_start.isoweekday() != 1:
    raise HTTPException(422, "week_start должен быть понедельником")
  tagline = tagline.strip()
  if not 15 <= len(tagline) <= 20:
    raise HTTPException(422, "Слоган должен быть 15-20 символов")

  raw = banner.file.read(MAX_BANNER_BYTES + 1)
  if len(raw) > MAX_BANNER_BYTES:
    raise HTTPException(413, "Файл больше 10 МБ")

  try:
    Image.open(BytesIO(raw)).verify()          # это вообще картинка?
    img = Image.open(BytesIO(raw)).convert("RGB")
  except Exception:
    raise HTTPException(422, "Не удалось прочитать изображение")

  w, h = img.size
  if w < 1280 or abs(w / h - 16 / 9) > 0.02:
    raise HTTPException(422, f"Нужен арт 16:9 от 1280 px по ширине (получено {w}x{h})")
  img = img.resize(BANNER_SIZE, Image.LANCZOS)

  # Имя файла строим сами, чтобы никаких имён от клиента
  BANNER_DIR.mkdir(parents=True, exist_ok=True)
  filename = f"{week_start.isoformat()}-{position}.webp"
  final_path = BANNER_DIR / filename
  tmp_path = final_path.with_suffix(".part")
  img.save(tmp_path, format="WEBP", quality=85)

  banner_path = f"{BANNER_DB_PREFIX}/{filename}"

  # Сначала БД, потом rename: при любой ошибке старый арт остаётся нетронутым
  try:
    with get_conn() as conn:
      row = conn.execute(
          """
          INSERT INTO anime_of_the_week (anime_id, banner_path, tagline, week_start, position)
          SELECT id, %s, %s, %s, %s FROM anime_list WHERE shikimori_id = %s
          ON CONFLICT (week_start, position) DO UPDATE
             SET anime_id = EXCLUDED.anime_id,
                 banner_path = EXCLUDED.banner_path,
                 tagline = EXCLUDED.tagline
          RETURNING id
          """,
          (banner_path, tagline, week_start, position, shikimori_id),
      ).fetchone()
  except UniqueViolation:
    tmp_path.unlink(missing_ok=True)
    raise HTTPException(409, "Это аниме уже стоит на этой неделе в другом слоте")
  except Exception:
    tmp_path.unlink(missing_ok=True)
    raise

  if row is None:
    tmp_path.unlink(missing_ok=True)
    raise HTTPException(404, "Аниме с таким shikimori_id нет в каталоге: сначала найди его через /api/search/sync")

  tmp_path.replace(final_path)
  return {"id": row[0], "banner_path": banner_path, "position": position, "week_start": str(week_start)}
