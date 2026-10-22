"""Data-only story, artwork and DLC ZIPs. No package scripts are executed."""
from __future__ import annotations
from io import BytesIO
import copy
import hashlib
import json
from pathlib import PurePosixPath
import re
import stat
import uuid
import zipfile

import story_engine as engine

MAX_UPLOAD = 512 * 1024 * 1024


def _archive(stream):
    try:
        archive = zipfile.ZipFile(stream)
        infos = archive.infolist()
        if len(infos) > 2000 or sum(i.file_size for i in infos) > MAX_UPLOAD:
            raise engine.StoryError('資料包過大。')
        seen = set()
        for info in infos:
            original = info.orig_filename
            path = PurePosixPath(original)
            if (original in seen or path.is_absolute() or '..' in path.parts or '\\' in original or '\x00' in original
                    or ':' in original or info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16)
                    or info.file_size > 16 * 1024 * 1024):
                raise engine.StoryError('ZIP 路徑、容量或格式不安全。')
            seen.add(original)
        raw = archive.read('schat-package.json')
        if len(raw) > 2 * 1024 * 1024:
            raise engine.StoryError('故事索引過大。')
        manifest = json.loads(raw)
        if (not isinstance(manifest, dict) or manifest.get('schema_version') != 1
                or manifest.get('type') not in ('story', 'assets', 'dlc')):
            raise engine.StoryError('不支援的故事包版本或類型。')
        engine._id(manifest.get('package_id'))
        if not isinstance(manifest.get('version'), str) or not manifest['version']:
            raise engine.StoryError('資料包缺少版本。')
        return archive, manifest, hashlib.sha256(raw).hexdigest()
    except (zipfile.BadZipFile, KeyError, ValueError, TypeError, OSError):
        raise engine.StoryError('ZIP 或故事索引不完整。') from None


def _images(archive, bindings, story):
    from PIL import Image
    if not isinstance(bindings, list) or len(bindings) > 1000:
        raise engine.StoryError('圖片綁定格式錯誤。')
    prepared = []
    characters = {c['id']:c for c in story['characters']}
    scenes = {s['id']:s for s in story['scenes']}
    for binding in bindings:
        if not isinstance(binding, dict):
            raise engine.StoryError('圖片綁定格式錯誤。')
        kind, target = binding.get('kind'), binding.get('id')
        node = characters.get(target) if kind == 'character' else scenes.get(target) if kind == 'scene' else None
        if node is None:
            raise engine.StoryError('圖片只能綁定此故事中存在的角色或場景。')
        try:
            raw = archive.read(binding['path'])
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError()
            if hashlib.sha256(raw).hexdigest() != binding.get('sha256'):
                raise ValueError()
            with Image.open(BytesIO(raw)) as image:
                ext = {'WEBP':'webp', 'PNG':'png', 'JPEG':'jpg'}.get(image.format)
                if not ext or max(image.size) > 6000:
                    raise ValueError()
                image.verify()
        except (KeyError, ValueError, OSError, zipfile.BadZipFile):
            raise engine.StoryError('圖片缺少、雜湊不符或無法讀取。') from None
        name = uuid.uuid4().hex + '.' + ext
        node['avatar' if kind == 'character' else 'background'] = name
        prepared.append((name, raw))
    return prepared


