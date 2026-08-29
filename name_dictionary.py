"""キャラ名辞書の読み込みと曖昧一致。"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

CHARACTERS_PATH = Path(__file__).with_name("characters.txt")
SLOT_LINE_PATTERN = re.compile(r"^(.+?)[\t ]+(st|sp)$", re.IGNORECASE)

# ゲーム内表記と辞書表記の差分（OCR 結果の別名）
ALIASES = {
    "シロコテラー": "シロコ＊テラー",
    "シロコ*テラー": "シロコ＊テラー",
    "シロコ＊テ": "シロコ＊テラー",
    "シロコ*テ": "シロコ＊テラー",
    "三ネ": "ミネ",
    "三力": "ミカ",
}

# Wiki 一覧に載っていない追加名があればここへ
EXTRA_NAMES: list[str] = []


def normalize_for_match(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("*", "＊")
    text = text.replace("(", "（").replace(")", "）")
    text = text.replace(" ", "").replace("　", "")
    text = re.sub(r"[|｜/Iil1＿_·・~〜=]", "", text)
    return text


def parse_dictionary_line(line: str) -> tuple[str, str | None] | None:
    cleaned = line.strip()
    if not cleaned or cleaned.startswith("#"):
        return None

    match = SLOT_LINE_PATTERN.match(cleaned)
    if match:
        return match.group(1).strip(), match.group(2).lower()

    return cleaned, None


def expand_aliases_in_raw(cleaned: str) -> str:
    """ベース名の別名を衣装付き名前にも適用する（例: 三力（水着）→ ミカ（水着））。"""
    for alias, target in sorted(ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        alias_key = normalize_for_match(alias)
        target_key = normalize_for_match(target)
        if cleaned == alias_key:
            return target_key
        costume_prefix = alias_key + "（"
        if cleaned.startswith(costume_prefix):
            return target_key + cleaned[len(alias_key) :]
    return cleaned


def costume_parts(name: str) -> tuple[str, str | None]:
    match = re.fullmatch(r"(.+?)（(.+)）", name)
    if match:
        return match.group(1), match.group(2)
    return name, None


def tiebreak_score(raw: str, key: str, primary: float) -> tuple[float, float, float]:
    raw_core, raw_costume = costume_parts(raw)
    key_core, key_costume = costume_parts(key)
    costume_bonus = 1.0 if raw_costume and raw_costume == key_costume else 0.0
    core_bonus = SequenceMatcher(None, raw_core, key_core).ratio() if raw_core and key_core else 0.0
    contained_bonus = 1.0 if len(key_core) >= 2 and key_core in raw else 0.0
    return (primary, costume_bonus, core_bonus + contained_bonus)


def slot_group_for_column(column: str) -> str | None:
    match = re.fullmatch(r"(?:left|right)_(\d+)", column)
    if not match:
        return None
    return "sp" if int(match.group(1)) >= 5 else "st"


class CharacterDictionary:
    def __init__(self, names: list[str]) -> None:
        self._canonical: dict[str, str] = {}
        self._slot_by_key: dict[str, str | None] = {}

        for line in names:
            parsed = parse_dictionary_line(line)
            if parsed is None:
                continue
            display_name, slot = parsed
            key = normalize_for_match(display_name)
            self._canonical[key] = display_name
            self._slot_by_key[key] = slot

        for alias, target in ALIASES.items():
            alias_key = normalize_for_match(alias)
            target_key = normalize_for_match(target)
            if target_key not in self._canonical:
                continue
            self._canonical[alias_key] = self._canonical[target_key]
            self._slot_by_key[alias_key] = self._slot_by_key[target_key]

        self._entries = list(self._canonical.items())

    def is_known(self, name: str) -> bool:
        cleaned = normalize_for_match(name)
        if not cleaned:
            return True
        return cleaned in self._canonical

    @classmethod
    def load(cls, path: Path | None = None) -> CharacterDictionary:
        dictionary_path = path or CHARACTERS_PATH
        names = list(EXTRA_NAMES)
        if dictionary_path.exists():
            names.extend(dictionary_path.read_text(encoding="utf-8").splitlines())
        return cls(names)

    def match(self, raw: str, threshold: float = 0.55, slot_group: str | None = None) -> str:
        matched, _ = self.match_with_status(raw, threshold=threshold, slot_group=slot_group)
        return matched

    def _slot_allowed(self, key: str, slot_group: str | None) -> bool:
        if slot_group is None:
            return True
        slot = self._slot_by_key.get(key)
        return slot is None or slot == slot_group

    def _iter_candidates(self, slot_group: str | None):
        for key, canonical in self._entries:
            if self._slot_allowed(key, slot_group):
                yield key, canonical

    def match_with_status(
        self,
        raw: str,
        threshold: float = 0.55,
        slot_group: str | None = None,
    ) -> tuple[str, bool]:
        """辞書名と登録済みかを返す。登録済みでない場合は (名前, False)。"""
        cleaned = normalize_for_match(raw)
        if not cleaned:
            return "", True

        cleaned = expand_aliases_in_raw(cleaned)

        if cleaned in self._canonical and self._slot_allowed(cleaned, slot_group):
            return self._canonical[cleaned], True

        if len(cleaned) <= 2:
            matched = raw.strip()
            known = cleaned in self._canonical and self._slot_allowed(cleaned, slot_group)
            return matched, known

        best_name = cleaned
        best_tiebreak = (-1.0, -1.0, -1.0)
        for key, canonical in self._iter_candidates(slot_group):
            primary = SequenceMatcher(None, cleaned, key).ratio()
            tiebreak = tiebreak_score(cleaned, key, primary)
            if tiebreak > best_tiebreak:
                best_tiebreak = tiebreak
                best_name = canonical

        if best_tiebreak[0] >= threshold:
            return best_name, True
        return raw.strip(), False
