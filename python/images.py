import asyncio
from pathlib import Path
from urllib.parse import urlparse

import httpx

# Папка anime_photo лежит рядом с этим файлом (и рядом с main.py / shikimori.py)
BASE_DIR = Path(__file__).resolve().parent
PHOTO_DIR = BASE_DIR / "anime_photo"
MAIN_DIR = PHOTO_DIR / "mainurl_folder"
ORIGINAL_DIR = PHOTO_DIR / "originalurl_folder"

# Создаем папки при импорте (если уже есть - ничего не произойдет)
MAIN_DIR.mkdir(parents=True, exist_ok=True)
ORIGINAL_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {"User-Agent": "Yume-anime"}  # Как и в shikimori.py


async def _download(client: httpx.AsyncClient, url: str | None, folder: Path, shikimori_id: str) -> str | None:
  """Скачивает одну картинку в folder и возвращает ОТНОСИТЕЛЬНЫЙ путь вида
  'anime_photo/mainurl_folder/5081_main-74bf....webp'. Если не вышло - None."""
  if not url:
    return None

  # Имя берем из ссылки (.name отрезает любые ../, так что выйти из папки нельзя)
  # и добавляем id аниме, чтобы файлы разных аниме не пересеклись
  filename = f"{shikimori_id}_{Path(urlparse(url).path).name}"
  target = folder / filename

  # Если уже скачивали раньше - второй раз не качаем
  if not target.exists():
    try:
      response = await client.get(url)
      response.raise_for_status()
    except httpx.HTTPError as e:
      print(f"Не удалось скачать {url}: {e}")
      return None

    # Сначала пишем во временный файл, потом переименовываем,
    # чтобы не осталось битой наполовину скачанной картинки
    tmp = target.with_name(target.name + ".part")
    tmp.write_bytes(response.content)
    tmp.replace(target)

  # as_posix() -> всегда прямые слеши, удобно и для БД, и для URL во фронтенде
  return target.relative_to(BASE_DIR).as_posix()


async def download_anime_images(shikimori_id: str, original_url: str | None, main_url: str | None):
  """Качает обе картинки параллельно. Возвращает (original_path, main_path)."""
  async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
    return await asyncio.gather(
        _download(client, original_url, ORIGINAL_DIR, shikimori_id),
        _download(client, main_url, MAIN_DIR, shikimori_id),
    )
