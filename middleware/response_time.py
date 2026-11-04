from starlette.middleware.base import BaseHTTPMiddleware
class ResponseTimeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        import time
        start = time.time()

        response = await call_next(request)

        process_time = time.time() - start
        response.headers["X-Process-Time"] = str(process_time)

        return response