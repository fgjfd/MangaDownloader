# -*- coding: utf-8 -*-
"""
拷贝漫画（caigle.org）爬虫 —— 混合方案（浏览器取章节列表 + requests 收集图片）

站点结构（2026-08 探查确认，MCCMS 系统 / baozi_pc 模板）：
- 搜索页  GET /search/{关键词}.html → SSR 明文，结果在 a.comics-card__poster
  （href=/books/{id}.html，title=漫画名，src=封面图，另含 amp-img）
- 详情页  /books/{id}.html → SSR 有 h1 标题、封面（img[src*=zzxxv]）
  但**章节列表由 Vue 组件 JS 动态加载**（SSR 仅含最新1章+阅读按钮），
  必须浏览器渲染后取 a.comics-chapters__item
- 章节列表项  a.comics-chapters__item，href=/chook/{cid}，从新到旧排列，
  含重复渲染（"阅读"按钮/最新章节 与真实章节 href 重复），需按 href 去重
- 章节阅读页  /chook/{cid} → 图片**SSR 明文**在 img.lazy-read 的 data-original
  （完整 CDN URL，如 http://f2-img.534zm.com/colafm/.../xxx.webp），
  带 Referer 可直连下载，无需解密、无需浏览器渲染
- 图片防盗链：CDN 需 Referer（CONFIG['image_referer']）

方案：
- search_comic：浏览器打开详情页（渲染章节列表），返回 ChromiumTab（框架契约）
- get_chapter_count / _get_chapter_urls_from_page：从渲染后 DOM 用 xpath 取章节链接
- 图片收集：requests 直抓章节页 SSR 的 data-original（快，免浏览器）
"""
import time
import threading
from urllib.parse import quote

import requests

from utils import is_normal_url


