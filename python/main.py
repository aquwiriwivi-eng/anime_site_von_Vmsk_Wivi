import asyncio
import logging
import os
import secrets
import uuid
from datetime import date
from io import BytesIO
from pathlib import Path

import psycopg  # ЧТОБЫ ОБЩАТЬСЯ С POSTGRES
from fastapi import (Depends, FastAPI, File, Form, HTTPException, Query,
                     Request, Response, UploadFile)
from fastapi.staticfiles import StaticFiles  # Чтобы отдавать картинки фронтенду
from itsdangerous import BadSignature, URLSafeTimedSerializer
from PIL import Image
from prometheus_fastapi_instrumentator import Instrumentator  # Prometheus: сбор метрик
from psycopg.errors import UniqueViolation

from images import PHOTO_DIR, download_anime_images
from shikimori import fetch_anime_from_shikimori

# Логи uvicorn уходят в Docker -> Alloy -> Loki, поэтому пишем туда же
log = logging.getLogger("uvicorn.error")

#--------------------------------------------------

app = FastAPI()

# Картинки будут доступны по адресу /anime_photo/mainurl_folder/<файл>
# Это совпадает с относительным путём, который лежит в БД
app.mount("/anime_photo", StaticFiles(directory=PHOTO_DIR), name="anime_photo")

Instrumentator().instrument(app).expose(app)


def get_conn():
  return psycopg.connect(
      host="postgre_sql",
      port=5432,
      dbname=os.environ["POSTGRES_DB"],
      user=os.environ["POSTGRES_USER"],
      password=os.environ["DB_PASSWORD"],
  )


# ---------- Настройки админки ----------

# Если пароль или секрет не заданы, админка выключена (503), а сайт всё равно стартует
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ADMIN_SECRET_KEY = os.environ.get("ADMIN_SECRET_KEY")
SESSION_TTL = 2 * 60 * 60
COOKIE_NAME = "admin_session"
# Secure-cookie уходит только по HTTPS. Для локальной разработки по http: COOKIE_SECURE=0
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") != "0"
signer = (URLSafeTimedSerializer(ADMIN_SECRET_KEY, salt="admin-session")
          if ADMIN_SECRET_KEY else None)

BANNER_DIR = Path(PHOTO_DIR) / "week"
BANNER_DB_PREFIX = "anime_photo/week"   # так же, как в БД лежат mainurl/originalurl
MAX_BANNER_BYTES = 10 * 1024 * 1024
MAX_BANNER_PIXELS = 40_000_000          # защита от "бомб": маленький файл, огромная картинка
BANNER_SIZE = (1920, 1080)
Image.MAX_IMAGE_PIXELS = MAX_BANNER_PIXELS

SEARCH_LIMIT = 50


def client_ip(request: Request) -> str:
  # nginx перезаписывает X-Real-IP, поэтому значению можно верить (только для логов)
  return request.headers.get("x-real-ip") or (request.client.host if request.client else "?")


def require_admin(request: Request):
  if not signer or not ADMIN_PASSWORD:
    raise HTTPException(503, "Админка не настроена")
  try:
    ok = signer.loads(request.cookies.get(COOKIE_NAME, ""), max_age=SESSION_TTL) == "admin"
  except BadSignature:  # включая истёкшую подпись
    ok = False
  if not ok:
    raise HTTPException(401, "Unauthorized")
  # CSRF: с чужого сайта кастомный заголовок без CORS не отправить
  if request.method not in ("GET", "HEAD") and request.headers.get("x-requested-with") != "admin-ui":
    raise HTTPException(403, "Forbidden")


@app.post("/api/admin/login")
def admin_login(request: Request, response: Response, password: str = Form(..., max_length=256)):
  if not ADMIN_PASSWORD or not signer:
    raise HTTPException(503, "Админка не настроена")
  if not secrets.compare_digest(password.encode(), ADMIN_PASSWORD.encode()):
    log.warning("admin: неудачный вход, ip=%s", client_ip(request))
    raise HTTPException(401, "Неверный пароль")
  response.set_cookie(COOKIE_NAME, signer.dumps("admin"), max_age=SESSION_TTL,
                      httponly=True, secure=COOKIE_SECURE, samesite="strict", path="/api/admin")
  log.info("admin: вход, ip=%s", client_ip(request))
  return {"ok": True}


