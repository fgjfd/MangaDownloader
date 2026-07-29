import time
import threading

from utils import is_normal_url


class MangacopyCrawler:
    """拷贝漫画爬虫"""
    
    # 站点元数据
    SITE_NAME = '拷贝漫画'
    SITE_URL = 'https://www.mangacopy.com/comics'
    REQUIRES_LOGIN = False
    
    # 站点配置
    CONFIG = {
        'site_url': 'https://www.mangacopy.com/comics',
        'locators': {
            'search_result': 'xpath:/html/body/main/div[2]/div/div/div[1]/div[1]/div[1]/a',
            'cover_image': 'xpath:/html/body/main/div[1]/div/div[1]/div/img',
            'chapter_list': 'xpath:/html/body/main/div[2]/div[3]/div/div[2]/div/div[1]/ul[1]/a',
            'chapter_link': 'xpath:/html/body/main/div[2]/div[3]/div/div[2]/div/div[1]/ul[1]/a[num]',
            'chapter_image_parent': 'xpath:/html/body/div[2]/div/ul/li',
            'chapter_image': 'xpath:/html/body/div[2]/div/ul/li[num]/img'
        },
        'image_attr': 'data-src',
        'chapter_group_size': None
    }
    def __init__(self, crawler):
        self.crawler = crawler
        self.locators = crawler.locators
        self.image_attr = crawler.image_attr
    
    def search_comic(self, comic_name, comic_id=None):
        search_url = f"https://www.mangacopy.com/search?q={comic_name}&q_type="
        print(f"正在搜索漫画: {comic_name}")
        print(f"搜索URL: {search_url}")
        
        self.crawler.tab.get(search_url)
        time.sleep(2)
        
        print(f"开始查找搜索结果...")
        print(f"使用的定位器: {self.locators['search_result']}")
        
        max_wait_time = 15
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            try:
                result = self.crawler.tab.ele(self.locators['search_result'], timeout=0)
                if result:
                    print(f"找到搜索结果元素")
                    href = result.attr('href')
                    print(f"搜索结果链接: {href}")
                    if href:
                        print(f"正在打开漫画详情页: {href}")
                        target_comic_tab = self.crawler.page.new_tab(href)
                        print("已打开漫画详情页")
                        return target_comic_tab
                    else:
                        print("搜索结果元素没有href属性")
                else:
                    print("未找到搜索结果元素")
            except Exception as e:
                print(f"查找搜索结果时出错: {e}")
            
            print(f"等待搜索结果... ({int(time.time() - start_time)}s/{max_wait_time}s)")
            time.sleep(1)
        
        print(f"超时！当前页面URL: {self.crawler.tab.url}")
        print(f"当前页面标题: {self.crawler.tab.title}")
        
        raise Exception(f"搜索漫画 '{comic_name}' 超时，未找到搜索结果")
    
    def get_chapter_count(self, target_comic_tab):
        chapter_list_xpath = self.locators['chapter_list']
        chapter_eles = target_comic_tab.eles(chapter_list_xpath)
        return len(chapter_eles)
    
    def get_chapter_image_urls(self, chapter_tab, max_img_num):
        herf_list = []
        
        try:
            try:
                max_img_text = chapter_tab.ele("xpath:/html/body/div[1]/span[2]", timeout=3).text
                expected_img_num = int(max_img_text.strip())
                print(f"页面显示最大图片数: {expected_img_num}")
            except Exception as e:
                print(f"无法获取最大图片数，使用传入值: {max_img_num}")
                expected_img_num = max_img_num
            
            print("开始模拟鼠标滚动触发懒加载...")
            scroll_step = 300
            max_scrolls = expected_img_num * 2
            scroll_count = 0
            
            while scroll_count < max_scrolls:
                img_elements = chapter_tab.eles(self.locators['chapter_image_parent'])
                actual_img_num = len(img_elements)
                
                print(f"当前已加载{actual_img_num}张图片，目标{expected_img_num}张，已滚动{scroll_count}次")
                
                if actual_img_num >= expected_img_num:
                    print(f"✓ 已加载所有图片 ({actual_img_num}/{expected_img_num})")
                    break
                
                chapter_tab.scroll.down(scroll_step)
                time.sleep(0.5)
                scroll_count += 1
            
            img_elements = chapter_tab.eles(self.locators['chapter_image_parent'])
            actual_img_num = len(img_elements)
            
            print(f"最终检测到{actual_img_num}张图片")
            
            if actual_img_num < expected_img_num:
                print(f"⚠️ 实际图片数({actual_img_num})少于预期({expected_img_num})")
                try:
                    html_content = chapter_tab.html
                    debug_file = f"chapter_{expected_img_num}_debug.html"
                    with open(debug_file, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    print(f"已保存网页HTML到: {debug_file}")
                except Exception as e:
                    print(f"保存HTML失败: {e}")
            
            print(f"开始获取图片URL，共{actual_img_num}张...")
            for num in range(1, actual_img_num + 1):
                try:
                    img_xpath = f"xpath:/html/body/div[2]/div/ul/li[{num}]/img"
                    img_ele = chapter_tab.ele(img_xpath, timeout=3)
                    herf = img_ele.attr('data-src')
                    
                    if is_normal_url(herf):
                        print(f"第{num}张图片: {herf}")
                        herf_list.append(herf)
                    else:
                        print(f"第{num}张图片URL无效: {herf}")
                        
                except Exception as e:
                    print(f"获取第{num}张图片时出错: {e}")
        
        except Exception as e:
            print(f"获取图片列表时出错: {e}")
        
        return herf_list
    
    def collect_chapter_images(self, chapter_info, max_wait_time=3):
        chapter_num = chapter_info['chapter_num']
        chapter_url = chapter_info['url']
        main_tab = chapter_info['main_tab']
        
        print(f"正在处理章节{chapter_num}: {chapter_url}")
        
        try:
            chapter_tab = main_tab.new_tab(chapter_url)
            time.sleep(2)
            
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
                        chapter_tab.get(chapter_url)
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
        
        chapter_list_xpath = self.locators['chapter_list']
        chapter_eles = target_comic_tab.eles(chapter_list_xpath)
        all_chapters_num = len(chapter_eles)
        print(f"总章节数: {all_chapters_num}")
        
        chapter_urls = []
        for i, chapter_ele in enumerate(chapter_eles, 1):
            href = chapter_ele.attr('href')
            chapter_urls.append(href)
            print(f"章节{i}: {href}")
        
        if not chapter_urls:
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
                chapter_url = chapter_urls[num - 1]
                
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
