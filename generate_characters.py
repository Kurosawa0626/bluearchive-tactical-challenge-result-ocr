"""ブルアカ Wiki のキャラ一覧から characters.txt を生成する。"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from html import unescape
from pathlib import Path

from name_dictionary import parse_dictionary_line

WIKI_URL = "https://bluearchive.wikiru.jp/?%E3%82%AD%E3%83%A3%E3%83%A9%E3%82%AF%E3%82%BF%E3%83%BC%E4%B8%80%E8%A6%A7"
OUTPUT = Path(__file__).with_name("characters.txt")
USER_AGENT = "ba-screenshot-ocr/1.0 (+local character dictionary generator)"

# Wiki 表の title 属性からキャラ名を抽出
NAME_PATTERN = re.compile(
    r'<td[^>]*>\s*★[123]\s*</td>\s*<td[^>]*>.*?title="([^"]+)"',
    re.S,
)


def fetch_wiki_html(url: str = WIKI_URL) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def extract_character_names(html: str) -> list[str]:
    names = {unescape(name.strip()) for name in NAME_PATTERN.findall(html)}
    names.discard("")
    return sorted(names)


def load_existing_slots(path: Path) -> dict[str, str]:
    slots: dict[str, str] = {}
    if not path.exists():
        return slots

    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = parse_dictionary_line(line)
        if parsed is None:
            continue
        name, slot = parsed
        if slot:
            slots[name] = slot
    return slots


def main() -> None:
    try:
        html = fetch_wiki_html()
    except urllib.error.URLError as exc:
        raise SystemExit(f"Wiki の取得に失敗しました: {exc}") from exc

    names = extract_character_names(html)
    if not names:
        raise SystemExit("キャラ名を1件も抽出できませんでした。Wiki の HTML 構造が変わった可能性があります。")

    existing_slots = load_existing_slots(OUTPUT)
    lines = ["# 末尾に st（1-4列）または sp（5-6列）を付けて配置制約を指定（省略時は両方）"]
    for name in names:
        slot = existing_slots.get(name)
        if slot:
            lines.append(f"{name}\t{slot}")
        else:
            lines.append(name)

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    preserved = sum(1 for name in names if name in existing_slots)
    print(f"{len(names)} 件を書き出しました: {OUTPUT}")
    print(f"スロット指定を引き継ぎ: {preserved} 件")
    print(f"参照元: {WIKI_URL}")


if __name__ == "__main__":
    main()
