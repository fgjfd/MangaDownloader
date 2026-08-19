import time
import threading
from urllib.parse import quote

from utils import is_normal_url


class WmhCrawler:
    """漫画1234爬虫 (m.wmh1234.com)"""

    # 站点元数据
    SITE_NAME = '漫画1234'
    SITE_URL = 'https://m.wmh1234.com/'
    REQUIRES_LOGIN = False

    # 站点配置
    CONFIG = {
        'site_url': 'https://m.wmh1234.com/',
        'locators': {
            'search_result': 'xpath:/html/body/main[1]/section[2]/div[2]/article[1]/a[1]',
            'cover_image': 'xpath:/html/body/main[1]/section[1]/div[2]/div[1]/div[1]/img[1]',
            'chapter_list_container': 'xpath:/html/body/main[1]/section[4]/div[1]/div[2]/div[1]',
            'chapter_item': 'xpath:/html/body/main[1]/section[4]/div[1]/div[2]/div[1]/a',
        },
        'image_attr': 'data-src',
        'chapter_group_size': None,
    }

    def __init__(self, crawler):
        self.crawler = crawler
        self.locators = crawler.locators
        self.image_attr = crawler.image_attr

    def get_cover_image(self, target_comic_tab):
        """封面图片 - 使用src属性（封面用src而非data-src）"""
        try:
            img_ele = target_comic_tab.ele(self.locators['cover_image'], timeout=15)
            cover_url = img_ele.attr('src')
            if not cover_url:
                cover_url = img_ele.attr('data-src')
            print(f"封面图片URL: {cover_url}")
            return cover_url
        except Exception as e:
            print(f"获取封面图片失败: {e}")
            return None

    def search_comic(self, comic_name, comic_id=None):
        search_url = f"https://m.wmh1234.com/search?key={quote(comic_name)}"
        print(f"正在搜索漫画: {comic_name}")
        print(f"搜索URL: {search_url}")

        # 重试机制 - 处理偶发加载失败或SmartScreen拦截
        max_retries = 3
        href = None
        for attempt in range(1, max_retries + 1):
            self.crawler.tab.get(search_url)
            time.sleep(3)
            # 处理Edge SmartScreen警告
            self._handle_smartscreen(self.crawler.tab)
            try:
                result_ele = self.crawler.tab.ele(self.locators['search_result'], timeout=15)
                href = result_ele.attr('href')
                if href:
                    break
            except Exception as e:
                print(f"第{attempt}次搜索未找到结果: {e}")
                if attempt < max_retries:
                    time.sleep(2)

        if not href:
            raise Exception(f"搜索'{comic_name}'失败，已重试{max_retries}次")
        print(f"搜索结果链接: {href}")

        target_comic_tab = self.crawler.page.new_tab(href)
        time.sleep(3)
        # 处理Edge SmartScreen警告
        self._handle_smartscreen(target_comic_tab)
        return target_comic_tab

    def get_chapter_count(self, target_comic_tab):
        """获取章节数 - 章节列表已完整加载，无需展开"""
        try:
            all_a = target_comic_tab.eles(self.locators['chapter_item'], timeout=20)
            total = len(all_a)
            # a[1]是"APP观看"推广链接，非章节，需排除
            count = total - 1 if total > 0 else 0
            print(f"检测到 {count} 个章节（排除1个APP推广链接）")
            return count
        except Exception as e:
            print(f"获取章节数失败: {e}")
            return 0

    def _get_chapter_urls_from_page(self, target_comic_tab):
        """从章节列表获取所有章节URL，按从旧到新排列 - xpath遍历方式

        注意：a[1]是"APP观看"推广链接，需从a[2]开始遍历
        章节顺序已是从旧到新，无需reversed()
        """
        chapter_urls = []

        try:
            # 1. 先获取所有a元素，确定数量
            all_a = target_comic_tab.eles(self.locators['chapter_item'], timeout=20)
            total = len(all_a)
            print(f"找到 {total} 个a元素")

            if total > 1:
                # 2. 从a[2]开始遍历（跳过a[1]的APP推广链接）
                for i in range(2, total + 1):
                    try:
                        a_ele = target_comic_tab.ele(
                            f'xpath:/html/body/main[1]/section[4]/div[1]/div[2]/div[1]/a[{i}]',
                            timeout=5
                        )
                        href = a_ele.attr('href')
                        title = a_ele.text.strip() if a_ele.text else f"第{len(chapter_urls) + 1}章"
                        if href and '/go/' in href:
                            chapter_urls.append({
                                'num': len(chapter_urls) + 1,
                                'url': href,
                                'title': title
                            })
                    except Exception as e:
                        print(f"提取第{i}个a元素失败: {e}")

        except Exception as e:
            print(f"从页面获取章节URL失败: {e}")

        print(f"共获取 {len(chapter_urls)} 个章节URL")
        return chapter_urls

    def get_chapter_image_urls(self, chapter_tab):
        """从章节页面提取所有图片URL - xpath遍历方式

        图片在 /html/body/main[1]/img[N]，URL在data-src属性
        data-src已在SSR HTML中，无需滚动触发懒加载
        """
        herf_list = []

        try:
            time.sleep(2)

            # 1. 先获取图片元素，确定数量
            img_containers = chapter_tab.eles('xpath:/html/body/main[1]/img', timeout=10)
            total_imgs = len(img_containers)
            print(f"找到 {total_imgs} 个图片元素")

            if total_imgs > 0:
                # 2. 遍历每个img，获取data-src
                for i in range(1, total_imgs + 1):
                    try:
                        img_ele = chapter_tab.ele(
                            f'xpath:/html/body/main[1]/img[{i}]',
                            timeout=5
                        )
                        src = img_ele.attr('data-src')
                        if not src:
                            src = img_ele.attr('src')
                        if src and is_normal_url(src) and 'placeholder' not in src:
                            herf_list.append(src)
                        else:
                            print(f"第{i}张图片URL无效: {src}")
                    except Exception as e:
                        print(f"提取第{i}张图片时出错: {e}")

            print(f"共提取 {len(herf_list)} 张图片")

        except Exception as e:
            print(f"提取图片URL失败: {e}")

        return herf_list

    def _handle_smartscreen(self, tab):
        """处理Edge SmartScreen安全警告 - 自动点击'不阻止此站点'"""
        try:
            btn = tab.ele('text:不阻止', timeout=3)
            if btn:
                print("检测到Edge SmartScreen警告，点击'不阻止此站点'")
                btn.click()
                time.sleep(3)
                return True
        except:
            pass
        return False

    def collect_chapter_images(self, chapter_info, max_wait_time=5):
        chapter_num = chapter_info['chapter_num']
        chapter_url = chapter_info['url']
        main_tab = chapter_info['main_tab']

        print(f"正在处理章节{chapter_num}: {chapter_url}")

        try:
            chapter_tab = main_tab.new_tab(chapter_url)
            time.sleep(3)

            # 处理Edge SmartScreen警告
            self._handle_smartscreen(chapter_tab)

            # 等待章节内容加载 - 重试机制
            # /go/链接会重定向到 reader.hqread.cc 阅读页
            retry_count = 0
            max_retries = 3

            while retry_count <= max_retries:
                try:
                    img_containers = chapter_tab.eles('xpath:/html/body/main[1]/img', timeout=5)
                    if len(img_containers) > 0:
                        print(f"章节{chapter_num}检测到{len(img_containers)}张图片")
                        break
                except:
                    pass

                if retry_count < max_retries:
                    retry_count += 1
                    print(f"章节{chapter_num} 未检测到图片，第{retry_count}次重新加载...")
                    chapter_tab.get(chapter_url)
                    time.sleep(3)
                    self._handle_smartscreen(chapter_tab)
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

    def collect_chapters_images(self, target_comic_tab, chapter_start=1, chapter_end=0, max_threads=3,
                                progress_callback=None):
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
