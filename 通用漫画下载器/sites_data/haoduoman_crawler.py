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
            'chapter_list': 'xpath://ul[contains(@class, "comic-chapters")]/li',
            'chapter_link': 'xpath://ul[contains(@class, "comic-chapters")]/li[num]/a'
        },
        'image_attr': 'data-original',
        'chapter_group_size': None
    }

    # 章节页图片URL经过加密：页面内联的params密文由站点JS解密后挂到全局params上，
    # 解密后以blob形式渲染（img的src为blob:，无data-original属性）。
    # 直接读取解密后的params：真实URL = images_hosts[0] + chapter_images[i]，CDN可直连下载
    _CHAPTER_IMAGES_JS = """
    if (typeof params === 'object' && params && Array.isArray(params.chapter_images)) {
        var host = (params.images_hosts && params.images_hosts[0]) || '';
        return params.chapter_images.map(function(p) { return host + p; });
    }
    return null;
    """
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
    
    def get_cover_image(self, target_comic_tab):
        # 封面img现在直接使用src属性（无data-original懒加载）
        try:
            cover_ele = target_comic_tab.ele(self.locators['cover_image'])
            cover_url = cover_ele.attr('src')
            if not is_normal_url(cover_url):
                cover_url = cover_ele.attr(self.image_attr)
            print(f"封面图片URL: {cover_url}")
            return cover_url
        except Exception as e:
            print(f"获取封面图片失败: {e}")
            return None
    
    def get_chapter_image_urls(self, chapter_tab, max_img_num=None):
        # 从页面全局的解密params中拼接真实图片URL（host + 相对路径）
        herf_list = chapter_tab.run_js(self._CHAPTER_IMAGES_JS, timeout=10) or []
        
        normal_list = []
        for herf in herf_list:
            if is_normal_url(herf):
                normal_list.append(herf)
        
        print(f"共提取 {len(normal_list)} 张图片")
        return normal_list
    
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
            herf_list = []
            
            while retry_count <= max_retries:
                # 等待站点JS完成params解密（解密后全局params含chapter_images数组）
                herf_list = self.get_chapter_image_urls(chapter_tab)
                
                if herf_list:
                    print(f"章节{chapter_num}检测到{len(herf_list)}张图片")
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
                            'title': chapter_info.get('title', ''),
                            'herf_list': []
                        }
                else:
                    time.sleep(0.5)
            
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
        
        chapter_eles = target_comic_tab.eles(self.locators['chapter_list'])
        all_chapters_num = len(chapter_eles)
        print(f"总章节数: {all_chapters_num}")
        
        first_chapter_xpath = self.locators['chapter_link'].replace("num", "1")
        first_chapter_ele = target_comic_tab.ele(first_chapter_xpath, timeout=5)
        first_chapter_href = first_chapter_ele.attr("href")
        print(f"第一个章节链接: {first_chapter_href}")

        # 提取章节元素文本作为章节名（li内a的文本，如"第1话 xxx"；缺失时回退）
        chapter_titles = []
        for li_ele in chapter_eles:
            title = ' '.join((li_ele.text or '').split())
            chapter_titles.append(title)
        print(f"已提取 {len([t for t in chapter_titles if t])} 个章节名")
        
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

                title = chapter_titles[num - 1] if num - 1 < len(chapter_titles) else ''
                if not title:
                    title = f"第{num}章"

                batch_chapters_info.append({
                    'chapter_num': num,
                    'url': chapter_url,
                    'title': title,
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
