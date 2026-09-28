import time
import threading
import re
import subprocess
from functools import partial

# 隐藏子进程的控制台窗口
# errors='ignore'兜底：部分系统进程（cmd/wmic）输出GBK，强制utf-8解码会在后台线程崩溃
CREATE_NO_WINDOW = 0x08000000
subprocess.Popen = partial(subprocess.Popen, encoding='utf-8', errors='ignore', creationflags=CREATE_NO_WINDOW)

from lxml import etree
from utils import is_normal_url

# execjs 为可选依赖（仅作为解密兜底）。无 Node/execjs 环境（含打包 exe）时不影响纯Python解密。
try:
    import execjs
    _EXECJS_AVAILABLE = True
except ImportError:
    execjs = None
    _EXECJS_AVAILABLE = False


js_code = """
var document = {
    getElementsByTagName: function(tag) {
        return tag === 'html' ? [{}] : [];
    },
    getElementById: function(id) { return null; },
    querySelector: function(sel) { return null; },
    querySelectorAll: function(sel) { return []; }
};
var window = {
    Array: Array,
    Object: Object,
    String: String,
    Number: Number,
    Boolean: Boolean,
    Math: Math,
    Date: Date,
    parseInt: parseInt,
    parseFloat: parseFloat,
    isNaN: isNaN,
    isFinite: isFinite,
    JSON: JSON
};
var navigator = { userAgent: '' };

function Base(data, nonce) {
    W = {}
    W['DATA'] = data;
    W['nonce'] = nonce;
    _keyStr = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=";
    this.decode = function(c) {
        var a = "", b, d, h, f, g, e = 0;
        for (c = c.replace(/[^A-Za-z0-9\\+\\/\\=]/g, "");
            e < c.length;)
            b = _keyStr.indexOf(c.charAt(e++)), d = _keyStr.indexOf(c.charAt(e++)), f = _keyStr.indexOf(c.charAt(e++)), g = _keyStr.indexOf(c.charAt(e++)), b = b << 2 | d >> 4, d = (d & 15) << 4 | f >> 2, h = (f & 3) << 6 | g, a += String.fromCharCode(b), 64 != f && (a += String.fromCharCode(d)), 64 != g && (a += String.fromCharCode(h));
        return a = _utf8_decode(a)
    };
    _utf8_decode = function(c) {
        for (var a = "", b = 0, d = c1 = c2 = 0;
            b < c.length;)
            d = c.charCodeAt(b), 128 > d ? (a += String.fromCharCode(d), b++) : 191 < d && 224 > d ? (c2 = c.charCodeAt(b + 1), a += String.fromCharCode((d & 31) << 6 | c2 & 63), b += 2) : (c2 = c.charCodeAt(b + 1), c3 = c.charCodeAt(b + 2), a += String.fromCharCode((d & 15) << 12 | (c2 & 63) << 6 | c3 & 63), b += 3);
        return a
    }
    var T = W['DA' + 'TA'].split(''), N = W['n' + 'onc' + 'e'], len, locate, str;
    N = N.match(/\\d+[a-zA-Z]+/g);
    len = N.length;
    while (len--) {
        locate = parseInt(N[len]) & 255;
        str = N[len].replace(/\\d+/g, '');
        T.splice(locate, str.length)
    }
    T = T.join('');
    _v = JSON.parse(this.decode(T));
    return _v;
}
"""


def _tencent_decode(data, nonce):
    """纯Python复现腾讯动漫 Base(data, nonce) 解密算法，无需 execjs/Node 运行时。

    算法（与页面 JS 一致）：
    1. 按 nonce 的 \\d+[a-zA-Z]+ 段逆序对 DATA 做字符删除(splice)
    2. base64 解码 + UTF-8
    3. JSON.parse，返回含 'picture' 的 dict
    """
    import base64
    import json

    # 1. 按 nonce 的 \d+[a-zA-Z]+ 段逆序对 DATA 做字符删除(splice)
    T = list(data)
    segments = re.findall(r'\d+[a-zA-Z]+', nonce)
    for seg in reversed(segments):
        locate = int(re.match(r'\d+', seg).group()) & 255
        str_len = len(re.sub(r'\d+', '', seg))
        # JS splice(locate, str_len)：从 locate 位置删除 str_len 个字符
        del T[locate:locate + str_len]
    joined = ''.join(T)

    # 2. base64 解码 + UTF-8（b64decode 默认丢弃非 base64 字符，与 JS 的 replace 一致）
    decoded = base64.b64decode(joined).decode('utf-8')

    # 3. JSON.parse
    return json.loads(decoded)


