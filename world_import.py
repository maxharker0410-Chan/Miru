"""Import a world ZIP and its WebP ZIP without executing archive contents.

All checks happen in staging. The story file is the commit point; existing
stories, sessions, login and model credentials are never overwritten.
"""
from collections import Counter
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import zipfile

from PIL import Image
import story_engine as engine

MAX_UPLOAD = 512 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
MAX_ENTRY = 20 * 1024 * 1024
WORLD_ID = 'world_magic_isekai'
COUNTS = {'important_character': 54, 'npc': 99, 'background': 42}
# Background coverage of authored sublocations, based on the supplied area
# descriptions. This maps pictures only; location identities remain distinct.
AREA_BACKGROUNDS = {
    'loc_02_dorm':'loc_02_zone_c', 'loc_02_academy':'loc_02_teaching',
    'loc_03_guild':'loc_03_zone_b', 'loc_03_warehouse':'loc_03_zone_a',
    'loc_03_council':'loc_03_zone_c', 'loc_03_auction':'loc_03_zone_d',
    'loc_03_tavern':'loc_03_zone_e', 'loc_03_blackmarket':'loc_03_zone_f',
    'loc_06_hall':'loc_06_zone_b', 'loc_06_council':'loc_06_zone_a',
    'loc_06_market':'loc_06_zone_c', 'loc_06_dorm':'loc_06_zone_c',
    'loc_06_gate':'loc_06_zone_e', 'loc_07_fort':'loc_07_zone_c', 'loc_07_seal':'loc_07_zone_e'}


def fail(message):
    raise engine.StoryError(message)


class Package:
    def __init__(self, stream):
        try:
            self.archive = zipfile.ZipFile(stream)
        except (zipfile.BadZipFile, OSError):
            fail('不是有效的 ZIP 資料包。')
        self.files = {}
        entries = self.archive.infolist()
        if len(entries) > 2048 or sum(i.file_size for i in entries) > MAX_EXPANDED:
            fail('ZIP 展開容量或檔案數量超過限制。')
        for info in entries:
            path = PurePosixPath(info.filename)
            if (path.is_absolute() or '..' in path.parts or '\\' in info.filename
                    or ':' in info.filename or '\x00' in info.filename
                    or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1):
                fail('ZIP 含有不安全路徑、連結或加密檔案。')
            if info.is_dir():
                continue
            if info.filename in self.files or info.file_size > MAX_ENTRY:
                fail('ZIP 檔名重複或單一檔案過大。')
            self.files[info.filename] = info

    def read(self, name):
        if name not in self.files:
            fail('資料包缺少檔案：' + name)
        try:
            return self.archive.read(self.files[name])
        except (zipfile.BadZipFile, RuntimeError, OSError):
            fail('ZIP 檔案毀損：' + name)

    def document(self, suffix):
        matches = [name for name in self.files if name == suffix or name.endswith('/' + suffix)]
        if len(matches) != 1:
            fail('資料包需要唯一的 ' + suffix)
        if self.files[matches[0]].file_size > 4 * 1024 * 1024:
            fail('資料索引過大。')
        try:
            return json.loads(self.read(matches[0]).decode('utf-8-sig'))
        except (UnicodeError, ValueError):
            fail('JSON 資料無法讀取：' + suffix)

    def close(self):
        self.archive.close()


def indexed(items, label):
    if not isinstance(items, list) or len(items) > 1000:
        fail(label + '索引格式錯誤。')
    result = {}
    for item in items:
        if not isinstance(item, dict):
            fail(label + '資料格式錯誤。')
        identifier = engine._id(item.get('id'))
        if identifier in result:
            fail(label + ' ID 重複。')
        result[identifier] = item
    return result


def validate_world(world, knowledge):
    if not isinstance(world, dict) or not isinstance(knowledge, dict):
        fail('世界資料格式錯誤。')
    if (world.get('world_id') != WORLD_ID or world.get('world_version') != '1.0.0'
            or world.get('schema_version') != '1.0.0' or knowledge.get('schema_version') != '1.0.0'):
        fail('目前支援魔法異世界 V1.0 資料包。')
    regions = indexed(world.get('regions'), '地區')
    characters = indexed(world.get('characters'), '角色')
    locations = indexed(world.get('locations'), '地點')
    facts = indexed(world.get('facts'), '事實')
    if len(characters) != 54:
        fail('世界資料包需要 54 名重要角色。')
    for character in characters.values():
        if character.get('home_region_id') not in regions:
            fail('角色的地區 ID 不存在。')
    for location in locations.values():
        if location.get('region_id') is not None and location.get('region_id') not in regions:
            fail('地點的地區 ID 不存在。')
        parent = location.get('parent_location_id')
        seen = {location['id']}
        while parent:
            if parent not in locations or parent in seen:
                fail('地點父子關係含有缺漏或循環。')
            seen.add(parent)
            parent = locations[parent].get('parent_location_id')
    for grant in knowledge.get('grants', []):
        if not isinstance(grant, dict) or any(fid not in facts for fid in grant.get('fact_ids', [])):
            fail('知識授權含有未知事實。')
    for relation in knowledge.get('relationships', []):
        if not isinstance(relation, dict) or any(cid not in characters for cid in relation.get('holders', [])):
            fail('私人關係含有未知角色。')
    return regions, characters, locations


