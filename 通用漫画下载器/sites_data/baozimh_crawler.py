import time
import re
import threading

from utils import is_normal_url


class BaozimhCrawler:
    """小包子漫画爬虫 (baozimh.org)"""

    # 站点元数据
    SITE_NAME = '小包子'
    SITE_URL = 'https://baozimh.org/'
    REQUIRES_LOGIN = False

    # 站点配置
    CONFIG = {
        'site_url': 'https://baozimh.org/',
        'locators': {
            'search_result': 'xpath:/html/body/main/div/div[4]/div[1]/a',
            'cover_image': 'xpath:/html/body/main/div[2]/div[2]/div[1]/div/div[1]/div[1]/div/div/img',
            'chapter_list_link': 'xpath:/html/body/main/div[2]/div[2]/div[2]/div[1]/div[5]/a',
        },
        'image_attr': 'data-src',
        'chapter_group_size': None,
    }

    def __init__(self, crawler):
        self.crawler = crawler
        self.locators = crawler.locators
        self.image_attr = crawler.image_attr
        self._cached_chapter_urls = None  # 缓存章节列表，避免重复请求

    def get_cover_image(self, target_comic_tab):
        """封面图片 - 等待加载后获取src"""
        try:
            img_ele = target_comic_tab.ele(self.locators['cover_image'], timeout=15)
            cover_url = img_ele.attr('src')
            if not cover_url:
                cover_url = target_comic_tab.run_js('return document.querySelector("main img.object-cover")?.src')
            print(f"封面图片URL: {cover_url}")
            return cover_url
        except Exception as e:
            print(f"获取封面图片失败: {e}")
            return None

    def search_comic(self, comic_name, comic_id=None):
        search_url = f"https://baozimh.org/s?q={comic_name}"
        print(f"正在搜索漫画: {comic_name}")
        print(f"搜索URL: {search_url}")

        self.crawler.tab.get(search_url)
        time.sleep(2)

        result_ele = self.crawler.tab.ele(self.locators['search_result'], timeout=10)
        href = result_ele.attr('href')
        print(f"搜索结果链接: {href}")

        target_comic_tab = self.crawler.page.new_tab(href)
        return target_comic_tab

    def _wait_allchapters_ready(self, timeout=15):
        """等待章节目录页#allchapters元素渲染完成（懒加载，可能晚于导航完成）"""
        js = "return !!document.getElementById('allchapters');"
        waited = 0.0
        while waited < timeout:
            try:
                if self.crawler.tab.run_js(js, timeout=5):
                    return True
            except Exception:
                pass
            time.sleep(0.5)
            waited += 0.5
        return False

    def _fetch_chapters_via_api(self, target_comic_tab):
        """用run_js执行fetch请求获取章节列表（无头模式下Alpine.js不渲染DOM，需用API）"""
        try:
            # 获取章节目录页URL
            chapterlist_url = target_comic_tab.url
            if '/chapterlist/' not in chapterlist_url:
                # 不在章节目录页，先找链接导航
                chapterlist_link = target_comic_tab.ele(self.locators['chapter_list_link'], timeout=5)
                if chapterlist_link:
                    chapterlist_url = chapterlist_link.attr('href')
                    if chapterlist_url and not chapterlist_url.startswith('http'):
                        chapterlist_url = f"https://baozimh.org{chapterlist_url}"
                else:
                    # 从详情页URL提取manga_slug构造章节目录页URL
                    parts = chapterlist_url.rstrip('/').split('/')
                    manga_slug = parts[-1] if parts else ''
                    chapterlist_url = f"https://baozimh.org/chapterlist/{manga_slug}"

            print(f"导航到章节目录页: {chapterlist_url}")
            self.crawler.tab.get(chapterlist_url)

            # 等待#allchapters就绪（懒加载竞态：未就绪时run_js立即返回
            # "allchapters not found"，导致章节数误判为0）
            if not self._wait_allchapters_ready():
                print("等待#allchapters元素超时，仍尝试fetch")
            time.sleep(1)

            # 用run_js从#allchapters获取mid，再fetch API获取章节列表
            js_code = """
            return new Promise((resolve) => {
                const el = document.getElementById('allchapters');
                if (!el) { resolve(JSON.stringify({error: 'allchapters not found'})); return; }
                const mid = el.getAttribute('data-mid');
                if (!mid) { resolve(JSON.stringify({error: 'data-mid not found'})); return; }
                fetch('https://v2.apikk.top/api/manga/get?mid=' + mid + '&mode=all')
                    .then(r => r.json())
                    .then(data => resolve(JSON.stringify(data)))
                    .catch(e => resolve(JSON.stringify({error: e.message})));
            });
            """
            result = self.crawler.tab.run_js(js_code, as_expr=False, timeout=30)
            if not result:
                print("run_js返回空")
                return []

            import json
            body = json.loads(result)
            if 'error' in body:
                print(f"获取章节列表失败: {body['error']}")
                return []

            data = body.get('data', {})
            manga_slug = data.get('slug', '')
            chapters = data.get('chapters', [])

            # API偶发只返回部分章节（如默认分页大小）时，重试一次fetch
            if 0 < len(chapters) < 10:
                print(f"警告: API仅返回 {len(chapters)} 个章节，疑为部分响应，重试fetch...")
                time.sleep(1.5)
                result = self.crawler.tab.run_js(js_code, as_expr=False, timeout=30)
                if result:
                    try:
                        body = json.loads(result)
                        data = body.get('data', {})
                        manga_slug = data.get('slug', manga_slug)
                        chapters = data.get('chapters', chapters)
                        print(f"重试后API返回 {len(chapters)} 个章节")
                    except Exception:
                        pass

            # API返回章节已按order从旧到新排列
            chapter_urls = []
            for ch in chapters:
                attrs = ch.get('attributes', {})
                slug = attrs.get('slug', '')
                title = attrs.get('title', f"第{len(chapter_urls)+1}章")
                if slug:
                    url = f"https://baozimh.org/manga/{manga_slug}/{slug}"
                    chapter_urls.append({
                        'num': len(chapter_urls) + 1,
                        'url': url,
                        'title': title
                    })

            print(f"从API获取 {len(chapter_urls)} 个章节")
            return chapter_urls
        except Exception as e:
            print(f"从API获取章节列表失败: {e}")
            return []

    def get_chapter_count(self, target_comic_tab):
        """获取章节数 - 用listen监听API获取章节列表"""
        try:
            chapter_urls = self._fetch_chapters_via_api(target_comic_tab)
            self._cached_chapter_urls = chapter_urls
            count = len(chapter_urls)
            print(f"检测到 {count} 个章节")
            return count
        except Exception as e:
            print(f"获取章节数失败: {e}")
        return 0

    def _get_chapter_urls_from_page(self, target_comic_tab):
        """获取章节URL列表，按从旧到新排列"""
        # 优先使用缓存（get_chapter_count已获取过）
        if self._cached_chapter_urls is not None:
            print(f"使用缓存的章节列表: {len(self._cached_chapter_urls)} 个")
            return self._cached_chapter_urls

        chapter_urls = self._fetch_chapters_via_api(target_comic_tab)
        self._cached_chapter_urls = chapter_urls
        print(f"共获取 {len(chapter_urls)} 个章节URL")
        return chapter_urls

    def get_chapter_image_urls(self, chapter_tab):
        """从章节页面提取所有图片URL - xpath遍历方式"""
        herf_list = []

        try:
            time.sleep(2)

            # 1. 先获取图片容器元素，确定数量
            img_containers = chapter_tab.eles('xpath:/html/body/main/section/div/div/div[4]/div/div[1]/div/div', timeout=10)
            total_imgs = len(img_containers)
            print(f"找到 {total_imgs} 个图片容器")

            if total_imgs > 0:
                # 2. 遍历每个容器，获取其中的img
                for i in range(1, total_imgs + 1):
                    try:
                        img_ele = chapter_tab.ele(f'xpath:/html/body/main/section/div/div/div[4]/div/div[1]/div/div[{i}]/img', timeout=5)
                        src = img_ele.attr('data-src')
                        if src and is_normal_url(src):
                            herf_list.append(src)
                        else:
                            print(f"第{i}张图片URL无效: {src}")
                    except Exception as e:
                        print(f"提取第{i}张图片时出错: {e}")

            print(f"共提取 {len(herf_list)} 张图片")

        except Exception as e:
            print(f"提取图片URL失败: {e}")

        return herf_list

    def collect_chapter_images(self, chapter_info, max_wait_time=5):
        chapter_num = chapter_info['chapter_num']
        chapter_url = chapter_info['url']
        main_tab = chapter_info['main_tab']

        print(f"正在处理章节{chapter_num}: {chapter_url}")

        try:
            chapter_tab = main_tab.new_tab(chapter_url)
            time.sleep(2)

            # 等待章节内容加载 - 重试机制
            retry_count = 0
            max_retries = 3

            while retry_count <= max_retries:
                try:
                    img_containers = chapter_tab.eles('xpath:/html/body/main/section/div/div/div[4]/div/div[1]/div/div', timeout=5)
                    if len(img_containers) > 0:
                        print(f"章节{chapter_num}检测到{len(img_containers)}张图片")
                        break
                except:
                    pass

                if retry_count < max_retries:
                    retry_count += 1
                    print(f"章节{chapter_num} 未检测到图片，第{retry_count}次重新加载...")
                    chapter_tab.get(chapter_url)
                    time.sleep(2)
                else:
                    print(f"章节{chapter_num} 已达最大重试次数({max_retries})")
                    chapter_tab.close()
                    return {
                        'chapter_num': chapter_num,
                        'title': chapter_info.get('title', ''),
                        'herf_list': []
                    }

            herf_list = self.get_chapter_image_urls(chapter_tab)
            chapter_tab.close()

        except Exception as e:
            print(f"处理章节{chapter_num}时出错: {e}")
            herf_list = []

        return {
            'chapter_num': chapter_num,
            'title': chapter_info.get('title', ''),
            'herf_list': herf_list
        }

    def collect_chapters_images(self, target_comic_tab, chapter_start=1, chapter_end=0, max_threads=3, progress_callback=None):
        print(f"设置最大同时收集线程数: {max_threads}")

        # 获取章节URL列表
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
        current_chapter = actual_start

        while current_chapter <= actual_end:
            group_end = min(current_chapter + max_threads - 1, actual_end)
            print(f"\n处理章节范围: {current_chapter}-{group_end}")

            batch_chapters_info = []
            for num in range(current_chapter, group_end + 1):
                chapter_url = chapter_urls[num - 1]['url']

                batch_chapters_info.append({
                    'chapter_num': num,
                    'url': chapter_url,
                    'title': chapter_urls[num - 1].get('title', ''),
                    'main_tab': self.crawler.tab
                })

                print(f"准备处理第{num}章节: {chapter_url}")

            threads = []
            results = []

            def thread_wrapper(chapter_info):
                result = self.collect_chapter_images(chapter_info)
                results.append(result)

            for chapter_info in batch_chapters_info:
                thread = threading.Thread(target=thread_wrapper, args=(chapter_info,))
                threads.append(thread)
                thread.start()

            for thread in threads:
                thread.join()

            all_chapters_data.extend(results)
            for _ in results:
                if progress_callback:
                    progress_callback()
            current_chapter = group_end + 1

        return all_chapters_data