import httpx

async def fetch_anime_from_shikimori(search_title: str):
  # 1. Куда отправляем запрос (официальный адрес GraphQL от Shikimori)
  url = "https://shikimori.io/api/graphql"

# 2. Обязательный заголовок по правилам Shikimori (иначе заблокируют IP)
  headers = {
      "User-Agent": "MyAnimeSiteProject"  # Можешь написать имя своего сайта
  }