def convert(world, knowledge, manifest, bindings, images):
    regions, characters, locations = validate_world(world, knowledge)
    assets = manifest.get('assets')
    if (manifest.get('world_id') != world['world_id'] or manifest.get('world_version') != world['world_version']
            or manifest.get('schema_version') != '1.0.0' or bindings.get('schema_version') != '1.0.0'
            or not isinstance(assets, list) or len(assets) != 195):
        fail('圖片包版本不符或不是完整的 195 張素材。')
    if Counter(a.get('category') for a in assets if isinstance(a, dict)) != Counter(COUNTS):
        fail('素材數量應為 54 名重要角色、99 名 NPC、42 張背景。')
    if set(bindings.get('characters', {})) != set(characters):
        fail('重要角色 ID 無法與世界資料逐一對應。')
    if len(bindings.get('npcs', {})) != 99 or len(bindings.get('locations', {})) != 42:
        fail('NPC 或背景綁定表不完整。')
    if len(bindings.get('portrait_usage_overrides', {})) != 12:
        fail('圖片包需保留 12 張已確認直接使用的人物圖設定。')
    if any(cid not in (set(bindings['characters']) | set(bindings['npcs']))
           or value.get('cutout_required') is not False
           for cid, value in bindings['portrait_usage_overrides'].items()):
        fail('未去背人物的使用設定與角色 ID 不符。')
    portrait = {}
    backgrounds = {}
    keys, paths, ids = set(), set(), set()
    for asset in assets:
        cid = engine._id(asset.get('entity_id'))
        category = asset['category']
        key, path = asset.get('asset_key'), asset.get('path')
        if not isinstance(key, str) or key in keys or path in paths or cid in ids:
            fail('素材 ID、鍵或檔案路徑重複。')
        keys.add(key); paths.add(path); ids.add(cid)
        section = {'important_character':'characters', 'npc':'npcs', 'background':'locations'}[category]
        field = 'background_asset_key' if category == 'background' else 'portrait_asset_key'
        if bindings[section].get(cid, {}).get(field) != key or asset.get('region_id') not in regions:
            fail('素材綁定或地區對應錯誤。')
        if not isinstance(path, str) or not path.endswith('.webp') or path not in images:
            fail('素材 WebP 未通過驗證。')
        if category == 'background':
            backgrounds[cid] = asset
            if cid not in locations:
                locations[cid] = {'id':cid, 'name':asset['label'], 'region_id':asset['region_id'],
                                  'parent_location_id':None, 'record_status':'asset_location'}
        else:
            portrait[cid] = asset
    # Bound image-area IDs are distinct locations, never silent aliases for
    # authored location IDs. Parent/region backgrounds may serve as fallbacks.
    result_characters = []
    for cid in list(characters) + list(bindings['npcs']):
        art = portrait[cid]
        identity = characters.get(cid) or {'id':cid, 'display_label':art['label'], 'name':None,
            'home_region_id':art['region_id'], 'record_status':'npc_asset_index', 'follower_candidate':None}
        name = identity.get('name') or identity.get('display_label') or cid
        result_characters.append({'id':cid, 'name':name,
            'personality':'依作者設定扮演；未設定姓名或個性時不要自行定稿。',
            'backstory':identity.get('display_label', name), 'avatar':images[art['path']],
            'visual_states':[], 'default_visual_state':'', 'kind':'npc' if cid in bindings['npcs'] else 'important_character',
            'region_id':identity['home_region_id'], 'search_label':art['label'],
            'portrait_render_mode':'image_with_original_background' if cid in bindings.get('portrait_usage_overrides', {}) else 'portrait',
            'identity':identity})
    by_region = {rid:[lid for lid, loc in locations.items() if loc.get('region_id') == rid] for rid in [*regions, None]}
    by_region = {rid:nodes for rid,nodes in by_region.items() if nodes}
    primary = {rid:next((lid for lid in nodes if lid in backgrounds), nodes[0]) for rid, nodes in by_region.items()}
    def backdrop(lid):
        current, visited = lid, set()
        while current and current not in visited:
            visited.add(current)
            if current in backgrounds:
                return images[backgrounds[current]['path']]
            area = AREA_BACKGROUNDS.get(current)
            if area in backgrounds:
                return images[backgrounds[area]['path']]
            current = locations[current].get('parent_location_id')
        return ''
    scenes = []
    for lid, loc in locations.items():
        rid = loc['region_id']
        # No invented worldwide shortcuts. Same-region destinations are offered
        # locally; cross-region travel uses a separately accepted travel action.
        scenes.append({'id':lid, 'title':loc['name'], 'description':(regions[rid]['name'] if rid in regions else '大陸自然地點') + '・' + loc['name'],
            'background':backdrop(lid), 'cast':[], 'next':[n for n in by_region[rid] if n != lid], 'region_id':rid or ''})
    start = 'loc_03_guild' if 'loc_03_guild' in locations else scenes[0]['id']
    return {'id':world['world_id'], 'title':world['title'], 'premise':'以作者世界資料及本局狀態推進魔法異世界故事。',
        'opening':'你抵達了新的地點。可從角色名冊安排會面，或選擇下一個目的地。',
        'characters':result_characters, 'scenes':scenes, 'start_scene':start,
        'world':{'definition':world, 'knowledge':knowledge, 'locations':list(locations.values()),
                 'region_starts':{rid or 'unassigned':lid for rid,lid in primary.items()}}}


