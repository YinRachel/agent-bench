"""Provider compatibility at the real learner/auxiliary gateway boundary."""
import json
import unittest

import httpx

from skilltrainbench.gateway import BudgetMeter, Ledger, build_app, learner_request_options

LUNA = 'openai-gpt-5-6-luna'


class LunaGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, *, learner_model=None, model=LUNA, stream=False, budget=2000):
        received = []
        def respond(request):
            payload = json.loads(request.content)
            received.append(payload)
            usage = {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}
            if stream:
                event = {'id': 'test', 'model': model, 'choices': [], 'usage': usage}
                return httpx.Response(200, text='data: ' + json.dumps(event) + '\n\ndata: [DONE]\n\n', headers={'content-type': 'text/event-stream'})
            return httpx.Response(200, json={'id': 'test', 'model': model, 'choices': [{'message': {'role': 'assistant', 'content': 'OK'}, 'finish_reason': 'stop'}], 'usage': usage})
        meter, ledger = BudgetMeter(budget), Ledger()
        async with httpx.AsyncClient(base_url='https://upstream.test', transport=httpx.MockTransport(respond)) as upstream:
            app = build_app(meter, client=upstream, ledger=ledger, learner_model=learner_model)
            async with httpx.AsyncClient(base_url='http://gateway', transport=httpx.ASGITransport(app=app)) as client:
                response = await client.post('/v1/chat/completions', json={
                    'model': model, 'messages': [{'role': 'user', 'content': 'Hi'}],
                    'max_tokens': 4096, 'reasoning_effort': 'high', 'stream': stream,
                    'tools': [{'type': 'function', 'function': {'name': 'test', 'parameters': {'type': 'object', 'properties': {}}}}],
                })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(meter.usage()['total_tokens'], 15)
        return received[0]

    async def test_luna_settings_and_budget_clamping(self):
        for model in (LUNA, 'openai/' + LUNA):
            for stream in (False, True):
                with self.subTest(model=model, stream=stream):
                    payload = await self.request(learner_model=model, stream=stream)
                    self.assertEqual(payload['reasoning_effort'], 'none')
                    self.assertNotIn('max_tokens', payload)
                    self.assertGreater(payload['max_completion_tokens'], 0)
                    self.assertLess(payload['max_completion_tokens'], 2000)
                    self.assertEqual(payload['tools'][0]['function']['name'], 'test')

    async def test_auxiliary_gateway_unchanged_even_for_luna(self):
        payload = await self.request()
        self.assertEqual(payload['reasoning_effort'], 'high')
        self.assertIn('max_tokens', payload)
        self.assertNotIn('max_completion_tokens', payload)

    async def test_glm_and_grader_requests_unchanged(self):
        for model in ('zai-glm-5-3-flash', 'anthropic-claude-haiku-4-5'):
            with self.subTest(model=model):
                payload = await self.request(learner_model=LUNA, model=model)
                self.assertEqual(payload['reasoning_effort'], 'high')
                self.assertIn('max_tokens', payload)
                self.assertNotIn('max_completion_tokens', payload)

    def test_unknown_models_have_no_overrides(self):
        for model in (None, 'zai-glm-5-3-flash', 'other/openai-gpt-5-6-luna'):
            self.assertEqual(learner_request_options(model), {})
