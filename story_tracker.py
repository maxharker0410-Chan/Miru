"""Author-defined story values; validated updates share the turn's atomic save."""
from __future__ import annotations

import math
import re

_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _value(field, value):
    if field["kind"] == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return None
        if not field["min"] <= value <= field["max"]:
            return None
        return round(value, 2)
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        return None
    value = value.strip()
    if field.get("choices") and value not in field["choices"]:
        return None
    return value


def validate(groups, characters):
    if not isinstance(groups, list) or len(groups) > 20:
        raise ValueError("數值追蹤最多可設定 20 個分類")
    result, seen, count = [], set(), 0
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("數值追蹤分類格式錯誤")
        gid, title = group.get("id"), group.get("title")
        if not isinstance(gid, str) or not _ID.fullmatch(gid) or gid in seen or not isinstance(title, str) or not title.strip():
            raise ValueError("數值追蹤分類需要名稱與不重複的 ID")
        seen.add(gid)
        fields = group.get("fields")
        if not isinstance(fields, list) or not 1 <= len(fields) <= 12:
            raise ValueError("每個追蹤分類需有 1 至 12 個項目")
        clean = {"id": gid, "title": title.strip()[:80], "fields": []}
        role = group.get("character_name", "")
        if isinstance(role, str) and role.strip():
            clean["character_name"] = role.strip()[:80]
            # Rebind by name after author edits; removing a role never invents presence.
            cid = group.get("character_id")
            matched = next((c for c in characters if c["id"] == cid), None)
            if matched is None:
                matched = next((c for c in characters if role.split(" (")[0] in c["name"]), None)
            clean["character_id"] = matched["id"] if matched else ""
        field_ids = set()
        for field in fields:
            if not isinstance(field, dict):
                raise ValueError("數值追蹤項目格式錯誤")
            fid, label, kind = field.get("id"), field.get("label"), field.get("kind")
            if not isinstance(fid, str) or not _ID.fullmatch(fid) or fid in field_ids or not isinstance(label, str) or not label.strip() or kind not in ("number", "text"):
                raise ValueError("追蹤項目的名稱、ID 或類型無效")
            field_ids.add(fid)
            item = {"id": fid, "label": label.strip()[:80], "kind": kind,
                    "unit": str(field.get("unit", ""))[:20], "note": str(field.get("note", ""))[:400]}
            if kind == "number":
                low, high = field.get("min", 0), field.get("max", 100)
                if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in (low, high)) or low >= high:
                    raise ValueError("追蹤數值範圍無效")
                item.update(min=low, max=high)
            choices = field.get("choices", [])
            if not isinstance(choices, list) or len(choices) > 20 or any(not isinstance(v, str) or not v.strip() or len(v) > 160 for v in choices):
                raise ValueError("追蹤狀態選項無效")
            if choices:
                item["choices"] = choices
            initial = _value(item, field.get("initial"))
            if initial is None:
                raise ValueError("追蹤項目的初始值不符合範圍或狀態選項")
            item["initial"] = initial
            clean["fields"].append(item)
            count += 1
        result.append(clean)
    if count > 100:
        raise ValueError("最多可追蹤 100 個項目")
    return result


def reconcile(story, session):
    old = session.get("tracker", {})
    old = old if isinstance(old, dict) else {}
    current = {}
    for group in story.get("state_tracker", []):
        for field in group["fields"]:
            key = group["id"] + "." + field["id"]
            value = _value(field, old.get(key))
            current[key] = field["initial"] if value is None else value
    changed = session.get("tracker") != current
    if current or "tracker" in session:
        session["tracker"] = current
    return changed if current or "tracker" in session else False


def model_values(story, session, character_id=None):
    groups = []
    for group in story.get("state_tracker", []):
        if character_id is not None and group.get("character_name") and group.get("character_id") != character_id:
            continue
        groups.append({"title": group["title"], "character_id": group.get("character_id", ""),
                       "fields": [{**f, "key": group["id"] + "." + f["id"],
                                   "value": session["tracker"][group["id"] + "." + f["id"]]}
                                  for f in group["fields"]]})
    return groups


def apply_updates(story, session, updates):
    if not isinstance(updates, dict):
        return
    events = []
    for group in story.get("state_tracker", []):
        # An absent character's feelings cannot change just to advance a counter.
        if group.get("character_name") and group.get("character_id") not in session["cast"]:
            continue
        for field in group["fields"]:
            key = group["id"] + "." + field["id"]
            update = updates.get(key)
            if not isinstance(update, dict) or not isinstance(update.get("reason"), str) or not update["reason"].strip():
                continue
            value = _value(field, update.get("value"))
            before = session["tracker"][key]
            if value is not None and value != before:
                session["tracker"][key] = value
                events.append({"key": key, "before": before, "value": value, "reason": update["reason"].strip()[:240]})
    if events:
        previous = session.get("tracker_events", [])
        session["tracker_events"] = ((previous if isinstance(previous, list) else []) + events)[-30:]


def camp_tracker(characters):
    def number(fid, label, initial, unit="%", note=""):
        return dict(id=fid, label=label, kind="number", initial=initial, min=0, max=100, unit=unit, note=note)
    def text(fid, label, initial, choices=None):
        field = dict(id=fid, label=label, kind="text", initial=initial)
        if choices:
            field["choices"] = choices
        return field
    groups = [dict(id="camp", title="營地資源", fields=[
        number("water", "淡水儲備", 5, "單位", "少量破損水囊；每日消耗，缺少時全體依賴度與健康下降。未指定每日消耗量，勿自行發明固定扣量。"),
        number("wood", "乾木儲量", 0, "單位", "四周皆為潮濕漂流木；用於生火、加固庇護所與驅逐猛獸。"),
        number("food", "食物肉乾", 2, "單位", "微薄乾糧；維持體能。"),
        number("safety", "營地安全度", 10, "%", "毫無遮蔽的開闊沙灘；防禦設施與野獸、蠻族威脅。")]),
        dict(id="relations", title="部族關係與封印", fields=[
            number("reputation", "獵骨氏族聲望", 0, "%", "已被氏族偵察兵發現；影響襲擊或貿易。"),
            text("attitude", "氏族態度", "敵對", ["冷淡", "敵對", "認可", "崇敬"]),
            number("seal", "噬魔巨獸封印穩定度", 100, "%", "若注入魔力，此數值將暴跌引發天災。")])]
    roles = [("elena", "艾蓮娜 (法師)", 5, 10, "企圖發號施令"),
             ("celia", "瑟莉亞 (聖騎)", 10, 5, "茫然挫敗、難以提劍"),
             ("lilian", "莉莉安 (神官)", 15, 20, "極度恐懼、眼角泛淚"),
             ("vivian", "薇薇安 (刺客)", 5, 15, "暗中防備"),
             ("talya", "塔爾婭 (蠻族)", 0, 0, "潛伏在叢林邊緣，觀察中")]
    for gid, name, affinity, reliance, state in roles:
        groups.append(dict(id=gid, title=name, character_name=name, fields=[
            number("affinity", "好感度", affinity),
            number("submission" if gid == "talya" else "dependency", "屈服度" if gid == "talya" else "依賴度", reliance),
            text("state", "心理狀態", state)]))
    return validate(groups, characters)
