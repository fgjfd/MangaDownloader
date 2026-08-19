import time
import threading

import requests

from utils import is_normal_url


class KuaikanCrawler:
    """快看漫画爬虫（纯桌面web方案）"""
    
    # 站点元数据
    SITE_NAME = '快看'
    SITE_URL = 'https://www.kuaikanmanhua.com/'
    REQUIRES_LOGIN = True
    
    # 站点配置
    CONFIG = {
        'site_url': 'https://www.kuaikanmanhua.com/',
        'locators': {
            # 桌面搜索页(/sou/)改版后的新版结构：搜索结果漫画链接为 /web/topic/{id} 格式
            'search_result': 'xpath:/html/body/div[1]/div[1]/div[1]/div[1]/div[3]/div[1]/div[1]/div[1]/a[1]',
            # 详情页(/web/topic/{id})封面
            'cover_image': 'xpath:/html/body/div[1]/div[1]/div[1]/div[1]/div[2]/div[1]/div[1]/div[1]/div[1]/img[3]',
            # 章节列表项（.episode-title 下的 .title-item，默认渲染50个）
            'chapter_list': 'xpath:/html/body/div[1]/div[1]/div[1]/div[1]/div[2]/div[1]/div[2]/div[1]/div[1]/div[1]/div[3]/div',
            # 章节分组按钮（.episode-interval 下的 .interval-item，如"1 - 50"）
            'chapter_group_button': 'xpath:/html/body/div[1]/div[1]/div[1]/div[1]/div[2]/div[1]/div[2]/div[1]/div[1]/div[1]/div[2]/div',
            # 章节阅读页(/webs/comic-next/{id})图片容器（.comicDetails > .imgList > .img-box）
            'chapter_image_parent': 'xpath:/html/body/div[1]/div[1]/div[1]/div[1]/div[4]/div[1]/div[1]/div',
            'chapter_image': 'xpath:/html/body/div[1]/div[1]/div[1]/div[1]/div[4]/div[1]/div[1]/div[num]/img[1]',
        },
        'image_attr': 'data-src',
        'chapter_group_size': 50
    }

    # 官方搜索API（桌面搜索页改版后，用于回退定位作品ID；ID与web详情页 /web/topic/{id} 一致）
    _SEARCH_API = 'https://www.kuaikanmanhua.com/search/mini/topic/title_and_author'
    _PC_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')

    def __init__(self, crawler):
        self.crawler = crawler
        self.locators = crawler.locators
        self.image_attr = crawler.image_attr
        # 每组分章数（章节列表按50章一组分页，需点击切换）
        self.group_size = self.crawler.site_config.get('chapter_group_size', 50)
        # 总章节数缓存（遍历全部分组统计一次后复用，避免重复点击）
        self._desktop_total = None

    # ==================== 通用接口 ====================

    def _search_topic_id_by_api(self, comic_name):
        """调快看官方搜索API定位作品ID（桌面搜索无结果时回退）

        Returns:
            topic_id(int) 或 None
        """
        try:
            resp = requests.get(
                self._SEARCH_API,
                params={'q': comic_name, 'page': 1, 'size': 10},
                headers={'User-Agent': self._PC_UA},
                timeout=15)
            if resp.status_code != 200:
                print(f"搜索API请求失败: HTTP {resp.status_code}")
                return None
            data = resp.json()
        except Exception as e:
            print(f"搜索API请求异常: {e}")
            return None

        hits = data.get('hits') or []
        if not hits:
            print(f"搜索API未找到 '{comic_name}' 相关漫画")
            return None

        # 优先标题完全匹配，其次包含关系，最后取第一个结果
        def _first_hit(matcher):
            for h in hits:
                if matcher((h.get('title') or '').strip()):
                    return h
            return None

        hit = (_first_hit(lambda t: t == comic_name)
               or _first_hit(lambda t: comic_name in t or t in comic_name)
               or hits[0])
        topic_id = hit.get('id') or hit.get('topic_id')
        print(f"搜索到漫画: {hit.get('title')} (作品ID: {topic_id})")
        return topic_id

    def search_comic(self, comic_name, comic_id=None):
        # 按ID下载：直接打开桌面端web详情页（新版链接为 /web/topic/{id}）
        if comic_id:
            url = f"https://www.kuaikanmanhua.com/web/topic/{comic_id}"
            print(f"正在通过ID访问漫画: {url}")
            tab = self.crawler.page.new_tab(url)
            return tab, comic_name

        # 1) 桌面搜索：搜索结果链接为 /web/topic/{id} 新格式（旧 /comic/{id} 已废弃）
        search_url = f"https://www.kuaikanmanhua.com/sou/{comic_name}"
        print(f"正在搜索漫画: {comic_name}")
        print(f"搜索URL: {search_url}")
        
        self.crawler.tab.get(search_url)
        
        if self.crawler.login_mode:
            if self.crawler.has_saved_cookies():
                self.crawler.load_cookies()
                self.crawler.tab.refresh()
                time.sleep(1)
        
        time.sleep(2)
        
        # 优先用固定xpath定位第一个搜索结果（改版后搜索结果区结构稳定）
        href = None
        try:
            result_ele = self.crawler.tab.ele(self.locators['search_result'], timeout=5)
            if result_ele:
                href = result_ele.attr('href')
        except Exception:
            href = None
        if not href:
            # 兜底：JS匹配 /web/topic/ 链接（需含可见文本，排除导航/推荐位）
            href = self.crawler.tab.run_js("""
            var links = document.querySelectorAll('a[href*="/web/topic/"]');
            for (var i = 0; i < links.length; i++) {
                var h = links[i].getAttribute('href') || '';
                var t = (links[i].innerText || '').trim();
                if (h && t) return h;
            }
            return null;
            """)
        if href:
            if not href.startswith('http'):
                href = 'https://www.kuaikanmanhua.com' + href
            print(f"搜索结果链接: {href}")
            target_comic_tab = self.crawler.page.new_tab(href)
            return target_comic_tab

        # 2) 搜索无结果（可能快看上无版权/名称不符），回退官方搜索API定位作品ID，
        #    拿到ID后同样打开桌面端web详情页（web与API的topic_id一致）
        print("桌面搜索未找到漫画，改用官方搜索API...")
        topic_id = self._search_topic_id_by_api(comic_name)
        if topic_id:
            url = f"https://www.kuaikanmanhua.com/web/topic/{topic_id}"
            print(f"通过API定位作品，打开详情页: {url}")
            tab = self.crawler.page.new_tab(url)
            if tab:
                return tab

        raise Exception(f"搜索 '{comic_name}' 未找到漫画。请检查名称是否正确，或改用漫画ID下载。")
    
    def _count_all_chapters(self, target_comic_tab):
        """点击遍历每个分组按钮，累计各组的章节数得到总章数

        快看章节列表一次只渲染50章（最后一组可能不足50），
        仅统计可见组会漏掉后续章节。遍历后切回第1组，避免影响后续下载流程。
        """
        total = 0
        group_index = 1
        while True:
            try:
                group_buttons = target_comic_tab.eles(self.locators['chapter_group_button'], timeout=2)
            except Exception:
                break
            if group_index > len(group_buttons):
                break  # 已遍历完所有分组
            if not self.click_chapter_group(target_comic_tab, group_index):
                break
            try:
                chapter_eles = target_comic_tab.eles(self.locators['chapter_list'], timeout=2)
            except Exception:
                break
            count = len(chapter_eles)
            if count <= 0:
                break  # 页面未就绪，返回当前累计值（调用方会重试）
            total += count
            if count < self.group_size:
                break  # 最后一组不足50章
            group_index += 1
        # 切回第1组，保证后续 collect_chapters_images 从正确分组开始
        self.click_chapter_group(target_comic_tab, 1)
        return total

    def get_chapter_count(self, target_comic_tab):
        # 只数可见组会漏掉后续章节（每组仅渲染50章），
        # 必须遍历点击所有分组累计；结果缓存避免重复点击（结果0不缓存，
        # 以便页面未加载完成时由上层稳定性校验重试）
        if self._desktop_total:
            return self._desktop_total
        total = self._count_all_chapters(target_comic_tab)
        if total > 0:
            self._desktop_total = total
        return total

    def get_cover_image(self, target_comic_tab):
        try:
            # 主封面 img[3] 的URL在 src 属性（data-src 为空、display:none 的懒加载图）
            coverimg_url = target_comic_tab.ele(self.locators['cover_image']).attr('src')
            # 兜底：主封面src为空时用缩略封面 img[2] 的 data-src
            if not is_normal_url(coverimg_url):
                coverimg_xpath = self.locators['cover_image'].replace('img[3]', 'img[2]')
                coverimg_url = target_comic_tab.ele(coverimg_xpath).attr(self.image_attr)
            print(f"封面图片URL: {coverimg_url}")
            return coverimg_url
        except Exception as e:
            print(f"获取封面图片失败: {e}")
            return None
    
    def get_chapter_image_urls(self, chapter_tab, max_img_num):
        herf_list = []
        
        for num in range(1, max_img_num + 1):
            try:
                img_xpath = self.locators['chapter_image'].replace("num", str(num))
                img_ele = chapter_tab.ele(img_xpath, timeout=3)
                herf = img_ele.attr(self.image_attr)
                
                if is_normal_url(herf):
                    print(f"第{num}张图片: {herf}")
                    herf_list.append(herf)
                else:
                    print(f"第{num}张图片URL无效: {herf}")
                    
            except Exception as e:
                print(f"获取第{num}张图片时出错: {e}")
        
        return herf_list
    
    def collect_chapter_images(self, chapter_info, max_wait_time=3):
        chapter_num = chapter_info['chapter_num']
        chapter_tab = chapter_info['tab']
        
        print(f"正在处理章节{chapter_num}")
        
        try:
            time.sleep(1)
            
            start_time = time.time()
            retry_count = 0
            max_retries = 3
            max_img_num = 0
            
            while retry_count <= max_retries:
                img_elements = chapter_tab.eles(self.locators['chapter_image_parent'])
                max_img_num = len(img_elements)
                
                if max_img_num > 0:
                    print(f"章节{chapter_num}检测到{max_img_num}张图片")
                    break
                
                elapsed = time.time() - start_time
                if elapsed >= max_wait_time:
                    if retry_count < max_retries:
                        retry_count += 1
                        print(f"章节{chapter_num} ⚠️ {max_wait_time}秒内未检测到图片，第{retry_count}次重新加载页面...")
                        chapter_tab.refresh()
                        time.sleep(1)
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
            
            herf_list = self.get_chapter_image_urls(chapter_tab, max_img_num)
            
        except Exception as e:
            print(f"处理章节{chapter_num}时出错: {e}")
            herf_list = []
        
        chapter_tab.close()
        
        return {
            'chapter_num': chapter_num,
            'title': chapter_info.get('title', ''),
            'herf_list': herf_list
        }
    
    def click_chapter_group(self, target_comic_tab, group_index):
        """点击分组按钮并验证切换成功（检查active状态，最多重试3次）

        快看章节列表按50章一组分页，页面所有分组按钮常驻DOM，
        点击后Vue即时切换active样式并重渲染列表。仅"点击"不校验的话，
        元素被遮挡/点击落空时列表不会切换，后续会读到错误的章节。
        """
        try:
            group_button_xpath = f"{self.locators['chapter_group_button']}[{group_index}]"
            # 该组的期望active文案，如第2组 -> "51 - 100"
            start = (group_index - 1) * self.group_size + 1
            expected = f"{start} - {start + self.group_size - 1}"

            def get_active_text():
                try:
                    # 注意：必须用 XPath 1.0 的 contains()，@class*='active' 是
                    # XPath 2.0 语法，DrissionPage 底层 lxml 不支持会找不到元素
                    active_btn = target_comic_tab.ele(
                        f"{self.locators['chapter_group_button']}[contains(@class, 'active')]",
                        timeout=1)
                    return ' '.join((active_btn.text or '').split())
                except Exception:
                    return None

            # 当前已是目标组则直接成功
            if get_active_text() == expected:
                return True

            for attempt in range(3):
                group_button = target_comic_tab.ele(group_button_xpath, timeout=5)
                group_button.click()
                # 等待active状态切换到该组（点击后Vue约几十毫秒内完成切换）
                for _ in range(10):  # 最多等5秒
                    time.sleep(0.5)
                    if get_active_text() == expected:
                        print(f"点击第{group_index}组按钮成功 ({expected})")
                        return True
            print(f"点击第{group_index}组按钮失败：未能切换到 {expected}")
            return False
        except Exception as e:
            print(f"点击第{group_index}组按钮失败: {e}")
            return False
    
    def collect_chapters_images(self, target_comic_tab, chapter_start=1, chapter_end=0, max_threads=3, progress_callback=None):
        print(f"设置最大同时收集线程数: {max_threads}")

        chapter_eles = target_comic_tab.eles(self.locators['chapter_list'])
        # 总数用 get_chapter_count 的缓存值（遍历全部分组统计的真实总数），
        # 而不是当前可见组数量（可见组最多只有50章，会让后续分组全部丢失）
        all_chapters_num = self.get_chapter_count(target_comic_tab)
        print(f"总章节数: {all_chapters_num}")
        
        actual_start = max(chapter_start, 1)
        actual_end = min(chapter_end, all_chapters_num) if chapter_end > 0 else all_chapters_num
        
        if actual_start > all_chapters_num:
            print(f"起始章节 {actual_start} 超过总章节数 {all_chapters_num}")
            return []
        
        actual_comic_num = actual_end
        print(f"将下载第 {actual_start}-{actual_end} 章，共 {actual_end - actual_start + 1} 章")

        all_chapters_data = []
        current_chapter = actual_start

        while current_chapter <= actual_comic_num:
            group_index = (current_chapter - 1) // self.group_size + 1
            self.click_chapter_group(target_comic_tab, group_index)

            # 等待分组列表渲染完成（点击切换后Vue重渲染，正常情况下毫秒级完成）
            chapters_in_group = 0
            for _ in range(10):
                chapter_eles = target_comic_tab.eles(self.locators['chapter_list'])
                chapters_in_group = len(chapter_eles)
                if chapters_in_group > 0:
                    break
                time.sleep(0.5)
            if chapters_in_group <= 0:
                print(f"⚠️ 第{group_index}组章节列表渲染失败，跳过该组章节")
                current_chapter = min(current_chapter + self.group_size, actual_comic_num + 1)
                continue

            group_end = min(current_chapter + max_threads - 1, actual_comic_num)
            group_end = min(group_end, current_chapter + chapters_in_group - 1)
            
            print(f"\n处理章节范围: {current_chapter}-{group_end}")

            batch_chapters_info = []
            for num in range(current_chapter, group_end + 1):
                try:
                    chapter_index_in_group = (num - 1) % self.group_size + 1
                    chapter_xpath = f"{self.locators['chapter_list']}[{chapter_index_in_group}]"
                    chapter_ele = target_comic_tab.ele(chapter_xpath)
                    chapter_title = ' '.join((chapter_ele.text or '').split())
                    chapter_tab = chapter_ele.click.for_new_tab()

                    batch_chapters_info.append({
                        'chapter_num': num,
                        'title': chapter_title,
                        'tab': chapter_tab
                    })

                    print(f"打开第{num}章节")

                except Exception as e:
                    print(f"打开第{num}章节时出错: {e}")

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

            # 按章节号排序，保证输出顺序稳定（与线程完成顺序无关）
            results.sort(key=lambda r: r['chapter_num'])
            all_chapters_data.extend(results)
            for _ in results:
                if progress_callback:
                    progress_callback()
            current_chapter = group_end + 1

        return all_chapters_data
