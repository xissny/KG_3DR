"""网络边界用模拟HTTP验证，不消耗DeepSeek额度，也不伪称调用过真实API。"""
import httpx
import pytest
from src.extraction import client as deepseek


def test_deepseek_json_request_and_cache(workspace,monkeypatch):
    calls=[]
    monkeypatch.setenv('DEEPSEEK_API_KEY','test-only')
    class FakeClient:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            calls.append(kwargs['json'])
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"facts":[]}'}}],
                                            'usage':{'total_tokens':1}},request=httpx.Request('POST',url))
    monkeypatch.setattr(deepseek.httpx,'Client',FakeClient)
    messages=[{'role':'system','content':'Return JSON'},{'role':'user','content':'Synthetic'}]
    first=deepseek.chat_json(messages,'test')
    second=deepseek.chat_json(messages,'test')
    assert first==second and len(calls)==1
    assert calls[0]['response_format']=={'type':'json_object'}
    assert calls[0]['thinking']=={'type':'disabled'}
    monkeypatch.setenv('DEEPSEEK_MODEL','another-model')
    deepseek.chat_json(messages,'test')
    assert len(calls)==2


def test_deepseek_no_key_fails_before_network(workspace,monkeypatch):
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    with pytest.raises(ValueError,match='DEEPSEEK_API_KEY'):
        deepseek.chat_json([{'role':'user','content':'Unique uncached request'}],'no-key')
