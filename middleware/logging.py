from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import time
import logging

# Configure logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("api_logger")


class LoggingMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        method = request.method
        path = request.url.path
        client_ip = request.client.host

        # Process request
        response = await call_next(request)

        process_time = round((time.time() - start_time) * 1000, 2)

        logger.info(
            f"{method} {path} | Status: {response.status_code} | "
            f"IP: {client_ip} | Time: {process_time}ms"
        )

        return response