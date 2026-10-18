"""Install versioned author content without overwriting saves or credentials."""
import copy
import hashlib
import json
import re
import story_engine as engine

MAX_RELEASE = 8 * 1024 * 1024


def validate(content, character_ids):
    if (not isinstance(content, dict) or content.get('schema_version') != '1.0.0'
            or content.get('world_id') != 'world_magic_isekai'
            or not isinstance(content.get('content_version'), str)
            or not re.fullmatch(r'\d+\.\d+\.\d+(?:-[a-z0-9.]+)?', content['content_version'])):
        raise engine.StoryError('新版設定的世界或版本格式不符。')
    rules = content.get('runtime_rules', {})
    if (not isinstance(rules, dict) or rules.get('party_limit') != 4
            or rules.get('memory_interval') != 8 or rules.get('memory_min') != 5
            or rules.get('memory_max') != 10 or rules.get('large_active_portrait') is not True):
        raise engine.StoryError('新版設定必須保留四位同行、大型立繪與 5～10 次記憶規則。')
    directions = content.get('character_directions')
    if not isinstance(directions, dict) or set(directions) != set(character_ids):
        raise engine.StoryError('新版能力方向必須與全部重要角色 ID 一致。')
    for value in directions.values():
        if not isinstance(value, dict) or set(value) - {'role', 'skills', 'limits', 'status'}:
            raise engine.StoryError('人物能力欄位格式錯誤。')
        if (not isinstance(value.get('role'), str) or len(value['role']) > 120
                or not isinstance(value.get('skills'), list) or len(value['skills']) > 6
                or any(not isinstance(x, str) or len(x) > 500 for x in value['skills'])
                or not isinstance(value.get('limits'), str) or len(value['limits']) > 1000):
            raise engine.StoryError('人物能力內容過長或不完整。')
    for key in ('quests', 'enemies', 'items'):
        records = content.get(key)
        if not isinstance(records, list) or len(records) > 200:
            raise engine.StoryError('新版設定的目錄格式錯誤。')
        seen = set()
        for item in records:
            if not isinstance(item, dict):
                raise engine.StoryError('新版設定目錄條目不完整。')
            ident = engine._id(item.get('id'))
            if ident in seen or not isinstance(item.get('text'), str) or len(item['text']) > 18000:
                raise engine.StoryError('新版設定目錄 ID 重複或內容過長。')
            seen.add(ident)
    if len(json.dumps(content, ensure_ascii=False).encode()) > 1024 * 1024:
        raise engine.StoryError('新版設定索引超過 1 MiB。')
    return copy.deepcopy(content)


def from_package(package, character_ids, required=True):
    matches = [p for p in package.files if p.endswith('release/content.json')]
    if not matches and not required:
        return None
    if len(matches) != 1:
        raise engine.StoryError('請使用完整測試資料 ZIP，其中需要唯一的 release/content.json。')
    return validate(package.document('release/content.json'), character_ids)


def install(user_dir, story_id, stream, expected_version):
    from world_import import Package
    pack = Package(stream)
    try:
        with engine._LOCK:
            story = engine.get_story(user_dir, story_id)
            if not story.get('world'):
                raise engine.StoryError('請先匯入魔法異世界。')
            ids = [c['id'] for c in story['characters'] if c['kind'] == 'important_character']
            content = from_package(pack, ids)
            current = story['world'].get('content_release', {})
            digest = lambda value:hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if digest(content) == digest(current):
                return {'story':story, 'already_installed':True}
            if expected_version != current.get('content_version', ''):
                raise engine.StoryError('設定已更新，請重新載入後再安裝；本次未覆蓋設定。')
            backup = engine._root(user_dir) / 'backups' / (engine._id(story_id) + '-content-' + digest(story)[:16] + '.json')
            backup.parent.mkdir(exist_ok=True)
            engine._write(backup, story)
            story['world']['content_release'] = content
            result = engine.validate_story(story, story_id)
            engine._write(engine._story_path(user_dir, story_id), result)
            return {'story':result, 'already_installed':False}
    finally:
        pack.close()
