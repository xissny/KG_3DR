"""DeepSeek HTTP 客户端：缓存属于可复现记录，不把 API 密钥写入日志。"""
from __future__ import annotations
import json
import os
import time
import httpx
from src.common.storage import DATA, digest, now, read_json, write_json


def chat_json(messages: list[dict], purpose: str, force: bool = False) -> dict:
    """调用 JSON 模式；网络/限流错误最多重试 3 次，4xx 配置错误立即停止。"""
    model = os.getenv('DEEPSEEK_MODEL', 'deepseek-flash')
    base = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/')
    payload = {'model': model, 'messages': messages, 'temperature': 0,
               'max_tokens': 6000, 'response_format': {'type': 'json_object'},
               # 当前模型默认开启思考；结构化抽取显式关闭，避免思考占满输出预算。
               'thinking': {'type': 'disabled'}}
    key = digest({'base': base, 'payload': payload, 'purpose': purpose})
    cache = DATA / 'cache' / f'{key}.json'
    cached = read_json(cache)
    if cached and not force:
        return cached
    secret = os.getenv('DEEPSEEK_API_KEY', '')
    if not secret:
        raise ValueError('未配置 DEEPSEEK_API_KEY，请在服务器项目 .env 中填写；教学样例无需密钥')
    last_error = ''
    for attempt in range(3):
        try:
            with httpx.Client(timeout=httpx.Timeout(180, connect=20)) as client:
                response = client.post(base + '/chat/completions', json=payload,
                                       headers={'Authorization': f'Bearer {secret}'})
            if response.status_code in (401, 403):
                raise ValueError('DeepSeek 认证失败，请检查服务地址与密钥')
            if response.status_code >= 400 and response.status_code not in (408, 429) and response.status_code < 500:
                raise ValueError(f'DeepSeek 请求配置错误，HTTP {response.status_code}')
            response.raise_for_status()
            raw = response.json()
            choice = raw['choices'][0]
            if choice.get('finish_reason') != 'stop':
                raise ValueError('DeepSeek 输出未完整结束，请缩小文本块或调整输出预算')
            content = json.loads(choice['message']['content'])
            result = {'data': content, 'raw': raw, 'request': payload,
                      'time': now(), 'model': model, 'base_url': base, 'cache_key': key, 'purpose': purpose}
            write_json(cache, result)
            return result
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
            last_error = type(exc).__name__
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise ValueError(f'DeepSeek 调用失败（{last_error}），已保留此前完成的块，可重跑恢复')
