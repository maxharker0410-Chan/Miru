"""S.Chat JSON calls, using the existing chat tier or saved story override."""
import json
import re


def vendor_extra_body(model, host='', reasoning=False, reasoning_budget=16000):
    hostname = (host or '').lower().split('/', 1)[0]
    if hostname == 'openrouter.ai':
        return {'reasoning':{'enabled':True,'max_tokens':reasoning_budget}} if reasoning else {'reasoning':{'enabled':False}}
    if hostname == 'api.deepseek.com' or hostname.endswith('.deepseek.com'):
        return {'thinking':{'type':'enabled' if reasoning else 'disabled'}}
    return {}


def parse_json(text):
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', str(text).strip())
    start = text.find('{')
    if start < 0:
        raise ValueError('模型未回傳 JSON。')
    value, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(value, dict):
        raise ValueError('模型回覆格式錯誤。')
    return value


def generate(config, system, user, label):
    import ai_config
    import openai
    if not all(config.get(key) for key in ('host', 'model', 'api_key')):
        raise ValueError('尚未設定原有聊天模型。')
    client = openai.OpenAI(api_key=config['api_key'],
        base_url=ai_config._openai_base_url_from_host(config['host']), timeout=60)
    response = client.chat.completions.create(model=config['model'], max_tokens=12000 if label == 'schat_author' else 2400,
        extra_body=vendor_extra_body(config['model'], ai_config._normalize_host(config['host'])),
        messages=[{'role':'system','content':system + '\n只輸出合法 JSON。'}, {'role':'user','content':user}])
    return parse_json(response.choices[0].message.content or '')
