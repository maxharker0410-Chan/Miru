"""Apply an author's consolidated DOCX without replacing stable IDs or saves."""
import copy
import hashlib
import re
import uuid
import xml.etree.ElementTree as ET

import story_engine as engine
from world_import import Package
from world_runtime import ConflictError

MAX_DOCUMENT = 16 * 1024 * 1024
NS = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
# Document-local codes are scoped to a region, never used as new runtime IDs.
CODE_IDS = {
    'region_01':{**{f'R{i:02}':f'char_01_r{i:02}' for i in range(1,10)},
                 **{f'F{i:02}':f'char_01_f{i:02}' for i in range(1,4)}},
    'region_02':dict(zip([f'A{i:02}' for i in range(1,10)],
        ['char_02_' + x for x in ('head','elements','healing','combat','student_head','genius','trouble','librarian','researcher')])),
    'region_03':dict(zip([f'G-R{i:02}' for i in range(1,7)] + [f'G-F{i:02}' for i in range(1,6)],
        ['char_03_' + x for x in ('guild_head','reception_head','merchant_head','mercenary_head','informant','captain','mage','warrior','adventurer_m','adventurer_f','assassin')])),
    'region_04':dict(zip(['D04-R01','D04-R02','D04-R03','D04-F01','D04-F02'],
        ['char_04_' + x for x in ('lord','commander','herbalist','youth','hunter')])),
    'region_05':dict(zip(['R01','R02','F01','R03','F02'],
        ['char_05_' + x for x in ('delegate','guardian','archer','priest','exile')])),
    'region_06':dict(zip(['R01','R02','R03','R04','R05','F01'],
        ['char_06_' + x for x in ('leader','smith','mine_head','guard_head','rune','warrior')])),
    'region_07':dict(zip([f'H{i:02}' for i in range(1,7)],
        ['char_07_' + x for x in ('lord','mage','commander','infiltrator','exile','warden')])),
}
CARD_HEAD = re.compile(r'^((?:G-|D04-)?[RAFH]\d{2})[｜|](.+)$')
SECTIONS = ('性格','能力','立場','情感關係','外貌細節','跟隨角色設定','可跟隨設定','可跟隨條件方向','生圖關鍵字')


def _text(node):
    return ''.join(n.text or '' for n in node.findall('.//w:t', NS)).strip()


def _paragraphs(node):
    return [_text(p) for p in node.findall('.//w:p', NS) if _text(p)]


def _sections(lines):
    result, heading = {}, '身分'
    for line in lines:
        match = next((key for key in SECTIONS if line == key), None)
        if match:
            heading = match
        elif re.match(r'^(?:適合)?生圖關鍵字[：:]', line):
            heading = '生圖關鍵字'
            result.setdefault(heading, []).append(line)
        else:
            result.setdefault(heading, []).append(line)
    return {key:'\n'.join(value) for key, value in result.items()}


