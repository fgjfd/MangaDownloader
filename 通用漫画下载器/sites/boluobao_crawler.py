import time
import threading
import json


class BoluobaoCrawler:
    def __init__(self, crawler):
        self.crawler = crawler
        self.locators = crawler.locators
        self.image_attr = crawler.image_attr
    
    def search_comic(self, comic_name, comic_id=None):
        self.crawler.tab.get(self.crawler.site_config['site_url'])
        
        if self.crawler.login_mode:
            if self.crawler.has_saved_cookies():
                self.crawler.load_cookies()
                self.crawler.tab.refresh()
                time.sleep(1)
        
        self.crawler.tab.ele(self.locators['search_input']).input(comic_name)
        self.crawler.tab.ele(self.locators['search_button']).click()
        
        time.sleep(2)
        
        result = self.crawler.tab.ele(self.locators['search_result'], timeout=10)
        href = result.attr('href')
        target_comic_tab = self.crawler.page.new_tab(href)
        
        return target_comic_tab
    
    def get_chapter_count(self, target_comic_tab):
        chapter_eles = target_comic_tab.eles(self.locators['chapter_list'])
        return len(chapter_eles)
    
    def get_chapter_image_urls(self, chapter_tab, chapter_num, timeout=10):
        herf_list = []
        
        print("开始监听网络请求...")
        
        try:
            packet = chapter_tab.listen.wait(timeout=timeout)
            if packet:
                print(f"找到getPics API请求: {packet.url}")
                response_body = packet.response.body
                print(f"章节{chapter_num} response_body类型: {type(response_body)}")
                
                if response_body:
                    if isinstance(response_body, dict):
                        data = response_body
                    else:
                        data = json.loads(response_body)
                    
                    if data.get('status') == 200 and 'data' in data:
                        herf_list = data['data']
                        print(f"从API响应获取到 {len(herf_list)} 张图片")
                        return herf_list
        except Exception as e:
            print(f"监听网络请求时出错: {e}")
        
        print(f"超时：未找到getPics API请求")
        return herf_list
    
    def collect_chapter_images(self, chapter_info, timeout=15):
        chapter_num = chapter_info['chapter_num']
        chapter_url = chapter_info['url']
        main_tab = chapter_info['main_tab']
        chapter_tab = None
        
        print(f"正在处理章节{chapter_num}: {chapter_url}")
        
        try:
            chapter_tab = main_tab.new_tab(chapter_url)
            chapter_tab.listen.start('getPics')
            
            time.sleep(0.5)
            
            chapter_tab.refresh()
            print(f"已刷新页面以触发数据包")
            
            time.sleep(1)
            
            herf_list = self.get_chapter_image_urls(chapter_tab, chapter_num, timeout)
            
        except Exception as e:
            print(f"处理章节{chapter_num}时出错: {e}")
            herf_list = []
        
        try:
            if chapter_tab:
                chapter_tab.listen.stop()
                chapter_tab.close()
        except:
            pass
        
        return {
            'chapter_num': chapter_num,
            'herf_list': herf_list
        }
    
    def collect_chapters_images(self, target_comic_tab, chapter_start=1, chapter_end=0, max_threads=5, progress_callback=None):
        print(f"设置最大同时收集线程数: {max_threads}")
        
        chapter_eles = target_comic_tab.eles(self.locators['chapter_list'])
        all_chapters_num = len(chapter_eles)
        print(f"总章节数: {all_chapters_num}")
        
        if all_chapters_num == 0:
            print("未找到任何章节")
            return []
        
        chapter_eles = list(reversed(chapter_eles))
        print(f"菠萝包章节顺序已反转（原顺序：最后一章在前，第一章在后）")
        
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
                idx = num - 1
                chapter_url = chapter_eles[idx].attr('href')
                
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
