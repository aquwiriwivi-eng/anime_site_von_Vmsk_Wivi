import httpx

async def fetch_anime_from_shikimori(search_title: str):
  # 1. Куда отправляем запрос (официальный адрес GraphQL от Shikimori)
  url = "https://shikimori.io/api/graphql"

# 2. Обязательный заголовок по правилам Shikimori (иначе заблокируют IP)
  headers = {
      "User-Agent": "Yume-anime"  # Можешь написать имя своего сайта
  }

  shikimori_query = """
    query ($search: String!) {
      animes(search: $search, limit: 3, kind: "!special") {
        id
        name
        russian
        japanese
        date
        airedOn { date }
        poster { originalUrl mainUrl }
      }
  }
  """

  variables = {"search": search_title}

  async with httpx.AsyncClient() as client:
    response = await client.post(
        url,
        json={
            "query": shikimori_query,
            "variables": variables,
        },
        headers=headers,
    )

  if response.status_code != 200:
    raise Exception(f"Ошибка API Шикимори:       ")

  return response.json()
