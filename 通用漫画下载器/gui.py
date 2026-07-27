# GUI界面 - 通用漫画下载器
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import asyncio
import os
import time
import json
from crawler import ComicCrawler
from downloader import download_cover_image, download_all_chapters
from utils import zip_main_folder
from config import DEFAULT_SITE, BROWSER_PATHS, DEFAULT_COOKIES_DIR, CONFIG_FILE
from site_discovery import get_all_site_names, get_sites_requiring_login, get_site_download_mode


class GenericComicDownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("通用漫画下载器")
        self.root.geometry("900x700")
        self.root.resizable(True, True)
        
        self.crawler = None
        self.login_window_open = False
        self.cookies_dir = self.load_config().get('cookies_dir', DEFAULT_COOKIES_DIR)
        
        self.canvas = tk.Canvas(root, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(root, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
        self.main_frame = ttk.Frame(self.canvas, padding="10")
        
        self.canvas_window = self.canvas.create_window((0, 0), window=self.main_frame, anchor="nw", width=860)
        
        def on_frame_configure(event=None):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        
        def on_canvas_configure(event=None):
            canvas_width = event.width
            self.canvas.itemconfig(self.canvas_window, width=canvas_width)
        
        self.main_frame.bind("<Configure>", on_frame_configure)
        self.canvas.bind("<Configure>", on_canvas_configure)
        
        def on_mousewheel(event):
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.canvas.bind_all("<MouseWheel>", on_mousewheel)
        
        title_label = ttk.Label(
            self.main_frame, 
            text="通用漫画下载器", 
            font=("微软雅黑", 18, "bold")
        )
        title_label.pack(pady=10)
        
        self.site_frame = ttk.Frame(self.main_frame)
        self.site_frame.pack(fill=tk.X, pady=5)
        
        # 动态获取可用网站列表
        self.available_sites = get_all_site_names()
        self.sites_requiring_login = get_sites_requiring_login()
        
        ttk.Label(self.site_frame, text="选择站点:", width=10).pack(side=tk.LEFT, padx=5)
        
        # 设置默认站点（如果存在）
        default_site = DEFAULT_SITE if DEFAULT_SITE in self.available_sites else (self.available_sites[0] if self.available_sites else "")
        
        self.site_var = tk.StringVar(value=default_site)
        self.site_combo = ttk.Combobox(
            self.site_frame, 
            textvariable=self.site_var, 
            values=self.available_sites,
            state="readonly",
            width=20
        )
        self.site_combo.pack(side=tk.LEFT, padx=5)
        
        self.name_frame = ttk.Frame(self.main_frame)
        self.name_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(self.name_frame, text="漫画名称:", width=10).pack(side=tk.LEFT, padx=5)
        self.comic_name_var = tk.StringVar()
        self.comic_name_entry = ttk.Entry(
            self.name_frame, 
            textvariable=self.comic_name_var, 
            font=("微软雅黑", 10)
        )
        self.comic_name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        self.num_frame = ttk.Frame(self.main_frame)
        self.num_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(self.num_frame, text="章节范围:", width=10).pack(side=tk.LEFT, padx=5)
        
        self.chapter_start_var = tk.StringVar(value="1")
        self.chapter_start_entry = ttk.Entry(
            self.num_frame, 
            textvariable=self.chapter_start_var, 
            font=("微软雅黑", 10),
            width=8
        )
        self.chapter_start_entry.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(self.num_frame, text="到").pack(side=tk.LEFT, padx=2)
        
        self.chapter_end_var = tk.StringVar(value="0")
        self.chapter_end_entry = ttk.Entry(
            self.num_frame, 
            textvariable=self.chapter_end_var, 
            font=("微软雅黑", 10),
            width=8
        )
        self.chapter_end_entry.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(self.num_frame, text="(结束填0表示到最后一章)").pack(side=tk.LEFT, padx=5)
        
        self.comic_id_frame = ttk.Frame(self.main_frame)
        
        self.use_comic_id_var = tk.BooleanVar(value=False)
        self.use_comic_id_check = ttk.Checkbutton(
            self.comic_id_frame,
            text="使用漫画ID",
            variable=self.use_comic_id_var,
            command=self.on_comic_id_check_change
        )
        self.use_comic_id_check.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(self.comic_id_frame, text="漫画ID:", width=8).pack(side=tk.LEFT, padx=5)
        self.comic_id_var = tk.StringVar()
        self.comic_id_entry = ttk.Entry(
            self.comic_id_frame,
            textvariable=self.comic_id_var,
            font=("微软雅黑", 10),
            width=15,
            state=tk.DISABLED
        )
        self.comic_id_entry.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(self.comic_id_frame, text="(腾讯动漫可直接输入ID，如: 544298)", font=("微软雅黑", 9)).pack(side=tk.LEFT, padx=5)
        
        self.login_frame = ttk.Frame(self.main_frame)
        
        self.login_var = tk.BooleanVar(value=False)
        self.login_check = ttk.Checkbutton(
            self.login_frame,
            text="需要登录账号",
            variable=self.login_var,
            command=self.on_login_check_change
        )
        self.login_check.pack(side=tk.LEFT, padx=5)
        
        self.login_status_label = ttk.Label(
            self.login_frame,
            text="",
            font=("微软雅黑", 9)
        )
        self.login_status_label.pack(side=tk.LEFT, padx=5)
        
        self.login_button = ttk.Button(
            self.login_frame,
            text="打开登录页面",
            command=self.open_login_page,
            width=12
        )
        self.login_button.pack(side=tk.LEFT, padx=5)
        
        self.login_complete_button = ttk.Button(
            self.login_frame,
            text="登录完成",
            command=self.complete_login,
            width=10,
            state=tk.DISABLED
        )
        self.login_complete_button.pack(side=tk.LEFT, padx=5)
        
        self.cookies_path_frame = ttk.Frame(self.main_frame)
        
        ttk.Label(self.cookies_path_frame, text="Cookies路径:", width=10).pack(side=tk.LEFT, padx=5)
        self.cookies_path_var = tk.StringVar(value=self.cookies_dir)
        self.cookies_path_entry = ttk.Entry(
            self.cookies_path_frame,
            textvariable=self.cookies_path_var,
            font=("微软雅黑", 10)
        )
        self.cookies_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        ttk.Button(
            self.cookies_path_frame,
            text="浏览",
            command=self.browse_cookies_path,
            width=8
        ).pack(side=tk.LEFT, padx=5)
        
        self.thread_frame = ttk.Frame(self.main_frame)
        
        ttk.Label(self.thread_frame, text="同时打开标签页数:", width=14).pack(side=tk.LEFT, padx=5)
        self.thread_var = tk.StringVar(value="5")
        self.thread_entry = ttk.Entry(
            self.thread_frame, 
            textvariable=self.thread_var, 
            font=("微软雅黑", 10),
            width=10
        )
        self.thread_entry.pack(side=tk.LEFT, padx=5)
        ttk.Label(self.thread_frame, text="(推荐5个)").pack(side=tk.LEFT)
        
        self.download_thread_frame = ttk.Frame(self.main_frame)
        self.download_thread_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(self.download_thread_frame, text="下载线程数:", width=12).pack(side=tk.LEFT, padx=5)
        self.download_thread_var = tk.StringVar(value="4")
        self.download_thread_entry = ttk.Entry(
            self.download_thread_frame, 
            textvariable=self.download_thread_var, 
            font=("微软雅黑", 10),
            width=10
        )
        self.download_thread_entry.pack(side=tk.LEFT, padx=5)
        
        # 下载模式选择
        self.download_mode_var = tk.StringVar(value="coroutine")
        ttk.Radiobutton(
            self.download_thread_frame, 
            text="协程模式", 
            variable=self.download_mode_var, 
            value="coroutine"
        ).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(
            self.download_thread_frame, 
            text="纯多线程", 
            variable=self.download_mode_var, 
            value="thread_only"
        ).pack(side=tk.LEFT, padx=5)
        
        # 超时时间设置
        self.timeout_frame = ttk.Frame(self.main_frame)
        self.timeout_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(self.timeout_frame, text="首次超时:", width=10).pack(side=tk.LEFT, padx=5)
        self.first_timeout_var = tk.StringVar(value="8")
        self.first_timeout_entry = ttk.Entry(
            self.timeout_frame, 
            textvariable=self.first_timeout_var, 
            font=("微软雅黑", 10),
            width=8
        )
        self.first_timeout_entry.pack(side=tk.LEFT, padx=5)
        ttk.Label(self.timeout_frame, text="秒").pack(side=tk.LEFT, padx=(0, 15))
        
        ttk.Label(self.timeout_frame, text="重试超时:", width=10).pack(side=tk.LEFT, padx=5)
        self.retry_timeout_var = tk.StringVar(value="15")
        self.retry_timeout_entry = ttk.Entry(
            self.timeout_frame, 
            textvariable=self.retry_timeout_var, 
            font=("微软雅黑", 10),
            width=8
        )
        self.retry_timeout_entry.pack(side=tk.LEFT, padx=5)
        ttk.Label(self.timeout_frame, text="秒 (推荐: 首次8秒, 重试15秒)").pack(side=tk.LEFT)
        
        def on_site_change(*args):
            site_name = self.site_var.get()

            if site_name == "腾讯动漫":
                self.comic_id_frame.pack(fill=tk.X, pady=5, after=self.num_frame)
            else:
                self.comic_id_frame.pack_forget()
                self.use_comic_id_var.set(False)
                self.comic_id_var.set("")

            # 根据网站配置设置默认下载模式
            download_mode = get_site_download_mode(site_name)
            self.download_mode_var.set(download_mode)

            # 使用动态获取的需要登录网站列表
            if site_name in self.sites_requiring_login:
                self.login_frame.pack(fill=tk.X, pady=5, after=self.comic_id_frame if site_name == "腾讯动漫" else self.num_frame)
                self.cookies_path_frame.pack(fill=tk.X, pady=5, after=self.login_frame)
                self.thread_frame.pack(fill=tk.X, pady=5, after=self.cookies_path_frame)
                self.update_login_status()
            elif site_name == "拷贝漫画":
                self.login_frame.pack_forget()
                self.cookies_path_frame.pack_forget()
                self.thread_frame.pack(fill=tk.X, pady=5, after=self.comic_id_frame if site_name == "腾讯动漫" else self.num_frame)
            else:
                self.login_frame.pack_forget()
                self.cookies_path_frame.pack_forget()
                self.thread_frame.pack_forget()
        
        self.site_var.trace("w", on_site_change)
        on_site_change()
        
        self.path_frame = ttk.Frame(self.main_frame)
        self.path_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(self.path_frame, text="下载路径:", width=10).pack(side=tk.LEFT, padx=5)
        self.download_path_var = tk.StringVar()
        self.download_path_entry = ttk.Entry(
            self.path_frame, 
            textvariable=self.download_path_var, 
            font=("微软雅黑", 10)
        )
        self.download_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        ttk.Button(
            self.path_frame, 
            text="浏览", 
            command=self.browse_path,
            width=8
        ).pack(side=tk.LEFT, padx=5)
        
        self.browser_frame = ttk.LabelFrame(self.main_frame, text="浏览器设置", padding="10")
        self.browser_frame.pack(fill=tk.X, pady=10)
        
        self.browser_type_frame = ttk.Frame(self.browser_frame)
        self.browser_type_frame.pack(fill=tk.X, pady=3)
        
        ttk.Label(self.browser_type_frame, text="浏览器类型:", width=10).pack(side=tk.LEFT, padx=5)
        self.browser_type_var = tk.StringVar(value="edge")
        
        ttk.Radiobutton(
            self.browser_type_frame, 
            text="Edge", 
            variable=self.browser_type_var, 
            value="edge",
            command=self.update_browser_path
        ).pack(side=tk.LEFT, padx=10)
        
        ttk.Radiobutton(
            self.browser_type_frame, 
            text="Chrome", 
            variable=self.browser_type_var, 
            value="chrome",
            command=self.update_browser_path
        ).pack(side=tk.LEFT, padx=10)
        
        self.browser_path_frame = ttk.Frame(self.browser_frame)
        self.browser_path_frame.pack(fill=tk.X, pady=3)
        
        ttk.Label(self.browser_path_frame, text="浏览器路径:", width=10).pack(side=tk.LEFT, padx=5)
        self.browser_path_var = tk.StringVar(value=BROWSER_PATHS['edge'])
        self.browser_path_entry = ttk.Entry(
            self.browser_path_frame, 
            textvariable=self.browser_path_var, 
            font=("微软雅黑", 10)
        )
        self.browser_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        ttk.Button(
            self.browser_path_frame, 
            text="浏览", 
            command=self.browse_browser,
            width=8
        ).pack(side=tk.LEFT, padx=5)
        
        self.browser_mode_frame = ttk.Frame(self.browser_frame)
        self.browser_mode_frame.pack(fill=tk.X, pady=3)
        
        ttk.Label(self.browser_mode_frame, text="浏览器模式:", width=10).pack(side=tk.LEFT, padx=5)
        self.browser_mode_var = tk.StringVar(value="headed")
        
        ttk.Radiobutton(
            self.browser_mode_frame, 
            text="有头模式", 
            variable=self.browser_mode_var, 
            value="headed"
        ).pack(side=tk.LEFT, padx=10)
        
        ttk.Radiobutton(
            self.browser_mode_frame, 
            text="无头模式", 
            variable=self.browser_mode_var, 
            value="headless"
        ).pack(side=tk.LEFT, padx=10)
        

        
        self.button_frame = ttk.Frame(self.main_frame)
        self.button_frame.pack(fill=tk.X, pady=10)
        
        self.confirm_button = ttk.Button(
            self.button_frame,
            text="开始下载",
            command=self.start_download,
            style="Accent.TButton"
        )
        self.confirm_button.pack(side=tk.RIGHT, padx=5)
        
        ttk.Button(
            self.button_frame,
            text="清空状态",
            command=self.clear_status
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            self.button_frame,
            text="下载失败图片",
            command=self.download_failed_images
        ).pack(side=tk.LEFT, padx=5)
        

        
        ttk.Button(
            self.button_frame,
            text="退出",
            command=root.quit
        ).pack(side=tk.RIGHT, padx=5)
        
        self.url_progress_frame = ttk.LabelFrame(self.main_frame, text="获取图片URL进度", padding="10")
        self.url_progress_frame.pack(fill=tk.X, pady=5)
        
        self.url_info_frame = ttk.Frame(self.url_progress_frame)
        self.url_info_frame.pack(fill=tk.X, pady=5)
        
        self.url_progress_label = ttk.Label(
            self.url_info_frame,
            text="进度: 0/0 个章节",
            font=("微软雅黑", 10)
        )
        self.url_progress_label.pack(side=tk.LEFT, padx=5)
        
        self.url_progress_bar = ttk.Progressbar(
            self.url_progress_frame,
            orient=tk.HORIZONTAL,
            mode='determinate',
            length=600
        )
        self.url_progress_bar.pack(fill=tk.X, pady=5)
        
        self.progress_frame = ttk.LabelFrame(self.main_frame, text="下载进度", padding="10")
        self.progress_frame.pack(fill=tk.X, pady=5)
        
        self.info_frame = ttk.Frame(self.progress_frame)
        self.info_frame.pack(fill=tk.X, pady=5)
        
        self.progress_label = ttk.Label(
            self.info_frame,
            text="进度: 0/0 张图片",
            font=("微软雅黑", 10)
        )
        self.progress_label.pack(side=tk.LEFT, padx=5)
        
        self.speed_label = ttk.Label(
            self.info_frame,
            text="网速: 0 KB/s",
            font=("微软雅黑", 10)
        )
        self.speed_label.pack(side=tk.RIGHT, padx=5)
        
        self.progress_bar = ttk.Progressbar(
            self.progress_frame,
            orient=tk.HORIZONTAL,
            mode='determinate',
            length=600
        )
        self.progress_bar.pack(fill=tk.X, pady=5)
        

        
        self.status_frame = ttk.LabelFrame(self.main_frame, text="下载状态", padding="10")
        self.status_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.status_text = tk.Text(
            self.status_frame, 
            font=("微软雅黑", 10),
            wrap=tk.WORD,
            state=tk.DISABLED
        )
        self.status_text.pack(fill=tk.BOTH, expand=True)
        
        self.scrollbar = ttk.Scrollbar(self.status_text, command=self.status_text.yview)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.status_text.config(yscrollcommand=self.scrollbar.set)

        self.style = ttk.Style()
        self.style.configure(
            "Accent.TButton", 
            foreground="black", 
            background="black",
            font=("微软雅黑", 10, "bold")
        )
    
    def load_config(self):
        """加载配置文件"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载配置文件失败: {e}")
        return {}
    
    def save_config(self):
        """保存配置文件"""
        try:
            config = {
                'cookies_dir': self.cookies_path_var.get().strip()
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self.cookies_dir = config['cookies_dir']
        except Exception as e:
            print(f"保存配置文件失败: {e}")
    
    def update_login_status(self):
        """更新登录状态显示"""
        site_name = self.site_var.get()
        # 使用动态获取的需要登录网站列表
        if site_name in self.sites_requiring_login:
            temp_crawler = ComicCrawler.__new__(ComicCrawler)
            temp_crawler.site_name = site_name
            temp_crawler.cookies_dir = self.cookies_path_var.get().strip() or DEFAULT_COOKIES_DIR
            if temp_crawler.has_saved_cookies():
                self.login_status_label.config(text="[已保存登录信息]", foreground="green")
            else:
                self.login_status_label.config(text="[未登录]", foreground="gray")
    
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
            
            use_comic_id = site_name == "腾讯动漫" and self.use_comic_id_var.get()
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
                if comic_id:
                    self.append_status(f"正在通过ID访问漫画...")
                    result = crawler.search_comic(comic_name, comic_id)
                    if isinstance(result, tuple):
                        target_comic_tab, actual_comic_name = result
                        comic_name = actual_comic_name
                        self.append_status(f"获取到漫画名字: {comic_name}")
                    else:
                        target_comic_tab = result
                else:
                    self.append_status(f"正在搜索漫画: {comic_name}")
                    target_comic_tab = crawler.search_comic(comic_name)
                self.append_status("成功打开漫画详情页")
                
                self.append_status("正在获取封面图片...")
                cover_url = crawler.get_cover_image(target_comic_tab)
                
                self.append_status("正在获取章节数量...")
                total_chapters = crawler.get_chapter_count(target_comic_tab)
                
                # 计算实际下载范围
                actual_start = chapter_start
                actual_end = min(chapter_end, total_chapters) if chapter_end > 0 else total_chapters
                actual_chapters = actual_end - actual_start + 1
                
                self.append_status(f"总章节数: {total_chapters}, 将下载: {actual_start}-{actual_end} 共{actual_chapters}章")
                self.append_status(f"DEBUG: chapter_start={chapter_start}, chapter_end={chapter_end}, actual_start={actual_start}, actual_end={actual_end}")
                self.reset_url_progress(actual_chapters)
                
                self.append_status("正在收集章节图片链接...")
                max_workers = int(self.thread_var.get().strip())
                self.append_status(f"同时打开标签页数: {max_workers}")
                
                self.append_status(f"DEBUG: 传给collect_chapters_images: chapter_start={actual_start}, chapter_end={actual_end}")
                all_chapters_data = crawler.collect_chapters_images(
                    target_comic_tab, 
                    chapter_start=actual_start,
                    chapter_end=actual_end,
                    max_workers=max_workers, 
                    progress_callback=self.update_url_progress
                )

                self.append_status(f"将下载 {len(all_chapters_data)} 个章节")
                
                total_images = sum(len(c['herf_list']) for c in all_chapters_data)
                self.reset_progress(total_images)
                self.append_status(f"总计 {total_images} 张图片")
                
                download_path = self.download_path_var.get().strip()
                
                if cover_url:
                    self.append_status("正在下载封面...")
                    asyncio.run(download_cover_image(cover_url, comic_name, download_path if download_path else None))
                
                if all_chapters_data:
                    self.append_status("开始下载章节图片...")
                    download_thread_count = int(self.download_thread_var.get().strip())
                    use_thread_only = self.download_mode_var.get() == "thread_only"
                    first_timeout = int(self.first_timeout_var.get().strip())
                    retry_timeout = int(self.retry_timeout_var.get().strip())
                    if use_thread_only:
                        self.append_status(f"使用纯多线程模式，线程数: {download_thread_count}")
                    else:
                        self.append_status(f"使用协程模式")
                    self.append_status(f"首次超时: {first_timeout}秒, 重试超时: {retry_timeout}秒")
                    failed_downloads, failed_json_path, should_zip = asyncio.run(
                        download_all_chapters(
                            all_chapters_data,
                            comic_name,
                            download_path if download_path else None,
                            download_thread_count=download_thread_count,
                            progress_callback=self.update_progress,
                            max_retries=3,
                            use_thread_only=use_thread_only,
                            first_timeout=first_timeout,
                            retry_timeout=retry_timeout
                        )
                    )

                    if failed_downloads:
                        self.append_status(f"\n⚠️  注意：以下图片最终下载失败（共 {len(failed_downloads)} 张）:")
                        for failed in failed_downloads:
                            self.append_status(f"  - 章节{failed['chapter_num']}-第{failed['image_index']}张")
                            self.append_status(f"    路径: {failed['path']}")
                            self.append_status(f"    URL: {failed['url']}")
                        self.append_status(f"\n失败列表已保存到: {failed_json_path}")

                    if should_zip:
                        self.append_status("正在压缩文件夹...")
                        zip_main_folder(comic_name, download_path if download_path else None)

                        self.append_status(f"✓ 漫画《{comic_name}》下载完成！")
                        messagebox.showinfo("成功", f"漫画《{comic_name}》下载完成！")
                    else:
                        self.append_status("⚠️ 由于存在下载失败的图片，跳过压缩步骤")
                        self.append_status(f"✓ 漫画《{comic_name}》下载完成（有失败图片）！")
                        messagebox.showwarning("完成", f"漫画《{comic_name}》下载完成！\n\n注意：有 {len(failed_downloads)} 张图片最终下载失败。\n失败列表已保存到:\n{failed_json_path}\n\n请使用'下载失败图片'功能重新下载。")
                
            finally:
                crawler.page.close()
                self.append_status("浏览器已关闭")
                
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




def main():
    root = tk.Tk()
    app = GenericComicDownloaderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
