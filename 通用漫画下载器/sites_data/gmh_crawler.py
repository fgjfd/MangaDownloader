import time
import threading

from utils import is_normal_url


class GmhCrawler:
    """G社漫画爬虫 (m.g-mh.org)"""

    # 站点元数据
    SITE_NAME = 'G社漫画'
    SITE_URL = 'https://m.g-mh.org/'
    REQUIRES_LOGIN = False

    # 站点配置
    CONFIG = {
        'site_url': 'https://m.g-mh.org/',
        'locators': {
            'search_result': 'xpath:/html/body/main/div/div[5]/div[1]/a',
            'cover_image': 'xpath:/html/body/main/div[2]/div[2]/div[1]/div/div/div/div/div/img',
            'all_chapters_btn': 'xpath:/html/body/main/div[2]/div[2]/div[2]/div/div[5]/button',
            'chapter_list_container': 'xpath:/html/body/main/div[2]/div[2]/div[2]/div/div[7]/div[2]/div[2]/div[1]',
            'chapter_item': 'xpath:/html/body/main/div[2]/div[2]/div[2]/div/div[7]/div[2]/div[2]/div[1]/div',
        },
        'image_attr': 'data-src',
        'chapter_group_size': None,
        # 图片CDN域名与站点不同，带上Referer以防后续启用防盗链
        'image_referer': 'https://m.g-mh.org/',
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
        search_url = f"https://m.g-mh.org/s/{comic_name}"
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
        """获取章节数 - 需要先点击"查看所有章節"展开列表"""
        try:
            # 确保章节列表已展开
            expanded = self._ensure_chapter_list_expanded(target_comic_tab)

            # 获取章节div元素数量
            chapter_divs = target_comic_tab.eles(self.locators['chapter_item'], timeout=10)
            count = len(chapter_divs)

            # 可疑校验：展开失败且数量很少时，等页面继续加载后重读一次，
            # 避免懒加载竞态下把折叠态的部分章节当成全部
            if count <= 20 and not expanded:
                print(f"警告: 检测到 {count} 个章节但展开未确认，等待后重读...")
                time.sleep(3)
                chapter_divs = target_comic_tab.eles(self.locators['chapter_item'], timeout=10)
                count = len(chapter_divs)
                print(f"重读后章节数: {count}")

            print(f"检测到 {count} 个章节")
            return count
        except Exception as e:
            print(f"获取章节数失败: {e}")
        return 0

    def _count_chapters(self, target_comic_tab):
        """统计当前DOM中章节div数量"""
        try:
            return len(target_comic_tab.eles(self.locators['chapter_item'], timeout=10))
        except Exception:
            return 0

    def _ensure_chapter_list_expanded(self, target_comic_tab):
        """确保章节列表已展开（避免重复点击toggle按钮导致关闭）

        展开为懒加载：点击按钮后章节逐步渲染，不能固定sleep(3)后直接数，
        改为轮询等待章节数稳定（连续两次相同）才认为展开完成。
        按钮未就绪/点击失败时重试，避免静默返回导致只数到折叠态的少量章节。
        """
        # 先检查是否已有完整章节列表
        before = self._count_chapters(target_comic_tab)
        if before > 20:
            print(f"章节列表已展开，共{before}章")
            return True

        # 未展开，点击按钮（最多重试3次，每次点击后轮询等待稳定）
        for click_attempt in range(3):
            try:
                btn = target_comic_tab.ele(self.locators['all_chapters_btn'], timeout=5)
                if not btn:
                    print(f"展开按钮未找到（第{click_attempt + 1}次）")
                    time.sleep(1.5)
                    continue
                btn.click()
                print(f"已点击展开按钮（第{click_attempt + 1}次），等待章节列表加载...")
            except Exception as e:
                print(f"点击展开按钮失败（第{click_attempt + 1}次）: {e}")
                time.sleep(1.5)
                continue

            # 轮询等待章节数稳定：最多等15秒，连续两次读数相同即认为加载完成
            prev_count = self._count_chapters(target_comic_tab)
            stable_rounds = 0
            waited = 0.0
            while waited < 15:
                time.sleep(1.0)
                waited += 1.0
                cur_count = self._count_chapters(target_comic_tab)
                if cur_count == prev_count:
                    stable_rounds += 1
                    if stable_rounds >= 2:
                        break
                else:
                    stable_rounds = 0
                prev_count = cur_count

            if cur_count > 20:
                print(f"章节列表展开成功，共{cur_count}章")
                return True
            if cur_count > before:
                # 有增长但没到完整阈值，可能是站内短篇漫画，按实际数量返回
                print(f"章节列表部分展开，共{cur_count}章")
                return True

        print("章节列表展开失败，可能仍为折叠态")
        return False

    def _get_chapter_urls_from_page(self, target_comic_tab):
        """从展开的章节列表获取所有章节URL，按从旧到新排列 - xpath遍历方式"""
        chapter_urls = []

        try:
            # 确保章节列表已展开
            self._ensure_chapter_list_expanded(target_comic_tab)

            # 1. 先获取所有章节div元素，确定数量
            chapter_divs = target_comic_tab.eles(self.locators['chapter_item'], timeout=20)
            total_chapters = len(chapter_divs)
            print(f"找到 {total_chapters} 个章节div")

            if total_chapters > 0:
                # 2. 遍历每个div，获取其中的a标签
                for i in range(1, total_chapters + 1):
                    try:
                        a_ele = target_comic_tab.ele(
                            f'xpath:/html/body/main/div[2]/div[2]/div[2]/div/div[7]/div[2]/div[2]/div[1]/div[{i}]/a',
                            timeout=5
                        )
                        href = a_ele.attr('href')
                        # 章节标题在 .chaptertitle span 内（a元素文本会混入日期"9月15日"），
                        # 优先取 span 文本；旧章节只有序号（如"01"），新章节有真实标题（如"第521回 完结篇"）
                        title = ''
                        try:
                            t_ele = a_ele.ele('xpath:.//span[contains(@class, "chaptertitle")]', timeout=1)
                            if t_ele and t_ele.text:
                                title = t_ele.text.strip()
                        except Exception:
                            pass
                        if not title:
                            title = a_ele.text.strip() if a_ele.text else f"第{i}章"
                        if href:
                            chapter_urls.append({
                                'num': i,
                                'url': href if href.startswith('http') else f"https://m.g-mh.org{href}",
                                'title': title
                            })
                    except Exception as e:
                        print(f"提取第{i}个章节链接失败: {e}")

                # 从新到旧排列，反转为从旧到新
                chapter_urls = list(reversed(chapter_urls))
                for i, item in enumerate(chapter_urls, 1):
                    item['num'] = i

        except Exception as e:
            print(f"从页面获取章节URL失败: {e}")

        print(f"共获取 {len(chapter_urls)} 个章节URL")
        return chapter_urls

    def get_chapter_image_urls(self, chapter_tab):
        """从章节页面提取所有图片URL - xpath遍历方式"""
        herf_list = []

        try:
            time.sleep(2)

            # 1. 先获取图片容器元素，确定数量
            img_containers = chapter_tab.eles(
                'xpath:/html/body/main/section/div/div/div[5]/div[2]/div[1]/div[1]/div',
                timeout=10
            )
            total_imgs = len(img_containers)
            print(f"找到 {total_imgs} 个图片容器")

            if total_imgs > 0:
                # 2. 遍历每个容器，获取其中的img
                for i in range(1, total_imgs + 1):
                    try:
                        img_ele = chapter_tab.ele(
                            f'xpath:/html/body/main/section/div/div/div[5]/div[2]/div[1]/div[1]/div[{i}]/img',
                            timeout=5
                        )
                        src = img_ele.attr('data-src')
                        if not src:
                            src = img_ele.attr('src')
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
                    img_containers = chapter_tab.eles(
                        'xpath:/html/body/main/section/div/div/div[5]/div[2]/div[1]/div[1]/div',
                        timeout=5
                    )
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
