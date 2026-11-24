import httpx


class ShikimoriError(Exception):
  """Shikimori ответил не 200. status нужен, чтобы отличить 429 (лимит) от остальных ошибок."""

  def __init__(self, status: int, body: str = ""):
    super().__init__(f"Ошибка API Шикимори: статус {status}, ответ: {body[:200]}")
    self.status = status


async def fetch_anime_from_shikimori(search_title: str):
  # 1. Куда отправляем запрос (официальный адрес GraphQL от Shikimori)
  url = "https://shikimori.io/api/graphql"

  # 2. Обязательный заголовок по правилам Shikimori (иначе заблокируют IP)
  headers = {
      "User-Agent": "Yume-anime"  # Пишем как представляется наш сервис
  }

  shikimori_query = """
    query ($search: String!) {
      animes(search: $search, limit: 3, kind: "!special") {
        id
        name
        russian
        japanese
        airedOn { date }
        poster { originalUrl mainUrl }
        description
      }
  }
  """

  variables = {"search": search_title}

  # Явный таймаут: зависший Shikimori не должен держать запросы посетителей
  async with httpx.AsyncClient(timeout=httpx.Timeout(8.0)) as client:
    response = await client.post(
        url,
        json={
            "query": shikimori_query,
            "variables": variables,
        },
        headers=headers,
    )

  if response.status_code != 200:
    raise ShikimoriError(response.status_code, response.text)

  return response.json()
