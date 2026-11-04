from fastapi.responses import JSONResponse
from fastapi import Request
import traceback
import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)


async def global_exception_handler(
    request: Request,
    exc: Exception
):

    error_id = str(uuid.uuid4())[:8]

    error_trace = traceback.format_exc()

    logger.error(
        f"""
        ERROR_ID: {error_id}

        PATH: {request.url.path}

        METHOD: {request.method}

        ERROR: {str(exc)}

        TRACEBACK:
        {error_trace}
        """
    )

    return JSONResponse(
        status_code=500,
        content={
            "success": False,

            "message": "Internal Server Error",

            "error_id": error_id,

            "path": request.url.path,

            "method": request.method,

            "timestamp": datetime.utcnow().isoformat(),

            "detail": str(exc)
        }
    )