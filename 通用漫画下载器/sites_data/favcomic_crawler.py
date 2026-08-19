# -*- coding: utf-8 -*-
"""
喜漫漫画 (favcomic.xyz) 爬虫

图片全站加密，但**解密算法已逆向**，纯 HTTP 下载 + Python 解密（无需浏览器）：

加密协议（从 decrypt.chapter.worker.js 动态生成代码还原）：
- 图片文件结构: [iv 16字节][AES-CBC 密文]，PKCS7 padding
- 密钥: base64Key 解码后按 UTF-8 解析（16字节 = AES-128）
- base64Key 为站点固定值（多章节/多时间/多浏览器实测一致）：
  btoa('6X+b6.E>bsXb}+=N') = 'NlgrYjYuRT5ic1hifSs9Tg=='
  若解密结果非图片魔数（RIFF/WEBP/FFD8/8950），说明站点更换密钥，
  需重新用浏览器 hook btoa 捕获新 key（见 skill special-strategies.md）
- 下载时带 Referer（CONFIG['image_referer']），无 Referer 403

访问策略：
- 代理出口 IP 被站点 WAF 拉黑（直连200/代理403）→ requests 直连优先，失败回退系统代理
- 页面 SSR 明文（搜索/详情/章节列表全量内联），无需浏览器

登录：
- 无浏览器登录（REQUIRES_LOGIN=False，GUI不显示"打开登录"按钮）
- 支持 Cookie 字符串输入（SUPPORTS_COOKIE_INPUT=True）：会员/付费章节
  未登录只返回3张预览，登录后完整返回
"""
import time
import threading
from urllib.parse import quote

import requests
from lxml import etree

from utils import is_normal_url
from downloader import get_system_proxy


