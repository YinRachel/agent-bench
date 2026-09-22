import unittest
import httpx
from skilltrainbench.gateway import BudgetMeter, build_app


class TokenLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_token_limit_parameter(self):
        for parameter in ('max_tokens', 'max_completion_tokens'):
            with self.subTest(parameter=parameter):
                received = []
                def upstream_response(request):
                    import json
                    received.append(json.loads(request.content))
                    return httpx.Response(200, json={
                        'id': 'test', 'object': 'chat.completion', 'model': 'test',
                        'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'OK'}, 'finish_reason': 'stop'}],
                        'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
                    })
                async with httpx.AsyncClient(base_url='https://upstream.test', transport=httpx.MockTransport(upstream_response)) as upstream:
                    app = build_app(BudgetMeter(10000), client=upstream)
                    async with httpx.AsyncClient(base_url='http://gateway', transport=httpx.ASGITransport(app=app)) as client:
                        response = await client.post('/v1/chat/completions', json={'model': 'test', 'messages': [{'role': 'user', 'content': 'Hi'}], parameter: 256})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(received[0][parameter], 256)
                other = 'max_tokens' if parameter == 'max_completion_tokens' else 'max_completion_tokens'
                self.assertNotIn(other, received[0])
