import os
import threading


def browse_dialog(dialog_type: str, title: str, initial_dir: str, filetypes: list) -> str:
    result = [""]

    def _run():
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            result[0] = "__unavailable__"
            return
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        start = initial_dir if initial_dir and os.path.exists(initial_dir) else os.path.expanduser("~")
        ft = [(f[0], f[1]) for f in filetypes] if filetypes else [("All", "*")]
        if dialog_type == "directory":
            result[0] = filedialog.askdirectory(title=title, initialdir=start) or ""
        elif dialog_type == "save":
            result[0] = filedialog.asksaveasfilename(
                title=title, initialdir=start, defaultextension=".yml", filetypes=ft
            ) or ""
        else:
            result[0] = filedialog.askopenfilename(title=title, initialdir=start, filetypes=ft) or ""
        root.destroy()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=120)
    return result[0]