class FavcomicCrawler:
    """喜漫漫画爬虫 (https://www.favcomic.xyz/)"""

    # ========== 元数据 ==========
    SITE_NAME = '喜漫漫画'
    SITE_URL = 'https://www.favcomic.xyz/'
    REQUIRES_LOGIN = False
    # 纯requests实现（SSR明文 + 解密），无需浏览器
    NEEDS_BROWSER = False
    # 登录非必需，但 Cookie 解锁会员/付费章节（完整图片列表），支持 Cookie 输入
    SUPPORTS_COOKIE_INPUT = True

    # ========== 配置 ==========
    CONFIG = {
        'site_url': 'https://www.favcomic.xyz/',
        'locators': {
            'search_result': 'xpath:/html/body/div[2]/ul/li[1]//a[contains(@href, "/comic/detail/")]',
            'cover_image': 'xpath:/html/body/div[4]/div[1]/div/img',
            'chapter_item': 'xpath://a[contains(@href, "/comic/chapter/")]',
        },
        'image_attr': 'data-src',
        'chapter_group_size': None,
        # 图片CDN防盗链：下载时自动带Referer
        'image_referer': 'https://www.favcomic.xyz/',
        # 图片解密配置（downloader 自动执行：下载字节 → AES-CBC 解密 → 转JPEG → 保存）
        'decrypt': {
            'mode': 'aes_cbc',          # 通用 AES-CBC 解密（iv=密文前16字节）
            'base64_key': 'NlgrYjYuRT5ic1hifSs9Tg==',
            'convert': 'jpeg',          # 解密后转JPEG（原图webp，兼容所有阅读器）
        },
    }

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36',
        'Accept-Encoding': 'gzip, deflate',
    }

    def __init__(self, crawler):
        self.crawler = crawler
        self.locators = crawler.locators
        self.image_attr = crawler.image_attr
        self._comic_info = None  # search_comic 的详情数据缓存
        self._system_proxy = None
        # Session 复用连接（favcomic 直连 TLS 握手慢，复用可显著提速）
        self._session = requests.Session()
        self._session.headers.update(self.HEADERS)

    # ========== 内部工具 ==========

    def _get_cookie_header(self):
        """从框架取已保存的Cookie字符串（用户GUI输入或文件加载）"""
        cookie_str = getattr(self.crawler, 'cookie_str', None)
        if cookie_str:
            return {'Cookie': cookie_str}
        return {}

    def _fetch(self, url, retries=3, timeout=25):
        """GET请求（Session复用连接）：直连优先，失败回退系统代理"""
        last_err = None
        proxies_list = [None]
        try:
            if self._system_proxy is None:
                self._system_proxy = get_system_proxy()
            if self._system_proxy:
                proxies_list.append(self._system_proxy)
        except Exception:
            pass

        for attempt in range(retries):
            for proxies in proxies_list:
                try:
                    headers = dict(self.HEADERS)
                    headers.update(self._get_cookie_header())
                    resp = self._session.get(url, headers=headers, timeout=timeout, proxies=proxies)
                    if resp.status_code == 200 and len(resp.text) > 500:
                        return resp.text
                    last_err = f'状态码{resp.status_code}'
                except Exception as e:
                    last_err = str(e)[:80]
            if attempt < retries - 1:
                time.sleep(1.5)
        raise Exception(f'请求失败 {url}: {last_err}')

    @staticmethod
    def _parse(html):
        return etree.HTML(html)

    @staticmethod
    def _extract_detail_id(url):
        """从 /comic/detail/{id} 或 /comic/chapter/{id} 提取id"""
        return url.rstrip('/').split('/')[-1]

    @staticmethod
    def _is_button_text(title):
        """判断是否为阅读按钮文案（开始/继续/上次读到），其cid与真实章节重复"""
        t = title or ''
        for kw in ('开始阅读', '继续阅读', '从头', '上次', '读到'):
            if kw in t:
                return True
        return False

    @staticmethod
    def _is_chapter_like_title(title):
        """判断标题是否含"第N话/章/卷"（章节名特征，支持小数如第530.5话）"""
        import re
        return bool(re.search(r'第\s*\d+(\.\d+)?\s*[话卷章]', title or ''))

    @staticmethod
    def _clean_chapter_title(title):
        """清洗章节名：去价格（￥0/￥1.5）、会员/付费标签，压缩空白"""
        import re
        t = ' '.join((title or '').split())
        t = re.sub(r'￥\s*\d+(\.\d+)?', '', t)
        t = re.sub(r'会员专享|付费|VIP', '', t)
        return ' '.join(t.split()).strip()

    # ========== 必须实现的方法 ==========

    def search_comic(self, comic_name, comic_id=None):
        """搜索漫画并抓取详情页数据，返回详情信息 dict（纯 requests）"""
        if comic_id:
            detail_url = f"https://www.favcomic.xyz/comic/detail/{comic_id}"
        else:
            search_url = f"https://www.favcomic.xyz/search?keyword={quote(comic_name)}"
            print(f"正在搜索漫画: {comic_name}")
            print(f"搜索URL: {search_url}")
            html = self._fetch(search_url)
            tree = self._parse(html)

            result_a = tree.xpath(
                '/html/body/div[2]/ul/li[1]//a[contains(@href, "/comic/detail/")]')
            if not result_a:
                result_a = tree.xpath('//a[contains(@href, "/comic/detail/")]')
            if not result_a:
                raise Exception(f"搜索 '{comic_name}' 未找到结果")

            detail_url = 'https://www.favcomic.xyz' + result_a[0].get('href')
            print(f"搜索结果: {detail_url}")

        detail_id = self._extract_detail_id(detail_url)
        print(f"正在获取详情页: {detail_url}")
        html = self._fetch(detail_url)
        tree = self._parse(html)

        # 标题
        title = ''
        h1 = tree.xpath('//h1')
        if h1:
            title = (h1[0].text or '').strip()

        # 封面（详情页第一个 app/cover 图，密文URL，下载时解密）
        cover_url = ''
        cover_imgs = tree.xpath('//img[contains(@data-src, "app/cover/")]/@data-src')
        if cover_imgs:
            cover_url = cover_imgs[0]

        # 章节列表（页面顺序即从旧到新）
        # 详情页顶部存在"开始阅读/从头开始阅读/继续阅读/上次读到第X话"按钮链接，
        # 其cid与章节列表中的真实章节重复。处理策略：
        # 1. 先收集 cid -> 全部标题，为每个cid挑选最佳标题（含"第N话"的章节名优先）；
        # 2. 再按DOM顺序遍历，跳过按钮位置链接（避免按钮占位打乱章节序号），
        #    真实章节位置用最佳标题。
        # 真实章节标题格式多样（"第1话 xxx"/"564"/"通知"），仅靠文本无法区分，
        # 必须依赖"按钮cid与真实章节cid重复"这一特征。
        cid_titles = {}
        cid_hrefs = {}
        for a in tree.xpath('//a[contains(@href, "/comic/chapter/")]'):
            href = a.get('href') or ''
            cid = self._extract_detail_id(href)
            if not cid:
                continue
            ch_title = self._clean_chapter_title(''.join(a.itertext()))
            cid_titles.setdefault(cid, []).append(ch_title)
            cid_hrefs.setdefault(cid, href)

        def _pick_best_title(titles):
            """从同cid的多个标题中选最像章节名的
            （含"第N话"且非按钮文案优先，其次任意非按钮文案）
            """
            for t in titles:
                if self._is_chapter_like_title(t) and not self._is_button_text(t):
                    return t
            for t in titles:
                if not self._is_button_text(t):
                    return t
            return titles[0]

        chapters = []
        seen = set()
        for a in tree.xpath('//a[contains(@href, "/comic/chapter/")]'):
            href = a.get('href') or ''
            cid = self._extract_detail_id(href)
            if not cid:
                continue
            ch_title = self._clean_chapter_title(''.join(a.itertext()))
            # 跳过按钮链接位置（不占章节序号），真实章节位置才收集
            if self._is_button_text(ch_title):
                continue
            if cid in seen:
                continue
            seen.add(cid)
            chapters.append({
                'id': cid,
                'url': 'https://www.favcomic.xyz' + (cid_hrefs.get(cid) or href),
                'title': _pick_best_title(cid_titles.get(cid) or [ch_title]),
            })
        print(f"漫画标题: {title}, 章节数: {len(chapters)}")

        self._comic_info = {
            'comic_id': detail_id,
            'title': title,
            'cover_url': cover_url,
            'chapters': chapters,
        }
        return self._comic_info

    def get_chapter_count(self, target_comic_tab):
        """获取章节总数（target_comic_tab 为 search_comic 返回的详情信息 dict）"""
        if self._comic_info:
            return len(self._comic_info['chapters'])
        return 0

    def get_chapter_image_urls(self, chapter_url):
        """抓章节页提取加密图片URL列表（下载时逐张解密）"""
        try:
            html = self._fetch(chapter_url, retries=2)
            tree = self._parse(html)
            urls = tree.xpath(
                '//div[contains(@class, "comic_chapter_box")]'
                '//img[contains(@class, "encrypted-image")]/@data-src')
            return [u for u in urls if is_normal_url(u)]
        except Exception as e:
            print(f"获取章节图片URL失败: {e}")
            return []

    def collect_chapters_images(self, target_comic_tab, chapter_start=1, chapter_end=0,
                                max_threads=3, progress_callback=None):
        """收集指定章节范围内的所有图片URL（纯requests，多线程抓取章节页）"""
        if not self._comic_info:
            print("缺少漫画详情数据，请先 search_comic")
            return []

        chapters = self._comic_info['chapters']
        all_chapters_num = len(chapters)
        print(f"总章节数: {all_chapters_num}")

        if all_chapters_num == 0:
            print("未找到任何章节")
            return []

        actual_start = max(chapter_start, 1)
        actual_end = min(chapter_end, all_chapters_num) if chapter_end > 0 else all_chapters_num

        if actual_start > all_chapters_num:
            print(f"起始章节 {actual_start} 超过总章节数 {all_chapters_num}")
            return []

        print(f"将收集第 {actual_start}-{actual_end} 章，共 {actual_end - actual_start + 1} 章")

        all_chapters_data = []
        lock = threading.Lock()
        total = actual_end - actual_start + 1
        done = [0]

        def worker(chapter):
            try:
                urls = self.get_chapter_image_urls(chapter['url'])
                with lock:
                    all_chapters_data.append({
                        'chapter_num': chapter['chapter_num'],
                        'title': chapter.get('title', ''),
                        'herf_list': urls,
                        'url': chapter['url'],
                    })
                    done[0] += 1
                    if progress_callback:
                        progress_callback()
                    print(f"[{done[0]}/{total}] 第{chapter['chapter_num']}章: "
                          f"{len(urls)}张图片")
            except Exception as e:
                print(f"第{chapter['chapter_num']}章收集失败: {e}")
                with lock:
                    all_chapters_data.append({
                        'chapter_num': chapter['chapter_num'],
                        'title': chapter.get('title', ''),
                        'herf_list': [],
                        'url': chapter['url'],
                    })
                    done[0] += 1
                    if progress_callback:
                        progress_callback()

        threads = []
        for num in range(actual_start, actual_end + 1):
            chapter = dict(chapters[num - 1])
            chapter['chapter_num'] = num
            t = threading.Thread(target=worker, args=(chapter,))
            threads.append(t)
            t.start()
            while len([x for x in threads if x.is_alive()]) >= max_threads:
                time.sleep(0.2)

        for t in threads:
            t.join()

        all_chapters_data.sort(key=lambda x: x['chapter_num'])
        return all_chapters_data

    # ========== 可选重写 ==========

    def get_cover_image(self, target_comic_tab):
        """封面密文URL（下载时由 downloader 解密）"""
        if self._comic_info:
            return self._comic_info.get('cover_url')
        return None
