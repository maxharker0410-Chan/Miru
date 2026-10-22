"""Explicit player actions, kept distinct from unmarked text."""
import re

PLAYER_INPUT_RULES = (
    'player_input 是玩家原文；player_input_parts 依原順序區分 action 與 speech。'
    '成對 * 或 ** 中間的文字必須視為玩家的動作或行為，不是說出口的台詞。'
    '中文引號「…」中的文字是玩家說話；未標記文字按語意判讀，不確定而後果重大才釐清。'
    'speech 是未標記文字，通常是台詞；若明確敘述自己的行動，仍可按行動理解。'
    '回應動作的可觀察反應，不把動作冒充玩家或角色說出口的話，也不替玩家決定後續行動。'
    '動作描述不保證成功；結果仍須遵守世界規則、能力與現場條件。'
)


def input_parts(text):
    parts, cursor = [], 0
    pattern = r'(?<!\*)(\*\*|\*)(?!\*)([\s\S]+?)(?<!\*)\1(?!\*)|「([^」]*)」'
    for match in re.finditer(pattern, text):
        value = (match.group(2) if match.group(1) else match.group(3)).strip()
        if not value:
            continue
        if match.start() > cursor:
            parts.append({'kind':'speech', 'text':text[cursor:match.start()]})
        parts.append({'kind':'action' if match.group(1) else 'speech', 'text':value})
        cursor = match.end()
    if cursor < len(text):
        parts.append({'kind':'speech', 'text':text[cursor:]})
    return parts
