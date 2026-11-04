from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import time

class RateLimitMiddleware(BaseHTTPMiddleware):

    def __init__(self, app, max_requests: int = 5, window: int = 10):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window
        self.clients = {}  # {ip: [timestamps]}

    async def dispatch(self, request: Request, call_next):
        ip = request.client.host
        current_time = time.time()

        # Initialize if new IP
        if ip not in self.clients:
            self.clients[ip] = []

        # Remove expired timestamps
        self.clients[ip] = [
            ts for ts in self.clients[ip]
            if ts > current_time - self.window
        ]

        # Check limit
        if len(self.clients[ip]) >= self.max_requests:
            return JSONResponse(
                status_code=429,
                content={"message": "Too many requests. Try again later."}
            )

        # Add current request
        self.clients[ip].append(current_time)

        response = await call_next(request)
        return response