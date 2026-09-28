"""Probe the configured learner's native tool API without executing tools."""
import argparse
import json
import os

import httpx
from skilltrainbench.config import load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='local-vllm.toml')
    args = parser.parse_args()
    cfg = load_config(args.config)
    base = cfg.learner_upstream_base_url or cfg.upstream_base_url
    key_env = cfg.learner_upstream_key_env if cfg.learner_upstream_base_url else cfg.upstream_key_env
    key = os.environ.get(key_env) if key_env else None
    payload = {
        'model': cfg.learner_model.removeprefix('openai/'),
        'messages': [{'role': 'user', 'content': 'Call report_value with value 7. Do not answer in prose.'}],
        'tools': [{'type': 'function', 'function': {
            'name': 'report_value', 'description': 'Report the requested integer.',
            'parameters': {'type': 'object', 'properties': {'value': {'type': 'integer'}},
                           'required': ['value']}}}],
        'tool_choice': 'auto', 'max_tokens': 4096, 'temperature': 0,
    }
    try:
        response = httpx.post(base.rstrip('/').removesuffix('/v1') + '/v1/chat/completions',
                              json=payload, headers={'Authorization': f'Bearer {key}'} if key else {},
                              timeout=600)
        if response.is_error:
            print(f'FAIL HTTP {response.status_code}: {response.text[:2000]}')
            return 1
        data = response.json()
        calls = data['choices'][0]['message'].get('tool_calls') or []
        if len(calls) != 1 or calls[0]['function']['name'] != 'report_value':
            print('FAIL: expected a structured report_value tool call; received:',
                  json.dumps(data['choices'][0])[:2000])
            return 1
        if json.loads(calls[0]['function']['arguments']) != {'value': 7}:
            print('FAIL: incorrect tool arguments')
            return 1
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
        print(f'FAIL: {error}')
        return 1
    print('PASS: native auto tool call parsed correctly. No tool was executed.')
    print('Next validate a one-task OpenHands run; this probe does not establish agent reliability.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
