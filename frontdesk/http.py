"""Bound request memory and log only server-generated, non-sensitive metadata."""
import json
import logging
from time import monotonic
from uuid import uuid4

from starlette.responses import JSONResponse


class RequestSafety:
    def __init__(self, app, max_bytes=65536):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request_id = uuid4().hex
        scope.setdefault('state', {})['request_id'] = request_id
        started = monotonic()
        status = 500

        async def traced_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                message.setdefault('headers', []).append((b'x-request-id', request_id.encode()))
            await send(message)

        try:
            # Count actual streamed bytes: Content-Length can be absent or false.
            chunks = []
            size = 0
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                chunk = message.get('body', b'')
                size += len(chunk)
                if size > self.max_bytes:
                    response = JSONResponse({'detail': 'Request body too large'}, status_code=413)
                    return await response(scope, receive, traced_send)
                chunks.append(chunk)
                if not message.get('more_body', False):
                    break
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
                return await receive()

            await self.app(scope, replay, traced_send)
        finally:
            route = scope.get('route')
            logging.getLogger('frontdesk.requests').info(json.dumps({
                'event': 'request', 'request_id': request_id, 'method': scope['method'],
                'route': getattr(route, 'path', 'unmatched'), 'status': status,
                'duration_ms': round((monotonic() - started) * 1000, 2),
            }))
