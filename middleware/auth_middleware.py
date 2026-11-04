from fastapi import Request, HTTPException, Depends

from utils.enum import userType
from services.session_service import (
    SessionTokenService,

)



# =========================
# USER AUTH
# =========================
async def jwt_auth(
    request: Request,
 
):
    token = request.headers.get("Authorization")

    if not token:
        raise HTTPException(status_code=401, detail="Authorization header missing")

    if not token.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Bearer token format")

    exact_token = token.split(" ")[1]

    #  Check session in DB (ASYNC)


    #  Decode token (STATIC)
    try:
        user_id = SessionTokenService.decode_session(exact_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    return True