class CaigleCrawler:
    """拷贝漫画爬虫 (https://www.caigle.org/)"""

    # ========== 元数据 ==========
    SITE_NAME = '拷贝漫画2'
    SITE_URL = 'https://www.caigle.org/category/'
    REQUIRES_LOGIN = False

    # ========== 配置 ==========
    CONFIG = {
        'site_url': 'https://www.caigle.org/',
        'locators': {
            'search_result': 'xpath://a[contains(@class, "comics-card__poster")]',
            'cover_image': 'xpath://img[contains(@src, "zzxxv")]',
            'all_chapters_btn': 'xpath://a[contains(@class, "comics-chapters__item")]',
            'chapter_item': 'xpath://a[contains(@class, "comics-chapters__item")]',
            'chapter_image': 'xpath://img[contains(@class, "lazy-read")]',
        },
        'image_attr': 'data-original',
        'chapter_group_size': None,
        # 图片 CDN 防盗链：下载时自动带 Referer
        'image_referer': 'https://www.caigle.org/',
    }

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36',
        'Accept-Encoding': 'gzip, deflate',
    }

    def __init__(self, crawler):
        self.crawler = crawler
        self.locators = crawler.locators
        self.image_attr = crawler.image_attr
        self._session = requests.Session()
        self._session.headers.update(self.HEADERS)

    # ========== 内部工具 ==========

    def _get_cookie_header(self):
        """从框架取已保存的Cookie字符串"""
        cookie_str = getattr(self.crawler, 'cookie_str', None)
        if cookie_str:
            return {'Cookie': cookie_str}
        return {}

    def _fetch(self, url, retries=3, timeout=20):
        """requests GET（直连优先）"""
        last_err = None
        for attempt in range(retries):
            try:
                headers = dict(self.HEADERS)
                headers.update(self._get_cookie_header())
                resp = self._session.get(url, headers=headers, timeout=timeout)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    return resp.content.decode('utf-8', errors='replace')
                last_err = f'状态码{resp.status_code}'
            except Exception as e:
                last_err = str(e)[:80]
            if attempt < retries - 1:
                time.sleep(1.5)
        raise Exception(f'请求失败 {url}: {last_err}')

    @staticmethod
    def _extract_chook_id(url):
        """从 /chook/{cid} 提取 cid"""
        try:
            return url.rstrip('/').split('/')[-1]
        except Exception:
            return ''

    # ========== 必须实现的方法 ==========

    def search_comic(self, comic_name, comic_id=None):
        """搜索漫画并打开详情页（浏览器渲染章节列表），返回详情页标签页"""
        if comic_id:
            detail_url = f"https://www.caigle.org/books/{comic_id}.html"
            print(f"通过ID打开: {detail_url}")
        else:
            search_url = f"https://www.caigle.org/search/{quote(comic_name)}.html"
            print(f"正在搜索漫画: {comic_name}")
            print(f"搜索URL: {search_url}")

            html = self._fetch(search_url)
            from lxml import etree
            tree = etree.HTML(html)
            result_a = tree.xpath('//a[contains(@class, "comics-card__poster")]')
            if not result_a:
                raise Exception(f"搜索 '{comic_name}' 未找到结果")
            href = result_a[0].get('href')
            if href and not href.startswith('http'):
                href = 'https://www.caigle.org' + href
            print(f"搜索结果: {href}")
            detail_url = href

        # 浏览器打开详情页，等待章节列表 JS 渲染
        target_comic_tab = self.crawler.page.new_tab(detail_url)
        # 等待章节列表加载（懒加载 JS 渲染）
        for _ in range(15):
            try:
                chapters = target_comic_tab.eles(self.locators['chapter_item'], timeout=1)
                if len(chapters) > 3:
                    break
            except Exception:
                pass
            time.sleep(1)
        return target_comic_tab

    def get_chapter_count(self, target_comic_tab):
        """获取章节总数（去重后）"""
        try:
            chapter_eles = target_comic_tab.eles(self.locators['chapter_item'], timeout=10)
            hrefs = set()
            for ele in chapter_eles:
                href = ele.attr('href')
                if href:
                    hrefs.add(href)
            return len(hrefs)
        except Exception as e:
            print(f"获取章节数失败: {e}")
            return 0

    def _get_chapter_urls_from_page(self, target_comic_tab):
        """从渲染后详情页取全部章节链接（去重，从旧到新排序编号）"""
        chapter_urls = []
        try:
            chapter_eles = target_comic_tab.eles(self.locators['chapter_item'], timeout=10)
            seen = set()
            items = []
            for ele in chapter_eles:
                href = ele.attr('href')
                if not href:
                    continue
                if href not in seen:
                    seen.add(href)
                    if not href.startswith('http'):
                        href = 'https://www.caigle.org' + href
                    title = ' '.join((ele.text or '').split())
                    items.append({'url': href, 'title': title, 'cid': self._extract_chook_id(href)})

            # 页面从新到旧排列 → 反转为从旧到新并重新编号
            items.reverse()
            for i, item in enumerate(items, 1):
                chapter_urls.append({
                    'num': i,
                    'url': item['url'],
                    'title': item['title'] or f"第{i}章",
                    'cid': item['cid'],
                })
            print(f"获取到 {len(chapter_urls)} 个唯一章节")
        except Exception as e:
            print(f"获取章节URL列表失败: {e}")
        return chapter_urls

    def get_chapter_image_urls(self, chapter_url):
        """requests 直抓章节页 SSR 的 data-original 图片 URL（明文）"""
        herf_list = []
        try:
            html = self._fetch(chapter_url, retries=2)
            from lxml import etree
            tree = etree.HTML(html)
            imgs = tree.xpath('//img[contains(@class, "lazy-read")]/@data-original')
            for src in imgs:
                if src and is_normal_url(src):
                    herf_list.append(src)
            if not herf_list:
                # 回退：任何带 data-original 的图片
                imgs2 = tree.xpath('//img[@data-original]/@data-original')
                herf_list = [s for s in imgs2 if s and is_normal_url(s)]
        except Exception as e:
            print(f"获取章节图片URL失败: {e}")
        return herf_list

    def collect_chapters_images(self, target_comic_tab, chapter_start=1, chapter_end=0,
                                max_threads=3, progress_callback=None):
        """收集指定章节范围内的所有图片URL（requests 多线程）"""
        print(f"设置最大同时收集线程数: {max_threads}")

        chapter_urls = self._get_chapter_urls_from_page(target_comic_tab)
        all_chapters_num = len(chapter_urls)
        print(f"总章节数: {all_chapters_num}")

        if all_chapters_num == 0:
            print("未找到任何章节链接")
            return []

        actual_start = max(chapter_start, 1)
        actual_end = min(chapter_end, all_chapters_num) if chapter_end > 0 else all_chapters_num

        if actual_start > all_chapters_num:
            print(f"起始章节 {actual_start} 超过总章节数 {all_chapters_num}")
            return []

        print(f"将下载第 {actual_start}-{actual_end} 章，共 {actual_end - actual_start + 1} 章")

        all_chapters_data = []
        lock = threading.Lock()
        total = actual_end - actual_start + 1
        done = [0]

        def worker(chapter):
            try:
                urls = self.get_chapter_image_urls(chapter['url'])
                with lock:
                    all_chapters_data.append({
                        'chapter_num': chapter['num'],
                        'title': chapter.get('title', ''),
                        'herf_list': urls,
                        'url': chapter['url'],
                    })
                    done[0] += 1
                    if progress_callback:
                        progress_callback()
                    print(f"[{done[0]}/{total}] 第{chapter['num']}章: {len(urls)}张图片")
            except Exception as e:
                print(f"第{chapter['num']}章收集失败: {e}")
                with lock:
                    all_chapters_data.append({
                        'chapter_num': chapter['num'],
                        'title': chapter.get('title', ''),
                        'herf_list': [],
                        'url': chapter['url'],
                    })
                    done[0] += 1
                    if progress_callback:
                        progress_callback()

        threads = []
        for idx in range(actual_start - 1, actual_end):
            chapter = chapter_urls[idx]
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
        """详情页封面（浏览器渲染后的 img src，明文）"""
        try:
            cover = target_comic_tab.ele(self.locators['cover_image'], timeout=5)
            src = cover.attr('src')
            if src and is_normal_url(src):
                return src
            # 回退 data-src
            src2 = cover.attr('data-src')
            if src2 and is_normal_url(src2):
                return src2
            print(f"封面图片URL: {src or src2}")
            return src or src2 or None
        except Exception as e:
            print(f"获取封面图片失败: {e}")
            return None