def _decrypt_tencent(data, nonce):
    """解密入口：优先纯Python，失败回退 execjs（可选兜底，execjs 不可用时不影响）。"""
    try:
        return _tencent_decode(data, nonce)
    except Exception as e:
        print(f"纯Python解密失败，尝试execjs兜底: {e}")
        if not _EXECJS_AVAILABLE:
            raise
        try:
            ctx = execjs.compile(js_code)
            return ctx.call("Base", data, nonce)
        except Exception as e2:
            print(f"execjs兜底解密也失败: {e2}")
            raise


class TencentCrawler:
    """腾讯动漫爬虫"""
    
    # 站点元数据
    SITE_NAME = '腾讯动漫'
    SITE_URL = 'https://ac.qq.com/'
    REQUIRES_LOGIN = True
    
    # 站点配置
    CONFIG = {
        'site_url': 'https://ac.qq.com/',
        'locators': {
            'search_input': '@tag()=input',
            'search_button': '@tag()=button',
            'search_result': 'xpath:/html/body/div[3]/ul/li[1]/a',
            'cover_image': 'xpath:/html/body/div[3]/div[3]/div/div/div[1]/a/img',
            'chapter_list_container': 'xpath:/html/body/div[3]/em/div[2]/div[2]/div/div[2]/ol[1]/li',
            'chapter_image_parent': 'xpath:/html/body/div[5]/ul/li',
            'chapter_image': 'xpath:/html/body/div[5]/ul/li[num]/img'
        },
        'image_attr': 'src',
        'chapter_group_size': None
    }
    
    def __init__(self, crawler):
        self.crawler = crawler
        self.locators = crawler.locators
        self.image_attr = crawler.image_attr
    
    def search_comic(self, comic_name, comic_id=None):
        if comic_id:
            target_url = f"https://ac.qq.com/Comic/ComicInfo/id/{comic_id}"
            self.crawler.tab.get(self.crawler.site_config['site_url'])
            
            if self.crawler.login_mode:
                if self.crawler.has_saved_cookies():
                    self.crawler.load_cookies()
                    self.crawler.tab.refresh()
                    time.sleep(1)
            
            target_comic_tab = self.crawler.page.new_tab(target_url)
            
            try:
                comic_name_xpath = 'xpath:/html/body/div[3]/div[3]/div/div/div[2]/div/div[1]/h2/strong'
                comic_name_ele = target_comic_tab.ele(comic_name_xpath, timeout=5)
                if comic_name_ele:
                    actual_comic_name = comic_name_ele.text
                    print(f"获取到漫画名字: {actual_comic_name}")
                    return target_comic_tab, actual_comic_name
            except Exception as e:
                print(f"获取漫画名字失败: {e}")
            
            return target_comic_tab
        
        search_url = f"https://ac.qq.com/Comic/searchList?search={comic_name}"
        print(f"\n========== 腾讯动漫搜索开始 ==========")
        print(f"搜索关键词: {comic_name}")
        print(f"搜索URL: {search_url}")
        
        self.crawler.tab.get(search_url)
        print(f"已打开搜索页面")
        
        if self.crawler.login_mode:
            if self.crawler.has_saved_cookies():
                print(f"加载已保存的Cookie...")
                self.crawler.load_cookies()
                self.crawler.tab.refresh()
                time.sleep(1)
        
        print(f"等待搜索结果加载...")
        time.sleep(2)
        
        try:
            print(f"查找搜索结果 (定位器: {self.locators['search_result']})")
            result = self.crawler.tab.ele(self.locators['search_result'], timeout=10)
            print(f"找到搜索结果元素")
            
            href = result.attr('href')
            print(f"搜索结果链接: {href}")
            
            if href:
                print(f"打开新标签页访问漫画详情页...")
                target_comic_tab = self.crawler.page.new_tab(href)
                print(f"漫画详情页URL: {target_comic_tab.url}")
                print(f"漫画详情页标题: {target_comic_tab.title}")
                print(f"========== 搜索完成 ==========\n")
                return target_comic_tab
            else:
                raise Exception("搜索结果没有href属性")
        except Exception as e:
            print(f"查找搜索结果时出错: {e}")
            print(f"当前页面URL: {self.crawler.tab.url}")
            print(f"当前页面标题: {self.crawler.tab.title}")
            import traceback
            traceback.print_exc()
            raise Exception(f"搜索漫画 '{comic_name}' 失败: {e}")
    
    def get_chapter_count(self, target_comic_tab):
        try:
            html = target_comic_tab.html
            tree = etree.HTML(html)
            
            li_xpath = self.locators['chapter_list_container'].replace('xpath:', '')
            a_elements = tree.xpath(f'{li_xpath}/p/span/a')
            
            total_count = len(a_elements)
            print(f"总章节数: {total_count}")
            return total_count
        except Exception as e:
            print(f"获取章节数量失败: {e}")
            return 0
    
    def get_chapter_urls(self, target_comic_tab):
        chapter_urls = []
        
        print(f"========== 开始获取章节列表 ==========")
        print(f"漫画页面URL: {target_comic_tab.url}")
        print(f"漫画页面标题: {target_comic_tab.title}")
        
        try:
            html = target_comic_tab.html
            tree = etree.HTML(html)
            
            li_xpath = self.locators['chapter_list_container'].replace('xpath:', '')
            a_elements = tree.xpath(f'{li_xpath}/p/span/a')
            
            print(f"找到 {len(a_elements)} 个章节链接")
            
            for idx, a_ele in enumerate(a_elements, 1):
                href = a_ele.get('href')
                if href:
                    if href.startswith('/'):
                        href = 'https://ac.qq.com' + href
                    chapter_urls.append({
                        'num': idx,
                        'url': href,
                        'title': ' '.join(''.join(a_ele.itertext()).split()),
                    })
            
            print(f"\n========== 章节列表获取完成 ==========")
            print(f"成功获取 {len(chapter_urls)} 个章节链接")
            for ch in chapter_urls[:10]:
                print(f"  前10章预览 - 章节{ch['num']}: {ch['url']}")
            if len(chapter_urls) > 10:
                print(f"  ... 还有 {len(chapter_urls) - 10} 个章节")
        except Exception as e:
            print(f"获取章节列表失败: {e}")
            import traceback
            traceback.print_exc()
        
        return chapter_urls
    
    def get_chapter_image_urls(self, chapter_tab):
        herf_list = []
        
        print(f"\n========== 开始获取章节图片 ==========")
        print(f"章节页面URL: {chapter_tab.url}")
        print(f"章节页面标题: {chapter_tab.title}")
        
        try:
            tree = etree.HTML(chapter_tab.html)
            
            contain_data = tree.xpath('//script[contains(text(),"var DATA =")]/text()')
            if not contain_data:
                print("未找到DATA变量")
                return herf_list
            
            pattern = r"var\s+DATA\s*=\s*'([^']+)'"
            match = re.search(pattern, contain_data[0])
            if not match:
                print("未匹配到DATA值")
                return herf_list
            
            data = match.group(1)
            print(f"成功提取DATA")

            # 获取 nonce：页面脚本执行后会把 window["n"+"once"]/window["no"+"nce"] 覆盖成随机浮点诱饵，
            # 因此不能直接读 window 变量。真实 nonce 在 HTML 内联脚本的混淆表达式中，
            # 用 run_js 在浏览器 JS 引擎里 eval（无需 Node/execjs）。
            nonce = None
            nonce_script_list = tree.xpath('//script[contains(text(),"window[")]/text()')
            if len(nonce_script_list) >= 2:
                nonce_js_code = nonce_script_list[1].strip()
                print(f"提取的nonce JS代码:\n{nonce_js_code}")
                pattern = r'window\["[^"]*"\s*\+\s*"[^"]*"\]\s*=\s*(.+?);'
                m = re.search(pattern, nonce_js_code)
                if m:
                    nonce_expr = m.group(1).strip()
                    # 1) 优先用浏览器 JS 引擎 eval（无 Node 依赖）
                    try:
                        val = chapter_tab.run_js(f'return ({nonce_expr})')
                        if val:
                            nonce = str(val)
                    except Exception as e:
                        print(f"run_js计算nonce失败: {e}")
                    # 2) 回退 execjs eval（仅当 execjs 可用）
                    if not nonce and _EXECJS_AVAILABLE:
                        try:
                            ctx = execjs.compile(js_code)
                            nonce = ctx.eval(nonce_expr)
                        except Exception as e:
                            print(f"execjs计算nonce失败: {e}")

            # 3) 最后回退：直接读 window 变量（部分页面可能未被覆盖为诱饵）
            if not nonce:
                for expr in ('return window["n"+"once"]', 'return window["no"+"nce"]'):
                    try:
                        val = chapter_tab.run_js(expr)
                        if val and re.fullmatch(r'[0-9a-f]+', str(val)):
                            nonce = str(val)
                            break
                    except Exception as e:
                        print(f"run_js获取nonce失败 ({expr}): {e}")

            if not nonce:
                print("未找到nonce")
                return herf_list

            print(f"计算后的nonce值: {nonce}")

            result = _decrypt_tencent(data, nonce)
            urls = [item['url'] for item in result['picture']]
            # 保留 is_normal_url 过滤
            urls = [u for u in urls if is_normal_url(u)]
            print(f"图片URL列表:")
            for url in urls:
                print(url)
            herf_list = urls
            
            print(f"\n========== 图片获取完成 ==========")
            print(f"成功获取 {len(herf_list)} 张图片URL")
        except Exception as e:
            print(f"获取图片列表时出错: {e}")
            import traceback
            traceback.print_exc()
        
        return herf_list
    
    def collect_chapter_images(self, chapter_info, max_wait_time=5):
        chapter_num = chapter_info['chapter_num']
        chapter_url = chapter_info['url']
        main_tab = chapter_info['main_tab']
        
        print(f"\n{'='*60}")
        print(f"开始处理章节 {chapter_num}")
        print(f"章节URL: {chapter_url}")
        print(f"{'='*60}")
        
        try:
            chapter_tab = main_tab.new_tab(chapter_url)
            print(f"已打开新标签页")
            
            print(f"刷新页面...")
            chapter_tab.refresh()
            
            start_time = time.time()
            retry_count = 0
            max_retries = 3
            
            while retry_count <= max_retries:
                # 等待条件改为"页面存在 var DATA 脚本"，与图片来源一致
                # （懒加载的 li 标签不是图片来源，定位失败会导致误判为空）
                has_data = False
                try:
                    val = chapter_tab.run_js('return typeof window.DATA !== "undefined"')
                    if val:
                        has_data = True
                except Exception:
                    pass
                if not has_data:
                    try:
                        has_data = 'var DATA =' in chapter_tab.html
                    except Exception:
                        has_data = False

                if has_data:
                    print(f"章节{chapter_num}检测到DATA脚本，开始获取图片")
                    break
                
                elapsed = time.time() - start_time
                if elapsed >= max_wait_time:
                    if retry_count < max_retries:
                        retry_count += 1
                        print(f"章节{chapter_num} ⚠️ {max_wait_time}秒内未检测到内容，第{retry_count}次重新加载页面...")
                        chapter_tab.get(chapter_url)
                        time.sleep(1)
                        start_time = time.time()
                    else:
                        print(f"章节{chapter_num} ✗ 已达到最大重试次数({max_retries})，仍未检测到内容")
                        print(f"当前页面URL: {chapter_tab.url}")
                        print(f"当前页面标题: {chapter_tab.title}")
                        chapter_tab.close()
                        return {
                            'chapter_num': chapter_num,
                            'title': chapter_info.get('title', ''),
                            'herf_list': []
                        }
                else:
                    time.sleep(0.5)
            
            herf_list = self.get_chapter_image_urls(chapter_tab)
            
            print(f"章节{chapter_num}获取完成，共{len(herf_list)}张图片")
            chapter_tab.close()
            
        except Exception as e:
            print(f"处理章节{chapter_num}时出错: {e}")
            import traceback
            traceback.print_exc()
            herf_list = []
        
        return {
            'chapter_num': chapter_num,
            'title': chapter_info.get('title', ''),
            'herf_list': herf_list
        }
    
    def collect_chapters_images(self, target_comic_tab, chapter_start=1, chapter_end=0, max_threads=3, progress_callback=None):
        print(f"设置最大同时收集线程数: {max_threads}")
        
        chapter_urls = self.get_chapter_urls(target_comic_tab)
        total_chapters = len(chapter_urls)
        print(f"总章节数: {total_chapters}")
        
        if not chapter_urls:
            print("未找到任何章节链接")
            return []
        
        actual_start = max(chapter_start, 1)
        actual_end = min(chapter_end, total_chapters) if chapter_end > 0 else total_chapters
        
        if actual_start > total_chapters:
            print(f"起始章节 {actual_start} 超过总章节数 {total_chapters}")
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
