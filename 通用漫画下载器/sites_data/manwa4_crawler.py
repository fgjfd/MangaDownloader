# -*- coding: utf-8 -*-
"""
漫蛙4（漫蛙地址二 manwaye.cc）爬虫

与漫蛙1 同源（mwmw.cc 系列镜像域名，后端相同），API 结构/加密算法完全一致。
差异仅在入口域名：本文件指向漫蛙地址二 https://manwaye.cc/
详细协议说明见 manwa1_crawler.py 头注释。

图片加密：AES-256-CBC，key=UTF-8('0B6666A0-BB59-1381-B746-a0E4C9AC')[:32]
"""
import time
import threading
from urllib.parse import quote

import requests

from utils import is_normal_url
from downloader import get_system_proxy

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False


class Manwa4Crawler:
    """漫蛙4爬虫 (https://manwaye.cc/)"""

    # ========== 元数据 ==========
    SITE_NAME = '漫蛙4'
    SITE_URL = 'https://manwaye.cc/'
    REQUIRES_LOGIN = False
    # 纯requests实现（API明文URL + Python解密），无需浏览器
    NEEDS_BROWSER = False
    # 登录非必需，但Cookie可解锁VIP章节，支持 Cookie 输入
    SUPPORTS_COOKIE_INPUT = True

    # ========== 配置 ==========
    CONFIG = {
        'site_url': 'https://manwaye.cc/',
        'locators': {
            'search_result': 'xpath:/html/body/div[2]/ul/li[1]//a[contains(@href, "/comic/")]',
            'cover_image': 'xpath://img[contains(@class, "comic-cover")]',
            'chapter_item': 'xpath://a[contains(@href, "/comic/")]',
        },
        'image_attr': 'data-src',
        'chapter_group_size': None,
        # 图片CDN防盗链：下载时自动带Referer
        'image_referer': 'https://manwaye.cc/',
        # 图片解密配置（downloader 自动执行：下载字节 → AES-256-CBC 解密 → 转JPEG → 保存）
        'decrypt': {
            'mode': 'site_func',   # 自定义解密器（见 get_decryptor）
            'ext': 'jpg',          # 解密后统一转 JPEG（兼容所有阅读器）
        },
    }

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36',
        'Accept-Encoding': 'gzip, deflate',
    }

    # 图片CDN源（chapter.js 中 IMAGE_SOURCES，按优先级排列，逐个尝试）
    IMAGE_SOURCES = [
        'https://mwtuyi.cc',
        'https://tu.mwzu.cc',
        'https://mwtuwu.cc',
        'https://mwtuer.cc',
        'https://mwtusan.cc',
    ]

    # 可用API线路（mwmw.cc/manwalu.cc 为跳转页，API 请求需落到真实内容域名）
    API_BASES = [
        'https://manwali.cc',
        'https://manwaye.cc',
        'https://mwmw.cc',
        'https://manwalu.cc',
    ]

    def __init__(self, crawler):
        self.crawler = crawler
        self.locators = crawler.locators
        self.image_attr = crawler.image_attr
        self._comic_info = None  # search_comic 的详情数据缓存
        self._system_proxy = None
        self._session = requests.Session()
        self._session.headers.update(self.HEADERS)
        self._api_base = None  # 探测到的可用 API 基础域名（缓存）

    # ========== 内部工具 ==========

    def get_decryptor(self):
        """返回图片解密函数 data(bytes) -> bytes（AES-256-CBC + 转JPEG）

        加密协议：文件结构 [iv 16字节][AES-CBC 密文]，PKCS7 padding
        密钥：UTF-8 编码 '0B6666A0-BB59-1381-B746-a0E4C9AC' 前 32 字节
        明文格式为 webp，统一转 JPEG（与封面一致，兼容所有阅读器）
        """
        key = '0B6666A0-BB59-1381-B746-a0E4C9AC'.encode('utf-8')[:32]

        def decrypt(data):
            if not _HAS_CRYPTO:
                raise RuntimeError('缺少 pycryptodome，无法解密图片，请 pip install pycryptodome')
            if data[:4] == b'RIFF' or data[:3] == b'\xff\xd8' or data[:8] == b'\x89PNG':
                plain = data  # 已是明文图片
            else:
                iv = data[:16]
                ciphertext = data[16:]
                cipher = AES.new(key, AES.MODE_CBC, iv)
                plain = unpad(cipher.decrypt(ciphertext), AES.block_size)
            # 统一转 JPEG（webp/jpg/png 均转码，保证扩展名一致）
            try:
                from PIL import Image
                import io as _io
                img = Image.open(_io.BytesIO(plain))
                buf = _io.BytesIO()
                img.convert('RGB').save(buf, 'JPEG', quality=92)
                return buf.getvalue()
            except Exception as e:
                print(f"  ✗ 转码JPEG失败（保留原格式）: {e}")
                return plain

        return decrypt

    def _get_cookie_header(self):
        """从框架取已保存的Cookie字符串（用户GUI输入或文件加载）"""
        cookie_str = getattr(self.crawler, 'cookie_str', None)
        if cookie_str:
            return {'Cookie': cookie_str}
        return {}

    def _resolve_api_base(self):
        """探测可用的 API 基础域名（首个能返回 JSON 的域名）"""
        if self._api_base:
            return self._api_base
        for base in self.API_BASES:
            try:
                resp = self._session.get(
                    base + '/api/comic/chapter/info/2110710',
                    headers={**self.HEADERS, **self._get_cookie_header()},
                    timeout=8, proxies=self._proxies())
                if resp.status_code == 200 and resp.text.strip().startswith('{'):
                    self._api_base = base
                    print(f"漫蛙 API 线路可用: {base}")
                    return base
            except Exception:
                continue
        # 全部失败则退回第一个域名（后续请求会抛异常）
        return self.API_BASES[0]

    def _proxies(self):
        """直连优先，失败回退系统代理"""
        try:
            if self._system_proxy is None:
                self._system_proxy = get_system_proxy()
            if self._system_proxy:
                return self._system_proxy
        except Exception:
            pass
        return None

    def _fetch_json(self, path, params=None, retries=3, timeout=20):
        """GET JSON API（自动尝试可用线路）"""
        base = self._resolve_api_base()
        last_err = None
        for attempt in range(retries):
            try:
                resp = self._session.get(
                    base + path, params=params, headers={**self.HEADERS, **self._get_cookie_header()},
                    timeout=timeout, proxies=self._proxies())
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict) and data.get('code') == 200:
                        return data
                    last_err = f'code={data.get("code")}'
                else:
                    last_err = f'status={resp.status_code}'
            except Exception as e:
                last_err = str(e)[:80]
                # 当前线路失败，切换下一线路重试
                self._api_base = None
                base = self._resolve_api_base()
            if attempt < retries - 1:
                time.sleep(1)
        raise Exception(f'API请求失败 {path}: {last_err}')

    # ========== 必须实现的方法 ==========

    def search_comic(self, comic_name, comic_id=None):
        """搜索漫画并抓取详情数据，返回详情信息 dict（纯 requests）"""
        if comic_id:
            data = self._fetch_json(f'/api/comic/{comic_id}/chapters')
            list_data = data.get('data', {}).get('list', [])
            if not list_data:
                raise Exception(f"未找到漫画ID {comic_id} 的章节")
            title = comic_name
            cover_url = ''
        else:
            print(f"正在搜索漫画: {comic_name}")
            data = self._fetch_json('/api/search', params={'keyword': comic_name})
            results = data.get('data', {}).get('list', [])
            if not results:
                raise Exception(f"搜索 '{comic_name}' 未找到结果")
            item = results[0]
            comic_id = item.get('id')
            title = item.get('title') or item.get('alias') or comic_name
            cover_url = item.get('cover', '')
            print(f"搜索结果: {title} (id={comic_id})")

        # 获取章节列表
        data = self._fetch_json(f'/api/comic/{comic_id}/chapters')
        raw_list = data.get('data', {}).get('list', [])
        # 按 sortId 升序（旧→新）
        raw_list.sort(key=lambda x: x.get('sortId', 0))

        chapters = []
        for i, ch in enumerate(raw_list, 1):
            cid = ch.get('id')
            ch_title = ch.get('title') or ''
            chapters.append({
                'id': cid,
                'cid': cid,
                'num': i,
                'title': ch_title,
                'url': f"/comic/{comic_id}/{cid}",
            })

        print(f"漫画标题: {title}, 章节数: {len(chapters)}")

        self._comic_info = {
            'comic_id': str(comic_id),
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

    def get_chapter_image_urls(self, cid, total_hint=None):
        """按 cid 分页拉取章节全部图片URL（明文URL，下载时解密）"""
        urls = []
        try:
            page = 1
            while True:
                data = self._fetch_json(
                    f'/api/comic/image/{cid}',
                    params={
                        'page': page,
                        'page_size': 100,
                        'image_source': self.IMAGE_SOURCES[0],
                    })
                d = data.get('data', {})
                images = d.get('images', []) or []
                for img in images:
                    u = img.get('url', '')
                    if u and is_normal_url(u):
                        urls.append(u)
                pagination = d.get('pagination', {}) or {}
                total = pagination.get('total', 0)
                total_pages = pagination.get('total_pages', 1) or 1
                if page >= total_pages or not images or (total and len(urls) >= total):
                    break
                page += 1
        except Exception as e:
            print(f"获取章节图片URL失败 cid={cid}: {e}")
            return []
        return urls

    def collect_chapters_images(self, target_comic_tab, chapter_start=1, chapter_end=0,
                                max_threads=3, progress_callback=None):
        """收集指定章节范围内的所有图片URL（纯requests，多线程）"""
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
                urls = self.get_chapter_image_urls(chapter['cid'])
                with lock:
                    all_chapters_data.append({
                        'chapter_num': chapter['num'],
                        'title': chapter.get('title', ''),
                        'herf_list': urls,
                        'url': self._resolve_api_base() + chapter['url'],
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
                        'url': self._resolve_api_base() + chapter['url'],
                    })
                    done[0] += 1
                    if progress_callback:
                        progress_callback()

        threads = []
        for idx in range(actual_start - 1, actual_end):
            chapter = chapters[idx]
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
        """封面URL（明文，下载时由 downloader 解密）"""
        if self._comic_info:
            return self._comic_info.get('cover_url') or None
        return None