@app.post("/api/admin/logout")
def admin_logout(response: Response):
  response.delete_cookie(COOKIE_NAME, path="/api/admin")
  return {"ok": True}


# ---------- Каталог и поиск ----------

SEARCH_COLUMNS = "id, shikimori_id, name, russian, japanese, date, originalurl, mainurl, description"


def like_pattern(q: str) -> str:
  """Экранируем % и _ , чтобы пользователь не мог искать по маске."""
  escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
  return f"%{escaped}%"


def anime_row_to_dict(r):
  return {
      "id": r[0],
      "shikimori_id": r[1],
      "name": r[2],
      "russian": r[3],
      "japanese": r[4],
      "date": str(r[5]) if r[5] else None,
      "originalurl": r[6],
      "mainurl": r[7],
      "description": r[8],
  }


def find_local(q: str) -> list[dict]:
  pattern = like_pattern(q)
  with get_conn() as conn:
    rows = conn.execute(
        f"SELECT {SEARCH_COLUMNS} FROM anime_list "
        "WHERE name ILIKE %s OR russian ILIKE %s OR japanese ILIKE %s "
        "ORDER BY id LIMIT %s",
        (pattern, pattern, pattern, SEARCH_LIMIT),
    ).fetchall()
  return [anime_row_to_dict(r) for r in rows]


def find_by_shikimori_ids(ids: list[str]) -> list[dict]:
  if not ids:
    return []
  with get_conn() as conn:
    rows = conn.execute(
        f"SELECT {SEARCH_COLUMNS} FROM anime_list WHERE shikimori_id = ANY(%s)",
        (ids,),
    ).fetchall()
  return [anime_row_to_dict(r) for r in rows]


def save_new_animes(items: list[tuple]) -> list[dict]:
  """items: (anime, poster, original_path, main_path). Всё в одной транзакции."""
  saved = []
  with get_conn() as conn:
    for anime, poster, original_path, main_path in items:
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

      row = conn.execute(
          """
          INSERT INTO anime_list (shikimori_id, name, russian, japanese, date, originalurl, mainurl, description)
          VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
          ON CONFLICT (shikimori_id) DO UPDATE SET name = EXCLUDED.name
          RETURNING id
          """,
          (shikimori_id, name, russian, japanese, aired_date, original_url, main_url, description),
      ).fetchone()

      saved.append({
          "id": row[0],  # Реальный ID из Postgres
          "shikimori_id": shikimori_id,
          "name": name,
          "russian": russian,
          "japanese": japanese,
          "date": aired_date,
          "originalurl": original_url,  # путь вида anime_photo/originalurl_folder/...
          "mainurl": main_url,          # путь вида anime_photo/mainurl_folder/...
          "description": description,
      })
  return saved


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
def anime_search_local(q: str = Query(..., min_length=1, max_length=100)):
  return find_local(q)


