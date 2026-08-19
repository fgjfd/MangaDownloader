# GUI界面 - 通用漫画下载器
from utils import ensure_console_safe
ensure_console_safe()  # 入口加固：防GBK打印崩溃/无控制台print异常，须在其他导入前执行

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import asyncio
import os
import time
import json
from crawler import ComicCrawler
from download_flow import run_download_flow
from downloader import is_browser_render_site, get_active_proxy
from config import DEFAULT_SITE, BROWSER_PATHS, DEFAULT_COOKIES_DIR, CONFIG_FILE, DEFAULT_IMAGE_NAME_PADDING, DEFAULT_CHAPTER_FOLDER_NAMING
from site_discovery import get_all_site_names, get_sites_requiring_login, get_sites_supporting_cookie, get_site_download_mode, refresh_sites as _refresh_sites_cache, add_site_file as _add_site_file, add_site_folder as _add_site_folder, remove_site as _remove_site, _get_data_dir, get_all_sites_info


# 图片命名补零选项: (显示文本, 补零位数)，默认3位在前
NAME_PADDING_OPTIONS = [
    ('3位（001、002...）', 3),
    ('2位（01、02...）', 2),
    ('4位（0001、0002...）', 4),
    ('原样（1、2、3...）', 0),
]


# 章节文件夹命名选项: (显示文本, 模式值)
CHAPTER_FOLDER_NAMING_OPTIONS = [
    ('数字（1、2、3...）', 'number'),
    ('章节名（1 第1话 标题...）', 'title'),
]


def _chapter_naming_to_label(mode):
    """章节文件夹命名模式 -> 显示文本"""
    for label, value in CHAPTER_FOLDER_NAMING_OPTIONS:
        if str(value) == str(mode):
            return label
    return CHAPTER_FOLDER_NAMING_OPTIONS[0][0]


def _label_to_chapter_naming(label):
    """显示文本 -> 章节文件夹命名模式值"""
    for text, value in CHAPTER_FOLDER_NAMING_OPTIONS:
        if text == label:
            return str(value)
    return DEFAULT_CHAPTER_FOLDER_NAMING


def _padding_to_label(padding):
    """补零位数 -> 显示文本"""
    for label, value in NAME_PADDING_OPTIONS:
        if str(value) == str(padding):
            return label
    return NAME_PADDING_OPTIONS[0][0]


def _label_to_padding(label):
    """显示文本 -> 补零位数"""
    for text, value in NAME_PADDING_OPTIONS:
        if text == label:
            return str(value)
    return str(DEFAULT_IMAGE_NAME_PADDING)


# ===== 窗口尺寸三档选项 =====
WINDOW_SIZES = {
    'large': (1280, 860),
    'medium': (960, 720),
    'small': (780, 600),
}

# ===== 左侧边栏配色（深色主题，选中高亮蓝） =====
SIDEBAR_BG = "#1e293b"               # 侧栏底色 (slate-800)
SIDEBAR_HOVER_BG = "#334155"         # 导航悬停反馈 (slate-700)
NAV_SELECTED_BG = "#2563eb"          # 导航选中高亮 (blue-600)
NAV_SELECTED_HOVER_BG = "#3b82f6"    # 选中项悬停 (blue-500)
NAV_TEXT = "#cbd5e1"                 # 未选中文字 (slate-300)
NAV_SELECTED_TEXT = "#ffffff"        # 选中文字
SIDEBAR_TITLE_TEXT = "#f8fafc"       # 标题文字 (slate-50)
SIDEBAR_SEP_BG = "#475569"           # 分隔线 (slate-600)


class GenericComicDownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("通用漫画下载器")
        self.root.geometry("960x720")
        self.root.resizable(True, True)
        
        self.crawler = None
        self.login_window_open = False
        self.cookies_dir = self.load_config().get('cookies_dir', DEFAULT_COOKIES_DIR)
        
        # 外层容器：左侧边栏 + 右侧内容区（不使用Canvas滚动）
        self.root_container = ttk.Frame(root)
        self.root_container.pack(fill="both", expand=True)

        # ========== 左侧边栏导航（固定宽度，不可被内容挤压） ==========
        self.sidebar = tk.Frame(self.root_container, bg=SIDEBAR_BG, width=100)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        # 应用标题
        tk.Label(
            self.sidebar,
            text="通用漫画\n下载器",
            font=("微软雅黑", 12, "bold"),
            bg=SIDEBAR_BG,
            fg=SIDEBAR_TITLE_TEXT,
            justify=tk.CENTER,
        ).pack(fill=tk.X, pady=(18, 4))

        # 标题与导航之间的分隔线
        tk.Frame(self.sidebar, bg=SIDEBAR_SEP_BG, height=1).pack(fill=tk.X, padx=14, pady=6)

        # 导航按钮：主页 / 设置（选中态高亮、悬停有反馈）
        self.nav_main_btn = tk.Button(
            self.sidebar, text="🏠 主页", font=("微软雅黑", 11),
            bg=SIDEBAR_BG, fg=NAV_TEXT,
            activebackground=SIDEBAR_HOVER_BG, activeforeground="#ffffff",
            relief=tk.FLAT, bd=0, highlightthickness=0,
            anchor="w", padx=14, pady=9, cursor="hand2",
            command=lambda: self.show_page('main')
        )
        self.nav_main_btn.pack(fill=tk.X, padx=6, pady=2)
        self.nav_settings_btn = tk.Button(
            self.sidebar, text="⚙ 设置", font=("微软雅黑", 11),
            bg=SIDEBAR_BG, fg=NAV_TEXT,
            activebackground=SIDEBAR_HOVER_BG, activeforeground="#ffffff",
            relief=tk.FLAT, bd=0, highlightthickness=0,
            anchor="w", padx=14, pady=9, cursor="hand2",
            command=lambda: self.show_page('settings')
        )
        self.nav_settings_btn.pack(fill=tk.X, padx=6, pady=2)

        # ========== 右侧内容区 ==========
        self.main_frame = ttk.Frame(self.root_container, padding="10")
        self.main_frame.pack(side=tk.LEFT, fill="both", expand=True)

        # ========== 主页面 ==========
        self.page_main = ttk.Frame(self.main_frame)
        self.page_main.pack(fill=tk.BOTH, expand=True)

        # ========== 站点选择 + 管理按钮 ==========
        site_row = ttk.Frame(self.page_main)
        site_row.pack(fill=tk.X, pady=3)

        ttk.Label(site_row, text="站点:").pack(side=tk.LEFT, padx=(0, 4))
        
        self.available_sites = get_all_site_names()
        self.sites_requiring_login = get_sites_requiring_login()
        self.sites_supporting_cookie = get_sites_supporting_cookie()
        self.site_url_map = self._build_site_url_map()
        default_site = DEFAULT_SITE if DEFAULT_SITE in self.available_sites else (self.available_sites[0] if self.available_sites else "")
        self.site_var = tk.StringVar(value=default_site)
        self.site_combo = ttk.Combobox(
            site_row, 
            textvariable=self.site_var, 
            values=self.available_sites,
            state="readonly",
            width=14
        )
        self.site_combo.pack(side=tk.LEFT, padx=2)

        ttk.Button(site_row, text="添加文件", command=self.add_site_file, width=9).pack(side=tk.LEFT, padx=2)
        ttk.Button(site_row, text="添加文件夹", command=self.add_site_folder, width=9).pack(side=tk.LEFT, padx=2)
        ttk.Button(site_row, text="删除站点", command=self.remove_current_site, width=9).pack(side=tk.LEFT, padx=2)
        ttk.Button(site_row, text="刷新", command=self.refresh_site_list, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(site_row, text="打开目录", command=self.open_sites_dir, width=8).pack(side=tk.LEFT, padx=2)

        self.site_count_label = ttk.Label(
            site_row,
            text=f"已加载 {len(self.available_sites)} 个站点",
            font=("微软雅黑", 9)
        )
        self.site_count_label.pack(side=tk.RIGHT, padx=4)

        # ========== 当前站点网址显示 ==========
        url_row = ttk.Frame(self.page_main)
        url_row.pack(fill=tk.X, pady=(0, 3))
        ttk.Label(url_row, text="网站地址:", font=("微软雅黑", 9)).pack(side=tk.LEFT, padx=(0, 4))
        self.site_url_label = ttk.Label(
            url_row,
            text="",
            font=("微软雅黑", 9),
            foreground="blue"
        )
        self.site_url_label.pack(side=tk.LEFT)
        ttk.Button(url_row, text="复制", command=self.copy_site_url, width=5).pack(side=tk.LEFT, padx=(4, 0))

        # ========== 两栏布局 ==========
        columns_frame = ttk.Frame(self.page_main)
        columns_frame.pack(fill=tk.X, pady=5)

        # 左栏 - 漫画设置
        left_col = ttk.LabelFrame(columns_frame, text="漫画设置", padding="8")
        left_col.pack(fill=tk.BOTH, expand=True)

        # 漫画名称
        name_row = ttk.Frame(left_col)
        name_row.pack(fill=tk.X, pady=2)
        ttk.Label(name_row, text="漫画名称:", width=9).pack(side=tk.LEFT)
        self.comic_name_var = tk.StringVar()
        self.comic_name_entry = ttk.Entry(name_row, textvariable=self.comic_name_var, font=("微软雅黑", 10))
        self.comic_name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 章节范围
        chapter_row = ttk.Frame(left_col)
        chapter_row.pack(fill=tk.X, pady=2)
        ttk.Label(chapter_row, text="章节范围:", width=9).pack(side=tk.LEFT)
        self.chapter_start_var = tk.StringVar(value="1")
        ttk.Entry(chapter_row, textvariable=self.chapter_start_var, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(chapter_row, text="到").pack(side=tk.LEFT)
        self.chapter_end_var = tk.StringVar(value="0")
        ttk.Entry(chapter_row, textvariable=self.chapter_end_var, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(chapter_row, text="(0=末章)", font=("微软雅黑", 9)).pack(side=tk.LEFT, padx=4)

        # 漫画ID (腾讯动漫/快看)
        self.comic_id_frame = ttk.Frame(left_col)
        self.use_comic_id_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self.comic_id_frame,
            text="使用漫画ID",
            variable=self.use_comic_id_var,
            command=self.on_comic_id_check_change
        ).pack(side=tk.LEFT)
        ttk.Label(self.comic_id_frame, text="ID:").pack(side=tk.LEFT, padx=2)
        self.comic_id_var = tk.StringVar()
        self.comic_id_entry = ttk.Entry(
            self.comic_id_frame,
            textvariable=self.comic_id_var,
            width=12,
            state=tk.DISABLED
        )
        self.comic_id_entry.pack(side=tk.LEFT, padx=2)

        # 登录设置
        self.login_frame = ttk.Frame(left_col)
        self.login_var = tk.BooleanVar(value=False)
        self.login_check = ttk.Checkbutton(
            self.login_frame,
            text="需要登录",
            variable=self.login_var,
            command=self.on_login_check_change
        )
        self.login_check.pack(side=tk.LEFT)
        self.login_status_label = ttk.Label(self.login_frame, text="", font=("微软雅黑", 9))
        self.login_status_label.pack(side=tk.LEFT, padx=4)
        self.login_button = ttk.Button(self.login_frame, text="打开登录", command=self.open_login_page, width=10, state=tk.DISABLED)
        self.login_button.pack(side=tk.LEFT, padx=2)
        self.login_complete_button = ttk.Button(self.login_frame, text="登录完成", command=self.complete_login, width=8, state=tk.DISABLED)
        self.login_complete_button.pack(side=tk.LEFT, padx=2)

        # Cookies路径
        self.cookies_path_frame = ttk.Frame(left_col)
        ttk.Label(self.cookies_path_frame, text="Cookies:", width=9).pack(side=tk.LEFT)
        self.cookies_path_var = tk.StringVar(value=self.cookies_dir)
        ttk.Entry(self.cookies_path_frame, textvariable=self.cookies_path_var, font=("微软雅黑", 10)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Button(self.cookies_path_frame, text="浏览", command=self.browse_cookies_path, width=6).pack(side=tk.LEFT, padx=2)

        # Cookie字符串输入（仅对声明支持Cookie的站点显示，如B站漫画解锁已购章节）
        self.cookie_str_frame = ttk.Frame(left_col)
        ttk.Label(self.cookie_str_frame, text="Cookie:", width=9).pack(side=tk.LEFT)
        self.cookie_str_var = tk.StringVar()
        ttk.Entry(self.cookie_str_frame, textvariable=self.cookie_str_var, font=("微软雅黑", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Button(self.cookie_str_frame, text="保存", command=self.save_cookie_str, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Button(self.cookie_str_frame, text="清除", command=self.clear_cookie_str, width=5).pack(side=tk.LEFT, padx=1)

        # 下载路径
        path_row = ttk.Frame(left_col)
        self.path_row = path_row
        path_row.pack(fill=tk.X, pady=2)
        ttk.Label(path_row, text="下载路径:", width=9).pack(side=tk.LEFT)
        self.download_path_var = tk.StringVar()
        ttk.Entry(path_row, textvariable=self.download_path_var, font=("微软雅黑", 10)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Button(path_row, text="浏览", command=self.browse_path, width=6).pack(side=tk.LEFT, padx=2)

        # ========== 通用设置变量（控件位于"⚙ 设置"对话框，见 open_settings） ==========
        self.thread_var = tk.StringVar(value="5")
        self.download_thread_var = tk.StringVar(value="4")
        self.download_mode_var = tk.StringVar(value="coroutine")
        self.first_timeout_var = tk.StringVar(value="8")
        self.retry_timeout_var = tk.StringVar(value="15")
        self.browser_type_var = tk.StringVar(value="edge")
        self.browser_mode_var = tk.StringVar(value="headed")
        self.browser_path_var = tk.StringVar(value=BROWSER_PATHS['edge'])
        self.create_zip_var = tk.BooleanVar(value=False)
        self.image_name_padding_var = tk.StringVar(value=str(DEFAULT_IMAGE_NAME_PADDING))
        self.chapter_folder_naming_var = tk.StringVar(value=DEFAULT_CHAPTER_FOLDER_NAMING)
        self.window_size_var = tk.StringVar(value="medium")
        # 初始化完成前禁止自动保存（避免构建期间 on_site_change 等以默认值覆盖 config.json）
        self._config_loaded = False

        # 通用设置任一选项变化即自动保存（设置面板修改即时生效）
        for _var in (self.thread_var, self.download_thread_var, self.download_mode_var,
                     self.first_timeout_var, self.retry_timeout_var,
                     self.browser_type_var, self.browser_mode_var, self.browser_path_var,
                     self.create_zip_var, self.image_name_padding_var,
                     self.chapter_folder_naming_var):
            _var.trace_add('write', self._on_settings_changed)

        # ========== 站点切换逻辑 ==========
        def on_site_change(*args):
            site_name = self.site_var.get()

            # 更新网站地址显示
            site_url = self.site_url_map.get(site_name, '')
            if site_url:
                self.site_url_label.config(text=site_url, foreground="blue")
            else:
                self.site_url_label.config(text="（未提供网址）", foreground="gray")

            # 站点为空时（首次启动无站点），隐藏条件区域
            if not site_name:
                self.comic_id_frame.pack_forget()
                self.login_frame.pack_forget()
                self.cookies_path_frame.pack_forget()
                self.cookie_str_frame.pack_forget()
                return

            # 漫画ID
            if site_name in ("腾讯动漫", "快看"):
                self.comic_id_frame.pack(fill=tk.X, pady=2, after=self.comic_name_entry.master)
            else:
                self.comic_id_frame.pack_forget()
                self.use_comic_id_var.set(False)
                self.comic_id_var.set("")

            # 下载模式
            try:
                download_mode = get_site_download_mode(site_name)
                self.download_mode_var.set(download_mode)
            except ValueError:
                pass

            # 登录
            if site_name in self.sites_requiring_login:
                self.login_frame.pack(fill=tk.X, pady=2, after=self.comic_id_frame if site_name == "腾讯动漫" else chapter_row)
                self.cookies_path_frame.pack(fill=tk.X, pady=2, after=self.login_frame)
                self.update_login_status()
            elif site_name == "拷贝漫画":
                self.login_frame.pack_forget()
                self.cookies_path_frame.pack_forget()
            else:
                self.login_frame.pack_forget()
                self.cookies_path_frame.pack_forget()

            # Cookie字符串输入：仅对声明支持Cookie的站点显示
            if site_name in self.sites_supporting_cookie:
                self.cookie_str_frame.pack(fill=tk.X, pady=2, before=self.path_row)
                self._sync_cookie_str_display(site_name)
            else:
                self.cookie_str_frame.pack_forget()

        self.site_var.trace("w", on_site_change)
        on_site_change()

        # ========== 按钮行 ==========
        self.button_frame = ttk.Frame(self.page_main)
        self.button_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Button(self.button_frame, text="清空状态", command=self.clear_status).pack(side=tk.LEFT, padx=3)
        ttk.Button(self.button_frame, text="下载失败图片", command=self.download_failed_images).pack(side=tk.LEFT, padx=3)
        ttk.Button(self.button_frame, text="退出", command=root.quit).pack(side=tk.RIGHT, padx=3)
        self.confirm_button = ttk.Button(
            self.button_frame,
            text="开始下载",
            command=self.start_download,
            style="Accent.TButton"
        )
        self.confirm_button.pack(side=tk.RIGHT, padx=3)

        # ========== 进度区域 ==========
        self.url_progress_frame = ttk.LabelFrame(self.page_main, text="获取图片URL进度", padding="8")
        self.url_progress_frame.pack(fill=tk.X, pady=3)

        url_info = ttk.Frame(self.url_progress_frame)
        url_info.pack(fill=tk.X)
        self.url_progress_label = ttk.Label(url_info, text="进度: 0/0 个章节", font=("微软雅黑", 10))
        self.url_progress_label.pack(side=tk.LEFT, padx=4)
        self.url_progress_bar = ttk.Progressbar(self.url_progress_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.url_progress_bar.pack(fill=tk.X, pady=3)

        self.progress_frame = ttk.LabelFrame(self.page_main, text="下载进度", padding="8")
        self.progress_frame.pack(fill=tk.X, pady=3)

        dl_info = ttk.Frame(self.progress_frame)
        dl_info.pack(fill=tk.X)
        self.progress_label = ttk.Label(dl_info, text="进度: 0/0 张图片", font=("微软雅黑", 10))
        self.progress_label.pack(side=tk.LEFT, padx=4)
        self.speed_label = ttk.Label(dl_info, text="网速: 0 KB/s", font=("微软雅黑", 10))
        self.speed_label.pack(side=tk.RIGHT, padx=4)
        self.progress_bar = ttk.Progressbar(self.progress_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=3)

        # ========== 状态日志 ==========
        self.status_frame = ttk.LabelFrame(self.page_main, text="下载状态", padding="8")
        self.status_frame.pack(fill=tk.BOTH, expand=True, pady=3)

        self.status_text = tk.Text(
            self.status_frame,
            font=("微软雅黑", 10),
            wrap=tk.WORD,
            state=tk.DISABLED,
            height=12
        )
        self.status_text.pack(fill=tk.BOTH, expand=True)

        status_scrollbar = ttk.Scrollbar(self.status_text, command=self.status_text.yview)
        status_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.status_text.config(yscrollcommand=status_scrollbar.set)

        self.style = ttk.Style()
        # ===== 界面美化：统一字体、间距与主题色 =====
        # 全局基础字体统一为微软雅黑（未单独指定字体的控件继承此设置）
        self.style.configure(".", font=("微软雅黑", 10))
        self.style.configure(
            "Accent.TButton", 
            font=("微软雅黑", 10, "bold"),
            padding=(12, 4)
        )
        # 分组卡片统一内边距与标题字重
        self.style.configure("Card.TLabelframe", padding="12")
        self.style.configure("Card.TLabelframe.Label", font=("微软雅黑", 10, "bold"))

        # ========== 设置页面 ==========
        self.page_settings = ttk.Frame(self.main_frame)
        self.page_settings.columnconfigure(0, weight=1)

        # ---- 图片设置 ----
        img_frame = ttk.LabelFrame(self.page_settings, text="图片设置", style="Card.TLabelframe")
        img_frame.grid(row=0, column=0, sticky='ew', padx=12, pady=(12, 6))
        img_frame.columnconfigure(1, weight=1)
        ttk.Label(img_frame, text="图片命名:").grid(row=0, column=0, sticky='e', padx=(0, 10), pady=4)
        self.padding_combo = ttk.Combobox(
            img_frame,
            values=[label for label, _ in NAME_PADDING_OPTIONS],
            state="readonly",
            width=28
        )
        self.padding_combo.set(_padding_to_label(self.image_name_padding_var.get()))
        self.padding_combo.grid(row=0, column=1, sticky='w', pady=4)
        self.padding_combo.bind('<<ComboboxSelected>>', self._on_padding_selected)
        ttk.Label(img_frame, text="示例：001、002、003（下载的图片文件名）",
                  font=("微软雅黑", 9), foreground="gray").grid(row=1, column=1, sticky='w')

        ttk.Label(img_frame, text="章节文件夹命名:").grid(row=2, column=0, sticky='e', padx=(0, 10), pady=4)
        self.chapter_naming_combo = ttk.Combobox(
            img_frame,
            values=[label for label, _ in CHAPTER_FOLDER_NAMING_OPTIONS],
            state="readonly",
            width=28
        )
        self.chapter_naming_combo.set(_chapter_naming_to_label(self.chapter_folder_naming_var.get()))
        self.chapter_naming_combo.grid(row=2, column=1, sticky='w', pady=4)
        self.chapter_naming_combo.bind('<<ComboboxSelected>>', self._on_chapter_naming_selected)
        ttk.Label(img_frame, text="示例：1、2、3 或 1 第1话 xxx（漫画内章节文件夹名）",
                  font=("微软雅黑", 9), foreground="gray").grid(row=3, column=1, sticky='w')

        # ---- 窗口设置 ----
        window_frame = ttk.LabelFrame(self.page_settings, text="窗口设置", style="Card.TLabelframe")
        window_frame.grid(row=1, column=0, sticky='ew', padx=12, pady=6)
        window_frame.columnconfigure(1, weight=1)

        ttk.Label(window_frame, text="窗口大小:").grid(row=0, column=0, sticky='e', padx=(0, 10), pady=4)
        size_row = ttk.Frame(window_frame)
        size_row.grid(row=0, column=1, sticky='w', pady=4)
        ttk.Radiobutton(size_row, text="大（1280×860）", variable=self.window_size_var,
                        value="large", command=self._on_window_size_change).pack(side=tk.LEFT)
        ttk.Radiobutton(size_row, text="中（960×720）", variable=self.window_size_var,
                        value="medium", command=self._on_window_size_change).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Radiobutton(size_row, text="小（780×600）", variable=self.window_size_var,
                        value="small", command=self._on_window_size_change).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Label(window_frame, text="切换后立即调整窗口大小并自动保存；窗口仍可手动拉伸",
                  font=("微软雅黑", 9), foreground="gray").grid(row=1, column=1, sticky='w')

        # ---- 下载设置 ----
        dl_frame = ttk.LabelFrame(self.page_settings, text="下载设置", style="Card.TLabelframe")
        dl_frame.grid(row=2, column=0, sticky='ew', padx=12, pady=6)
        dl_frame.columnconfigure(0, weight=1)
        dl_frame.columnconfigure(1, weight=1)
        dl_left = ttk.Frame(dl_frame)
        dl_left.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        dl_right = ttk.Frame(dl_frame)
        dl_right.grid(row=0, column=1, sticky='nsew', padx=(8, 0))
        for sub in (dl_left, dl_right):
            sub.columnconfigure(1, weight=1)

        # 左半：标签页数 / 首次超时 / 下载模式（提示文字紧贴输入框）
        ttk.Label(dl_left, text="标签页数:").grid(row=0, column=0, sticky='e', padx=(0, 8), pady=4)
        tabs_row = ttk.Frame(dl_left)
        tabs_row.grid(row=0, column=1, sticky='w', pady=4)
        ttk.Spinbox(tabs_row, from_=1, to=20, textvariable=self.thread_var, width=7).pack(side=tk.LEFT)
        ttk.Label(tabs_row, text="(推荐5)", font=("微软雅黑", 9), foreground="gray").pack(side=tk.LEFT, padx=(4, 0))

        ttk.Label(dl_left, text="首次超时:").grid(row=1, column=0, sticky='e', padx=(0, 8), pady=4)
        timeout_row = ttk.Frame(dl_left)
        timeout_row.grid(row=1, column=1, sticky='w', pady=4)
        ttk.Spinbox(timeout_row, from_=1, to=120, textvariable=self.first_timeout_var, width=7).pack(side=tk.LEFT)
        ttk.Label(timeout_row, text="秒", font=("微软雅黑", 9)).pack(side=tk.LEFT, padx=(4, 0))

        ttk.Label(dl_left, text="下载模式:").grid(row=2, column=0, sticky='e', padx=(0, 8), pady=4)
        mode_row = ttk.Frame(dl_left)
        mode_row.grid(row=2, column=1, sticky='w', pady=4)
        ttk.Radiobutton(mode_row, text="协程", variable=self.download_mode_var, value="coroutine").pack(side=tk.LEFT)
        ttk.Radiobutton(mode_row, text="多线程", variable=self.download_mode_var, value="thread_only").pack(side=tk.LEFT, padx=(12, 0))

        # 右半：下载线程 / 重试超时 / 压缩包
        ttk.Label(dl_right, text="下载线程:").grid(row=0, column=0, sticky='e', padx=(0, 8), pady=4)
        ttk.Spinbox(dl_right, from_=1, to=32, textvariable=self.download_thread_var, width=7).grid(row=0, column=1, sticky='w', pady=4)

        ttk.Label(dl_right, text="重试超时:").grid(row=1, column=0, sticky='e', padx=(0, 8), pady=4)
        retry_row = ttk.Frame(dl_right)
        retry_row.grid(row=1, column=1, sticky='w', pady=4)
        ttk.Spinbox(retry_row, from_=1, to=300, textvariable=self.retry_timeout_var, width=7).pack(side=tk.LEFT)
        ttk.Label(retry_row, text="秒", font=("微软雅黑", 9)).pack(side=tk.LEFT, padx=(4, 0))

        ttk.Label(dl_right, text="压缩包:").grid(row=2, column=0, sticky='e', padx=(0, 6), pady=4)
        ttk.Checkbutton(
            dl_right, text="下载完成后生成",
            variable=self.create_zip_var, command=self.on_create_zip_change
        ).grid(row=2, column=1, columnspan=2, sticky='w', pady=4)

        # ---- 浏览器设置 ----
        browser_frame = ttk.LabelFrame(self.page_settings, text="浏览器设置", style="Card.TLabelframe")
        browser_frame.grid(row=3, column=0, sticky='ew', padx=12, pady=(6, 12))
        browser_frame.columnconfigure(1, weight=1)

        ttk.Label(browser_frame, text="类型:").grid(row=0, column=0, sticky='e', padx=(0, 10), pady=4)
        type_row = ttk.Frame(browser_frame)
        type_row.grid(row=0, column=1, sticky='w', pady=4)
        ttk.Radiobutton(type_row, text="Edge", variable=self.browser_type_var, value="edge", command=self.update_browser_path).pack(side=tk.LEFT)
        ttk.Radiobutton(type_row, text="Chrome", variable=self.browser_type_var, value="chrome", command=self.update_browser_path).pack(side=tk.LEFT, padx=(16, 0))

        ttk.Label(browser_frame, text="模式:").grid(row=1, column=0, sticky='e', padx=(0, 10), pady=4)
        mode_row2 = ttk.Frame(browser_frame)
        mode_row2.grid(row=1, column=1, sticky='w', pady=4)
        ttk.Radiobutton(mode_row2, text="有头（显示窗口）", variable=self.browser_mode_var, value="headed").pack(side=tk.LEFT)
        ttk.Radiobutton(mode_row2, text="无头（后台运行）", variable=self.browser_mode_var, value="headless").pack(side=tk.LEFT, padx=(16, 0))

        ttk.Label(browser_frame, text="路径:").grid(row=2, column=0, sticky='e', padx=(0, 10), pady=4)
        path_row = ttk.Frame(browser_frame)
        path_row.grid(row=2, column=1, sticky='ew', pady=4)
        path_row.columnconfigure(0, weight=1)
        ttk.Entry(path_row, textvariable=self.browser_path_var, font=("微软雅黑", 9)).grid(row=0, column=0, sticky='ew', padx=(0, 6))
        ttk.Button(path_row, text="浏览", command=self.browse_browser, width=6).grid(row=0, column=1)

        # 恢复上次保存的下载设置
        self.apply_saved_config()
        # 初始显示主页面
        self.show_page('main')
    
    def load_config(self):
        """加载配置文件（utf-8-sig 兼容带 BOM 的文件）"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8-sig') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载配置文件失败: {e}")
        return {}
    
    def save_config(self):
        """保存配置文件（含全部下载设置，下次启动自动恢复）"""
        try:
            config = {
                'cookies_dir': self.cookies_path_var.get().strip(),
                'download_path': self.download_path_var.get().strip(),
                'max_tabs': self.thread_var.get().strip(),
                'download_threads': self.download_thread_var.get().strip(),
                'download_mode': self.download_mode_var.get(),
                'first_timeout': self.first_timeout_var.get().strip(),
                'retry_timeout': self.retry_timeout_var.get().strip(),
                'browser_type': self.browser_type_var.get(),
                'browser_mode': self.browser_mode_var.get(),
                'browser_path': self.browser_path_var.get().strip(),
                'create_zip': self.create_zip_var.get(),
                'image_name_padding': self.image_name_padding_var.get(),
                'chapter_folder_naming': self.chapter_folder_naming_var.get(),
                'window_size': self.window_size_var.get(),
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self.cookies_dir = config['cookies_dir']
        except Exception as e:
            print(f"保存配置文件失败: {e}")
    
    def apply_saved_config(self):
        """启动时恢复上次保存的设置"""
        config = self.load_config()
        if not config:
            self._config_loaded = True
            return
        mapping = {
            'download_path': self.download_path_var,
            'max_tabs': self.thread_var,
            'download_threads': self.download_thread_var,
            'first_timeout': self.first_timeout_var,
            'retry_timeout': self.retry_timeout_var,
            'browser_path': self.browser_path_var,
        }
        for key, var in mapping.items():
            if config.get(key):
                var.set(config[key])
        if config.get('download_mode') in ('coroutine', 'thread_only'):
            self.download_mode_var.set(config['download_mode'])
        if config.get('browser_type') in ('edge', 'chrome'):
            self.browser_type_var.set(config['browser_type'])
        if config.get('browser_mode') in ('headed', 'headless'):
            self.browser_mode_var.set(config['browser_mode'])
        if 'create_zip' in config:
            self.create_zip_var.set(bool(config['create_zip']))
        if 'image_name_padding' in config:
            padding = config['image_name_padding']
            if str(padding) in [str(v) for _, v in NAME_PADDING_OPTIONS]:
                self.image_name_padding_var.set(str(padding))
        if 'chapter_folder_naming' in config:
            mode = config['chapter_folder_naming']
            if str(mode) in [str(v) for _, v in CHAPTER_FOLDER_NAMING_OPTIONS]:
                self.chapter_folder_naming_var.set(str(mode))
        # 窗口大小（仅接受三档合法值，非法/缺失则保持默认"中"）
        if config.get('window_size') in WINDOW_SIZES:
            self.window_size_var.set(config['window_size'])
            w, h = WINDOW_SIZES[config['window_size']]
            self.root.geometry(f"{w}x{h}")
        # 配置恢复完成，此后设置变更才自动保存
        self._config_loaded = True
    
    def update_login_status(self):
        """更新登录状态显示"""
        site_name = self.site_var.get()
        # 使用动态获取的需要登录网站列表
        if site_name in self.sites_requiring_login:
            temp_crawler = self._make_temp_crawler()
            if temp_crawler.has_saved_cookies() or temp_crawler.has_cookie_str():
                self.login_status_label.config(text="[已保存登录信息]", foreground="green")
            else:
                self.login_status_label.config(text="[未登录]", foreground="gray")
    
    def _make_temp_crawler(self):
        """构造不启动浏览器的临时Crawler实例（仅用于Cookie文件操作）"""
        site_name = self.site_var.get()
        temp_crawler = ComicCrawler.__new__(ComicCrawler)
        temp_crawler.site_name = site_name
        temp_crawler.cookies_dir = self.cookies_path_var.get().strip() or DEFAULT_COOKIES_DIR
        # 补齐 __init__ 才会设置的属性（has_saved_cookies 等依赖 needs_browser 判断）
        try:
            from site_discovery import get_site_crawler_class
            site_cls = get_site_crawler_class(site_name)
            temp_crawler.needs_browser = bool(getattr(site_cls, 'NEEDS_BROWSER', True))
        except Exception:
            temp_crawler.needs_browser = True
        return temp_crawler

    def _sync_cookie_str_display(self, site_name=None):
        """切换站点时回显已保存的Cookie字符串"""
        try:
            temp_crawler = self._make_temp_crawler()
            saved = temp_crawler.load_cookie_str()
            self.cookie_str_var.set(saved or '')
        except Exception:
            self.cookie_str_var.set('')

    def save_cookie_str(self):
        """保存用户粘贴的Cookie字符串"""
        cookie_str = self.cookie_str_var.get().strip()
        if not cookie_str:
            messagebox.showinfo("提示", "请先粘贴Cookie字符串")
            return
        try:
            temp_crawler = self._make_temp_crawler()
            if temp_crawler.save_cookie_str(cookie_str):
                self.append_status(f"Cookie已保存（下次下载自动以登录态访问 {self.site_var.get()}）")
                self.update_login_status()
        except Exception as e:
            self.append_status(f"保存Cookie失败: {e}")

    def clear_cookie_str(self):
        """清除已保存的Cookie字符串"""
        try:
            temp_crawler = self._make_temp_crawler()
            temp_crawler.clear_cookie_str()
            self.cookie_str_var.set('')
            self.append_status(f"已清除 {self.site_var.get()} 的Cookie")
            self.update_login_status()
        except Exception as e:
            self.append_status(f"清除Cookie失败: {e}")
    
    def _padding_display(self, padding):
        """补零位数 -> 状态日志显示文本"""
        if padding == 0:
            return "原样（1、2、3...）"
        return f"{padding}位补零（{'0' * (padding - 1)}1、{'0' * (padding - 1)}2...）"

    def on_create_zip_change(self):
        """压缩包选项改变时的回调"""
        if self.create_zip_var.get():
            self.append_status("已开启：下载完成后生成压缩包")
        else:
            self.append_status("已关闭：下载完成后不生成压缩包")

    def show_page(self, page_name):
        """左侧边栏页面切换：'main' 主页面 / 'settings' 设置页面"""
        if page_name == 'main':
            self.page_settings.pack_forget()
            self.page_main.pack(fill=tk.BOTH, expand=True)
        else:
            self.page_main.pack_forget()
            self.page_settings.pack(fill=tk.BOTH, expand=True)
        self._update_nav_highlight(page_name)

    def _update_nav_highlight(self, page_name):
        """更新侧边栏导航按钮的选中高亮（选中蓝底白字，未选中与侧栏底色融合）"""
        for btn, name in ((self.nav_main_btn, 'main'), (self.nav_settings_btn, 'settings')):
            if name == page_name:
                btn.config(bg=NAV_SELECTED_BG, fg=NAV_SELECTED_TEXT,
                           activebackground=NAV_SELECTED_HOVER_BG)
            else:
                btn.config(bg=SIDEBAR_BG, fg=NAV_TEXT,
                           activebackground=SIDEBAR_HOVER_BG)

    def _on_window_size_change(self):
        """窗口尺寸变化：立即调整窗口大小并保存配置"""
        w, h = WINDOW_SIZES.get(self.window_size_var.get(), WINDOW_SIZES['medium'])
        self.root.geometry(f"{w}x{h}")
        self.save_config()

    def _on_settings_changed(self, *args):
        """通用设置任一选项变化时自动保存到config.json（初始化完成前不保存）"""
        if not self._config_loaded:
            return
        try:
            self.save_config()
        except Exception as e:
            print(f"保存设置失败: {e}")

    def _on_padding_selected(self, event=None):
        """图片命名下拉选择：文本选项 -> 补零位数并保存"""
        self.image_name_padding_var.set(_label_to_padding(self.padding_combo.get()))

    def _on_chapter_naming_selected(self, event=None):
        """章节文件夹命名下拉选择：文本选项 -> 模式值并保存"""
        self.chapter_folder_naming_var.set(_label_to_chapter_naming(self.chapter_naming_combo.get()))

    def on_comic_id_check_change(self):
        """漫画ID选项改变时的回调"""
        if self.use_comic_id_var.get():
            self.comic_id_entry.config(state=tk.NORMAL)
        else:
            self.comic_id_entry.config(state=tk.DISABLED)
            self.comic_id_var.set("")
    
    def on_login_check_change(self):
        """登录选项改变时的回调"""
        if self.login_var.get():
            self.login_button.config(state=tk.NORMAL)
            self.update_login_status()
        else:
            self.login_button.config(state=tk.DISABLED)
            self.login_complete_button.config(state=tk.DISABLED)
            self.login_status_label.config(text="")
    
    def open_login_page(self):
        """打开登录页面"""
        if self.login_window_open:
            messagebox.showinfo("提示", "登录页面已打开，请完成登录后点击'登录完成'按钮")
            return
        
        site_name = self.site_var.get()
        browser_path = self.browser_path_var.get().strip()
        cookies_dir = self.cookies_path_var.get().strip() or DEFAULT_COOKIES_DIR
        
        self.save_config()
        
        def login_task():
            try:
                self.login_button.config(state=tk.DISABLED)
                self.append_status(f"正在打开 {site_name} 登录页面...")
                
                self.crawler = ComicCrawler(site_name, browser_path, headless=False, login_mode=True, cookies_dir=cookies_dir)
                self.crawler.open_login_page()
                
                self.login_window_open = True
                self.login_complete_button.config(state=tk.NORMAL)
                self.append_status("请在浏览器中完成登录，然后点击'登录完成'按钮")
                
            except Exception as e:
                self.append_status(f"打开登录页面失败: {e}")
                import traceback
                self.append_status(traceback.format_exc())
                self.login_button.config(state=tk.NORMAL)
        
        login_thread = threading.Thread(target=login_task)
        login_thread.daemon = True
        login_thread.start()
    
    def complete_login(self):
        """完成登录，保存cookies"""
        if not self.crawler:
            messagebox.showerror("错误", "请先打开登录页面")
            return
        
        try:
            self.crawler.complete_login()
            self.append_status("登录信息已保存！")
            self.login_status_label.config(text="[已保存登录信息]", foreground="green")
            self.login_complete_button.config(state=tk.DISABLED)
            self.login_window_open = False
            
            if self.crawler.page:
                self.crawler.page.close()
                self.append_status("浏览器已关闭")
            self.crawler = None
            
        except Exception as e:
            self.append_status(f"保存登录信息失败: {e}")
            import traceback
            self.append_status(traceback.format_exc())
    
    def browse_path(self):
        path = filedialog.askdirectory(title="选择下载路径")
        if path:
            self.download_path_var.set(path)
    
    def browse_cookies_path(self):
        """选择cookies保存路径"""
        path = filedialog.askdirectory(title="选择Cookies保存路径")
        if path:
            self.cookies_path_var.set(path)
            self.save_config()
            self.update_login_status()
    
    def browse_browser(self):
        path = filedialog.askopenfilename(
            title="选择浏览器可执行文件",
            filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")]
        )
        if path:
            self.browser_path_var.set(path)
    
    def update_browser_path(self):
        browser_type = self.browser_type_var.get()
        if browser_type in BROWSER_PATHS:
            self.browser_path_var.set(BROWSER_PATHS[browser_type])
    
    def append_status(self, text):
        self.status_text.config(state=tk.NORMAL)
        self.status_text.insert(tk.END, text + "\n")
        self.status_text.see(tk.END)
        self.status_text.config(state=tk.DISABLED)
        self.root.update()
    
    def clear_status(self):
        self.status_text.config(state=tk.NORMAL)
        self.status_text.delete(1.0, tk.END)
        self.status_text.config(state=tk.DISABLED)
        self.reset_progress()
    
    def reset_url_progress(self, total_chapters=0):
        self.total_chapters = total_chapters
        self.collected_chapters = 0
        
        self.url_progress_bar['value'] = 0
        self.url_progress_bar['maximum'] = total_chapters if total_chapters > 0 else 1
        self.url_progress_label.config(text=f"进度: 0/{total_chapters} 个章节")
    
    def update_url_progress(self):
        self.collected_chapters += 1
        self.url_progress_bar['value'] = self.collected_chapters
        self.url_progress_label.config(text=f"进度: {self.collected_chapters}/{self.total_chapters} 个章节")
        self.root.update()
    
    def reset_progress(self, total_images=0):
        self.total_images = total_images
        self.downloaded_images = 0
        self.total_downloaded_bytes = 0
        self.start_time = time.time()
        self.last_update_time = self.start_time
        self.last_downloaded_bytes = 0
        
        self.progress_bar['value'] = 0
        self.progress_bar['maximum'] = total_images if total_images > 0 else 1
        self.progress_label.config(text=f"进度: 0/{total_images} 张图片")
        self.speed_label.config(text="网速: 0 KB/s")
    

    
    def update_progress(self, downloaded_bytes=0):
        self.downloaded_images += 1
        self.total_downloaded_bytes += downloaded_bytes
        
        current_time = time.time()
        elapsed = current_time - self.last_update_time
        
        if elapsed >= 0.5:
            speed_bytes = self.total_downloaded_bytes - self.last_downloaded_bytes
            speed_kb = speed_bytes / elapsed / 1024
            self.last_update_time = current_time
            self.last_downloaded_bytes = self.total_downloaded_bytes
            
            if speed_kb >= 1024:
                speed_str = f"{speed_kb / 1024:.2f} MB/s"
            else:
                speed_str = f"{speed_kb:.2f} KB/s"
            self.speed_label.config(text=f"网速: {speed_str}")
        
        self.progress_bar['value'] = self.downloaded_images
        self.progress_label.config(text=f"进度: {self.downloaded_images}/{self.total_images} 张图片")
        self.root.update()
    
    def download_task(self):
        try:
            site_name = self.site_var.get()
            # 使用动态获取的网站列表验证
            if site_name not in self.available_sites:
                messagebox.showerror("错误", "请选择有效的站点")
                return
            
            use_comic_id = site_name in ("腾讯动漫", "快看") and self.use_comic_id_var.get()
            comic_id = self.comic_id_var.get().strip() if use_comic_id else None
            
            comic_name = self.comic_name_var.get().strip()
            if not comic_name and not comic_id:
                if use_comic_id:
                    messagebox.showerror("错误", "请输入漫画ID")
                else:
                    messagebox.showerror("错误", "请输入漫画名称")
                return
            
            try:
                chapter_start = int(self.chapter_start_var.get().strip() or "1")
                chapter_end = int(self.chapter_end_var.get().strip() or "0")
            except ValueError:
                messagebox.showerror("错误", "章节范围必须是数字")
                return
            
            if chapter_start < 1:
                messagebox.showerror("错误", "起始章节必须大于等于1")
                return
            
            if chapter_end > 0 and chapter_end < chapter_start:
                messagebox.showerror("错误", "结束章节必须大于等于起始章节")
                return
            
            browser_type = self.browser_type_var.get()
            browser_path = self.browser_path_var.get().strip()
            headless = self.browser_mode_var.get() == "headless"
            
            # 使用动态获取的需要登录网站列表
            login_mode = self.login_var.get() and site_name in self.sites_requiring_login
            cookies_dir = self.cookies_path_var.get().strip() or DEFAULT_COOKIES_DIR
            
            self.save_config()
            self.confirm_button.config(state=tk.DISABLED)
            self.append_status(f"使用站点: {site_name}")
            if comic_id:
                self.append_status(f"使用漫画ID: {comic_id}")
            else:
                self.append_status(f"开始下载漫画: {comic_name}")
            if chapter_end > 0:
                self.append_status(f"下载章节范围: 第{chapter_start}章 到 第{chapter_end}章")
            else:
                self.append_status(f"下载章节范围: 第{chapter_start}章 到 最后一章")
            self.append_status(f"浏览器模式: {'无头' if headless else '有头'}")
            if login_mode:
                self.append_status(f"登录模式: 已启用")
                self.append_status(f"Cookies路径: {cookies_dir}")
            
            self.append_status("正在启动浏览器...")
            crawler = ComicCrawler(site_name, browser_path, headless, login_mode=login_mode, cookies_dir=cookies_dir)
                        
            try:
                max_threads = int(self.thread_var.get().strip())
                download_thread_count = int(self.download_thread_var.get().strip())
                use_thread_only = self.download_mode_var.get() == "thread_only"
                first_timeout = int(self.first_timeout_var.get().strip())
                retry_timeout = int(self.retry_timeout_var.get().strip())
                download_path = self.download_path_var.get().strip()
            
                self.append_status(f"同时打开标签页数: {max_threads}")
                self.append_status(f"下载模式: {'纯多线程' if use_thread_only else '协程'}，线程数: {download_thread_count}")
                self.append_status(f"首次超时: {first_timeout}秒, 重试超时: {retry_timeout}秒")
                image_padding = int(self.image_name_padding_var.get().strip() or DEFAULT_IMAGE_NAME_PADDING)
                self.append_status(f"图片命名: {self._padding_display(image_padding)}")
                chapter_folder_naming = self.chapter_folder_naming_var.get()
                self.append_status(f"章节文件夹命名: {_chapter_naming_to_label(chapter_folder_naming)}")
                create_zip = self.create_zip_var.get()
                if create_zip:
                    self.append_status("压缩包选项: 已开启（下载完成后生成zip）")
                else:
                    self.append_status("压缩包选项: 未开启（下载完成后不生成zip）")
            
                def pre_collect(actual_count):
                    self.reset_url_progress(actual_count)
            
                def pre_download(total_images):
                    self.reset_progress(total_images)
                    if total_images == 0 and is_browser_render_site(crawler.site_crawler):
                        self.append_status("浏览器渲染模式：图片总数在下载时确定")
                    else:
                        self.append_status(f"总计 {total_images} 张图片")
            
                result = run_download_flow(
                    crawler, comic_name, comic_id=comic_id,
                    chapter_start=chapter_start, chapter_end=chapter_end,
                    max_threads=max_threads,
                    download_path=download_path if download_path else None,
                    log=self.append_status,
                    progress_callback=self.update_progress,
                    download_thread_count=download_thread_count,
                    use_thread_only=use_thread_only,
                    first_timeout=first_timeout,
                    retry_timeout=retry_timeout,
                    url_progress_callback=self.update_url_progress,
                    pre_download_hook=pre_download,
                    pre_collect_hook=pre_collect,
                    create_zip=create_zip,
                    image_name_padding=image_padding,
                    chapter_folder_naming=chapter_folder_naming,
                )
            
                comic_name = result['comic_name']
                failed_downloads = result['failed_downloads']
            
                if not result['chapters_data']:
                    self.append_status("没有获取到任何章节数据")
                elif failed_downloads:
                    self.append_status(f"\n⚠️  注意：以下图片最终下载失败（共 {len(failed_downloads)} 张）:")
                    for failed in failed_downloads:
                        self.append_status(f"  - 章节{failed['chapter_num']}-第{failed['image_index']}张")
                        self.append_status(f"    路径: {failed['path']}")
                        self.append_status(f"    URL: {failed['url']}")
                    self.append_status(f"\n失败列表已保存到: {result['failed_json_path']}")
                    self.append_status("⚠️  由于存在下载失败的图片，跳过压缩步骤")
                    self.append_status(f"✓ 漫画《{comic_name}》下载完成（有失败图片）！")
                    messagebox.showwarning("完成", f"漫画《{comic_name}》下载完成！\n\n注意：有 {len(failed_downloads)} 张图片最终下载失败。\n失败列表已保存到:\n{result['failed_json_path']}\n\n请使用'下载失败图片'功能重新下载。")
                else:
                    self.append_status(f"✓ 漫画《{comic_name}》下载完成！")
                    if create_zip:
                        self.append_status(f"已生成压缩包: {os.path.join(download_path if download_path else '.', comic_name + '.zip')}")
                    else:
                        self.append_status("未生成压缩包（如需生成请勾选'下载完成后生成压缩包'）")
                    messagebox.showinfo("成功", f"漫画《{comic_name}》下载完成！")
                            
            finally:
                if crawler.page:
                    crawler.page.close()
                    self.append_status("浏览器已关闭")
                else:
                    self.append_status("该站点无需浏览器（纯HTTP下载）")
                
        except Exception as e:
            self.append_status(f"下载过程中出错: {e}")
            import traceback
            self.append_status(traceback.format_exc())
            messagebox.showerror("错误", f"下载过程中出错: {e}")
        finally:
            self.confirm_button.config(state=tk.NORMAL)
    
    def start_download(self):
        download_thread = threading.Thread(target=self.download_task)
        download_thread.daemon = True
        download_thread.start()

    def download_failed_images(self):
        """从失败列表JSON文件下载失败图片"""
        json_path = filedialog.askopenfilename(
            title="选择失败列表JSON文件",
            filetypes=[("JSON文件", "*.json"), ("所有文件", "*.*")]
        )
        if not json_path:
            return

        def retry_task():
            try:
                self.confirm_button.config(state=tk.DISABLED)
                self.append_status(f"\n{'='*50}")
                self.append_status("开始下载失败图片...")
                self.append_status(f"JSON文件: {json_path}")

                # 读取JSON获取总图片数
                import json
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                total_images = len(data['failed_images'])
                self.reset_progress(total_images)

                download_thread_count = int(self.download_thread_var.get().strip())

                if data.get('render_mode'):
                    # 浏览器渲染模式（加密站点）：HTTP重试无效，重跑失败章节的浏览器提取
                    retry_site = data.get('site_name') or self.site_var.get()
                    browser_path = self.browser_path_var.get().strip()
                    headless = self.browser_mode_var.get() == "headless"
                    cookies_dir = self.cookies_path_var.get().strip() or DEFAULT_COOKIES_DIR
                    # 浏览器重试会重新生成文件名，需恢复命名规则
                    from downloader import set_active_name_padding
                    set_active_name_padding(int(self.image_name_padding_var.get().strip() or 0))
                    self.append_status(f"浏览器渲染模式({data.get('render_mode')})：重跑失败章节的浏览器提取，站点: {retry_site}")
                    from downloader import retry_failed_chapters_via_browser
                    still_failed, all_success = retry_failed_chapters_via_browser(
                        json_path, retry_site, browser_path, headless=headless,
                        cookies_dir=cookies_dir,
                        progress_callback=self.update_progress,
                        max_workers=max(1, download_thread_count))
                else:
                    first_timeout = int(self.first_timeout_var.get().strip())
                    retry_timeout = int(self.retry_timeout_var.get().strip())

                    # 导入函数
                    from downloader import download_from_failed_json

                    still_failed, all_success = asyncio.run(
                        download_from_failed_json(
                            json_path,
                            concurrent_limit=3,
                            download_thread_count=download_thread_count,
                            use_thread_coroutine=True,
                            progress_callback=self.update_progress,
                            max_retries=3,
                            first_timeout=first_timeout,
                            retry_timeout=retry_timeout
                        )
                    )

                if all_success:
                    self.append_status(f"\n✓ 所有失败图片下载成功！")
                    messagebox.showinfo("成功", "所有失败图片下载成功！")
                else:
                    self.append_status(f"\n⚠️ 仍有 {len(still_failed)} 张图片下载失败")
                    for failed in still_failed:
                        self.append_status(f"  - 章节{failed['chapter_num']}-第{failed['image_index']}张: {failed['url']}")
                    self.append_status(f"\n更新后的失败列表已保存")
                    messagebox.showwarning("完成", f"部分图片下载成功，仍有 {len(still_failed)} 张失败。\n更新后的失败列表已保存。")

                self.append_status(f"{'='*50}")

            except Exception as e:
                self.append_status(f"下载失败图片时出错: {e}")
                import traceback
                self.append_status(traceback.format_exc())
                messagebox.showerror("错误", f"下载失败图片时出错: {e}")
            finally:
                self.confirm_button.config(state=tk.NORMAL)

        retry_thread = threading.Thread(target=retry_task)
        retry_thread.daemon = True
        retry_thread.start()

    def refresh_site_list(self):
        """刷新站点列表"""
        _refresh_sites_cache()
        self.available_sites = get_all_site_names()
        self.sites_requiring_login = get_sites_requiring_login()
        self.sites_supporting_cookie = get_sites_supporting_cookie()

        # 更新站点下拉框
        self.site_combo['values'] = self.available_sites

        # 如果当前选中的站点不在列表中，选择第一个
        if self.site_var.get() not in self.available_sites:
            if self.available_sites:
                self.site_var.set(self.available_sites[0])
            else:
                self.site_var.set('')

        # 更新站点计数
        self.site_count_label.config(text=f"已加载 {len(self.available_sites)} 个站点")
        self.append_status(f"站点列表已刷新，共 {len(self.available_sites)} 个站点")

    def add_site_file(self):
        """添加站点文件"""
        file_paths = filedialog.askopenfilenames(
            title="选择站点爬虫文件",
            filetypes=[("Python文件", "*.py"), ("所有文件", "*.*")]
        )
        if not file_paths:
            return

        added = []
        errors = []
        skipped = []

        for path in file_paths:
            try:
                name = _add_site_file(path)
                added.append(name)
            except ValueError as e:
                err_msg = str(e)
                if '已存在' in err_msg:
                    skipped.append((os.path.basename(path), err_msg))
                else:
                    errors.append((os.path.basename(path), err_msg))

        if added:
            self.append_status(f"已添加站点: {', '.join(added)}")
            self.available_sites = get_all_site_names()
            self.sites_requiring_login = get_sites_requiring_login()
            self.sites_supporting_cookie = get_sites_supporting_cookie()
            self._refresh_site_url_map()
            self.site_combo['values'] = self.available_sites
            self.site_count_label.config(text=f"已加载 {len(self.available_sites)} 个站点")
            self.site_var.set(added[0])
        if skipped:
            for file, reason in skipped:
                self.append_status(f"跳过重复: {file} - {reason}")
        if errors:
            for file, err in errors:
                self.append_status(f"添加 {file} 失败: {err}")
            if not added:
                messagebox.showerror("添加失败", "\n".join(f"{f}: {e}" for f, e in errors))

    def add_site_folder(self):
        """添加站点文件夹"""
        folder = filedialog.askdirectory(title="选择包含站点爬虫文件的文件夹")
        if not folder:
            return

        try:
            added, errors, skipped = _add_site_folder(folder)
            if added:
                names = [n for _, n in added]
                self.append_status(f"已添加 {len(added)} 个站点: {', '.join(names)}")
                self.available_sites = get_all_site_names()
                self.sites_requiring_login = get_sites_requiring_login()
                self.sites_supporting_cookie = get_sites_supporting_cookie()
                self._refresh_site_url_map()
                self.site_combo['values'] = self.available_sites
                self.site_count_label.config(text=f"已加载 {len(self.available_sites)} 个站点")
                self.site_var.set(names[0])
            if skipped:
                for file, reason in skipped:
                    self.append_status(f"跳过重复: {file} - {reason}")
            if errors:
                for file, err in errors:
                    self.append_status(f"添加 {file} 失败: {err}")
            if not added and not errors and not skipped:
                self.append_status("该文件夹中没有找到站点文件(*_crawler.py)")
                messagebox.showinfo("提示", "该文件夹中没有找到站点文件(*_crawler.py)")
        except Exception as e:
            self.append_status(f"添加站点文件夹失败: {e}")
            messagebox.showerror("错误", str(e))

    def remove_current_site(self):
        """删除当前选中的站点"""
        site_name = self.site_var.get()
        if not site_name:
            messagebox.showwarning("提示", "请先选择要删除的站点")
            return

        if not messagebox.askyesno("确认删除", f"确定要删除站点「{site_name}」吗？"):
            return

        try:
            _remove_site(site_name)
            self.append_status(f"已删除站点: {site_name}")
            self.available_sites = get_all_site_names()
            self.sites_requiring_login = get_sites_requiring_login()
            self.sites_supporting_cookie = get_sites_supporting_cookie()
            self._refresh_site_url_map()
            self.site_combo['values'] = self.available_sites
            self.site_count_label.config(text=f"已加载 {len(self.available_sites)} 个站点")
            if self.available_sites:
                self.site_var.set(self.available_sites[0])
            else:
                self.site_var.set('')
        except Exception as e:
            self.append_status(f"删除站点失败: {e}")
            messagebox.showerror("错误", str(e))

    def open_sites_dir(self):
        """打开站点数据目录"""
        data_dir = _get_data_dir()
        os.startfile(data_dir)

    def copy_site_url(self):
        """复制当前站点网址到剪贴板"""
        url = self.site_url_label.cget("text")
        if url and url != "（未提供网址）":
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            self.append_status(f"已复制网址: {url}")

    def _build_site_url_map(self):
        """构建站点名称到网址的映射"""
        url_map = {}
        for info in get_all_sites_info():
            if info.get('site_url'):
                url_map[info['name']] = info['site_url']
        return url_map

    def _refresh_site_url_map(self):
        """刷新站点网址映射并更新显示"""
        self.site_url_map = self._build_site_url_map()
        site_name = self.site_var.get()
        site_url = self.site_url_map.get(site_name, '')
        if site_url:
            self.site_url_label.config(text=site_url, foreground="blue")
        else:
            self.site_url_label.config(text="（未提供网址）", foreground="gray")




def main():
    root = tk.Tk()
    app = GenericComicDownloaderGUI(root)
    # 代理检测移至后台：窗口先显示（避免阻塞启动），检测完成后再显示结果日志
    threading.Thread(target=get_active_proxy, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    main()
