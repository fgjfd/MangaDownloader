import time
import os
import json

from config import SITES, SITES_REQUIRING_LOGIN, DEFAULT_COOKIES_DIR
from sites.kuaikan_crawler import KuaikanCrawler
from sites.haoduoman_crawler import HaoduomanCrawler
from sites.mangacopy_crawler import MangacopyCrawler
from sites.tencent_crawler import TencentCrawler
from sites.boluobao_crawler import BoluobaoCrawler


class ComicCrawler:
    def __init__(self, site_name, browser_path, headless=False, cookie_str=None, login_mode=False, cookies_dir=None):
        from DrissionPage import ChromiumOptions, ChromiumPage
        from urllib.parse import urlparse, unquote
        
        self.site_name = site_name
        self.site_config = SITES[site_name]
        self.locators = self.site_config['locators']
        self.image_attr = self.site_config['image_attr']
        self.cookie_str = cookie_str
        self.login_mode = login_mode
        self.login_completed = False
        self.cookies_dir = cookies_dir if cookies_dir else DEFAULT_COOKIES_DIR
        
        print(f"正在初始化浏览器...")
        co = ChromiumOptions().set_paths(browser_path)
        
        import random
        debug_port = random.randint(9223, 9322)
        co.set_argument(f"--remote-debugging-port={debug_port}")
        
        if headless:
            co.headless()
            co.set_argument("--disable-gpu")
            co.set_argument("--no-sandbox")
            co.set_argument("--disable-dev-shm-usage")
            print("已启用无头模式")
        else:
            print("已启用有头模式")
        
        try:
            self.page = ChromiumPage(co)
            self.tab = self.page
        except Exception as e:
            print(f"浏览器连接失败: {e}")
            print("尝试关闭现有浏览器进程并重新启动...")
            import subprocess
            try:
                subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
                subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'], capture_output=True)
                time.sleep(2)
            except:
                pass
            self.page = ChromiumPage(co)
            self.tab = self.page
        
        self._init_site_crawler()
    
    def _init_site_crawler(self):
        if self.site_name == '快看':
            self.site_crawler = KuaikanCrawler(self)
        elif self.site_name == '好多漫':
            self.site_crawler = HaoduomanCrawler(self)
        elif self.site_name == '拷贝漫画':
            self.site_crawler = MangacopyCrawler(self)
        elif self.site_name == '腾讯动漫':
            self.site_crawler = TencentCrawler(self)
        elif self.site_name == '菠萝包':
            self.site_crawler = BoluobaoCrawler(self)
        else:
            raise ValueError(f"不支持的站点: {self.site_name}")
    
    def get_cookies_path(self):
        if not os.path.exists(self.cookies_dir):
            os.makedirs(self.cookies_dir)
        return os.path.join(self.cookies_dir, f"{self.site_name}_cookies.json")
    
    def save_cookies(self):
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
        cookies_path = self.get_cookies_path()
        return os.path.exists(cookies_path)
    
    def open_login_page(self):
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
        from urllib.parse import unquote
        
        cookies = []
        items = [item.strip() for item in cookie_str.split(';') if item.strip()]
        
        for item in items:
            if '=' in item:
                name, value = item.split('=', 1)
                name = name.strip()
                value = value.strip()
                
                try:
                    value = unquote(value)
                except:
                    pass
                
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
        
        try:
            from urllib.parse import urlparse
            
            print("正在设置Cookie...")
            domain = urlparse(self.site_config['site_url']).netloc
            
            cookies = self.parse_cookie_str(self.cookie_str, domain)
            print(f"解析到 {len(cookies)} 个Cookie项")
            
            self.tab.set.cookies(cookies)
            print("Cookie已设置")
            
            self.tab.refresh()
            print("Cookie已应用")
            return True
        except Exception as e:
            print(f"设置Cookie失败: {e}")
            return False
    
    def search_comic(self, comic_name, comic_id=None):
        return self.site_crawler.search_comic(comic_name, comic_id)
    
    def get_cover_image(self, target_comic_tab):
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
    
    def collect_chapters_images(self, target_comic_tab, chapter_start=1, chapter_end=0, max_workers=10, progress_callback=None):
        return self.site_crawler.collect_chapters_images(
            target_comic_tab, 
            chapter_start=chapter_start,
            chapter_end=chapter_end,
            max_threads=max_workers,
            progress_callback=progress_callback
        )