def import_packages(user_dir, world_stream, images_stream):
    world_pack, art_pack = Package(world_stream), None
    try:
        art_pack = Package(images_stream)
        world = world_pack.document('data/world.json')
        knowledge = world_pack.document('data/knowledge.json')
        manifest = art_pack.document('asset_manifest.json')
        bindings = art_pack.document('asset_bindings.json')
        if not isinstance(manifest, dict) or not isinstance(bindings, dict):
            fail('圖片索引格式錯誤。')
        fingerprint = hashlib.sha256(json.dumps([world, knowledge, manifest, bindings], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        root = engine._root(user_dir)
        path = engine._story_path(user_dir, WORLD_ID)
        with tempfile.TemporaryDirectory(prefix='.world-import-', dir=root) as temporary:
            staging = Path(temporary)
            images = {}
            assets = manifest.get('assets', [])
            if not isinstance(assets, list) or len(assets) != 195:
                fail('圖片索引需要 195 張素材。')
            listed = {a.get('path') for a in assets if isinstance(a, dict)}
            actual = {name for name in art_pack.files if name.lower().endswith('.webp')}
            if listed != actual:
                fail('圖片索引與 ZIP 中的 WebP 檔案不一致。')
            for asset in assets:
                raw = art_pack.read(asset['path'])
                digest = hashlib.sha256(raw).hexdigest()
                if len(raw) != asset.get('webp_bytes') or digest != asset.get('webp_sha256'):
                    fail('圖片大小或 SHA-256 不符：' + asset['path'])
                try:
                    with Image.open(BytesIO(raw)) as image:
                        if image.format != 'WEBP' or image.width > 6000 or image.height > 6000 or getattr(image, 'n_frames', 1) != 1:
                            fail('圖片不是支援的靜態 WebP。')
                        image.load()
                        if image.size != (asset.get('width'), asset.get('height')):
                            fail('圖片尺寸與索引不符。')
                except (OSError, ValueError, Image.DecompressionBombError):
                    fail('WebP 圖片無法解碼：' + asset['path'])
                name = digest[:32] + '.webp'
                (staging / name).write_bytes(raw)
                images[asset['path']] = name
            story = convert(world, knowledge, manifest, bindings, images)
            from world_release import from_package
            release = from_package(world_pack, [c['id'] for c in story['characters']
                if c['kind'] == 'important_character'], required=False)
            if release:
                story['world']['content_release'] = release
            story['import_info'] = {'fingerprint':fingerprint, 'important_characters':54, 'npcs':99,
                'backgrounds':42, 'images':195, 'opaque_portraits_used_directly':12, 'world_version':'1.0.0'}
            story = engine.validate_story(story, WORLD_ID)
            with engine._LOCK:
                if path.exists():
                    existing = engine._read(path)
                    if existing.get('import_info', {}).get('fingerprint') != fingerprint:
                        fail('此世界已匯入不同版本；請先提供 ID 遷移對照，既有紀錄未變更。')
                    return {'story':existing, 'already_imported':True, 'report':existing['import_info']}
                media = root / 'media'
                media.mkdir(exist_ok=True)
                created = []
                try:
                    for file in staging.iterdir():
                        target = media / file.name
                        if target.exists():
                            if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(file.read_bytes()).digest():
                                fail('既有素材名稱衝突，匯入取消。')
                        else:
                            os.replace(file, target)
                            created.append(target)
                    engine._write(path, story)
                except Exception:
                    for target in created:
                        target.unlink(missing_ok=True)
                    raise
            return {'story':story, 'already_imported':False, 'report':story['import_info']}
    finally:
        world_pack.close()
        if art_pack:
            art_pack.close()
