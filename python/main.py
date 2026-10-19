import os #БЕРЕМ ПАРОЛИ ИЗ ОКРУЖЕНИЯ BASH
import psycopg #ЧТОБЫ ОБЩАТЬСЯ С POSTGRESS
import httpx #Чтобы общаться с Shikimori_api и использовать http-протокол

from fastapi import FastAPI, HTTPException #Чтобы писать api
from pydantic import BaseModel #чтобы писать api и задавать классы - хз что значит

app = FastAPI()



