import time
import os
import json

from config import DEFAULT_COOKIES_DIR
from site_discovery import get_site_crawler_class


class ComicCrawler:
    def __init__(self, site_name, browser_path, headless=False, cookie_str=None, login_mode=False, cookies_dir=None):
        from DrissionPage import ChromiumOptions, ChromiumPage
        from urllib.parse import urlparse, unquote
        
        self.site_name = site_name
        
        # 动态加载网站爬虫类
        self.site_crawler_class = get_site_crawler_class(site_name)
        self.site_config = self.site_crawler_class.CONFIG
        
        self.locators = self.site_config['locators']
        self.image_attr = self.site_config['image_attr']
        self.cookie_str = cookie_str
        self.login_mode = login_mode
        self.login_completed = False
        self.cookies_dir = cookies_dir if cookies_dir else DEFAULT_COOKIES_DIR

        # 站点是否需要浏览器：纯requests实现的站点（如喜漫漫画）声明NEEDS_BROWSER=False，
        # 跳过浏览器启动（浏览器打开慢、且favcomic等站点代理出口被WAF拦截需直连）
        self.needs_browser = bool(getattr(self.site_crawler_class, 'NEEDS_BROWSER', True))

        # 未显式提供cookie_str时，尝试加载用户保存的Cookie字符串
        if not self.cookie_str:
            self.cookie_str = self.load_cookie_str()

        if not self.needs_browser:
            self.page = None
            self.tab = None
            print(f"站点 {site_name} 无需浏览器（纯HTTP实现），跳过浏览器启动")
            self.site_crawler = self.site_crawler_class(self)
            if self.cookie_str:
                self.set_cookie()
            return

        print(f"正在初始化浏览器...")
        co = ChromiumOptions()
        co.set_browser_path(browser_path)
        
        # 查找可用端口并直接设置地址，避免端口冲突导致浏览器无法启动或不显示窗口
        import socket
        debug_port = None
        for port in range(9223, 9323):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('127.0.0.1', port))
                    debug_port = port
                    break
            except OSError:
                continue
        if debug_port is None:
            import random
            debug_port = random.randint(9223, 9322)
        co.set_local_port(debug_port)
        print(f"使用调试端口: {debug_port}")
        
        # 每次启动使用独立的用户数据临时目录，避免复用残留目录导致浏览器进程连接异常
        import tempfile
        user_data_path = tempfile.mkdtemp(prefix='comic_dl_')
        co.set_user_data_path(user_data_path)
        
        # 禁用窗口遮挡检测与后台节流：窗口被遮挡/最小化时Chrome会把rAF节流到~1fps，
        # 依赖rAF的阅读器（如B漫）翻页动画/图片解密会卡死在第1页
        co.set_argument("--disable-backgrounding-occluded-windows")
        co.set_argument("--disable-renderer-backgrounding")
        co.set_argument("--disable-background-timer-throttling")
        co.set_argument("--disable-features=CalculateNativeWinOcclusion")
        
        if headless:
            co.headless()
            co.set_argument("--disable-gpu")
            co.set_argument("--no-sandbox")
            co.set_argument("--disable-dev-shm-usage")
            # 禁用Edge SmartScreen，避免无头模式下安全拦截导致页面无法访问
            co.set_argument("--disable-features=SmartScreen")
            # 设置正常UA并去除自动化特征，避免被Cloudflare等反爬检测阻止fetch请求
            co.set_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0")
            co.set_argument("--disable-blink-features=AutomationControlled")
            print("已启用无头模式")
        else:
            print("已启用有头模式")

        # 直连模式：站点CONFIG声明direct_connect时禁用系统代理（浏览器直连）
        # 适用于代理出口IP被站点WAF拉黑（直连200/代理403）的站点，如喜漫漫画
        if self.site_config.get('direct_connect'):
            co.set_argument('--no-proxy-server')
            print("该站点启用直连模式（禁用系统代理，浏览器直连访问）")
        
        try:
            self.page = ChromiumPage(co)
            self.tab = self.page
        except Exception as e:
            print(f"浏览器连接失败: {e}")
            print("尝试清理残留的调试浏览器进程并重新启动...")
            self._kill_leftover_debug_browsers()
            time.sleep(2)
            self.page = ChromiumPage(co)
            self.tab = self.page
        
        # 初始化网站爬虫实例
        self.site_crawler = self.site_crawler_class(self)

        # 有Cookie字符串时自动应用（登录态），后续所有请求/标签页均生效
        if self.cookie_str:
            self.set_cookie()

    def get_cookie_str_path(self):
        if not os.path.exists(self.cookies_dir):
            os.makedirs(self.cookies_dir)
        return os.path.join(self.cookies_dir, f"{self.site_name}_cookie_str.txt")

    def save_cookie_str(self, cookie_str):
        """保存用户粘贴的Cookie字符串到文件"""
        try:
            cookie_str = (cookie_str or '').strip()
            path = self.get_cookie_str_path()
            if not cookie_str:
                if os.path.exists(path):
                    os.remove(path)
                return True
            with open(path, 'w', encoding='utf-8') as f:
                f.write(cookie_str)
            print(f"Cookie字符串已保存到: {path}")
            return True
        except Exception as e:
            print(f"保存Cookie字符串失败: {e}")
            return False

    def load_cookie_str(self):
        """加载已保存的Cookie字符串，无则返回None"""
        try:
            path = self.get_cookie_str_path()
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    s = f.read().strip()
                if s:
                    print(f"已从文件加载Cookie字符串: {path}")
                    return s
        except Exception as e:
            print(f"加载Cookie字符串失败: {e}")
        return None

    def has_cookie_str(self):
        return os.path.exists(self.get_cookie_str_path())

    def clear_cookie_str(self):
        try:
            path = self.get_cookie_str_path()
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            print(f"清除Cookie字符串失败: {e}")
    
    def _kill_leftover_debug_browsers(self):
        """仅清理带调试端口的残留浏览器进程（上次异常退出遗留），
        不影响用户正常使用的浏览器"""
        import subprocess
        import re
        for name in ('msedge.exe', 'chrome.exe'):
            try:
                r = subprocess.run(
                    ['wmic', 'process', 'where', f"name='{name}'",
                     'get', 'ProcessId,CommandLine', '/format:csv'],
                    capture_output=True, text=True, encoding='gbk', errors='ignore')
                for line in r.stdout.splitlines():
                    if 'remote-debugging-port' in line:
                        m = re.search(r'(\d+)\s*$', line.strip())
                        if m:
                            subprocess.run(['taskkill', '/F', '/PID', m.group(1)],
                                           capture_output=True)
            except Exception:
                pass

    def get_cookies_path(self):
        if not os.path.exists(self.cookies_dir):
            os.makedirs(self.cookies_dir)
        return os.path.join(self.cookies_dir, f"{self.site_name}_cookies.json")
    
    def save_cookies(self):
        if not self.needs_browser:
            print("该站点无需浏览器（纯HTTP），不保存浏览器Cookie")
            return False
        try:
            cookies = self.tab.cookies()
            cookies_path = self.get_cookies_path()
            with open(cookies_path, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            print(f"Cookie已保存到: {cookies_path}")
            return True
        except Exception as e:
            print(f"保存Cookie失败: {e}")
            return False
    
    def load_cookies(self):
        if not self.needs_browser:
            return False
        try:
            cookies_path = self.get_cookies_path()
            if not os.path.exists(cookies_path):
                print(f"Cookie文件不存在: {cookies_path}")
                return False
            
            with open(cookies_path, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            
            self.tab.set.cookies(cookies)
            print(f"已从文件加载Cookie: {cookies_path}")
            return True
        except Exception as e:
            print(f"加载Cookie失败: {e}")
            return False
    
    def has_saved_cookies(self):
        if not self.needs_browser:
            return False
        cookies_path = self.get_cookies_path()
        return os.path.exists(cookies_path)
    
    def open_login_page(self):
        if not self.needs_browser:
            print(f"{self.site_name} 无需浏览器登录，请使用Cookie字符串输入")
            return False
        print(f"正在打开 {self.site_name} 登录页面...")
        self.tab.get(self.site_config['site_url'])
        print(f"请在浏览器中完成登录操作")
        print(f"登录完成后，请在GUI界面点击'登录完成'按钮")
        return True
    
    def complete_login(self):
        self.save_cookies()
        self.login_completed = True
        print(f"登录完成，Cookie已保存")
        return True
    
    def parse_cookie_str(self, cookie_str, domain):
        cookies = []
        items = [item.strip() for item in cookie_str.split(';') if item.strip()]
        
        for item in items:
            if '=' in item:
                name, value = item.split('=', 1)
                name = name.strip()
                value = value.strip()
                
                # 注意：不能对value做unquote！浏览器发送Cookie头时保持原始编码，
                # 解码会破坏SESSDATA等含%编码值的Cookie导致登录态失效
                
                cookies.append({
                    'name': name,
                    'value': value,
                    'domain': domain,
                    'path': '/'
                })
            else:
                cookies.append({
                    'name': item.strip(),
                    'value': '',
                    'domain': domain,
                    'path': '/'
                })
        
        return cookies
    
    def set_cookie(self):
        if not self.cookie_str:
            return False
        if not self.needs_browser:
            # 纯requests站点：cookie_str 由站点爬虫的请求头直接携带
            print("该站点无需浏览器，Cookie将由爬虫请求头直接携带")
            return True
        try:
            from urllib.parse import urlparse
            
            print("正在设置Cookie...")
            netloc = urlparse(self.site_config['site_url']).netloc
            # 使用主域（如 manga.bilibili.com → .bilibili.com），覆盖所有子域API请求
            parts = netloc.split(':')[0].split('.')
            domain = '.' + '.'.join(parts[-2:]) if len(parts) >= 2 else netloc
            
            cookies = self.parse_cookie_str(self.cookie_str, domain)
            print(f"解析到 {len(cookies)} 个Cookie项 (domain={domain})")
            
            self.tab.set.cookies(cookies)
            print("Cookie已设置（后续访问自动生效）")
            return True
        except Exception as e:
            print(f"设置Cookie失败: {e}")
            return False
    
    def search_comic(self, comic_name, comic_id=None):
        return self.site_crawler.search_comic(comic_name, comic_id)
    
    def get_cover_image(self, target_comic_tab):
        # 优先使用站点爬虫自定义的get_cover_image
        if hasattr(self.site_crawler, 'get_cover_image') and callable(self.site_crawler.get_cover_image):
            return self.site_crawler.get_cover_image(target_comic_tab)
        # 默认实现：用locators和image_attr
        try:
            coverimg_xpath = self.locators['cover_image']
            coverimg_url = target_comic_tab.ele(coverimg_xpath).attr(self.image_attr)
            print(f"封面图片URL: {coverimg_url}")
            return coverimg_url
        except Exception as e:
            print(f"获取封面图片失败: {e}")
            return None
    
    def get_chapter_count(self, target_comic_tab):
        return self.site_crawler.get_chapter_count(target_comic_tab)
    
    def collect_chapters_images(self, target_comic_tab, chapter_start=1, chapter_end=0, max_threads=10, progress_callback=None):
        return self.site_crawler.collect_chapters_images(
            target_comic_tab,
            chapter_start=chapter_start,
            chapter_end=chapter_end,
            max_threads=max_threads,
            progress_callback=progress_callback
        )
