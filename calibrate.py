"""座標キャリブレーション: 1枚のスクショで名前行の矩形を指定する。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox

from PIL import Image, ImageTk

CONFIG_PATH = Path(__file__).with_name("config.json")
EXPECTED_SIZE = (3840, 2160)


class Calibrator:
    def __init__(self, image_path: Path) -> None:
        self.image_path = image_path
        self.original = Image.open(image_path).convert("RGB")
        if self.original.size != EXPECTED_SIZE:
            messagebox.showwarning(
                "解像度",
                f"画像サイズ {self.original.size} は {EXPECTED_SIZE} と異なります。\n"
                "座標はこの画像サイズ基準で保存されます。",
            )

        self.config = self._load_config()
        self.scale = min(1400 / self.original.width, 900 / self.original.height, 1.0)
        display_size = (
            int(self.original.width * self.scale),
            int(self.original.height * self.scale),
        )
        self.display = self.original.resize(display_size, Image.Resampling.LANCZOS)

        self.root = tk.Tk()
        self.root.title("BA 名前座標キャリブレーション")
        self.canvas = tk.Canvas(
            self.root,
            width=display_size[0],
            height=display_size[1],
            cursor="crosshair",
        )
        self.canvas.pack()

        self.photo = ImageTk.PhotoImage(self.display)
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)

        self.active_key = tk.StringVar(value="left_row")
        self.drag_start: tuple[int, int] | None = None
        self.temp_rect_id: int | None = None

        frame = tk.Frame(self.root)
        frame.pack(fill="x", padx=8, pady=8)
        tk.Label(frame, text="編集対象:").pack(side="left")
        tk.Radiobutton(frame, text="左チーム行", variable=self.active_key, value="left_row").pack(
            side="left"
        )
        tk.Radiobutton(frame, text="右チーム行", variable=self.active_key, value="right_row").pack(
            side="left"
        )
        tk.Button(frame, text="保存", command=self.save).pack(side="right", padx=4)
        tk.Button(frame, text="閉じる", command=self.root.destroy).pack(side="right")

        help_text = (
            "ドラッグで矩形を描いて名前が6人分収まる行を指定してください。\n"
            "左→右の順で6等分されます。保存後 extract_names.py を実行します。"
        )
        tk.Label(self.root, text=help_text, justify="left").pack(padx=8, pady=(0, 8))

        self.rect_ids: dict[str, int] = {}
        for key in ("left_row", "right_row"):
            self._draw_saved_rect(key)

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

    def _load_config(self) -> dict:
        if CONFIG_PATH.exists():
            with CONFIG_PATH.open(encoding="utf-8") as f:
                return json.load(f)
        return {
            "resolution": list(EXPECTED_SIZE),
            "left_row": {"x": 780, "y": 1475, "width": 960, "height": 55},
            "right_row": {"x": 2040, "y": 1475, "width": 960, "height": 55},
            "columns": 6,
        }

    def _to_display(self, rect: dict) -> tuple[int, int, int, int]:
        return (
            int(rect["x"] * self.scale),
            int(rect["y"] * self.scale),
            int((rect["x"] + rect["width"]) * self.scale),
            int((rect["y"] + rect["height"]) * self.scale),
        )

    def _from_display(self, x1: int, y1: int, x2: int, y2: int) -> dict:
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        return {
            "x": int(round(x1 / self.scale)),
            "y": int(round(y1 / self.scale)),
            "width": max(1, int(round((x2 - x1) / self.scale))),
            "height": max(1, int(round((y2 - y1) / self.scale))),
        }

    def _draw_saved_rect(self, key: str) -> None:
        if key in self.rect_ids:
            self.canvas.delete(self.rect_ids[key])
        x1, y1, x2, y2 = self._to_display(self.config[key])
        color = "#0078d4" if key == "left_row" else "#d13438"
        self.rect_ids[key] = self.canvas.create_rectangle(
            x1, y1, x2, y2, outline=color, width=2
        )

    def on_press(self, event: tk.Event) -> None:
        self.drag_start = (event.x, event.y)
        if self.temp_rect_id is not None:
            self.canvas.delete(self.temp_rect_id)
        self.temp_rect_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="#333333", dash=(4, 2), width=2
        )

    def on_drag(self, event: tk.Event) -> None:
        if self.drag_start is None or self.temp_rect_id is None:
            return
        x0, y0 = self.drag_start
        self.canvas.coords(self.temp_rect_id, x0, y0, event.x, event.y)

    def on_release(self, event: tk.Event) -> None:
        if self.drag_start is None:
            return
        x0, y0 = self.drag_start
        rect = self._from_display(x0, y0, event.x, event.y)
        if rect["width"] < 20 or rect["height"] < 10:
            if self.temp_rect_id is not None:
                self.canvas.delete(self.temp_rect_id)
            self.temp_rect_id = None
            self.drag_start = None
            return

        key = self.active_key.get()
        self.config[key] = rect
        self._draw_saved_rect(key)
        if self.temp_rect_id is not None:
            self.canvas.delete(self.temp_rect_id)
        self.temp_rect_id = None
        self.drag_start = None

    def save(self) -> None:
        self.config["resolution"] = list(self.original.size)
        self.config["columns"] = 6
        with CONFIG_PATH.open("w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)
        messagebox.showinfo("保存", f"設定を保存しました:\n{CONFIG_PATH}")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    root = tk.Tk()
    root.withdraw()
    image_path = filedialog.askopenfilename(
        title="キャリブレーション用スクショを選択",
        filetypes=[("Images", "*.png *.jpg *.jpeg *.webp"), ("All", "*.*")],
    )
    root.destroy()
    if not image_path:
        print("画像が選択されませんでした。")
        sys.exit(1)
    Calibrator(Path(image_path)).run()


if __name__ == "__main__":
    main()
