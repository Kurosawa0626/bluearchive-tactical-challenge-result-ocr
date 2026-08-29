"""ブルアカ戦闘履歴スクショからキャラ名を一括抽出して CSV 出力する。"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

from name_dictionary import CharacterDictionary, slot_group_for_column
import cv2
import easyocr
import numpy as np
import torch
from PIL import Image
from tkinter import Tk, filedialog, messagebox
from tqdm import tqdm

CONFIG_PATH = Path(__file__).with_name("config.json")
EXPECTED_SIZE = (3840, 2160)
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
TEAM_SIZE = 6


def use_gpu_for_ocr() -> bool:
    if not torch.cuda.is_available():
        return False
    try:
        torch.zeros(1, device="cuda")
        return True
    except Exception:
        return False


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"設定ファイルがありません: {CONFIG_PATH}\n"
            "先に calibrate.py を実行して座標を設定してください。"
        )
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def normalize_name(text: str) -> str:
    text = text.strip()
    text = text.replace(" ", "").replace("　", "")
    text = text.replace("(", "（").replace(")", "）")
    text = re.sub(r"[|｜/Iil1＿_·・~〜=]", "", text)
    return text


def merge_name_fragments(names: list[str]) -> str:
    return "".join(names)


def crop_image(image: np.ndarray, rect: dict) -> np.ndarray:
    x1 = max(0, rect["x"])
    y1 = max(0, rect["y"])
    x2 = min(image.shape[1], rect["x"] + rect["width"])
    y2 = min(image.shape[0], rect["y"] + rect["height"])
    return image[y1:y2, x1:x2]


def merge_column_fragments(items: list[tuple[float, float, str]]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0][2]

    ys = [y for _, y, _ in items]
    if max(ys) - min(ys) < 15:
        items.sort(key=lambda item: item[0])
        return merge_name_fragments([text for _, _, text in items])

    sorted_by_y = sorted(items, key=lambda item: item[1])
    y_values = [y for _, y, _ in sorted_by_y]
    max_gap = 0.0
    split_index = len(sorted_by_y)
    for index in range(len(y_values) - 1):
        gap = y_values[index + 1] - y_values[index]
        if gap > max_gap:
            max_gap = gap
            split_index = index + 1

    if max_gap < 12:
        sorted_by_y.sort(key=lambda item: item[0])
        return merge_name_fragments([text for _, _, text in sorted_by_y])

    top_row = sorted(sorted_by_y[:split_index], key=lambda item: item[0])
    bottom_row = sorted(sorted_by_y[split_index:], key=lambda item: item[0])
    ordered = [text for _, _, text in top_row] + [text for _, _, text in bottom_row]
    return merge_name_fragments(ordered)


def ocr_column(reader: easyocr.Reader, column_crop: np.ndarray) -> str:
    if column_crop.size == 0:
        return ""

    results = reader.readtext(column_crop, detail=1, paragraph=False)
    items: list[tuple[float, float, str]] = []
    for bbox, text, confidence in results:
        cleaned = normalize_name(text)
        if len(cleaned) < 1 or confidence < 0.25:
            continue
        x_center = (bbox[0][0] + bbox[1][0]) / 2
        y_center = (bbox[0][1] + bbox[2][1]) / 2
        items.append((x_center, y_center, cleaned))

    return merge_column_fragments(items)


def ocr_row(reader: easyocr.Reader, image: np.ndarray, row: dict) -> list[str]:
    crop = crop_image(image, row)
    if crop.size == 0:
        return [""] * TEAM_SIZE

    scaled = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    row_width = scaled.shape[1]
    slot_width = row_width / TEAM_SIZE
    names: list[str] = []

    for index in range(TEAM_SIZE):
        x1 = int(round(index * slot_width))
        x2 = int(round((index + 1) * slot_width)) if index < TEAM_SIZE - 1 else row_width
        column_crop = scaled[:, x1:x2]
        names.append(ocr_column(reader, column_crop))

    return names


def iter_images(folder: Path) -> list[Path]:
    return [
        path
        for path in sorted(folder.iterdir())
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]


def choose_folder() -> Path | None:
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    folder = filedialog.askdirectory(title="スクリーンショットフォルダを選択")
    root.destroy()
    return Path(folder) if folder else None


def extract_from_folder(folder: Path, output_path: Path | None = None) -> Path:
    config = load_config()
    images = iter_images(folder)
    if not images:
        raise FileNotFoundError(f"画像が見つかりません: {folder}")

    if output_path is None:
        output_path = folder / "character_names.csv"

    use_gpu = use_gpu_for_ocr()
    if use_gpu:
        tqdm.write(f"GPU を使用: {torch.cuda.get_device_name(0)}")
    else:
        tqdm.write("GPU が使えないため CPU で実行します")
    reader = easyocr.Reader(["ja"], gpu=use_gpu, verbose=False)
    dictionary = CharacterDictionary.load()
    fieldnames = (
        ["filename"]
        + [f"left_{index}" for index in range(1, TEAM_SIZE + 1)]
        + [f"right_{index}" for index in range(1, TEAM_SIZE + 1)]
    )
    unknown_warnings: list[str] = []
    unknown_names: set[str] = set()

    def match_with_warning(raw_name: str, filename: str, column: str) -> str:
        slot_group = slot_group_for_column(column)
        matched, known = dictionary.match_with_status(raw_name, slot_group=slot_group)
        if matched and not known:
            unknown_names.add(matched)
            unknown_warnings.append(f"{filename} [{column}] {matched}")
            tqdm.write(f"[未登録] {filename} {column}: {matched}")
        return matched

    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for image_path in tqdm(images, desc="OCR", unit="枚"):
            with Image.open(image_path) as pil_image:
                if pil_image.size != EXPECTED_SIZE:
                    tqdm.write(
                        f"[スキップ] {image_path.name}: 解像度 {pil_image.size} "
                        f"(期待値 {EXPECTED_SIZE})"
                    )
                    continue
                image = cv2.cvtColor(np.array(pil_image.convert("RGB")), cv2.COLOR_RGB2BGR)

            left_names = [
                match_with_warning(name, image_path.name, f"left_{index}")
                for index, name in enumerate(ocr_row(reader, image, config["left_row"]), start=1)
            ]
            right_names = [
                match_with_warning(name, image_path.name, f"right_{index}")
                for index, name in enumerate(ocr_row(reader, image, config["right_row"]), start=1)
            ]
            writer.writerow(
                {
                    "filename": image_path.name,
                    **{f"left_{index}": left_names[index - 1] for index in range(1, TEAM_SIZE + 1)},
                    **{f"right_{index}": right_names[index - 1] for index in range(1, TEAM_SIZE + 1)},
                }
            )

    if unknown_names:
        warning_path = output_path.with_name("character_names_warnings.txt")
        warning_path.write_text("\n".join(unknown_warnings) + "\n", encoding="utf-8")
        unknown_path = output_path.with_name("character_names_unknown.txt")
        unknown_path.write_text("\n".join(sorted(unknown_names)) + "\n", encoding="utf-8")
        tqdm.write(f"\n[未登録] {len(unknown_warnings)} 件（{len(unknown_names)} 種類）")
        tqdm.write("未登録の名前:")
        for name in sorted(unknown_names):
            tqdm.write(f"  - {name}")
        tqdm.write(f"一覧: {unknown_path}")
        tqdm.write(f"詳細: {warning_path}")
    else:
        tqdm.write("未登録の名前は見つかりませんでした。")

    return output_path


def main() -> None:
    folder: Path | None
    if len(sys.argv) > 1:
        folder = Path(sys.argv[1])
        if not folder.is_dir():
            print(f"フォルダが見つかりません: {folder}", file=sys.stderr)
            sys.exit(1)
    else:
        folder = choose_folder()
        if folder is None:
            print("フォルダが選択されませんでした。")
            sys.exit(1)

    try:
        output_path = extract_from_folder(folder)
    except Exception as exc:
        if len(sys.argv) <= 1:
            root = Tk()
            root.withdraw()
            messagebox.showerror("エラー", str(exc))
            root.destroy()
        print(exc, file=sys.stderr)
        sys.exit(1)

    message = f"完了しました。\n\n出力: {output_path}"
    unknown_path = output_path.with_name("character_names_unknown.txt")
    if unknown_path.exists():
        unknown_names = unknown_path.read_text(encoding="utf-8").splitlines()
        message += f"\n\n未登録の名前 ({len(unknown_names)} 種類):\n"
        message += "\n".join(f"  - {name}" for name in unknown_names)
        message += f"\n\n{unknown_path}"
    warning_path = output_path.with_name("character_names_warnings.txt")
    if warning_path.exists():
        warning_count = len(warning_path.read_text(encoding="utf-8").splitlines())
        message += f"\n\n詳細: {warning_count} 件\n{warning_path}"
    print(message)
    if len(sys.argv) <= 1:
        root = Tk()
        root.withdraw()
        messagebox.showinfo("完了", message)
        root.destroy()


if __name__ == "__main__":
    main()