@app.get("/api/search/sync")
async def anime_search_sync(q: str = Query(..., min_length=2, max_length=100)):
  # Блокирующие вызовы psycopg выносим в потоки, чтобы не вешать event loop

  # 1. Сначала собираем то, что уже есть в локальной базе
  combined_results = await asyncio.to_thread(find_local, q)
  known_ids = {str(item["shikimori_id"]) for item in combined_results}

  # 2. Запрашиваем Шикимори
  try:
    shikimori_data = await fetch_anime_from_shikimori(q)
    shikimori_animes = ((shikimori_data.get("data") or {}).get("animes")) or []
  except Exception as e:
    # Детали ошибки - в лог, а не клиенту. Формат ответа всегда один: список.
    log.warning("Shikimori недоступен: %s", e)
    return combined_results

  shikimori_ids = [str(a["id"]) for a in shikimori_animes if a.get("id")]

  # 3. Что из ответа Shikimori уже есть в БД (но не нашлось локальным поиском по названию)
  in_db = await asyncio.to_thread(find_by_shikimori_ids, shikimori_ids)
  for item in in_db:
    if str(item["shikimori_id"]) not in known_ids:
      combined_results.append(item)
      known_ids.add(str(item["shikimori_id"]))
  db_ids = {str(item["shikimori_id"]) for item in in_db}

  # 4. Новыми считаем только то, чего реально нет в БД
  new_animes = [a for a in shikimori_animes
                if a.get("id") and str(a["id"]) not in db_ids and str(a["id"]) not in known_ids]
  if not new_animes:
    return combined_results

  # 5. Скачиваем картинки ДО работы с БД (все аниме параллельно).
  posters = [a.get("poster") or {} for a in new_animes]
  photo_paths = await asyncio.gather(*(
      download_anime_images(str(a.get("id")), p.get("originalUrl"), p.get("mainUrl"))
      for a, p in zip(new_animes, posters)
  ))

  # 6. Сохраняем: в БД идёт ПУТЬ к файлу, а не ссылка Shikimori
  items = [(a, p, paths[0], paths[1]) for a, p, paths in zip(new_animes, posters, photo_paths)]
  combined_results += await asyncio.to_thread(save_new_animes, items)

  return combined_results


