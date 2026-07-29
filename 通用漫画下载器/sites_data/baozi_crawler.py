import time
import re
import threading

from utils import is_normal_url


class BaoziCrawler:
    """包子漫画爬虫"""

    # 站点元数据
    SITE_NAME = '包子漫画'
    SITE_URL = 'https://cn.bzmanga.com/classify'
    REQUIRES_LOGIN = False

    # 站点配置
    CONFIG = {
        'site_url': 'https://cn.bzmanga.com/classify',
        'locators': {
            'search_result': 'xpath:/html/body/div/div/div/div[2]/div[2]/div[1]/a[1]',
            'cover_image': 'xpath:/html/body/div/div/div/div[2]/div[1]/div[3]/div/div[1]/amp-img/img',
            'chapter_link_template': 'xpath:/html/body/div/div/div/div[2]/div[3]/div/div[2]/div[1]/a',
            'chapter_image_filtered': 'xpath:(//ul/div[@data-v-67784caa])[num]/amp-img',
        },
        'image_attr': 'src',
        'chapter_group_size': None,
        'download_mode': 'thread_only'  # 纯多线程模式
    }

    def __init__(self, crawler):
        self.crawler = crawler
        self.locators = crawler.locators
        self.image_attr = crawler.image_attr

    def search_comic(self, comic_name, comic_id=None):
        search_url = f"https://cn.bzmanga.com/search?q={comic_name}"
        print(f"正在搜索漫画: {comic_name}")
        print(f"搜索URL: {search_url}")

        self.crawler.tab.get(search_url)
        time.sleep(2)

        result_ele = self.crawler.tab.ele(self.locators['search_result'], timeout=10)
        href = result_ele.attr('href')
        print(f"搜索结果链接: {href}")

        target_comic_tab = self.crawler.page.new_tab(href)
        return target_comic_tab

    def get_chapter_count(self, target_comic_tab):
        """从章节URL中提取最大章节号"""
        try:
            chapter_ele = target_comic_tab.ele(self.locators['chapter_link_template'], timeout=5)
            href = chapter_ele.attr('href')
            print(f"章节链接模板: {href}")

            # 从href中提取最大章节号，如 chapter_slot=271 -> 271
            match = re.search(r'chapter_slot=(\d+)', href)
            if match:
                count = int(match.group(1))
                print(f"最大章节数: {count}")
                # 保存模板URL供后续使用
                self.chapter_url_template = href
                return count
            else:
                print(f"无法从URL中提取章节号: {href}")
        except Exception as e:
            print(f"获取章节数失败: {e}")

        return 0

    def _click_continue_view(self, chapter_tab):
        """检查是否有'继续查看'按钮，有则点击并等待"""
        try:
            html = chapter_tab.html
            if '继续查看' in html:
                continue_btn = chapter_tab.ele('text:继续查看', timeout=3)
                if continue_btn:
                    continue_btn.click()
                    print("点击了'继续查看'按钮，等待图片加载...")
                    time.sleep(2)
                    return True
        except Exception as e:
            print(f"处理'继续查看'时出错: {e}")
        return False

    def _get_max_image_count(self, chapter_tab):
        """从HTML中统计ul下含有data-v-67784caa的div数量"""
        try:
            html = chapter_tab.html
            # 统计匹配的div数量
            matches = re.findall(r'<div[^>]*data-v-67784caa[^>]*>', html)
            count = len(matches)
            print(f"最大图片数: {count}")
            return count, html
        except Exception as e:
            print(f"获取最大图片数失败: {e}")
            return 0, ""

    def get_chapter_image_urls(self, chapter_tab, html):
        """从HTML中统一提取图片URL"""
        herf_list = []

        try:
            # 先提取第一个<ul>的内容
            ul_pattern = r'<ul[^>]*>(.*?)</ul>'
            ul_matches = re.findall(ul_pattern, html, re.DOTALL)

            if ul_matches:
                first_ul = ul_matches[0]
                print(f"找到第一个<ul>，内容长度: {len(first_ul)} 字符")

                # 从第一个<ul>中提取包含data-v-67784caa的div块
                div_pattern = r'<div[^>]*data-v-67784caa[^>]*>(.*?)</div>'
                div_matches = re.findall(div_pattern, first_ul, re.DOTALL)

                print(f"第一个<ul>下找到 {len(div_matches)} 个包含data-v-67784caa的div块")

                for div_idx, div_content in enumerate(div_matches, 1):
                    # 从每个div块中提取amp-img的src
                    img_pattern = r'<amp-img[^>]*src=["\']([^"\']+)["\'][^>]*>'
                    img_matches = re.findall(img_pattern, div_content)

                    for img_src in img_matches:
                        if img_src and is_normal_url(img_src):
                            print(f"div[{div_idx}] 提取图片: {img_src}")
                            herf_list.append(img_src)

                print(f"总计从第一个<ul>中提取到 {len(herf_list)} 张有效图片")
            else:
                print("未找到<ul>标签")

            # 如果方法1没有找到图片，尝试方法2（从整个HTML提取所有amp-img）
            if not herf_list:
                print("方法1未找到图片，尝试从整个HTML提取所有amp-img")
                pattern = r'<amp-img[^>]*src=["\']([^"\']+)["\'][^>]*>'
                matches = re.findall(pattern, html)

                print(f"从整个HTML提取到 {len(matches)} 个amp-img标签")

                for i, src in enumerate(matches, 1):
                    if src and is_normal_url(src):
                        print(f"全局第{i}张图片: {src}")
                        herf_list.append(src)
                    else:
                        print(f"全局第{i}张图片URL无效: {src}")

        except Exception as e:
            print(f"从HTML提取图片URL失败: {e}")

        return herf_list

    def collect_chapter_images(self, chapter_info, max_wait_time=3):
        chapter_num = chapter_info['chapter_num']
        chapter_url = chapter_info['url']
        main_tab = chapter_info['main_tab']

        print(f"正在处理章节{chapter_num}: {chapter_url}")

        try:
            chapter_tab = main_tab.new_tab(chapter_url)
            time.sleep(1)

            # 检查并点击"继续查看"
            self._click_continue_view(chapter_tab)

            start_time = time.time()
            retry_count = 0
            max_retries = 3
            max_img_num = 0
            html = ""

            while retry_count <= max_retries:
                max_img_num, html = self._get_max_image_count(chapter_tab)

                if max_img_num > 0:
                    print(f"章节{chapter_num}检测到{max_img_num}张图片")
                    break

                elapsed = time.time() - start_time
                if elapsed >= max_wait_time:
                    if retry_count < max_retries:
                        retry_count += 1
                        print(f"章节{chapter_num} ⚠️ {max_wait_time}秒内未检测到图片，第{retry_count}次重新加载页面...")
                        chapter_tab.get(chapter_url)
                        time.sleep(1)
                        self._click_continue_view(chapter_tab)
                        start_time = time.time()
                    else:
                        print(f"章节{chapter_num} ✗ 已达到最大重试次数({max_retries})，仍未检测到图片")
                        chapter_tab.close()
                        return {
                            'chapter_num': chapter_num,
                            'herf_list': []
                        }
                else:
                    time.sleep(0.5)

            herf_list = self.get_chapter_image_urls(chapter_tab, html)

            chapter_tab.close()

        except Exception as e:
            print(f"处理章节{chapter_num}时出错: {e}")
            herf_list = []

        return {
            'chapter_num': chapter_num,
            'herf_list': herf_list
        }

    def collect_chapters_images(self, target_comic_tab, chapter_start=1, chapter_end=0, max_threads=3, progress_callback=None):
        print(f"设置最大同时收集线程数: {max_threads}")

        all_chapters_num = self.get_chapter_count(target_comic_tab)
        print(f"总章节数: {all_chapters_num}")

        if all_chapters_num == 0:
            print("未获取到章节数，退出")
            return []

        actual_start = max(chapter_start, 1)
        actual_end = min(chapter_end, all_chapters_num) if chapter_end > 0 else all_chapters_num

        if actual_start > all_chapters_num:
            print(f"起始章节 {actual_start} 超过总章节数 {all_chapters_num}")
            return []

        print(f"将下载第 {actual_start}-{actual_end} 章，共 {actual_end - actual_start + 1} 章")

        # 生成章节URL列表（通过替换URL中的章节号）
        chapter_urls = []
        for num in range(1, all_chapters_num + 1):
            # 将模板URL中的chapter_slot参数替换为目标章节号
            chapter_url = re.sub(r'chapter_slot=\d+', f'chapter_slot={num}', self.chapter_url_template)
            chapter_urls.append(chapter_url)

        all_chapters_data = []
        current_chapter = actual_start

        while current_chapter <= actual_end:
            group_end = min(current_chapter + max_threads - 1, actual_end)
            print(f"\n处理章节范围: {current_chapter}-{group_end}")

            batch_chapters_info = []
            for num in range(current_chapter, group_end + 1):
                chapter_url = chapter_urls[num - 1]  # 索引从0开始

                batch_chapters_info.append({
                    'chapter_num': num,
                    'url': chapter_url,
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
