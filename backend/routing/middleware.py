"""One structured log line per request, with a request id that is echoed back to the client."""

from __future__ import annotations

import logging
import time
import uuid

logger = logging.getLogger("routing.requests")


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        started = time.perf_counter()
        response = self.get_response(request)
        duration_ms = (time.perf_counter() - started) * 1000
        response["X-Request-ID"] = request_id
        if request.path != "/api/health":
            logger.info(
                "request_id=%s method=%s path=%s status=%s duration_ms=%.0f",
                request_id,
                request.method,
                request.path,
                response.status_code,
                duration_ms,
            )
        return response
