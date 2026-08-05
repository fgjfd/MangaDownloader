import re
import time
from urllib.parse import quote

from utils import is_normal_url


class BilibiliCrawler:
    """哔哩哔哩漫画爬虫 (manga.bilibili.com)

    该站点图片经ECDH密钥交换加密，浏览器解密后以blob+canvas渲染（无img元素），
    采用 createObjectURL钩子 + 翻页遍历 的方式捕获解密后的明文图片。
    章节数据从详情页Vue组件实例(episodeData)中提取。
    """

    # 站点元数据
    SITE_NAME = '哔哩哔哩漫画'
    SITE_URL = 'https://manga.bilibili.com/'
    REQUIRES_LOGIN = False
    # 登录非必需，但支持Cookie输入（登录态可解锁已购章节）
    SUPPORTS_COOKIE_INPUT = True

    # 页面加载前注入的钩子：捕获所有createObjectURL产生的blob（解密后的明文图片）
    BLOB_HOOK_JS = """
    window.__captured_blobs = window.__captured_blobs || [];
    if (!window.__blob_hook_installed) {
        window.__blob_hook_installed = true;
        var __orig_cob = URL.createObjectURL.bind(URL);
        URL.createObjectURL = function(obj) {
            var url = __orig_cob(obj);
            if (url.indexOf('blob:') === 0) {
                window.__captured_blobs.push({url: url, size: obj.size || 0, type: obj.type || ''});
            }
            return url;
        };
    }
    """

    # 读取阅读器当前页码: 返回 [当前页, 总页数]
    PAGE_INFO_JS = """
    var texts = [];
    var spans = document.querySelectorAll('span, div');
    for (var i = 0; i < spans.length; i++) {
        var t = (spans[i].innerText || '').trim();
        var m = t.match(/^(\\d+)\\s*\\/\\s*(\\d+)$/);
        if (m) texts.push([parseInt(m[1]), parseInt(m[2])]);
    }
    return texts.length ? texts[0] : [0, 0];
    """

    # 翻页JS：阅读器监听完整鼠标事件序列（pointerdown/mousedown/.../click），
    # 仅el.click()在双页跨页模式(double-page)下不响应，必须带坐标派发完整序列
    NEXT_PAGE_JS = """
    var el = document.querySelector('.arrow-right');
    if (el) {
        var r = el.getBoundingClientRect();
        var x = r.x + r.width * 0.75, y = r.y + r.height * 0.5;
        ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(function(t){
            el.dispatchEvent(new MouseEvent(t, {bubbles:true, cancelable:true, view:window, clientX:x, clientY:y}));
        });
    }
    """

    PREV_PAGE_JS = """
    var el = document.querySelector('.pageup') || document.querySelector('.arrow-left');
    if (el) {
        var r = el.getBoundingClientRect();
        var x = r.x + r.width * 0.25, y = r.y + r.height * 0.5;
        ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(function(t){
            el.dispatchEvent(new MouseEvent(t, {bubbles:true, cancelable:true, view:window, clientX:x, clientY:y}));
        });
    }
    """

    # 从详情页Vue组件提取完整章节列表（含锁定状态）
    EPISODE_LIST_JS = """
    var items = document.querySelectorAll('.episode-list .list-item, .list-data .list-item');
    var r = [];
    for (var i = 0; i < items.length; i++) {
        var vm = items[i].__vue__;
        var ep = vm && vm.$props && vm.$props.episodeData;
        if (!ep || !ep.id) continue;
        var title = ((ep.short_title || '') + ' ' + (ep.title || '')).trim();
        r.push({
            id: ep.id,
            title: title || ('第' + (ep.ord || r.length + 1) + '话'),
            locked: !!items[i].querySelector('.lock-icon.locked')
        });
    }
    return r;
    """

    # 站点配置
    CONFIG = {
        'site_url': 'https://manga.bilibili.com/',
        'locators': {
            'search_result': 'css:a[href*="/detail/mc"]',
            'cover_image': 'css:.manga-cover img',
            'chapter_item': 'css:.episode-list .list-item, .list-data .list-item',
            'chapter_image': None,  # blob钩子模式不使用img元素
        },
        'image_attr': 'src',
        'chapter_group_size': None,
        # 图片加密，启用浏览器渲染下载
        'browser_render': True,
        # blob钩子模式：翻页遍历阅读器，捕获解密后blob
        'render_mode': 'blob_hook',
        # 封面为明文图片，HTTP直下即可，无需浏览器提取
        'cover_via_browser': False,
        'blob_hook': {
            # 向后翻页（回到第1页用）
            'prev_page_js': PREV_PAGE_JS,
            # 向前翻页
            'next_page_js': NEXT_PAGE_JS,
            # 停滞兜底也用完整鼠标事件序列（该阅读器不响应键盘事件）
            'stuck_next_js': NEXT_PAGE_JS,
            'page_info_js': PAGE_INFO_JS,
            'min_blob_size': 30000,   # 过滤UI小图
            'ready_wait': 8,          # 章节页加载等待秒数
            'page_interval': 0.8,     # 每次翻页间隔秒数
            'max_stuck': 3,           # 连续翻页无变化的容忍次数
        },
    }

    def __init__(self, crawler):
        self.crawler = crawler
        self.locators = crawler.locators
        self.image_attr = crawler.image_attr

    def get_cover_image(self, target_comic_tab):
        """封面图片URL（明文，可HTTP直下）"""
        try:
            img_ele = target_comic_tab.ele(self.locators['cover_image'], timeout=15)
            cover_url = img_ele.attr('src') or img_ele.attr('data-src')
            if cover_url and cover_url.startswith('//'):
                cover_url = 'https:' + cover_url
            print(f"封面图片URL: {cover_url}")
            return cover_url
        except Exception as e:
            print(f"获取封面图片失败: {e}")
            return None

    def _wait_detail_ready(self, tab, timeout=20):
        """条件等待详情页就绪（章节列表出现），替代固定sleep"""
        try:
            items = tab.eles(self.locators['chapter_item'], timeout=timeout)
            if items:
                return
        except Exception:
            pass
        time.sleep(2)  # 兜底短等

    def search_comic(self, comic_name, comic_id=None):
        """站内搜索，打开第一个结果的详情页"""
        if comic_id:
            detail_url = f"https://manga.bilibili.com/detail/mc{comic_id}"
            print(f"直接打开详情页: {detail_url}")
            target_comic_tab = self.crawler.page.new_tab(detail_url)
            self._wait_detail_ready(target_comic_tab)
            return target_comic_tab

        search_url = f"https://manga.bilibili.com/search?keyword={quote(comic_name)}"
        print(f"正在搜索漫画: {comic_name}")
        print(f"搜索URL: {search_url}")

        self.crawler.tab.get(search_url)
        # 条件等待搜索结果出现，替代固定sleep
        self.crawler.tab.ele('css:a[href*="/detail/mc"]', timeout=15)

        # 提取第一个有效的详情页链接（去重、跳过空文本容器）
        href = self.crawler.tab.run_js("""
        var cards = document.querySelectorAll('a[href*="/detail/mc"]');
        for (var i = 0; i < cards.length; i++) {
            var href = cards[i].getAttribute('href');
            var text = (cards[i].innerText || '').trim();
            if (href && text) return href;
        }
        return cards.length ? cards[0].getAttribute('href') : null;
        """)

        if not href:
            print("未找到搜索结果")
            return None

        if not href.startswith('http'):
            href = f"https://manga.bilibili.com{href}"
        print(f"搜索结果链接: {href}")

        target_comic_tab = self.crawler.page.new_tab(href)
        self._wait_detail_ready(target_comic_tab)
        return target_comic_tab

    def get_chapter_count(self, target_comic_tab):
        """获取章节数"""
        try:
            chapter_items = target_comic_tab.eles(self.locators['chapter_item'], timeout=15)
            count = len(chapter_items)
            print(f"检测到 {count} 个章节")
            return count
        except Exception as e:
            print(f"获取章节数失败: {e}")
            return 0

    def _get_episode_list(self, target_comic_tab):
        """从详情页Vue组件提取完整章节列表

        Returns:
            [{'id': ep_id, 'title': str, 'locked': bool}, ...]
        """
        episodes = target_comic_tab.run_js(self.EPISODE_LIST_JS)
        if not isinstance(episodes, list):
            print("提取章节列表失败")
            return []
        # 兜底：Vue提取失败时用DOM顺序+点击链接
        if not episodes:
            print("Vue提取章节为空，尝试DOM链接兜底")
            links = target_comic_tab.run_js("""
            var r = [];
            var links = document.querySelectorAll('a[href*="/mc"]');
            for (var i = 0; i < links.length; i++) {
                var m = (links[i].getAttribute('href') || '').match(/\\/mc\\d+\\/(\\d+)/);
                if (m) r.push({id: parseInt(m[1]), title: (links[i].innerText || '').trim(), locked: false});
            }
            return r;
            """)
            episodes = links if isinstance(links, list) else []
        return episodes

    def _get_comic_id(self, target_comic_tab):
        """从详情页URL提取comic_id"""
        try:
            url = target_comic_tab.url
            m = re.search(r'/detail/mc(\d+)', url)
            if m:
                return m.group(1)
            m = re.search(r'/mc(\d+)', url)
            return m.group(1) if m else None
        except Exception:
            return None

    def collect_chapters_images(self, target_comic_tab, chapter_start=1, chapter_end=0, max_threads=3,
                                progress_callback=None):
        """收集章节信息。blob钩子模式下图片在downloader浏览器渲染阶段提取，
        此处仅构建章节URL列表"""
        comic_id = self._get_comic_id(target_comic_tab)
        if not comic_id:
            print("无法从URL提取comic_id")
            return []

        episodes = self._get_episode_list(target_comic_tab)
        all_chapters_num = len(episodes)
        print(f"总章节数: {all_chapters_num}")

        if all_chapters_num == 0:
            print("未找到任何章节")
            return []

        actual_start = max(chapter_start, 1)
        actual_end = min(chapter_end, all_chapters_num) if chapter_end > 0 else all_chapters_num

        if actual_start > all_chapters_num:
            print(f"起始章节 {actual_start} 超过总章节数 {all_chapters_num}")
            return []

        print(f"将下载第 {actual_start}-{actual_end} 章，共 {actual_end - actual_start + 1} 章")

        all_chapters_data = []
        skipped_locked = 0
        for num in range(actual_start, actual_end + 1):
            ep = episodes[num - 1]
            if ep.get('locked'):
                skipped_locked += 1
                print(f"跳过锁定(付费/未解锁)章节 {num}: {ep['title']}")
                if progress_callback:
                    progress_callback()
                continue
            chapter_url = f"https://manga.bilibili.com/mc{comic_id}/{ep['id']}"
            all_chapters_data.append({
                'chapter_num': num,
                'url': chapter_url,
                'title': ep['title'],
                'herf_list': [],  # blob钩子模式下图片数量在下载时确定
            })
            if progress_callback:
                progress_callback()

        if skipped_locked:
            print(f"共跳过 {skipped_locked} 个锁定章节（登录并解锁后可编辑范围重试）")
        print(f"共收集 {len(all_chapters_data)} 个可下载章节")
        return all_chapters_data

    def prepare_blob_download(self):
        """下载前置准备：清除站点阅读进度（indexedDB），保证章节从第1页开始

        由downloader浏览器渲染下载前调用一次
        """
        try:
            tab = self.crawler.tab
            tab.get('https://manga.bilibili.com/')
            time.sleep(2)  # 首页仅需能访问到indexedDB，无需等待完整渲染
            deleted = tab.run_js("""
            async function() {
                if (!indexedDB.databases) return [];
                var dbs = await indexedDB.databases();
                var deleted = [];
                for (var i = 0; i < dbs.length; i++) {
                    if (/PageHistory/i.test(dbs[i].name)) {
                        await new Promise(function(res) {
                            var req = indexedDB.deleteDatabase(dbs[i].name);
                            req.onsuccess = req.onerror = req.onblocked = res;
                        });
                        deleted.push(dbs[i].name);
                    }
                }
                return deleted;
            }
            """)
            print(f"已清除阅读进度存储: {deleted}")
        except Exception as e:
            print(f"清除阅读进度失败（不影响下载，翻页时会自动回退）: {e}")
