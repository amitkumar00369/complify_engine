
from datetime import datetime, timedelta
from fastapi.encoders import jsonable_encoder
from fastapi import Depends
import jwt
from dotenv import load_dotenv
load_dotenv()
import os







# =========================
#  TOKEN SERVICE (STATIC)
# =========================
class SessionTokenService:

    @staticmethod
    def decode_session(token: str):
        payload = jwt.decode(token, os.getenv("SECRET_KEY"), algorithms=["HS256"])
        return payload.get("user_id")




    


