# ui/app.py
from __future__ import annotations
import os, sys, threading, time, multiprocessing as mp
from argparse import Namespace as NS
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# đảm bảo import được src/*
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src import main as app_main
from src.utils.logging_setup import setup_logging
from src.utils.io_excel import BASE_COLUMNS

if sys.platform.startswith("win"):
    mp.freeze_support()

APP_NAME = "Blog Comment Tool"

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("900x640")
        self.minsize(820, 560)

        # đường dẫn do người dùng chọn
        self.input_path  = tk.StringVar(value="")
        self.output_path = tk.StringVar(value="")
        # cache mặc định để tái sử dụng giữa các lần chạy
        self.cache_path  = tk.StringVar(value=str(ROOT / "data" / "forms_cache.json"))

        # options
        self.headless     = tk.BooleanVar(value=True)
        self.fast_analyze = tk.BooleanVar(value=True)
        self.per_host     = tk.BooleanVar(value=True)
        self.prefer_tpl   = tk.BooleanVar(value=True)
        self.use_tpl_only = tk.BooleanVar(value=False)

        self.find_timeout = tk.DoubleVar(value=3.0)
        self.post_workers = tk.IntVar(value=4)
        self.post_chunk   = tk.IntVar(value=80)

        self._build_ui()
        self.logger = setup_logging()
        self._append_log("Ready. Please choose an Excel file to start.")
        self._update_btns_state()

    # === UI ===
    def _build_ui(self):
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        row = 0
        ttk.Label(frm, text="Input Excel:").grid(row=row, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.input_path, width=70).grid(row=row, column=1, sticky="ew", padx=6)
        ttk.Button(frm, text="Browse…", command=self._choose_input).grid(row=row, column=2, sticky="e")
        ttk.Button(frm, text="Export template", command=self._export_template).grid(row=row, column=3, sticky="e", padx=(8,0))
        row += 1

        ttk.Label(frm, text="Output Excel:").grid(row=row, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.output_path, width=70).grid(row=row, column=1, sticky="ew", padx=6)
        ttk.Button(frm, text="Save as…", command=self._choose_output).grid(row=row, column=2, sticky="e")
        row += 1

        ttk.Label(frm, text="Cache JSON:").grid(row=row, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.cache_path, width=70).grid(row=row, column=1, sticky="ew", padx=6)
        ttk.Button(frm, text="Browse…", command=self._choose_cache).grid(row=row, column=2, sticky="e")
        row += 1

        for c in (1,):
            frm.columnconfigure(c, weight=1)

        # Options
        opt = ttk.LabelFrame(frm, text="Options", padding=8)
        opt.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(8,8))
        ttk.Checkbutton(opt, text="Headless", variable=self.headless, command=self._update_env_hint).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(opt, text="Fast analyze", variable=self.fast_analyze).grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(opt, text="Per-host analyze", variable=self.per_host).grid(row=0, column=2, sticky="w")
        ttk.Checkbutton(opt, text="Prefer template", variable=self.prefer_tpl).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(opt, text="Use template only", variable=self.use_tpl_only).grid(row=1, column=1, sticky="w")

        ttk.Label(opt, text="Find timeout (s):").grid(row=2, column=0, sticky="w", pady=(6,0))
        ttk.Entry(opt, textvariable=self.find_timeout, width=8).grid(row=2, column=1, sticky="w", pady=(6,0))
        ttk.Label(opt, text="Workers:").grid(row=2, column=2, sticky="e", pady=(6,0))
        ttk.Entry(opt, textvariable=self.post_workers, width=6).grid(row=2, column=3, sticky="w", pady=(6,0))
        ttk.Label(opt, text="Chunk:").grid(row=2, column=4, sticky="e", pady=(6,0))
        ttk.Entry(opt, textvariable=self.post_chunk, width=6).grid(row=2, column=5, sticky="w", pady=(6,0))

        for c in range(6):
            opt.columnconfigure(c, weight=1)

        # Buttons
        row += 1
        btns = ttk.Frame(frm)
        btns.grid(row=row, column=0, columnspan=4, sticky="ew")
        self.btn_analyze = ttk.Button(btns, text="Analyze", command=self._run_analyze)
        self.btn_scan    = ttk.Button(btns, text="Scan", command=self._run_scan)
        self.btn_post    = ttk.Button(btns, text="Post", command=self._run_post)
        self.btn_run_all = ttk.Button(btns, text="Run All", command=self._run_all, style="Accent.TButton")
        self.btn_analyze.pack(side="left")
        self.btn_scan.pack(side="left", padx=8)
        self.btn_post.pack(side="left")
        self.btn_run_all.pack(side="right")

        # Logs
        row += 1
        logf = ttk.LabelFrame(frm, text="Logs", padding=6)
        logf.grid(row=row, column=0, columnspan=4, sticky="nsew", pady=(8,0))
        self.txt = tk.Text(logf, height=20)
        self.txt.pack(fill="both", expand=True)
        frm.rowconfigure(row, weight=1)

    # === helpers ===
    def _append_log(self, text: str):
        self.txt.insert("end", text.strip() + "\n")
        self.txt.see("end")
        self.update()

    def _update_env_hint(self):
        pass

    def _update_btns_state(self):
        enabled = bool(self.input_path.get())
        for b in (self.btn_analyze, self.btn_scan, self.btn_post, self.btn_run_all):
            if enabled: b.state(["!disabled"])
            else: b.state(["disabled"])

    def _choose_input(self):
        fn = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")])
        if not fn: return
        # kiểm tra template
        try:
            import pandas as pd
            cols = pd.read_excel(fn, nrows=0).columns
            cols = [str(c).strip().lower() for c in cols]
            missing = [c for c in BASE_COLUMNS if c not in cols]
            if missing:
                messagebox.showerror(APP_NAME, f"File không đúng template.\nThiếu cột: {', '.join(missing)}")
                return
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Không mở được Excel:\n{e}")
            return

        self.input_path.set(fn)
        # gợi ý file output cùng thư mục, kèm timestamp
        p = Path(fn)
        ts = time.strftime("%Y%m%d-%H%M")
        self.output_path.set(str(p.with_name(f"{p.stem}_out_{ts}.xlsx")))
        self._append_log(f"Selected: {fn}")
        self._update_btns_state()

    def _choose_output(self):
        fn = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if fn: self.output_path.set(fn)

    def _choose_cache(self):
        fn = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if fn: self.cache_path.set(fn)

    def _export_template(self):
        fn = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
                                          initialfile="comments_template.xlsx")
        if not fn: return
        import pandas as pd
        df = pd.DataFrame(columns=BASE_COLUMNS)
        try:
            Path(fn).parent.mkdir(parents=True, exist_ok=True)
            df.to_excel(fn, index=False)
            messagebox.showinfo(APP_NAME, f"Đã xuất template:\n{fn}")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Không thể lưu template:\n{e}")

    def _thread(self, target, *args, **kwargs):
        t = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
        t.start()

    def _apply_env(self):
        # truyền cấu hình nhanh cho core (src.config đọc từ env)
        os.environ["HEADLESS"] = "true" if self.headless.get() else "false"
        os.environ["FIND_TIMEOUT"] = str(self.find_timeout.get())

    # === pipeline handlers ===
    def _run_analyze(self): self._thread(self._do_analyze)
    def _run_scan(self):    self._thread(self._do_scan)
    def _run_post(self):    self._thread(self._do_post)
    def _run_all(self):     self._thread(self._do_all)

    def _do_analyze(self):
        if not self.input_path.get():
            messagebox.showwarning(APP_NAME, "Hãy chọn file Excel trước.")
            return
        try:
            self._apply_env()
            inp, out = self.input_path.get(), self.output_path.get() or (str(Path(inp).with_name(f"{Path(inp).stem}_out_{time.strftime('%Y%m%d-%H%M')}.xlsx")))
            self.output_path.set(out)
            self._append_log(f"Analyze -> {out}")
            if self.fast_analyze.get():
                ns = NS(input=inp, output=out, fast=True, workers=32, connect_timeout=1.2, read_timeout=2.0, per_host=self.per_host.get())
            else:
                ns = NS(input=inp, output=out, fast=False)
            app_main.cmd_analyze(ns)
            self._append_log("Analyze done.")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Analyze failed:\n{e}")

    def _do_scan(self):
        out = self.output_path.get()
        if not out:
            messagebox.showwarning(APP_NAME, "Chưa có file output để scan. Hãy chạy Analyze trước.")
            return
        try:
            self._apply_env()
            cache = self.cache_path.get()
            self._append_log(f"Scan -> {cache}")
            ns = NS(input=out, cache=cache, scope="domain", start=0, limit=0, save_every=20, write_template=True)
            app_main.cmd_scan(ns)
            self._append_log("Scan done.")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Scan failed:\n{e}")

    def _do_post(self):
        out = self.output_path.get()
        if not out:
            messagebox.showwarning(APP_NAME, "Chưa có file output để post. Hãy chạy Analyze trước.")
            return
        try:
            self._apply_env()
            cache = self.cache_path.get()
            self._append_log(f"Post (workers={self.post_workers.get()}, chunk={self.post_chunk.get()})")
            ns = NS(
                input=out, start=0, limit=0, save_every=1, dry_run=False,
                cache=cache, prefer_template=self.prefer_tpl.get(),
                use_template_only=self.use_tpl_only.get(),
                workers=self.post_workers.get(), chunk=self.post_chunk.get()
            )
            app_main.cmd_post(ns)
            self._append_log("Post done.")
            messagebox.showinfo(APP_NAME, "Completed.")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Post failed:\n{e}")

    def _do_all(self):
        # chạy tuần tự trong 1 thread nền để không block UI
        self._do_analyze()
        self._do_scan()
        self._do_post()

def main():
    Path(ROOT / "logs").mkdir(parents=True, exist_ok=True)
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