def read_document(stream, story):
    package = Package(stream)
    try:
        raw = package.read('word/document.xml')
        if len(raw) > 4 * 1024 * 1024 or b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
            raise engine.StoryError('設定書 XML 過大或包含不支援的定義。')
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            raise engine.StoryError('設定書內容無法讀取。') from None
    finally:
        package.close()
    paragraphs = _paragraphs(root)
    regions = story['world']['definition']['regions']
    starts, cards = {}, {}
    for region in regions:
        number = int(region['id'].split('_')[-1])
        markers = [i for i, line in enumerate(paragraphs)
                   if line.startswith(f'{number:02}｜') and region['name'] in line]
        if not markers:
            raise engine.StoryError('設定書缺少區域：' + region['name'])
        starts[region['id']] = min(markers)
    ordered = sorted(starts, key=starts.get)
    if ordered != list(CODE_IDS):
        raise engine.StoryError('設定書的七區順序與世界 ID 不一致。')
    public_regions, chapters = {}, {}
    for index, rid in enumerate(ordered):
        end = starts[ordered[index + 1]] if index + 1 < len(ordered) else len(paragraphs)
        chapter = paragraphs[starts[rid]:end]
        chapters[rid] = chapter
        heads = [i for i,line in enumerate(chapter) if re.match(r'^四、\d+\s*位.*角色.*設定', line)]
        if len(heads) != 1:
            raise engine.StoryError('無法唯一識別區域角色詳細設定：' + rid)
        stop = next((i for i in range(heads[0] + 1, len(chapter)) if chapter[i].startswith('五、')), len(chapter))
        body = chapter[heads[0]+1:stop]
        positions = [(i, CARD_HEAD.match(line)) for i,line in enumerate(body) if CARD_HEAD.match(line)]
        if {m.group(1) for _,m in positions} != set(CODE_IDS[rid]) or len(positions) != len(CODE_IDS[rid]):
            raise engine.StoryError('角色編號缺漏或重複，未更新任何資料：' + rid)
        for at, (start, match) in enumerate(positions):
            end_card = positions[at+1][0] if at+1 < len(positions) else len(body)
            cid = CODE_IDS[rid][match.group(1)]
            fields = _sections(body[start+1:end_card])
            if not fields.get('性格') or not fields.get('能力'):
                raise engine.StoryError('角色詳細設定缺少性格或能力：' + cid)
            cards[cid] = {'id':cid, 'name':match.group(2).strip(), 'region_id':rid,
                'source_code':match.group(1), 'fields':fields}
        overview = next((i for i,line in enumerate(chapter) if line.startswith('一、')), 0)
        roster = next((i for i,line in enumerate(chapter) if line.startswith('三、')), heads[0])
        public_regions[rid] = '\n'.join(chapter[overview:roster])
    if set(cards) != {c['id'] for c in story['characters'] if c['kind'] == 'important_character'}:
        raise engine.StoryError('設定書角色與既有 ID 對照不完整。')
    # Read actual table cells, not flattened columns, to preserve jobs/schedules.
    body = root.find('w:body', NS)
    rid, npcs, natural = None, {}, {}
    for block in body:
        if block.tag == '{' + NS['w'] + '}p':
            line = _text(block)
            for region in regions:
                number = int(region['id'].split('_')[-1])
                if line.startswith(f'{number:02}｜') and region['name'] in line:
                    rid = region['id']
        elif block.tag == '{' + NS['w'] + '}tbl':
            rows = [[_text(cell) for cell in row.findall('w:tc', NS)] for row in block.findall('w:tr', NS)]
            if not rows:
                continue
            headers = rows[0]
            if headers[:2] == ['地點','世界設定與用途']:
                natural.update({row[0]:row[1] for row in rows[1:] if len(row) >= 2})
            if rid and headers[0] == '編號':
                for row in rows[1:]:
                    if not row:
                        continue
                    match = re.fullmatch(r'(?:G-|D04-)?N(\d{2})', row[0])
                    if not match:
                        continue
                    cid = 'npc_' + rid[-2:] + '_' + row[0].lower().replace('-', '_')
                    if cid in npcs:
                        raise engine.StoryError('常駐 NPC 編號重複：' + cid)
                    npcs[cid] = {'id':cid, 'region_id':rid, 'name':row[1],
                        'details':dict(zip(headers[1:], row[1:]))}
    if set(npcs) != {c['id'] for c in story['characters'] if c['kind'] == 'npc'}:
        raise engine.StoryError('常駐 NPC 與既有 99 個 ID 對照不完整。')
    return {'document_xml_sha256':hashlib.sha256(raw).hexdigest(), 'cards':cards, 'npcs':npcs,
        'public_rules':'\n'.join(paragraphs[:starts[ordered[0]]]),
        'public_regions':public_regions, 'chapters':chapters, 'natural_locations':natural}


def _scene_description(scene, data):
    if scene['title'] in data['natural_locations']:
        return data['natural_locations'][scene['title']]
    chapter = data['chapters'].get(scene.get('region_id'), [])
    heads = [(i, re.match(r'^[A-F][｜|](.+)$', line)) for i,line in enumerate(chapter) if re.match(r'^[A-F][｜|](.+)$', line)]
    for index, (start, match) in enumerate(heads):
        end = heads[index+1][0] if index+1 < len(heads) else next((i for i in range(start+1,len(chapter)) if chapter[i].startswith('三、')), start+1)
        block = chapter[start:end]
        if scene['title'] == match.group(1) or scene['title'] in block:
            return '\n'.join(block)
    return scene['description']


