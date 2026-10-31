#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BookVault 3.2 - 高颜值 4K 适配版
修复：DPI缩放导致的窗口过小、字体错乱、主题未加载问题
"""

import os
import sys
import json
import uuid
import webbrowser
import ctypes
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.exceptions import InvalidTag
except ImportError:
    messagebox.showerror("错误", "缺少加密库，请执行：pip install cryptography")
    sys.exit(1)

# ==================== 4K 高分屏适配 ====================
try:
    # 告诉 Windows 这是一个 DPI 感知程序
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

MAGIC = b"BVLT3"
SALT_LEN = 16
NONCE_LEN = 12
KDF_ITERATIONS = 600_000

def derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=KDF_ITERATIONS)
    return kdf.derive(password.encode("utf-8"))

def data_path() -> Path:
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parent
    return base_dir / "bookmarks.vault"

# ==================== 全局 UI 主题配置 ====================
def apply_theme(root):
    """统一配置所有窗口的字体和颜色"""
    style = ttk.Style()
    style.theme_use("clam") # 强制使用 clam，这个主题在各平台都好看
    
    # 全局字体设置
    my_font = ("Microsoft YaHei UI", 12) # UI 版微软雅黑更紧凑
    root.option_add("*Font", my_font)
    
    # 树状图设置
    style.configure("Treeview", font=("Microsoft YaHei UI", 12), rowheight=40, background="#ffffff", fieldbackground="#ffffff")
    style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 12, "bold"))
    
    # 按钮设置
    style.configure("TButton", font=("Microsoft YaHei UI", 11), padding=8)
    # 蓝底白字的主按钮
    style.configure("Accent.TButton", foreground="white", background="#0078D7", font=("Microsoft YaHei UI", 11, "bold"))
    style.map("Accent.TButton", background=[("active", "#005A9E")])
    
    # 标签和输入框
    style.configure("TLabel", font=("Microsoft YaHei UI", 12))
    style.configure("TEntry", padding=8)

# ==================== 加密存储模块 ====================
class Vault:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.key = None
        self.salt = None
        self.data = None

    def exists(self) -> bool:
        return self.path.is_file()

    def create(self, password: str) -> None:
        self.salt = os.urandom(SALT_LEN)
        self.key = derive_key(password, self.salt)
        self.data = [{"id": str(uuid.uuid4()), "type": "folder", "name": "常用书签", "children": []}]
        self.save()

    def unlock(self, password: str) -> None:
        blob = self.path.read_bytes()
        if not blob.startswith(MAGIC):
            raise ValueError("数据文件格式不正确")
        
        off = len(MAGIC)
        salt = blob[off:off + SALT_LEN]
        off += SALT_LEN
        nonce = blob[off:off + NONCE_LEN]
        off += NONCE_LEN
        ciphertext = blob[off:]

        key = derive_key(password, salt)
        try:
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, MAGIC + salt)
        except InvalidTag:
            raise ValueError("密码错误或文件被损坏")

        self.salt, self.key = salt, key
        self.data = json.loads(plaintext.decode("utf-8"))

    def save(self) -> None:
        if not self.key: return
        plaintext = json.dumps(self.data, ensure_ascii=False).encode("utf-8")
        nonce = os.urandom(NONCE_LEN)
        ciphertext = AESGCM(self.key).encrypt(nonce, plaintext, MAGIC + self.salt)
        blob = MAGIC + self.salt + nonce + ciphertext
        self.path.write_bytes(blob)

# ==================== 主界面 ====================
class App:
    def __init__(self, root, vault):
        self.root = root
        self.vault = vault
        self.current_node_id = None
        self.node_map = {}

        self.root.title("BookVault 3.2 - 本地加密书签")
        
        # 动态居中并设置合理的窗口大小 (屏幕宽度的 70%)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        win_w, win_h = int(screen_w * 0.7), int(screen_h * 0.7)
        x, y = (screen_w - win_w) // 2, (screen_h - win_h) // 2
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")
        
        apply_theme(self.root)
        self.build_ui()
        self.refresh_tree()

    def build_ui(self):
        toolbar = ttk.Frame(self.root, padding=15)
        toolbar.pack(fill="x")
        
        ttk.Button(toolbar, text="📁 新建文件夹", command=self.add_folder).pack(side="left", padx=(0, 10))
        ttk.Button(toolbar, text="🔗 新建书签", command=self.add_bookmark).pack(side="left", padx=10)
        ttk.Button(toolbar, text="❌ 删除", command=self.delete_node).pack(side="left", padx=10)
        
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=20)
        ttk.Button(toolbar, text="🔠 一键按名称排序", command=self.sort_tree).pack(side="left", padx=10)
        
        ttk.Button(toolbar, text="🔒 锁定退出", command=self.lock_app).pack(side="right", padx=10)
        ttk.Button(toolbar, text="💾 保存修改", style="Accent.TButton", command=self.save_data).pack(side="right", padx=10)

        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        # 左侧树
        left_frame = ttk.Frame(paned)
        self.tree = ttk.Treeview(left_frame, show="tree", selectmode="browse")
        tree_scroll = ttk.Scrollbar(left_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<Button-3>", self.show_context_menu)
        paned.add(left_frame, weight=1)

        # 右侧详情
        right_frame = ttk.LabelFrame(paned, text=" 详细信息 ", padding=30)
        paned.add(right_frame, weight=1)

        form = ttk.Frame(right_frame)
        form.pack(fill="x", pady=20)

        ttk.Label(form, text="名称:").grid(row=0, column=0, sticky="w", pady=15)
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(form, textvariable=self.name_var)
        self.name_entry.grid(row=0, column=1, sticky="ew", padx=(20, 0), pady=15)

        ttk.Label(form, text="网址:").grid(row=1, column=0, sticky="w", pady=15)
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(form, textvariable=self.url_var)
        self.url_entry.grid(row=1, column=1, sticky="ew", padx=(20, 0), pady=15)
        form.columnconfigure(1, weight=1)

        btn_frame = ttk.Frame(right_frame)
        btn_frame.pack(fill="x", pady=(30, 0))
        ttk.Button(btn_frame, text="💾 保存更改", style="Accent.TButton", command=self.save_current_item).pack(side="left")
        ttk.Button(btn_frame, text="🌐 一键在浏览器打开", command=lambda: self.open_url(self.url_var.get())).pack(side="left", padx=20)

        self.context_menu = tk.Menu(self.root, tearoff=0, font=("Microsoft YaHei UI", 11))
        self.context_menu.add_command(label="新建文件夹", command=self.add_folder)
        self.context_menu.add_command(label="新建书签", command=self.add_bookmark)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="删除", command=self.delete_node)

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.node_map.clear()
        
        def render(parent_node, data_list):
            for item in data_list:
                self.node_map[item["id"]] = item
                if item["type"] == "folder":
                    node = self.tree.insert(parent_node, "end", iid=item["id"], text="📁 " + item["name"], open=True)
                    render(node, item.get("children", []))
                else:
                    self.tree.insert(parent_node, "end", iid=item["id"], text="🔖 " + item["name"])

        render("", self.vault.data)

    def on_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        self.current_node_id = sel[0]
        item = self.node_map.get(self.current_node_id)
        if not item: return

        self.name_var.set(item["name"])
        if item["type"] == "bookmark":
            self.url_var.set(item.get("url", ""))
            self.url_entry.config(state="normal")
        else:
            self.url_var.set("")
            self.url_entry.config(state="disabled")

    def on_double_click(self, event):
        sel = self.tree.selection()
        if not sel: return
        item = self.node_map.get(sel[0])
        if item and item["type"] == "bookmark":
            self.open_url(item.get("url", ""))

    def open_url(self, url):
        if not url or url.strip() == "": return
        url = url.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        webbrowser.open(url)

    def show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def get_target_folder(self):
        if not self.current_node_id: return self.vault.data
        item = self.node_map.get(self.current_node_id)
        if item["type"] == "folder":
            return item["children"]
        else:
            parent_id = self.tree.parent(self.current_node_id)
            return self.vault.data if not parent_id else self.node_map[parent_id]["children"]

    def add_folder(self):
        name = simpledialog.askstring("新建文件夹", "请输入文件夹名称:", parent=self.root)
        if not name or not name.strip(): return
        folder = {"id": str(uuid.uuid4()), "type": "folder", "name": name.strip(), "children": []}
        self.get_target_folder().append(folder)
        self.save_data()
        self.refresh_tree()

    def add_bookmark(self):
        name = simpledialog.askstring("新建书签", "请输入书签名称:", parent=self.root)
        if not name or not name.strip(): return
        url = simpledialog.askstring("新建书签", "请输入网址 (例如 www.baidu.com):", parent=self.root)
        if not url or not url.strip(): return
        
        bm = {"id": str(uuid.uuid4()), "type": "bookmark", "name": name.strip(), "url": url.strip()}
        self.get_target_folder().append(bm)
        self.save_data()
        self.refresh_tree()

    def save_current_item(self):
        if not self.current_node_id: return
        item = self.node_map[self.current_node_id]
        new_name = self.name_var.get().strip()
        if not new_name: return
            
        item["name"] = new_name
        if item["type"] == "bookmark":
            item["url"] = self.url_var.get().strip()
            
        self.save_data()
        self.refresh_tree()

    def delete_node(self):
        if not self.current_node_id: return
        item = self.node_map[self.current_node_id]
        if not messagebox.askyesno("确认删除", f"确定删除 '{item['name']}' 吗？\n如果是文件夹，里面的内容也会被删除！"):
            return
        
        def remove_item(data_list, target_id):
            for i, x in enumerate(data_list):
                if x["id"] == target_id:
                    data_list.pop(i)
                    return True
                if x["type"] == "folder":
                    if remove_item(x.get("children", []), target_id):
                        return True
            return False

        remove_item(self.vault.data, self.current_node_id)
        self.current_node_id = None
        self.name_var.set("")
        self.url_var.set("")
        self.save_data()
        self.refresh_tree()

    def sort_tree(self):
        def sort_data(data_list):
            data_list.sort(key=lambda x: (0 if x["type"] == "folder" else 1, x["name"].lower()))
            for item in data_list:
                if item["type"] == "folder":
                    sort_data(item["children"])
        
        sort_data(self.vault.data)
        self.save_data()
        self.refresh_tree()
        messagebox.showinfo("排序完成", "当前所有文件夹和书签已按名称整理完毕！")

    def save_data(self):
        self.vault.save()
        self.root.title("BookVault 3.2 - 已自动保存")

    def lock_app(self):
        self.vault.key = None
        self.root.destroy()

# ==================== 登录窗口 ====================
def show_login_window(vault):
    login_root = tk.Tk()
    login_root.title("BookVault 安全验证")
    
    # 放大登录窗口尺寸，并使其居中
    win_w, win_h = 600, 400
    screen_w, screen_h = login_root.winfo_screenwidth(), login_root.winfo_screenheight()
    x, y = (screen_w - win_w) // 2, (screen_h - win_h) // 2
    login_root.geometry(f"{win_w}x{win_h}+{x}+{y}")
    
    login_root.resizable(False, False)
    apply_theme(login_root) # 登录页也应用漂亮主题

    # 顶部大标题
    ttk.Label(login_root, text="🔒 BookVault 本地加密保险库", font=("Microsoft YaHei UI", 20, "bold")).pack(pady=(60, 30))
    
    frame = ttk.Frame(login_root)
    frame.pack(pady=10)
    
    ttk.Label(frame, text="主密码:").pack(side="left")
    pw_entry = ttk.Entry(frame, show="*", width=25)
    pw_entry.pack(side="left", padx=10)
    pw_entry.focus_set()

    status_label = ttk.Label(login_root, text="", foreground="red", font=("Microsoft YaHei UI", 10))
    status_label.pack(pady=10)

    def do_login():
        pw = pw_entry.get()
        if not pw: return
        try:
            if vault.exists():
                vault.unlock(pw)
            else:
                if len(pw) < 8:
                    status_label.config(text="首次创建密码不能少于8位")
                    return
                vault.create(pw)
                messagebox.showinfo("创建成功", "加密数据库已创建！\n请务必牢记主密码！", parent=login_root)
            login_root.destroy()
        except Exception as e:
            status_label.config(text=str(e))

    # 使用高颜值的按钮
    ttk.Button(login_root, text="解锁 / 创建", style="Accent.TButton", command=do_login).pack(pady=10, ipadx=20, ipady=5)
    login_root.bind("<Return>", lambda e: do_login())
    login_root.mainloop()

def main():
    vault = Vault(data_path())
    show_login_window(vault)
    if vault.key:
        root = tk.Tk()
        app = App(root, vault)
        root.mainloop()

if __name__ == "__main__":
    main()