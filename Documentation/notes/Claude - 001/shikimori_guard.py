"""Защита квоты Shikimori (5 запросов/с и 90/мин на IP нашего сервера, то есть на ВЕСЬ сайт сразу).

Три механизма:
  1. кэш запросов (одинаковые поиски разных посетителей не доходят до Shikimori);
  2. склейка одновременных одинаковых запросов в один;
  3. глобальный лимитер со скользящим окном + пауза после 429.

Состояние лежит в памяти процесса. Это корректно, пока uvicorn запущен с ОДНИМ воркером
(так сейчас: `fastapi run`). При нескольких воркерах состояние нужно вынести в Redis.
"""
import asyncio
import logging
import time

from prometheus_client import Counter

from shikimori import ShikimoriError, fetch_anime_from_shikimori

log = logging.getLogger("uvicorn.error")

# Запас от официальных 5 rps / 90 rpm
PER_SECOND = 4
PER_MINUTE = 80
PAUSE_AFTER_429 = 60          # секунд не ходим в Shikimori после ответа 429
CACHE_TTL = 24 * 3600         # нашли аниме: помним сутки
EMPTY_TTL = 3600              # ничего не нашли: помним час (вдруг ошибка в запросе)
MAX_CACHE = 5000

REQUESTS = Counter("shikimori_requests_total", "Обращения к Shikimori по результату", ["result"])

now = time.monotonic          # подменяется в тестах


class ShikimoriBusy(Exception):
  """Внешний запрос не отправлен: лимит исчерпан или идёт пауза после 429."""


class RateGate:
  def __init__(self, per_second: int = PER_SECOND, per_minute: int = PER_MINUTE):
    self.per_second, self.per_minute = per_second, per_minute
    self.hits: list[float] = []
    self.blocked_until = 0.0

  def block_for(self, seconds: float):
    self.blocked_until = now() + seconds

  def try_acquire(self) -> bool:
    t = now()
    if t < self.blocked_until:
      return False
    self.hits = [h for h in self.hits if t - h < 60]
    if len(self.hits) >= self.per_minute:
      return False
    if sum(1 for h in self.hits if t - h < 1) >= self.per_second:
      return False
    self.hits.append(t)
    return True


gate = RateGate()
_cache: dict[str, tuple[float, dict]] = {}      # ключ -> (до какого момента верим, ответ)
_inflight: dict[str, asyncio.Future] = {}


def _key(q: str) -> str:
  return " ".join(q.lower().split())


def _cache_put(key: str, data: dict, ttl: float):
  if len(_cache) >= MAX_CACHE:
    t = now()
    for k in [k for k, (until, _) in _cache.items() if until <= t]:
      del _cache[k]
    while len(_cache) >= MAX_CACHE:             # всё ещё полно: выкидываем самые старые
      del _cache[next(iter(_cache))]
  _cache[key] = (now() + ttl, data)


async def search_shikimori(q: str) -> dict:
  """Как fetch_anime_from_shikimori, но с кэшем и лимитом. Бросает ShikimoriBusy, если нельзя ходить наружу."""
  key = _key(q)

  hit = _cache.get(key)
  if hit and hit[0] > now():
    REQUESTS.labels("cache_hit").inc()
    return hit[1]

  if key in _inflight:                          # такой же запрос уже летит: ждём его результат
    REQUESTS.labels("coalesced").inc()
    return await asyncio.shield(_inflight[key])

  if not gate.try_acquire():
    REQUESTS.labels("busy").inc()
    raise ShikimoriBusy()

  fut = asyncio.get_running_loop().create_future()
  _inflight[key] = fut
  try:
    data = await fetch_anime_from_shikimori(q)
    animes = ((data.get("data") or {}).get("animes")) or []
    _cache_put(key, data, CACHE_TTL if animes else EMPTY_TTL)
    REQUESTS.labels("upstream_ok").inc()
    fut.set_result(data)
    return data
  except Exception as e:
    if isinstance(e, ShikimoriError) and e.status == 429:
      gate.block_for(PAUSE_AFTER_429)
      log.warning("Shikimori вернул 429, пауза %s с", PAUSE_AFTER_429)
      REQUESTS.labels("upstream_429").inc()
    else:
      REQUESTS.labels("upstream_error").inc()   # ошибки в кэш не кладём
    fut.set_exception(e)
    fut.exception()                             # пометить как прочитанное, если ждунов не было
    raise
  finally:
    _inflight.pop(key, None)
