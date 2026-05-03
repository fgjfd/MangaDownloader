import time
import threading

from utils import is_normal_url


class KuaikanCrawler:
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
        
        time.sleep(0.5)
        
        target_comic_list = self.crawler.tab.ele(self.locators['search_result'])
        target_comic_tab = target_comic_list.click.for_new_tab()
        
        return target_comic_tab
    
    def get_chapter_count(self, target_comic_tab):
        chapter_eles = target_comic_tab.eles(self.locators['chapter_list'])
        return len(chapter_eles)
    
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
            'herf_list': herf_list
        }
    
    def click_chapter_group(self, target_comic_tab, group_index):
        try:
            group_button_xpath = f"{self.locators['chapter_group_button']}[{group_index}]"
            group_button = target_comic_tab.ele(group_button_xpath)
            group_button.click()
            time.sleep(0.5)
            print(f"点击第{group_index}组按钮")
            return True
        except Exception as e:
            print(f"点击第{group_index}组按钮失败: {e}")
            return False
    
    def collect_chapters_images(self, target_comic_tab, chapter_start=1, chapter_end=0, max_threads=3, progress_callback=None):
        print(f"设置最大同时收集线程数: {max_threads}")

        chapter_eles = target_comic_tab.eles(self.locators['chapter_list'])
        all_chapters_num = len(chapter_eles)
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
            group_index = (current_chapter - 1) // 50 + 1
            self.click_chapter_group(target_comic_tab, group_index)
            
            chapter_eles = target_comic_tab.eles(self.locators['chapter_list'])
            chapters_in_group = len(chapter_eles)
            
            group_end = min(current_chapter + max_threads - 1, actual_comic_num)
            group_end = min(group_end, current_chapter + chapters_in_group - 1)
            
            print(f"\n处理章节范围: {current_chapter}-{group_end}")

            batch_chapters_info = []
            for num in range(current_chapter, group_end + 1):
                try:
                    chapter_index_in_group = (num - 1) % 50 + 1
                    chapter_xpath = f"{self.locators['chapter_list']}[{chapter_index_in_group}]"
                    chapter_ele = target_comic_tab.ele(chapter_xpath)
                    chapter_tab = chapter_ele.click.for_new_tab()

                    batch_chapters_info.append({
                        'chapter_num': num,
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

            all_chapters_data.extend(results)
            for _ in results:
                if progress_callback:
                    progress_callback()
            current_chapter = group_end + 1

        return all_chapters_data
