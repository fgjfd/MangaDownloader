import time
import threading
import re

from utils import is_normal_url


class HaoduomanCrawler:
    """好多漫爬虫"""
    
    # 站点元数据
    SITE_NAME = '好多漫'
    SITE_URL = 'https://www.haoduoman.com/'
    REQUIRES_LOGIN = False
    
    # 站点配置
    CONFIG = {
        'site_url': 'https://www.haoduoman.com/',
        'locators': {
            'search_input': 'xpath:/html/body/header/div[2]/div/div[2]/div/form/div/p[1]/input',
            'search_button': 'xpath:/html/body/header/div[2]/div/div[2]/div/form/div/p[2]/button',
            'search_result': 'xpath:/html/body/main/div/div[2]/div/div[1]/div/div/div[2]/a',
            'cover_image': 'xpath:/html/body/main/div/div[2]/div[1]/div/div/div/div[1]/img',
            'chapter_list': 'xpath:/html/body/main/div/div[3]/div[2]/ul/li',
            'chapter_link': 'xpath:/html/body/main/div/div[3]/div[2]/ul/li[num]/a',
            'chapter_image_parent': 'xpath:/html/body/main/div[1]/div/div[1]/div',
            'chapter_image_data_original': 'xpath:/html/body/main/div[1]/div/div[1]/div[num]'
        },
        'image_attr': 'data-original',
        'chapter_group_size': None
    }
    def __init__(self, crawler):
        self.crawler = crawler
        self.locators = crawler.locators
        self.image_attr = crawler.image_attr
    
    def search_comic(self, comic_name, comic_id=None):
        self.crawler.tab.get(self.crawler.site_config['site_url'])
        
        self.crawler.tab.ele(self.locators['search_input']).input(comic_name)
        self.crawler.tab.ele(self.locators['search_button']).click()
        
        time.sleep(0.5)
        
        target_comic_list = self.crawler.tab.ele(self.locators['search_result'])
        href = target_comic_list.attr('href')
        target_comic_tab = self.crawler.tab.new_tab(href)
        
        return target_comic_tab
    
    def get_chapter_count(self, target_comic_tab):
        chapter_eles = target_comic_tab.eles(self.locators['chapter_list'])
        return len(chapter_eles)
    
    def get_chapter_image_urls(self, chapter_tab, max_img_num):
        herf_list = []
        
        for num in range(1, max_img_num + 1):
            try:
                div_xpath = self.locators['chapter_image_data_original'].replace("num", str(num))
                div_ele = chapter_tab.ele(div_xpath, timeout=3)
                herf = div_ele.attr(self.image_attr)
                
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
        
        chapter_eles = target_comic_tab.eles(self.locators['chapter_list'])
        all_chapters_num = len(chapter_eles)
        print(f"总章节数: {all_chapters_num}")
        
        first_chapter_xpath = self.locators['chapter_link'].replace("num", "1")
        first_chapter_ele = target_comic_tab.ele(first_chapter_xpath, timeout=5)
        first_chapter_href = first_chapter_ele.attr("href")
        print(f"第一个章节链接: {first_chapter_href}")
        
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
            group_end = min(current_chapter + max_threads - 1, actual_comic_num)
            print(f"\n处理章节范围: {current_chapter}-{group_end}")
            
            batch_chapters_info = []
            for num in range(current_chapter, group_end + 1):
                chapter_url = re.sub(r'/\d+\.html$', f'/{num}.html', first_chapter_href)
                
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
