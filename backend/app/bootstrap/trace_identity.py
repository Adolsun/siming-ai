"""Keep the authenticated request identity available to detached task context."""

from ..modules.operations.application.trace_capture import request_identity


class TraceIdentityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        state = scope.setdefault("state", {})
        token = request_identity.set(state)
        try:
            await self.app(scope, receive, send)
        finally:
            request_identity.reset(token)
