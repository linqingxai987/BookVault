#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BookVault 7.9 - 完美居中版

修复内容：
  - 编辑书签的弹窗（EditBookmarkDialog）现在会自动计算主窗口的中心位置，并居中显示。
  - 增加了屏幕边缘越界保护，确保弹窗永远不会跑到屏幕外。
"""

import os
import sys
import json
import uuid
import copy
import shutil
import webbrowser
import ctypes
import traceback
from pathlib import Path
from datetime import datetime
from html.parser import HTMLParser

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import tkinter.font as tkfont

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.exceptions import InvalidTag
except ImportError:
    try:
        _r = tk.Tk()
        _r.withdraw()
        messagebox.showerror("错误", "缺少加密库，请执行：pip install cryptography")
        _r.destroy()
    except Exception:
        print("缺少加密库，请执行：pip install cryptography", file=sys.stderr)
    sys.exit(1)

# ==================== 全局异常捕获 ====================
def exception_handler(exc_type, exc_value, exc_traceback):
    err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    try:
        with open("crash.log", "w", encoding="utf-8") as f:
            f.write(err_msg)
    except Exception:
        pass
    try:
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("程序崩溃", f"发生致命错误：\n{exc_value}\n\n详细信息已保存在 crash.log 中。")
        r.destroy()
    except Exception:
        print(err_msg, file=sys.stderr)
    sys.exit(1)

sys.excepthook = exception_handler

# ==================== HTML 书签解析器 ====================
class NetscapeBookmarkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = {"id": str(uuid.uuid4()), "type": "folder", "name": "导入的书签", "children": []}
        self.stack = [self.root]
        self.state = None
        self._current_name = ""
        self._current_href = ""
        self.bm_count = 0
        self.folder_count = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "h3":
            self.state = "h3"
            self._current_name = ""
        elif tag == "a":
            self.state = "a"
            self._current_name = ""
            self._current_href = dict(attrs).get("href", "")
        elif tag == "dl":
            if self.state == "h3_done":
                new_folder = {"id": str(uuid.uuid4()), "type": "folder", "name": self._current_name.strip(), "children": []}
                self.stack[-1]["children"].append(new_folder)
                self.stack.append(new_folder)
                self.folder_count += 1
                self.state = None

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "h3":
            self.state = "h3_done"
        elif tag == "a":
            self.state = None
            name = self._current_name.strip() or self._current_href
            if name:
                bm = {"id": str(uuid.uuid4()), "type": "bookmark", "name": name, "url": self._current_href}
                self.stack[-1]["children"].append(bm)
                self.bm_count += 1
        elif tag == "dl":
            if len(self.stack) > 1:
                self.stack.pop()

    def handle_data(self, data):
        if self.state in ("h3", "a"):
            self._current_name += data

# ==================== 常量 ====================
MAGIC = b"BVLT3"
SALT_LEN = 16
NONCE_LEN = 12
KDF_ITERATIONS = 600_000
GCM_TAG_LEN = 16
MIN_BLOB_LEN = len(MAGIC) + SALT_LEN + NONCE_LEN + GCM_TAG_LEN

# ==================== 主题管理器 ====================
class ThemeManager:
    LIGHT = {
        "bg": "#F0F0F0", "fg": "#000000", "panel_bg": "#FFFFFF", "entry_bg": "#FFFFFF",
        "entry_fg": "#000000", "tree_bg": "#FFFFFF", "tree_fg": "#000000",
        "select_bg": "#0078D7", "select_fg": "#FFFFFF", "status_bg": "#E5E5E5",
        "status_fg": "#606060", "btn_bg": "#E1E1E1", "btn_fg": "#000000",
        "accent": "#0078D7", "accent_fg": "#FFFFFF", "menu_bg": "#FFFFFF",
        "menu_fg": "#000000", "menu_active_bg": "#0078D7", "menu_active_fg": "#FFFFFF",
        "heading_bg": "#E1E1E1", "heading_fg": "#000000"
    }
    DARK = {
        "bg": "#1E1E1E", "fg": "#E0E0E0", "panel_bg": "#2D2D2D", "entry_bg": "#3C3C3C",
        "entry_fg": "#FFFFFF", "tree_bg": "#1E1E1E", "tree_fg": "#E0E0E0",
        "select_bg": "#005A9E", "select_fg": "#FFFFFF", "status_bg": "#111111",
        "status_fg": "#A0A0A0", "btn_bg": "#3C3C3C", "btn_fg": "#E0E0E0",
        "accent": "#0078D7", "accent_fg": "#FFFFFF", "menu_bg": "#2D2D2D",
        "menu_fg": "#E0E0E0", "menu_active_bg": "#005A9E", "menu_active_fg": "#FFFFFF",
        "heading_bg": "#2D2D2D", "heading_fg": "#E0E0E0"
    }

# ==================== 工具与驱动 ====================
def _init_process_dpi():
    try:
        ctypes.windll.shcore.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

_init_process_dpi()

def _apply_tk_scaling(root):
    try:
        dpi = root.winfo_fpixels("1i")
        root.tk.call("tk", "scaling", dpi / 72.0)
        return min(dpi / 96.0, 1.25)
    except Exception:
        return 1.0

def _pick_font(root, candidates):
    try:
        available = set(tkfont.families(root))
    except Exception:
        return "TkDefaultFont"
    for name in candidates:
        if name in available:
            return name
    return "TkDefaultFont"

# ==================== 加密存储 ====================
def derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=KDF_ITERATIONS)
    return kdf.derive(password.encode("utf-8"))

def data_path() -> Path:
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parent
    return base_dir / "bookmarks.vault"

class VaultLock:
    def __init__(self, vault_path: Path):
        self.lock_path = vault_path.with_suffix(vault_path.suffix + ".lock")
        self.fh = None

    def acquire(self):
        try: self.fh = open(self.lock_path, "a+")
        except OSError as e: raise RuntimeError(f"无法创建锁文件：{e}") from e
        try:
            self.fh.seek(0, os.SEEK_END)
            if self.fh.tell() == 0:
                self.fh.write("L"); self.fh.flush()
            self.fh.seek(0)
            if sys.platform == "win32":
                import msvcrt; msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl; fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            try: self.fh.close()
            except Exception: pass
            self.fh = None
            raise RuntimeError("另一个 BookVault 实例正在运行") from e

    def release(self):
        if not self.fh: return
        try:
            if sys.platform == "win32":
                import msvcrt; msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl; fcntl.flock(self.fh, fcntl.LOCK_UN)
        except Exception: pass
        try: self.fh.close()
        except Exception: pass
        self.fh = None

class Vault:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.key = None
        self.salt = None
        self.data = None

    def exists(self) -> bool:
        return self.path.is_file()

    def create(self, password: str) -> None:
        salt = os.urandom(SALT_LEN)
        key = derive_key(password, salt)
        data = [{"id": str(uuid.uuid4()), "type": "folder", "name": "常用书签", "children": []}]
        old = (self.salt, self.key, self.data)
        self.salt, self.key, self.data = salt, key, data
        try: self.save()
        except Exception:
            self.salt, self.key, self.data = old; raise

    def unlock(self, password: str) -> None:
        blob = self.path.read_bytes()
        if len(blob) < MIN_BLOB_LEN: raise ValueError("数据损坏或格式不对")
        if not blob.startswith(MAGIC): raise ValueError("数据格式错误")

        off = len(MAGIC)
        salt = blob[off:off + SALT_LEN]; off += SALT_LEN
        nonce = blob[off:off + NONCE_LEN]; off += NONCE_LEN
        ciphertext = blob[off:]

        key = derive_key(password, salt)
        try: plaintext = AESGCM(key).decrypt(nonce, ciphertext, MAGIC + salt)
        except InvalidTag: raise ValueError("密码错误或文件被损坏")
        try: data = json.loads(plaintext.decode("utf-8"))
        except (ValueError, UnicodeDecodeError): raise ValueError("数据内容损坏")
        if not isinstance(data, list): raise ValueError("数据结构不正确")

        self.salt, self.key = salt, key
        self.data = data

    def save(self) -> None:
        if not self.key: raise RuntimeError("保险库未解锁")
        plaintext = json.dumps(self.data, ensure_ascii=False).encode("utf-8")
        nonce = os.urandom(NONCE_LEN)
        ciphertext = AESGCM(self.key).encrypt(nonce, plaintext, MAGIC + self.salt)
        blob = MAGIC + self.salt + nonce + ciphertext

        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        bak = self.path.with_suffix(self.path.suffix + ".bak")

        try:
            if self.path.is_file():
                try: shutil.copy2(self.path, bak)
                except OSError: pass
            with open(tmp, "wb") as f:
                f.write(blob); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except OSError as e:
            try:
                if tmp.is_file(): tmp.unlink()
            except OSError: pass
            raise RuntimeError(f"保存失败：{e}") from e

# ==================== 编辑书签弹窗 ====================
class EditBookmarkDialog(tk.Toplevel):
    def __init__(self, app, bookmark, on_save):
        super().__init__(app.root)
        self.app = app
        self.bookmark = bookmark
        self.on_save = on_save
        
        self.title("编辑书签")
        self.transient(app.root)
        self.grab_set()
        
        theme = ThemeManager.DARK if app.is_dark_mode else ThemeManager.LIGHT
        self.configure(bg=theme["bg"])
        self.scale = app.scale
        
        w, h = int(480 * self.scale), int(280 * self.scale)
        
        # 【修复】自动计算居中位置
        main_x = app.root.winfo_x()
        main_y = app.root.winfo_y()
        main_w = app.root.winfo_width()
        main_h = app.root.winfo_height()
        
        x = main_x + (main_w - w) // 2
        y = main_y + (main_h - h) // 2
        
        # 防止越界
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = max(0, min(x, screen_w - w))
        y = max(0, min(y, screen_h - h))

        self.geometry(f"{w}x{h}+{x}+{y}")
        self.resizable(False, False)
        
        def f(size, bold=False):
            return ("Microsoft YaHei UI", max(8, int(round(size * self.scale))), "bold" if bold else "normal")
        
        style = ttk.Style()
        style.configure("Dialog.TLabel", background=theme["bg"], foreground=theme["fg"], font=f(10))
        
        main = ttk.Frame(self, padding=20)
        main.pack(fill="both", expand=True)
        
        main.columnconfigure(1, weight=1)
        
        ttk.Label(main, text="标题:", style="Dialog.TLabel").grid(row=0, column=0, sticky="e", padx=(0, 10), pady=12)
        self.name_var = tk.StringVar(value=bookmark.get("name", ""))
        ttk.Entry(main, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", pady=12)
        
        ttk.Label(main, text="网址:", style="Dialog.TLabel").grid(row=1, column=0, sticky="e", padx=(0, 10), pady=12)
        self.url_var = tk.StringVar(value=bookmark.get("url", ""))
        ttk.Entry(main, textvariable=self.url_var).grid(row=1, column=1, sticky="ew", pady=12)
        
        ttk.Label(main, text="图标:", style="Dialog.TLabel").grid(row=2, column=0, sticky="e", padx=(0, 10), pady=12)
        icon_frame = ttk.Frame(main)
        icon_frame.grid(row=2, column=1, sticky="w", pady=12)
        
        self.icon_label = ttk.Label(icon_frame, text="默认" if not bookmark.get("icon") else "已自定义", foreground=theme["status_fg"], style="Dialog.TLabel")
        self.icon_label.pack(side="left", padx=(0, 10))
        ttk.Button(icon_frame, text="选择本地图标", command=self.choose_icon).pack(side="left")
        
        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=(20, 0))
        ttk.Button(btn_frame, text="保存修改", style="Accent.TButton", command=self.save).pack(side="left", padx=10)
        ttk.Button(btn_frame, text="打开网站", command=lambda: self.app.open_url(self.url_var.get())).pack(side="left", padx=10)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side="left", padx=10)

    def choose_icon(self):
        filepath = filedialog.askopenfilename(
            title="选择本地图标 (仅支持 PNG/GIF)",
            filetypes=[("图片文件", "*.png *.gif")],
            parent=self
        )
        if filepath:
            self.bookmark["icon"] = str(Path(filepath).resolve())
            self.icon_label.config(text="已自定义", foreground="green")

    def save(self):
        name = self.name_var.get().strip()
        url = self.url_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "标题不能为空", parent=self)
            return
        self.bookmark["name"] = name
        self.bookmark["url"] = url
        self.on_save()
        self.destroy()

# ==================== 主界面 ====================
class App:
    def __init__(self, root: tk.Tk, vault: Vault):
        self.root = root
        self.vault = vault
        self.current_folder_id = None
        self.current_bm_id = None
        self.folder_map = {}
        self.bookmark_map = {}
        
        self._status_after = None
        self._image_cache = {}
        
        self._drag_item = None
        self._drag_start_y = 0
        self._last_drag_target = None
        self._last_highlighted = None
        self._initialized = False
        
        self.is_dark_mode = False
        self.load_settings()

        self.root.title("BookVault 7.9 - 本地加密书签")
        self.scale = _apply_tk_scaling(root)
        self.family_ui = _pick_font(root, ["Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "TkDefaultFont"])

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        win_w = max(int(1000 * self.scale), int(screen_w * 0.65))
        win_h = max(int(650 * self.scale), int(screen_h * 0.65))
        self.root.minsize(int(850 * self.scale), int(500 * self.scale))

        x = max(0, (screen_w - win_w) // 2)
        y = max(0, (screen_h - win_h) // 2)
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        self.build_ui()
        self.apply_theme_colors()
        self.refresh_left_tree()
        
        children = self.root_folder_children()
        if children:
            first_id = children[0]["id"]
            self.tree.selection_set(first_id)
            self.tree.see(first_id)

    def _get_settings_path(self):
        return self.vault.path.with_suffix(".settings.json")

    def load_settings(self):
        path = self._get_settings_path()
        if path.is_file():
            try:
                data = json.loads(path.read_text("utf-8"))
                self.is_dark_mode = data.get("is_dark", False)
            except Exception: pass

    def save_settings(self):
        try:
            self._get_settings_path().write_text(json.dumps({"is_dark": self.is_dark_mode}), "utf-8")
        except Exception: pass

    def toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode
        self.theme_btn.config(text="☀️ 日间" if self.is_dark_mode else "🌙 夜间")
        self.apply_theme_colors()
        self.save_settings()
        self.refresh_left_tree()

    def apply_theme_colors(self):
        theme = ThemeManager.DARK if self.is_dark_mode else ThemeManager.LIGHT
        self.root.configure(bg=theme["bg"])
        
        style = ttk.Style()
        try: style.theme_use("clam")
        except tk.TclError: pass

        def f(size, bold=False):
            return (self.family_ui, max(8, int(round(size * self.scale))), "bold" if bold else "normal")

        self.root.option_add("*Font", f(10))

        style.configure(".", background=theme["bg"], foreground=theme["fg"])
        
        style.configure("Treeview", font=f(11), rowheight=max(40, int(round(42 * self.scale))),
                        background=theme["tree_bg"], fieldbackground=theme["tree_bg"], foreground=theme["tree_fg"],
                        borderwidth=1, relief="solid")
        style.map("Treeview",
                  background=[("selected", theme["select_bg"])],
                  foreground=[("selected", theme["select_fg"])])
        
        style.configure("Treeview.Heading", font=f(10, True), background=theme["heading_bg"], foreground=theme["heading_fg"])
        
        style.configure("TButton", font=f(9), padding=max(2, int(round(3 * self.scale))),
                        background=theme["btn_bg"], foreground=theme["btn_fg"], borderwidth=1)
        style.map("TButton",
                  background=[("active", theme["select_bg"] if self.is_dark_mode else "#E5F1FB")],
                  foreground=[("active", theme["select_fg"] if self.is_dark_mode else theme["fg"])])
                  
        style.configure("Accent.TButton", foreground=theme["accent_fg"], background=theme["accent"], font=f(9, True))
        style.map("Accent.TButton",
                  background=[("active", "#005A9E"), ("pressed", "#004578"), ("disabled", "#A0A0A0")])
                  
        style.configure("TLabel", font=f(10), background=theme["bg"], foreground=theme["fg"])
        style.configure("TEntry", font=f(10), padding=max(2, int(round(3 * self.scale))),
                        fieldbackground=theme["entry_bg"], foreground=theme["entry_fg"], insertcolor=theme["fg"])
        style.configure("Status.TLabel", font=f(9), background=theme["status_bg"], foreground=theme["status_fg"])
        style.configure("TPanedwindow", background=theme["bg"])
        
        if hasattr(self, "context_menu_tree"):
            self.context_menu_tree.config(bg=theme["menu_bg"], fg=theme["menu_fg"], activebackground=theme["menu_active_bg"], activeforeground=theme["menu_active_fg"], borderwidth=0, font=f(10))
        if hasattr(self, "context_menu_bookmark"):
            self.context_menu_bookmark.config(bg=theme["menu_bg"], fg=theme["menu_fg"], activebackground=theme["menu_active_bg"], activeforeground=theme["menu_active_fg"], borderwidth=0, font=f(10))

    def _create_folder_icon(self, color):
        img = tk.PhotoImage(width=24, height=24)
        img.put(color, to=(2, 2, 22, 22))
        return img

    def _create_bookmark_icon(self, color):
        img = tk.PhotoImage(width=24, height=24)
        img.put(color, to=(6, 2, 18, 22))
        return img

    def build_ui(self):
        self.icon_root_folder = self._create_folder_icon("#1976D2")
        self.icon_sub_folder = self._create_folder_icon("#64B5F6")
        self.icon_bookmark = self._create_bookmark_icon("#FFB900")

        toolbar = ttk.Frame(self.root, padding=(5, 5, 5, 5))
        toolbar.pack(fill="x")

        ttk.Button(toolbar, text="📁 新建文件夹", command=self.add_folder).pack(side="left", padx=2)
        ttk.Button(toolbar, text="✏️ 重命名文件夹", command=self.rename_folder).pack(side="left", padx=2)
        ttk.Button(toolbar, text="🔗 新建书签", command=self.add_bookmark).pack(side="left", padx=2)
        
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=5)
        ttk.Button(toolbar, text="📥 导入 HTML 书签", command=self.import_html).pack(side="left", padx=2)
        ttk.Button(toolbar, text="🔠 书签排序", command=self.sort_bookmarks).pack(side="left", padx=2)

        self.theme_btn = ttk.Button(toolbar, text="🌙 夜间" if not self.is_dark_mode else "☀️ 日间", command=self.toggle_theme)
        self.theme_btn.pack(side="right", padx=2)

        ttk.Button(toolbar, text="🔒 锁定退出", command=self.on_close).pack(side="right", padx=2)
        ttk.Button(toolbar, text="🔑 修改密码", command=self.change_password).pack(side="right", padx=2)

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self.refresh_right_list())
        search_frame = ttk.Frame(toolbar)
        search_frame.pack(side="right", padx=(5, 10))
        ttk.Label(search_frame, text="搜索书签:").pack(side="left")
        ttk.Entry(search_frame, textvariable=self.search_var, width=15).pack(side="left", padx=(2, 0))

        status_bar = ttk.Frame(self.root)
        status_bar.pack(side="bottom", fill="x")
        
        self.status_var = tk.StringVar()
        ttk.Label(status_bar, textvariable=self.status_var, anchor="w", style="Status.TLabel").pack(side="left", fill="x", expand=True, padx=5, pady=2)
        
        try:
            ctime = os.path.getctime(self.vault.path)
            date_str = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M")
        except Exception:
            date_str = "未知"
        
        ttk.Label(status_bar, text=f"创建时间: {date_str}", anchor="e", style="Status.TLabel").pack(side="right", padx=10, pady=2)

        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        # ================= 左侧：树 =================
        left_frame = ttk.Frame(paned)
        
        self.tree = ttk.Treeview(left_frame, show="tree", selectmode="browse")
        tree_scroll = ttk.Scrollbar(left_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        self.tree.tag_configure("drag_in", background="#A8D1E7", foreground="black")
        self.tree.tag_configure("drag_before", background="#FFF2CC", foreground="black")
        self.tree.tag_configure("drag_after", background="#FFF2CC", foreground="black")

        self.tree.bind("<ButtonRelease-1>", self.on_tree_click)
        self.tree.bind("<Button-1>", self._on_tree_click, add="+")
        self.tree.bind("<Double-1>", self.on_tree_double_click)
        
        self.tree.bind("<ButtonPress-1>", self._on_drag_start, add="+")
        self.tree.bind("<B1-Motion>", self._on_drag_motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self._on_drag_drop, add="+")
        
        self.context_menu_tree = tk.Menu(self.root, tearoff=0)
        self.context_menu_tree.add_command(label="新建子文件夹", command=self.add_folder)
        self.context_menu_tree.add_command(label="重命名", command=self.rename_node)
        self.context_menu_tree.add_command(label="删除", command=self.delete_node)
        
        self.tree.bind("<Button-3>", self.show_tree_menu)
        paned.add(left_frame, weight=1)

        # ================= 右侧：列表 =================
        right_frame = ttk.Frame(paned)
        
        columns = ("name", "url")
        self.bookmark_tree = ttk.Treeview(right_frame, columns=columns, show="headings", selectmode="browse")
        self.bookmark_tree.heading("name", text="名称")
        self.bookmark_tree.heading("url", text="网址")
        self.bookmark_tree.column("name", width=150, minwidth=100)
        self.bookmark_tree.column("url", width=350, minwidth=150)
        
        bm_scroll = ttk.Scrollbar(right_frame, orient="vertical", command=self.bookmark_tree.yview)
        self.bookmark_tree.configure(yscrollcommand=bm_scroll.set)
        self.bookmark_tree.pack(side="left", fill="both", expand=True)
        bm_scroll.pack(side="right", fill="y")

        self.bookmark_tree.bind("<ButtonRelease-1>", self.on_bm_click)
        self.bookmark_tree.bind("<Double-1>", self.on_bm_list_double_click)
        
        self.bookmark_tree.bind("<ButtonPress-1>", self._on_drag_start, add="+")
        self.bookmark_tree.bind("<B1-Motion>", self._on_drag_motion, add="+")
        self.bookmark_tree.bind("<ButtonRelease-1>", self._on_drag_drop, add="+")
        
        self.context_menu_bookmark = tk.Menu(self.root, tearoff=0)
        self.context_menu_bookmark.add_command(label="编辑", command=self.edit_selected_bookmark)
        self.context_menu_bookmark.add_command(label="打开网站", command=self.open_selected_bookmark)
        self.context_menu_bookmark.add_separator()
        self.context_menu_bookmark.add_command(label="删除", command=self.delete_selected_bookmark)
        
        self.bookmark_tree.bind("<Button-3>", self.show_bookmark_menu)
        paned.add(right_frame, weight=3)

    def root_folder_children(self):
        return self.vault.data

    def set_status(self, text, timeout=3000):
        if self._status_after:
            try: self.root.after_cancel(self._status_after)
            except Exception: pass
            self._status_after = None
        self.status_var.set(text)
        if timeout:
            self._status_after = self.root.after(timeout, self._clear_status)

    def _clear_status(self):
        self.status_var.set("")
        self._status_after = None

    def _on_tree_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            self.current_folder_id = None
            self.current_bm_id = None
            self.tree.selection_remove(self.tree.selection())
            self.refresh_right_list()

    def on_tree_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if not item_id: return
        
        item = self.folder_map.get(item_id)
        if item:
            self.current_folder_id = item_id
            self.current_bm_id = None
            self.refresh_right_list()
            return
            
        item = self.bookmark_map.get(item_id)
        if item:
            parent_id = self.tree.parent(item_id)
            self.current_folder_id = parent_id if parent_id else None
            self.current_bm_id = item_id
            self.refresh_right_list()

    def on_bm_click(self, event):
        item_id = self.bookmark_tree.identify_row(event.y)
        if not item_id: return
        
        self.current_bm_id = item_id
        if self.tree.exists(item_id):
            self.tree.selection_set(item_id)
            self.tree.see(item_id)

    def on_tree_double_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if not item_id: return
        
        item = self.folder_map.get(item_id) or self.bookmark_map.get(item_id)
        
        if item and item.get("type") == "bookmark":
            self.edit_bookmark(item)
            return "break"
        elif item and item.get("type") == "folder":
            self.rename_folder()
            return "break"

    def on_bm_list_double_click(self, event):
        item_id = self.bookmark_tree.identify_row(event.y)
        if not item_id: return
        
        self.bookmark_tree.selection_set(item_id)
        item = self.bookmark_map.get(item_id)
        if item:
            self.edit_bookmark(item)
        return "break"

    def _on_drag_start(self, event):
        widget = event.widget
        self._drag_item = widget.identify_row(event.y)
        self._drag_start_y = event.y
        self._last_drag_target = None
        self._last_highlighted = None
        self._drag_source_widget = widget

    def _update_drag_visual(self, target_id, mode):
        if self._last_drag_target == (target_id, mode): return
        self._last_drag_target = (target_id, mode)

        if self._last_highlighted:
            try:
                if self._last_highlighted[0] == 'tree':
                    self.tree.item(self._last_highlighted[1], tags=())
                else:
                    self.bookmark_tree.item(self._last_highlighted[1], tags=())
            except Exception:
                pass

        self._last_highlighted = None

        if target_id and mode:
            tag_map = {"in": "drag_in", "before": "drag_before", "after": "drag_after"}
            tag = tag_map.get(mode)
            if tag:
                if self._drag_source_widget == self.tree or self.root.winfo_containing(event_x := self.root.winfo_pointerx(), event_y := self.root.winfo_pointery()) == self.tree:
                    self.tree.item(target_id, tags=(tag,))
                    self._last_highlighted = ('tree', target_id)
                else:
                    self.bookmark_tree.item(target_id, tags=(tag,))
                    self._last_highlighted = ('bm', target_id)

    def _on_drag_motion(self, event):
        if not self._drag_item: return
        if abs(event.y - self._drag_start_y) < 10: return

        self.tree.config(cursor="fleur")
        self.bookmark_tree.config(cursor="fleur")

        tree_height = event.widget.winfo_height()
        if event.y < 20:
            event.widget.yview_scroll(-1, "units")
        elif event.y > tree_height - 20:
            event.widget.yview_scroll(1, "units")

        x, y = self.root.winfo_pointerxy()
        target_widget = self.root.winfo_containing(x, y)
        
        if target_widget == self.tree:
            tree_y = self.tree.winfo_pointery() - self.tree.winfo_rooty()
            target_id = self.tree.identify_row(tree_y)
            
            if not target_id:
                self._update_drag_visual(None, None)
                self.set_status("移到根目录最下方", timeout=0)
                return

            bbox = self.tree.bbox(target_id)
            if not bbox: return
            _, ty, _, th = bbox
            ratio = (tree_y - ty) / th
            target_item = self.folder_map.get(target_id) or self.bookmark_map.get(target_id)

            if target_item and target_item.get("type") == "folder":
                if 0.3 <= ratio <= 0.7:
                    self.set_status(f"放入文件夹: {target_item['name']}", timeout=0)
                    self._update_drag_visual(target_id, "in")
                    return
            if ratio < 0.5:
                self.set_status(f"插入到前面", timeout=0)
                self._update_drag_visual(target_id, "before")
            else:
                self.set_status(f"插入到后面", timeout=0)
                self._update_drag_visual(target_id, "after")
        
        elif target_widget == self.bookmark_tree and self._drag_source_widget == self.bookmark_tree:
            bm_y = self.bookmark_tree.winfo_pointery() - self.bookmark_tree.winfo_rooty()
            target_id = self.bookmark_tree.identify_row(bm_y)
            
            if not target_id:
                self._update_drag_visual(None, None)
                self.set_status("移到最下方", timeout=0)
                return

            bbox = self.bookmark_tree.bbox(target_id)
            if not bbox: return
            _, ty, _, th = bbox
            ratio = (bm_y - ty) / th
            target_item = self.bookmark_map.get(target_id)

            if target_item:
                if ratio < 0.5:
                    self.set_status(f"插入到前面: {target_item['name']}", timeout=0)
                    self._update_drag_visual(target_id, "before")
                else:
                    self.set_status(f"插入到后面: {target_item['name']}", timeout=0)
                    self._update_drag_visual(target_id, "after")

    def _on_drag_drop(self, event):
        self.tree.config(cursor="")
        self.bookmark_tree.config(cursor="")
        self._update_drag_visual(None, None)
        self._clear_status()

        if not self._drag_item: return
        if abs(event.y - self._drag_start_y) < 10:
            self._drag_item = None
            return

        x, y = self.root.winfo_pointerxy()
        target_widget = self.root.winfo_containing(x, y)
        
        drop_list = None
        drop_target_id = None
        drop_position = "last"
        need_refresh = False

        if target_widget == self.tree:
            tree_y = self.tree.winfo_pointery() - self.tree.winfo_rooty()
            target_folder_id = self.tree.identify_row(tree_y)
            
            if not target_folder_id:
                drop_list = self.vault.data
                drop_position = "last"
                need_refresh = True
            else:
                bbox = self.tree.bbox(target_folder_id)
                if bbox:
                    _, ty, _, th = bbox
                    ratio = (tree_y - ty) / th
                    
                    if 0.3 <= ratio <= 0.7:
                        target_item = self.folder_map.get(target_folder_id)
                        if target_item and target_item.get("type") == "folder":
                            drop_list = target_item.setdefault("children", [])
                            drop_position = "last"
                            need_refresh = True
                    else:
                        parent_id = self.tree.parent(target_folder_id)
                        if not parent_id:
                            drop_list = self.vault.data
                        else:
                            parent_item = self.folder_map.get(parent_id)
                            if parent_item: drop_list = parent_item.setdefault("children", [])
                            
                        drop_target_id = target_folder_id
                        drop_position = "before" if ratio < 0.5 else "after"
                        need_refresh = True
                    
        elif target_widget == self.bookmark_tree and self._drag_source_widget == self.bookmark_tree:
            bm_y = self.bookmark_tree.winfo_pointery() - self.bookmark_tree.winfo_rooty()
            target_bm_id = self.bookmark_tree.identify_row(bm_y)
            
            folder = self.folder_map.get(self.current_folder_id)
            if folder:
                if not target_bm_id:
                    drop_list = folder.get("children", [])
                    drop_position = "last"
                    need_refresh = True
                else:
                    bbox = self.bookmark_tree.bbox(target_bm_id)
                    if bbox:
                        _, ty, _, th = bbox
                        ratio = (bm_y - ty) / th
                        drop_list = folder.get("children", [])
                        drop_target_id = target_bm_id
                        drop_position = "before" if ratio < 0.5 else "after"
                        need_refresh = True

        if need_refresh and drop_list is not None:
            if target_widget == self.tree and drop_target_id and self._drag_source_widget == self.tree:
                curr = drop_target_id
                while curr:
                    if curr == self._drag_item:
                        self.set_status("无法将文件夹移入其自身的子文件夹中")
                        self._drag_item = None
                        return
                    curr = self.tree.parent(curr)

            def do():
                node = self._extract_node(self.vault.data, self._drag_item)
                if not node: raise RuntimeError("找不到节点")

                if drop_position == "last":
                    drop_list.append(node)
                else:
                    idx = len(drop_list)
                    for i, x in enumerate(drop_list):
                        if x["id"] == drop_target_id:
                            idx = i
                            if drop_position == "after": idx += 1
                            break
                    drop_list.insert(idx, node)

            if self._mutate(do):
                self.set_status("移动成功")
                self.refresh_left_tree()
                if target_widget == self.tree:
                    self.tree.selection_set(self._drag_item)
                else:
                    self.bookmark_tree.selection_set(self._drag_item)
                
        self._drag_item = None

    def refresh_left_tree(self):
        open_ids = set()
        for iid in self.tree.get_children(""):
            self._record_open_state(iid, open_ids)
            
        self.tree.delete(*self.tree.get_children())
        self.folder_map.clear()
        self.bookmark_map.clear()
        
        first_load = not self._initialized
        
        def render_tree(parent_node, data_list, depth=0):
            for item in data_list:
                if item.get("type") == "folder":
                    self.folder_map[item["id"]] = item
                    
                    is_open = item["id"] in open_ids
                    if first_load and depth == 0:
                        is_open = True
                        
                    img = self.icon_root_folder if depth == 0 else self.icon_sub_folder
                    node = self.tree.insert(parent_node, "end", iid=item["id"], text=" " + item["name"], image=img, open=is_open)
                    render_tree(node, item.get("children", []), depth + 1)
                elif item.get("type") == "bookmark":
                    self.bookmark_map[item["id"]] = item
                    self.tree.insert(parent_node, "end", iid=item["id"], text=" " + item["name"])
                    
        render_tree("", self.vault.data)
        self._initialized = True
        
        target_id = self.current_folder_id or self.current_bm_id
        if target_id and self.tree.exists(target_id):
            parent = self.tree.parent(target_id)
            while parent:
                self.tree.item(parent, open=True)
                parent = self.tree.parent(parent)
                
            self.tree.selection_set(target_id)
            self.tree.see(target_id)
            self.refresh_right_list()

    def _record_open_state(self, item_id, open_ids):
        if self.tree.item(item_id, "open"):
            open_ids.add(item_id)
        for child in self.tree.get_children(item_id):
            self._record_open_state(child, open_ids)

    def refresh_right_list(self):
        self.bookmark_tree.delete(*self.bookmark_tree.get_children())
        
        if not self.current_folder_id:
            return
            
        folder = self.folder_map.get(self.current_folder_id)
        if not folder:
            return
            
        query = self.search_var.get().strip().lower()
        children = folder.get("children", [])
        
        for bm in children:
            if bm.get("type") == "bookmark":
                if query:
                    if query not in bm.get("name", "").lower() and query not in bm.get("url", "").lower():
                        continue
                
                img = self.icon_bookmark
                icon_path = bm.get("icon", "")
                if icon_path and Path(icon_path).is_file():
                    if icon_path not in self._image_cache:
                        try:
                            temp_img = tk.PhotoImage(file=icon_path)
                            if temp_img.width() > 24 or temp_img.height() > 24:
                                sub = max(temp_img.width() // 16, temp_img.height() // 16, 1)
                                temp_img = temp_img.subsample(sub, sub)
                            self._image_cache[icon_path] = temp_img
                        except Exception:
                            self._image_cache[icon_path] = self.icon_bookmark
                    img = self._image_cache[icon_path]
                    
                self.bookmark_tree.insert("", "end", iid=bm["id"], text=" " + bm["name"], image=img, values=(bm["name"], bm.get("url", "")))
        
        if self.current_bm_id and self.bookmark_tree.exists(self.current_bm_id):
            self.bookmark_tree.selection_set(self.current_bm_id)
            self.bookmark_tree.see(self.current_bm_id)

    def show_tree_menu(self, event):
        item_id = self.tree.identify_row(event.y)
        if item_id:
            self.tree.selection_set(item_id)
            self.context_menu_tree.post(event.x_root, event.y_root)
            return "break"
        else:
            self.current_folder_id = None
            self.current_bm_id = None
            self.tree.selection_remove(self.tree.selection())
            self.refresh_right_list()
            
            theme = ThemeManager.DARK if self.is_dark_mode else ThemeManager.LIGHT
            root_menu = tk.Menu(self.root, tearoff=0)
            root_menu.config(bg=theme["menu_bg"], fg=theme["menu_fg"], activebackground=theme["menu_active_bg"], activeforeground=theme["menu_active_fg"], borderwidth=0, font=(self.family_ui, 10))
            root_menu.add_command(label="在根目录新建文件夹", command=self.add_folder)
            root_menu.post(event.x_root, event.y_root)
            return "break"

    def show_bookmark_menu(self, event):
        item_id = self.bookmark_tree.identify_row(event.y)
        if item_id:
            self.bookmark_tree.selection_set(item_id)
            self.context_menu_bookmark.post(event.x_root, event.y_root)

    def add_folder(self):
        folder = {"id": str(uuid.uuid4()), "type": "folder", "name": "新建文件夹", "children": []}
        
        def do():
            if self.current_folder_id:
                parent = self.folder_map.get(self.current_folder_id)
                if parent: parent.setdefault("children", []).append(folder)
                else: self.vault.data.append(folder)
            else:
                self.vault.data.append(folder)
                
        if self._mutate(do):
            self.current_folder_id = folder["id"]
            self.refresh_left_tree()
            self.tree.selection_set(folder["id"])
            self.tree.see(folder["id"])
            self.rename_folder()

    def add_bookmark(self):
        if not self.current_folder_id:
            messagebox.showinfo("提示", "请先在左侧选择一个文件夹")
            return
            
        bm = {"id": str(uuid.uuid4()), "type": "bookmark", "name": "新书签", "url": ""}
        
        def do():
            folder = self.folder_map.get(self.current_folder_id)
            if folder: folder.setdefault("children", []).append(bm)
            
        if self._mutate(do):
            self.current_bm_id = bm["id"]
            self.refresh_left_tree()
            self.tree.selection_set(bm["id"])
            self.tree.see(bm["id"])
            self.refresh_right_list()
            item = self.bookmark_map.get(bm["id"])
            if item: self.edit_bookmark(item)

    def rename_node(self):
        sel = self.tree.selection()
        if not sel: return
        node_id = sel[0]
        
        if node_id in self.folder_map:
            self.rename_folder()
        elif node_id in self.bookmark_map:
            item = self.bookmark_map.get(node_id)
            if item: self.edit_bookmark(item)

    def rename_folder(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在左侧选择一个文件夹", parent=self.root)
            return
            
        folder_id = sel[0]
        folder = self._find_folder_by_id(self.vault.data, folder_id)
        if not folder:
            messagebox.showerror("错误", "未找到该文件夹，请重试", parent=self.root)
            return
            
        new_name = simpledialog.askstring("重命名文件夹", "请输入新名称：", initialvalue=folder["name"], parent=self.root)
        if new_name is not None:
            new_name = new_name.strip()
            if not new_name:
                messagebox.showwarning("提示", "名称不能为空", parent=self.root)
                return
            if new_name != folder["name"]:
                def do(): folder["name"] = new_name
                if self._mutate(do):
                    self.refresh_left_tree()
                    self.set_status("重命名成功")

    def _find_folder_by_id(self, data_list, target_id):
        for item in data_list:
            if item["id"] == target_id:
                return item
            if item.get("type") == "folder":
                res = self._find_folder_by_id(item.get("children", []), target_id)
                if res:
                    return res
        return None

    def edit_bookmark(self, bookmark_item):
        def on_save():
            self._save_vault()
            self.refresh_left_tree()
            self.refresh_right_list()
            self.bookmark_tree.selection_set(bookmark_item["id"])
            self.bookmark_tree.see(bookmark_item["id"])
            
        EditBookmarkDialog(self, bookmark_item, on_save)

    def edit_selected_bookmark(self):
        bm_id = self.bookmark_tree.selection()
        if bm_id:
            item = self.bookmark_map.get(bm_id[0])
            if item: self.edit_bookmark(item)

    def delete_node(self):
        sel = self.tree.selection()
        if not sel: return
        
        target_id = sel[0]
        
        item_type = "文件夹" if target_id in self.folder_map else "书签"
        name = ""
        if target_id in self.folder_map: name = self.folder_map[target_id]["name"]
        elif target_id in self.bookmark_map: name = self.bookmark_map[target_id]["name"]
        
        if messagebox.askyesno("确认", f"确定删除 {item_type} '{name}' 吗？\n如果是文件夹，里面的内容也会被删除！"):
            def do(): self._remove_from(self.vault.data, target_id)
            if self._mutate(do):
                if target_id == self.current_folder_id:
                    self.current_folder_id = None
                if target_id == self.current_bm_id:
                    self.current_bm_id = None
                    
                self.refresh_left_tree()
                self.refresh_right_list()

    def delete_selected_bookmark(self):
        bm_id = self.bookmark_tree.selection()
        if not bm_id: return
        target_id = bm_id[0]
        item = self.bookmark_map.get(target_id)
        if not item: return
        
        if messagebox.askyesno("确认", f"确定删除书签 '{item['name']}' 吗？"):
            def do(): self._remove_from(self.vault.data, target_id)
            if self._mutate(do):
                self.current_bm_id = None
                self.refresh_left_tree()
                self.refresh_right_list()

    def open_selected_bookmark(self):
        bm_id = self.bookmark_tree.selection()
        if bm_id:
            item = self.bookmark_map.get(bm_id[0])
            if item: self.open_url(item.get("url", ""))

    def sort_bookmarks(self):
        if not self.current_folder_id: return
        folder = self.folder_map.get(self.current_folder_id)
        if not folder: return
        
        def do():
            folder["children"].sort(key=lambda x: (0 if x.get("type") == "folder" else 1, x.get("name", "").lower()))
            
        if self._mutate(do):
            self.refresh_left_tree()
            self.set_status("排序完成")

    def import_html(self):
        filepath = filedialog.askopenfilename(
            title="选择 HTML 书签文件",
            filetypes=[("HTML 文件", "*.html *.htm"), ("所有文件", "*.*")],
            parent=self.root
        )
        if not filepath: return

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                
            parser = NetscapeBookmarkParser()
            parser.feed(content)
            
            if not parser.root.get("children"):
                messagebox.showinfo("提示", "该 HTML 文件没有解析到任何书签。")
                return
                
            timestamp = datetime.now().strftime("%m-%d %H:%M")
            parser.root["name"] = f"导入的书签 {timestamp}"
            
            def do():
                self.vault.data.append(parser.root)
                
            if self._mutate(do):
                self.current_folder_id = parser.root["id"]
                self.refresh_left_tree()
                self.tree.selection_set(self.current_folder_id)
                self.tree.see(self.current_folder_id)
                self.refresh_right_list()
                
                messagebox.showinfo(
                    "导入成功", 
                    f"成功导入 {parser.folder_count} 个文件夹，{parser.bm_count} 个书签！",
                    parent=self.root
                )
        except Exception as e:
            messagebox.showerror("解析失败", f"无法读取或解析该 HTML 文件：\n{e}", parent=self.root)

    def _mutate(self, action):
        old_data = copy.deepcopy(self.vault.data)
        try: action()
        except Exception as e:
            self.vault.data = old_data
            self.refresh_left_tree()
            messagebox.showerror("操作失败", str(e))
            return False
        if not self._save_vault():
            self.vault.data = old_data
            self.refresh_left_tree()
            return False
        return True

    def _save_vault(self):
        try:
            self.vault.save()
            self.set_status("已自动保存")
            return True
        except Exception as e:
            messagebox.showerror("保存失败", f"无法保存数据：{e}")
            return False

    def _remove_from(self, data_list, target_id):
        for i, x in enumerate(data_list):
            if x["id"] == target_id:
                data_list.pop(i)
                return True
            if x.get("type") == "folder":
                if self._remove_from(x.get("children", []), target_id):
                    return True
        return False

    def _extract_node(self, data_list, target_id):
        for i, x in enumerate(data_list):
            if x["id"] == target_id:
                return data_list.pop(i)
            if x.get("type") == "folder":
                res = self._extract_node(x.get("children", []), target_id)
                if res: return res
        return None

    def open_url(self, url):
        if not url or not url.strip(): return
        url = url.strip()
        if not url.startswith(("http://", "https://")): url = "https://" + url
        try: webbrowser.open(url)
        except Exception as e: self.set_status(f"打开失败：{e}")

    def change_password(self):
        old = simpledialog.askstring("修改主密码", "请输入当前主密码:", show="*", parent=self.root)
        if old is None: return
        if derive_key(old, self.vault.salt) != self.vault.key:
            messagebox.showerror("错误", "当前主密码不正确"); return

        new = simpledialog.askstring("修改主密码", "请输入新主密码（至少8位）:", show="*", parent=self.root)
        if not new or len(new) < 8: return
        confirm = simpledialog.askstring("修改主密码", "请再次输入新主密码:", show="*", parent=self.root)
        if new != confirm:
            messagebox.showerror("错误", "两次输入不一致"); return

        new_salt = os.urandom(SALT_LEN)
        new_key = derive_key(new, new_salt)
        old_salt, old_key = self.vault.salt, self.vault.key
        self.vault.salt, self.vault.key = new_salt, new_key
        try:
            self.vault.save()
            self.set_status("主密码已修改")
        except Exception as e:
            self.vault.salt, self.vault.key = old_salt, old_key
            messagebox.showerror("保存失败", f"无法保存新密码：{e}")

    def on_close(self):
        self.vault.key = None
        self.vault.data = None
        self.root.destroy()

def show_login_window(vault: Vault):
    root = tk.Tk()
    root.title("BookVault 安全验证")
    scale = _apply_tk_scaling(root)

    win_w, win_h = int(620 * scale), int(480 * scale)
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    x, y = max(0, (screen_w - win_w) // 2), max(0, (screen_h - win_h) // 2)
    root.geometry(f"{win_w}x{win_h}+{x}+{y}")
    root.resizable(False, False)

    family_ui = _pick_font(root, ["Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "TkDefaultFont"])

    def f(size, bold=False):
        return (family_ui, max(8, int(round(size * scale))), "bold" if bold else "normal")

    root.configure(bg="#F0F0F0")
    style = ttk.Style()
    try: style.theme_use("clam")
    except tk.TclError: pass
    
    style.configure("TLabel", font=f(10), background="#F0F0F0", foreground="#000000", borderwidth=0)
    style.configure("TFrame", background="#F0F0F0", borderwidth=0)
    style.configure("Accent.TButton", foreground="white", background="#0078D7", font=f(9, True))
    style.map("Accent.TButton", background=[("active", "#005A9E"), ("pressed", "#004578"), ("disabled", "#A0A0A0")])
    style.configure("TEntry", font=f(10), padding=max(2, int(round(4 * scale))), fieldbackground="#FFFFFF")

    ttk.Label(root, text="BookVault 加密书签", font=f(18, True)).pack(pady=(int(30 * scale), int(10 * scale)))
    ttk.Label(root, text="🔒 采用 AES-256-GCM 高强度加密", font=f(9), foreground="#606060").pack(pady=(0, 10))
    
    ttk.Label(root, text="⚠️ 请牢记主密码，忘记密码将无法恢复数据！", font=f(9), foreground="#D32F2F", wraplength=int(550 * scale), justify="center").pack(pady=(0, 25))
    
    is_new = not vault.exists()

    form_frame = ttk.Frame(root)
    form_frame.pack(pady=5)

    row1 = ttk.Frame(form_frame)
    row1.grid(row=0, column=0, pady=5, sticky="ew")
    ttk.Label(row1, text="主密码:", width=8, anchor="e").grid(row=0, column=0, padx=(0, 5), sticky="e")
    
    pw_var = tk.StringVar()
    pw_entry = ttk.Entry(row1, textvariable=pw_var, show="*", width=22)
    pw_entry.grid(row=0, column=1, sticky="w")
    pw_entry.focus_set()

    def toggle_pw():
        if pw_entry.cget("show") == "*":
            pw_entry.config(show="")
            btn_eye_pw.config(text="🔒")
        else:
            pw_entry.config(show="*")
            btn_eye_pw.config(text="👁")

    btn_eye_pw = ttk.Button(row1, text="👁", width=3, command=toggle_pw)
    btn_eye_pw.grid(row=0, column=2, padx=(5, 0))

    if is_new:
        row2 = ttk.Frame(form_frame)
        row2.grid(row=1, column=0, pady=5, sticky="ew")
        ttk.Label(row2, text="确认密码:", width=8, anchor="e").grid(row=0, column=0, padx=(0, 5), sticky="e")
        
        confirm_var = tk.StringVar()
        confirm_entry = ttk.Entry(row2, textvariable=confirm_var, show="*", width=22)
        confirm_entry.grid(row=0, column=1, sticky="w")

        def toggle_confirm():
            if confirm_entry.cget("show") == "*":
                confirm_entry.config(show="")
                btn_eye_confirm.config(text="🔒")
            else:
                confirm_entry.config(show="*")
                btn_eye_confirm.config(text="👁")

        btn_eye_confirm = ttk.Button(row2, text="👁", width=3, command=toggle_confirm)
        btn_eye_confirm.grid(row=0, column=2, padx=(5, 0))

    status_label = ttk.Label(root, text="", foreground="#D32F2F", font=f(9))
    status_label.pack(pady=10)

    def do_login(event=None):
        pw = pw_var.get()
        if not pw: return
        status_label.config(text="")
        
        try:
            if not is_new:
                vault.unlock(pw)
                root.destroy()
            else:
                if len(pw) < 8:
                    status_label.config(text="密码不能少于8位")
                    return
                if pw != confirm_var.get():
                    status_label.config(text="两次输入的密码不一致，请重试")
                    return
                
                vault.create(pw)
                messagebox.showinfo("创建成功", "加密数据库已创建！", parent=root)
                root.destroy()
        except Exception as e:
            status_label.config(text=str(e))

    btn_text = "创建并解锁" if is_new else "解锁"
    btn_login = ttk.Button(root, text=btn_text, style="Accent.TButton", command=do_login)
    btn_login.pack(pady=10, ipadx=15, ipady=3)

    root.bind("<Return>", do_login)
    root.mainloop()

def main():
    path = data_path()
    lock = VaultLock(path)
    try: lock.acquire()
    except RuntimeError as e:
        try:
            r = tk.Tk(); r.withdraw(); messagebox.showerror("BookVault", str(e)); r.destroy()
        except Exception: print(str(e), file=sys.stderr)
        sys.exit(1)

    try:
        vault = Vault(path)
        show_login_window(vault)
        if vault.key:
            root = tk.Tk()
            App(root, vault)
            root.mainloop()
    finally:
        lock.release()

if __name__ == "__main__":
    main()