def apply_document(user_dir, story_id, stream, base_revision):
    with engine._LOCK:
        story = engine.get_story(user_dir, story_id)
        if not story.get('world'):
            raise engine.StoryError('請先匯入魔法異世界，再更新設定書。')
        old = story['world'].get('author_settings') or {}
        if type(base_revision) is not int or base_revision != old.get('revision', 0):
            raise ConflictError('設定書已更新，請重新載入後操作；本次沒有覆蓋設定。')
        data = read_document(stream, story)
        if old.get('document_xml_sha256') == data['document_xml_sha256']:
            return {'story':story, 'already_applied':True, 'report':old['report']}
        updated = copy.deepcopy(story)
        identities = {c['id']:c for c in updated['world']['definition']['characters']}
        for c in updated['characters']:
            if c['kind'] == 'important_character':
                card = data['cards'][c['id']]
                fields = card['fields']
                c['name'] = card['name']
                c['personality'] = fields['性格']
                c['backstory'] = '\n'.join(key + '：\n' + value for key,value in fields.items() if key not in ('性格','生圖關鍵字'))
                identity = c['identity']
                role_line = next((line for line in fields.get('身分', '').splitlines() if '｜' in line), '')
                identity.update({'name':card['name'], 'record_status':'author_card', 'source_code':card['source_code'],
                    'author_card':fields, 'follower_candidate':False if '不可跟隨' in fields.get('身分', '') else (
                        identity.get('follower_candidate') is True or bool(re.search(r'可(?:長期)?跟隨', fields.get('身分', ''))))})
                if role_line:
                    identity['display_label'] = role_line.split('｜')[0]
                identities[c['id']].update(copy.deepcopy(identity))
            else:
                npc = data['npcs'][c['id']]
                c['name'] = npc['name']
                c['personality'] = '依固定身分工作、休息與日常互動；沒有特別劇情時不另造複雜私人背景。'
                c['backstory'] = '\n'.join(key + '：' + value for key,value in npc['details'].items())
                work = next((value for key,value in npc['details'].items() if '地點' in key), '')
                known = next((s['id'] for s in updated['scenes'] if s['region_id'] == c['region_id'] and s['title'] == work), None)
                c['identity'].update({'name':npc['name'], 'record_status':'author_npc', 'work_details':npc['details'],
                    'work_location_id':known, 'follower_candidate':False})
            if len(c['personality']) > 3000 or len(c['backstory']) > 3000 or len(c['name']) > 60:
                raise engine.StoryError('角色設定超過目前欄位容量，未截斷或更新：' + c['id'])
        for scene in updated['scenes']:
            description = _scene_description(scene, data)
            if len(description) > 4000:
                raise engine.StoryError('場景設定超過目前欄位容量：' + scene['id'])
            scene['description'] = description
        report = {'important_characters':len(data['cards']), 'npcs':len(data['npcs']),
            'scenes':len(updated['scenes']), 'sessions_preserved':True, 'portraits_preserved':True}
        updated['world']['author_settings'] = {'revision':old.get('revision', 0)+1,
            'document_xml_sha256':data['document_xml_sha256'], 'public_rules':data['public_rules'],
            'public_regions':data['public_regions'],
            'author_regions':{rid:'\n'.join(chapter) for rid,chapter in data['chapters'].items()},
            'report':report}
        updated['opening'] = ('這是自由探索的魔法異世界。新開局可選擇原生居民、異世界轉生、異世界穿越或自訂身世，'
            '描述你的角色與起始地點；已開始的旅程直接續玩。角色保留自己的工作、生活與選擇。')
        updated = engine.validate_story(updated, story_id)
        # Only the definition changes; session files, media and model config are
        # untouched. An immutable original remains available for recovery.
        backup = engine._root(user_dir) / 'world-settings-backups' / story_id
        backup.mkdir(parents=True, exist_ok=True)
        engine._write(backup / (str(old.get('revision', 0)) + '-' + uuid.uuid4().hex + '.json'), story)
        engine._write(engine._story_path(user_dir, story_id), updated)
        return {'story':updated, 'already_applied':False, 'report':report}