def install(user_dir, stream, story_id=None):
    archive, manifest, digest = _archive(stream)
    try:
        with engine._LOCK:
            root = engine._root(user_dir)
            if manifest['type'] == 'story':
                # Full stories always get their own namespace, even if the
                # author used the same character/scene IDs in another world.
                prior = [s for s in engine.list_stories(user_dir)
                         if engine.get_story(user_dir, s['id']).get('packages', {}).get(manifest['package_id'], {}).get('digest') == digest]
                if prior:
                    return {'story':engine.get_story(user_dir,prior[0]['id']), 'already_installed':True}
                story = engine.validate_story(manifest.get('story'))
            else:
                story = copy.deepcopy(engine.get_story(user_dir, story_id))
                target = manifest.get('target_story_id')
                valid_targets = {story['id'], story.get('world', {}).get('definition', {}).get('world_id')}
                if not isinstance(target, str) or target not in valid_targets:
                    raise engine.StoryError('資料包不屬於目前故事。')
                installed = story.get('packages', {}).get(manifest['package_id'])
                if installed:
                    if installed['digest'] == digest:
                        return {'story':story, 'already_installed':True}
                    raise engine.StoryError('這個 DLC ID 已安裝其他內容；請提供新的版本遷移包。')
                if manifest['type'] == 'dlc':
                    old_chars = {c['id'] for c in story['characters']}
                    old_scenes = {s['id'] for s in story['scenes']}
                    additions = manifest.get('characters', [])
                    places = manifest.get('scenes', [])
                    if not isinstance(additions, list) or not isinstance(places, list):
                        raise engine.StoryError('DLC 新增內容格式錯誤。')
                    if any(not isinstance(c,dict) or c.get('id') in old_chars for c in additions) or any(not isinstance(s,dict) or s.get('id') in old_scenes for s in places):
                        raise engine.StoryError('DLC 不能覆寫既有人物或地點。')
                    trial = {**copy.deepcopy(story), 'world':None,
                             'characters':story['characters'] + additions, 'scenes':story['scenes'] + places}
                    checked = engine.validate_story(trial, story['id'])
                    # Preserve imported author cards and identity fields.
                    story['characters'].extend(c for c in checked['characters'] if c['id'] not in old_chars)
                    if story.get('world'):
                        region = engine._scene(story, story['start_scene']).get('region_id')
                        source_chars = {c['id']:c for c in additions}
                        for c in story['characters']:
                            if c['id'] not in old_chars:
                                source = source_chars[c['id']]
                                c.update(kind='npc', region_id=source.get('region_id', region),
                                    identity={'display_label':source.get('role',c['name']), 'follower_candidate':True, 'fixed_identity':False})
                    story['scenes'].extend(s for s in checked['scenes'] if s['id'] not in old_scenes)
                    extension = story.setdefault('content_extensions', {'character_ids':[], 'scene_ids':[], 'events':[]})
                    extension['character_ids'].extend(c['id'] for c in story['characters'] if c['id'] not in old_chars)
                    extension['scene_ids'].extend(s['id'] for s in story['scenes'] if s['id'] not in old_scenes)
                    for item in manifest.get('events', [])[:100]:
                        if (not isinstance(item, dict) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', str(item.get('id','')))
                                or item.get('trigger') not in ('enter_scene', 'after_seconds')
                                or not isinstance(item.get('text'), str)):
                            raise engine.StoryError('DLC 事件格式錯誤。')
                        event = copy.deepcopy(item)
                        event['id'] = manifest['package_id'] + ':' + event['id']
                        event['retroactive'] = item.get('retroactive') is True
                        event['text'] = event['text'][:1800]
                        if item['trigger'] == 'enter_scene' and item.get('scene_id') not in {s['id'] for s in story['scenes']}:
                            raise engine.StoryError('DLC 事件地點不存在。')
                        if item['trigger'] == 'after_seconds' and (type(item.get('seconds')) is not int or not 0 <= item['seconds'] <= 30 * 86400):
                            raise engine.StoryError('DLC 事件時間格式錯誤。')
                        extension['events'].append(event)
            images = _images(archive, manifest.get('bindings', []), story)
            story.setdefault('packages', {})[manifest['package_id']] = {
                'version':manifest['version'], 'digest':digest, 'type':manifest['type']}
            # Validate everything before writing anything. Roll back newly
            # written artwork if the one atomic story commit fails.
            written = []
            try:
                for name, raw in images:
                    path = root / 'media' / name
                    path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes(raw); written.append(path)
                engine._write(engine._story_path(user_dir, story['id']), story)
            except Exception:
                for path in written:
                    path.unlink(missing_ok=True)
                raise
            return {'story':story, 'already_installed':False,
                    'report':{'type':manifest['type'], 'images':len(images), 'characters':len(story['characters']), 'scenes':len(story['scenes'])}}
    finally:
        archive.close()