# Забираем из POSTGRES подробные данные про одно аниме по id этого аниме.
# def, а не async def: psycopg блокирующий, FastAPI сам запустит это в пуле потоков.
@app.get("/api/anime/{anime_id}")
def anime_search_by_id(anime_id: int):
  with get_conn() as conn:
    anime_all_desc = conn.execute(
        "SELECT id, shikimori_id, name, russian, japanese, date, description, originalurl, mainurl "
        "FROM anime_list "
        "WHERE id = %s ",
        (anime_id,),
    ).fetchone()

  if not anime_all_desc:
    raise HTTPException(status_code=404, detail="Аниме не найдено в базе данных")

  return {
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


# ---------- Аниме недели: публичная часть ----------

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


@app.get("/api/anime-of-the-week")
def get_anime_of_the_week():
  """Слоты (до 3) последней начавшейся недели."""
  with get_conn() as conn:
    rows = conn.execute(
        WEEK_SELECT + """
        WHERE w.is_published AND NOT w.is_archived
          AND w.week_start = (
              SELECT MAX(week_start) FROM anime_of_the_week
              WHERE is_published AND NOT is_archived AND week_start <= CURRENT_DATE
          )
        ORDER BY w.position
        """
    ).fetchall()
  return [week_row_to_dict(r) for r in rows]


@app.get("/api/anime-of-the-week/archive")
def get_week_archive(
    year: int | None = Query(default=None, ge=2000, le=2100),
    shikimori_id: str | None = Query(default=None, max_length=50),
):
  """Архив. Фильтры необязательные: ?year=2025 и/или ?shikimori_id=16498"""
  conditions = ["w.week_start <= CURRENT_DATE"]
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


# ---------- Аниме недели: админка (всё под require_admin) ----------

ADMIN_SELECT = """
SELECT w.id, w.week_start, w.position, w.is_published, w.tagline, w.banner_path,
       a.shikimori_id, a.russian, a.name
FROM anime_of_the_week w JOIN anime_list a ON a.id = w.anime_id
"""


@app.get("/api/admin/anime-of-the-week", dependencies=[Depends(require_admin)])
def admin_list_week(limit: int = Query(30, ge=1, le=100)):
  """Все слоты, включая скрытые и будущие недели."""
  with get_conn() as conn:
    rows = conn.execute(
        ADMIN_SELECT + "WHERE NOT w.is_archived ORDER BY w.week_start DESC, w.position LIMIT %s", (limit,)
    ).fetchall()
  return [{"id": r[0], "week_start": str(r[1]), "position": r[2], "is_published": r[3],
           "tagline": r[4], "banner_path": r[5], "shikimori_id": r[6],
           "title": r[7] or r[8]} for r in rows]


@app.post("/api/admin/anime-of-the-week", dependencies=[Depends(require_admin)])
def admin_set_anime_of_the_week(
    request: Request,
    shikimori_id: str = Form(..., max_length=50),
    week_start: date = Form(...),
    position: int = Form(..., ge=1, le=3),
    tagline: str = Form(..., max_length=200),
    banner: UploadFile = File(...),
):
  if week_start.isoweekday() != 1:
    raise HTTPException(422, "week_start должен быть понедельником")
  tagline = tagline.strip()
  if not 5 <= len(tagline) <= 40:
    raise HTTPException(422, "Слоган должен быть 5-40 символов")

  raw = banner.file.read(MAX_BANNER_BYTES + 1)
  if len(raw) > MAX_BANNER_BYTES:
    raise HTTPException(413, "Файл больше 10 МБ")

  # Сначала проверяем размеры по заголовку, и только потом декодируем пиксели
  try:
    Image.open(BytesIO(raw)).verify()          # это вообще картинка?
    img = Image.open(BytesIO(raw))             # после verify() файл нужно открыть заново
    w, h = img.size
  except Exception:
    raise HTTPException(422, "Не удалось прочитать изображение")

  if w * h > MAX_BANNER_PIXELS:
    raise HTTPException(422, f"Слишком большое изображение ({w}x{h})")
  if w < 1280 or abs(w / h - 16 / 9) > 0.02:
    raise HTTPException(422, f"Нужен арт 16:9 от 1280 px по ширине (получено {w}x{h})")

  try:
    img = img.convert("RGB").resize(BANNER_SIZE, Image.LANCZOS)
  except Exception:
    raise HTTPException(422, "Не удалось обработать изображение")

  # Имя файла строим сами, чтобы никаких имён от клиента
  BANNER_DIR.mkdir(parents=True, exist_ok=True)
  filename = f"{week_start.isoformat()}-{position}-{uuid.uuid4().hex[:8]}.webp"
  final_path = BANNER_DIR / filename
  tmp_path = final_path.with_suffix(".part")
  img.save(tmp_path, format="WEBP", quality=85)

  banner_path = f"{BANNER_DB_PREFIX}/{filename}"

  # Сначала БД, потом rename: при любой ошибке старый арт остаётся нетронутым
  try:
    with get_conn() as conn:
      conn.execute(
          "UPDATE anime_of_the_week "
          "SET is_archived = TRUE, is_published = FALSE, archived_at = NOW() "
          "WHERE week_start = %s AND position = %s AND is_archived = FALSE",
          (week_start, position),
      )
      row = conn.execute(
          """
          INSERT INTO anime_of_the_week (anime_id, banner_path, tagline, week_start, position)
          SELECT id, %s, %s, %s, %s FROM anime_list WHERE shikimori_id = %s
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
  log.info("admin: слот %s недели %s -> shikimori_id=%s, ip=%s",
           position, week_start, shikimori_id, client_ip(request))
  return {"id": row[0], "banner_path": banner_path, "position": position, "week_start": str(week_start)}


@app.patch("/api/admin/anime-of-the-week/{item_id}", dependencies=[Depends(require_admin)])
def admin_toggle_week(request: Request, item_id: int, is_published: bool = Form(...)):
  with get_conn() as conn:
    row = conn.execute(
        "UPDATE anime_of_the_week SET is_published = %s WHERE id = %s AND is_archived = FALSE RETURNING id",
        (is_published, item_id),
    ).fetchone()
  if not row:
    raise HTTPException(404, "Слот не найден")
  log.info("admin: слот id=%s is_published=%s, ip=%s", item_id, is_published, client_ip(request))
  return {"id": item_id, "is_published": is_published}


@app.delete("/api/admin/anime-of-the-week/{item_id}", dependencies=[Depends(require_admin)])
def admin_delete_week(request: Request, item_id: int):
  with get_conn() as conn:
    row = conn.execute(
        "DELETE FROM anime_of_the_week WHERE id = %s RETURNING banner_path", (item_id,)
    ).fetchone()
  if not row:
    raise HTTPException(404, "Слот не найден")
  (BANNER_DIR / Path(row[0]).name).unlink(missing_ok=True)  # только имя файла, никаких путей
  log.info("admin: удалён слот id=%s, ip=%s", item_id, client_ip(request))
  return {"deleted": item_id}
