# 新站点爬虫开发Skill

## 第一步：站点探查（用Chrome MCP）
1. 导航到目标网站搜索页 → `navigate_page`
2. 搜索一个漫画 → 获取搜索结果页结构
3. 用 `evaluate_script` 计算关键元素xpath：
   ```javascript
   function getXPath(el) {
     if (!el || el === document.body) return '/html/body';
     let stack = [];
     while (el && el !== document.body) {
       let sib = el, cnt = 1;
       while (sib = sib.previousElementSibling) { if (sib.tagName === el.tagName) cnt++; }
       stack.unshift(el.tagName.toLowerCase() + '[' + cnt + ']');
       el = el.parentElement;
     }
     return '/html/body/' + stack.join('/');
   }
   ```
4. 需探查4个页面，找到5个关键xpath：
   - **搜索页**：搜索结果第一个链接 → `search_result`
   - **详情页**：封面图片 → `cover_image`；"查看所有章节"链接 → `chapter_list_link`
   - **章节目录页**：每个章节链接a → `chapter_item`（尽量用一步xpath如`.../div/a`）
   - **章节阅读页**：图片容器中的img → `chapter_image`

## 第二步：确定关键特性
- **image_attr**：图片URL在哪个属性？`src` / `data-src` / `data-path`
- **封面属性**：封面img可能用`src`而章节img用`data-src`，不同则需重写`get_cover_image`
- **章节排序**：目录页从新到旧需`reversed()`？从旧到新直接用？
- **JS渲染**：章节/图片是SSR直接在HTML中，还是JS动态渲染需等待？
- **是否需要滚动**：图片是否需要滚动触发懒加载？还是`data-src`已在HTML中？
- **是否需要登录**：`REQUIRES_LOGIN`
- **下载模式**：`download_mode` = `thread_only`（纯多线程）或 `coroutine`（协程）
- **代理需求**：图片CDN是否需要代理？CONFIG中设置proxy

## 第三步：创建爬虫文件
文件名：`sites_data/{站点名}_crawler.py`，类名：`{站点名}Crawler`

---

# Crawler 规范文档

## 1. 文件结构模板

```python
import time
import threading
from utils import is_normal_url


class XxxCrawler:
    """站点名称爬虫 (站点域名)"""

    # ========== 元数据（必填）==========
    SITE_NAME = '显示名'       # GUI下拉框显示的名称
    SITE_URL = 'https://...'   # 站点首页URL
    REQUIRES_LOGIN = False     # 是否需要登录

    # ========== 配置（必填）==========
    CONFIG = {
        'site_url': 'https://...',
        'locators': {
            'search_result': 'xpath:...',      # 搜索结果第一个链接
            'cover_image': 'xpath:...',        # 封面图片
            'all_chapters_btn': 'xpath:...',   # "查看所有章节"按钮（如有）
            'chapter_item': 'xpath:...',       # 章节项容器
        },
        'image_attr': 'data-src',              # 图片URL属性名
        'chapter_group_size': None,            # 章节分组（通常None）
    }

    # ========== 初始化（必填）==========
    def __init__(self, crawler):
        self.crawler = crawler           # 框架crawler实例
        self.locators = crawler.locators
        self.image_attr = crawler.image_attr

    # ========== 必须实现的方法 ==========
    # ...（见下方详细说明）

    # ========== 可选重写的方法 ==========
    # ...（见下方详细说明）
```

---

## 2. 必须实现的类属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `SITE_NAME` | str | GUI中显示的站点名（如"G社漫画"） |
| `SITE_URL` | str | 站点首页URL（如"https://m.g-mh.org/"） |
| `REQUIRES_LOGIN` | bool | 是否需要登录（默认False） |

---

## 3. CONFIG 配置说明

```python
CONFIG = {
    'site_url': 'https://...',           # 站点基础URL
    'locators': {                        # xpath定位器字典
        'search_result': 'xpath:...',    # 搜索结果第一个链接
        'cover_image': 'xpath:...',      # 详情页封面图片
        'chapter_item': 'xpath:...',     # 章节列表项容器（用于计算数量和遍历）
        # 其他自定义定位器...
    },
    'image_attr': 'data-src',            # 图片URL属性名（常见：src, data-src, data-path）
    'chapter_group_size': None,          # 章节分组大小（通常为None）
}
```

---

## 4. 必须实现的方法

### 4.1 `__init__(self, crawler)`

**功能**：初始化爬虫实例

**参数**：
- `crawler`: 框架提供的ComicCrawler实例

**必须保存的属性**：
```python
def __init__(self, crawler):
    self.crawler = crawler           # 框架实例，用于访问page、tab等
    self.locators = crawler.locators # xpath定位器
    self.image_attr = crawler.image_attr  # 图片属性名
```

---

### 4.2 `search_comic(self, comic_name, comic_id=None)`

**功能**：搜索漫画并打开详情页

**参数**：
- `comic_name` (str): 漫画名称
- `comic_id` (str, optional): 漫画ID（仅腾讯动漫等需要）

**返回值**：
- `ChromiumTab`: 漫画详情页的标签页对象

**实现模板**：
```python
def search_comic(self, comic_name, comic_id=None):
    search_url = f"https://xxx.com/s/{comic_name}"
    print(f"正在搜索漫画: {comic_name}")
    print(f"搜索URL: {search_url}")

    self.crawler.tab.get(search_url)
    time.sleep(2)

    # 获取第一个搜索结果
    result_ele = self.crawler.tab.ele(self.locators['search_result'], timeout=10)
    href = result_ele.attr('href')
    print(f"搜索结果链接: {href}")

    # 打开详情页
    target_comic_tab = self.crawler.page.new_tab(href)
    return target_comic_tab
```

---

### 4.3 `get_chapter_count(self, target_comic_tab)`

**功能**：获取漫画总章节数

**参数**：
- `target_comic_tab` (ChromiumTab): 漫画详情页标签页

**返回值**：
- `int`: 章节总数

**实现要点**：
- 如果详情页只显示部分章节，需要先点击"查看所有章节"按钮
- 使用xpath遍历获取章节数量

**实现模板**：
```python
def get_chapter_count(self, target_comic_tab):
    try:
        # 如需展开章节列表，先点击按钮
        # btn = target_comic_tab.ele(self.locators['all_chapters_btn'], timeout=5)
        # if btn:
        #     btn.click()
        #     time.sleep(3)

        # 获取章节div元素数量
        chapter_divs = target_comic_tab.eles(self.locators['chapter_item'], timeout=10)
        count = len(chapter_divs)

        print(f"检测到 {count} 个章节")
        return count
    except Exception as e:
        print(f"获取章节数失败: {e}")
        return 0
```

---

### 4.4 `collect_chapters_images(self, target_comic_tab, chapter_start=1, chapter_end=0, max_threads=3, progress_callback=None)`

**功能**：收集指定章节范围内的所有图片URL

**参数**：
- `target_comic_tab` (ChromiumTab): 漫画详情页标签页
- `chapter_start` (int): 起始章节号（从1开始）
- `chapter_end` (int): 结束章节号（0表示到最后一章）
- `max_threads` (int): 同时打开的标签页数量
- `progress_callback` (callable): 进度回调函数，每完成一章调用一次

**返回值**：
- `list`: 章节数据列表，每个元素格式：
  ```python
  [{'chapter_num': 1, 'herf_list': ['url1', 'url2', ...]}, ...]
  ```

**实现模板**：
```python
def collect_chapters_images(self, target_comic_tab, chapter_start=1, chapter_end=0, max_threads=3, progress_callback=None):
    print(f"设置最大同时收集线程数: {max_threads}")

    # 1. 获取章节URL列表
    chapter_urls = self._get_chapter_urls_from_page(target_comic_tab)
    all_chapters_num = len(chapter_urls)
    print(f"总章节数: {all_chapters_num}")

    if all_chapters_num == 0:
        print("未找到任何章节链接")
        return []

    # 2. 计算实际下载范围
    actual_start = max(chapter_start, 1)
    actual_end = min(chapter_end, all_chapters_num) if chapter_end > 0 else all_chapters_num

    if actual_start > all_chapters_num:
        print(f"起始章节 {actual_start} 超过总章节数 {all_chapters_num}")
        return []

    print(f"将下载第 {actual_start}-{actual_end} 章，共 {actual_end - actual_start + 1} 章")

    # 3. 分批并行处理
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
                'main_tab': self.crawler.tab
            })
            print(f"准备处理第{num}章节: {chapter_url}")

        # 并行处理
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
```

---

## 5. 可选重写的方法

### 5.1 `get_cover_image(self, target_comic_tab)`

**何时重写**：封面图片属性与章节图片属性不同时（如封面用`src`，章节用`data-src`）

**返回值**：
- `str`: 封面图片URL

**示例**：
```python
def get_cover_image(self, target_comic_tab):
    """封面使用src属性，章节使用data-src"""
    try:
        img_ele = target_comic_tab.ele(self.locators['cover_image'], timeout=15)
        cover_url = img_ele.attr('src')  # 注意：封面用src
        if not cover_url:
            cover_url = img_ele.attr('data-src')
        print(f"封面图片URL: {cover_url}")
        return cover_url
    except Exception as e:
        print(f"获取封面图片失败: {e}")
        return None
```

---

### 5.2 `get_chapter_image_urls(self, chapter_tab)`

**功能**：从章节页面提取所有图片URL

**参数**：
- `chapter_tab` (ChromiumTab): 章节阅读页标签页

**返回值**：
- `list`: 图片URL列表

**实现要点**：
- 使用xpath遍历方式
- 支持重试机制

**示例**：
```python
def get_chapter_image_urls(self, chapter_tab):
    herf_list = []
    try:
        time.sleep(2)

        # 1. 先获取图片容器元素，确定数量
        img_containers = chapter_tab.eles('xpath:/html/body/.../div', timeout=10)
        total_imgs = len(img_containers)
        print(f"找到 {total_imgs} 个图片容器")

        if total_imgs > 0:
            # 2. 遍历每个容器，获取img的data-src
            for i in range(1, total_imgs + 1):
                try:
                    img_ele = chapter_tab.ele(f'xpath:/html/body/.../div[{i}]/img', timeout=5)
                    src = img_ele.attr('data-src')
                    if not src:
                        src = img_ele.attr('src')
                    if src and is_normal_url(src):
                        herf_list.append(src)
                except Exception as e:
                    print(f"提取第{i}张图片时出错: {e}")

        print(f"共提取 {len(herf_list)} 张图片")
    except Exception as e:
        print(f"提取图片URL失败: {e}")

    return herf_list
```

---

### 5.3 `collect_chapter_images(self, chapter_info)`

**功能**：处理单个章节的图片收集

**参数**：
- `chapter_info` (dict): 包含 `chapter_num`, `url`, `main_tab`

**返回值**：
- `dict`: `{'chapter_num': int, 'herf_list': [url_str, ...]}`

**实现要点**：
- 打开新标签页
- 等待图片加载（建议重试3次）
- 提取图片URL
- 关闭标签页

**示例**：
```python
def collect_chapter_images(self, chapter_info):
    chapter_num = chapter_info['chapter_num']
    chapter_url = chapter_info['url']
    main_tab = chapter_info['main_tab']

    print(f"正在处理章节{chapter_num}: {chapter_url}")

    try:
        chapter_tab = main_tab.new_tab(chapter_url)
        time.sleep(2)

        # 重试机制
        retry_count = 0
        max_retries = 3
        while retry_count <= max_retries:
            try:
                img_containers = chapter_tab.eles('xpath:...', timeout=5)
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
                print(f"章节{chapter_num} 已达最大重试次数")
                chapter_tab.close()
                return {'chapter_num': chapter_num, 'herf_list': []}

        herf_list = self.get_chapter_image_urls(chapter_tab)
        chapter_tab.close()

    except Exception as e:
        print(f"处理章节{chapter_num}时出错: {e}")
        herf_list = []

    return {'chapter_num': chapter_num, 'herf_list': herf_list}
```

---

### 5.4 `_get_chapter_urls_from_page(self, target_comic_tab)`

**功能**：从章节目录页获取所有章节URL

**返回值**：
- `list`: 章节信息列表，每个元素格式：
  ```python
  [{'num': 1, 'url': 'https://...', 'title': '第1章'}, ...]
  ```

**注意**：章节列表如果是从新到旧排列，需要`reversed()`并重新编号

---

## 6. 代码规范

1. **必须使用完整xpath**：禁止使用CSS选择器
2. **遍历提取用索引方式**：`div[{i}]` 而非直接 `eles()`
3. **xpath索引从1开始**：DrissionPage特性，`range(1, total+1)`
4. **章节顺序**：确保从旧到新排列
5. **异常处理**：关键方法必须try-except，打印错误信息
6. **进度输出**：使用`print()`输出关键步骤信息

---

## 7. 文件命名规范

- 文件名：`{站点简称}_crawler.py`（如 `gmh_crawler.py`）
- 类名：`{站点简称大写}Crawler`（如 `GmhCrawler`）
- 存放位置：`sites_data/` 目录

## 第四步：放入爬虫文件
将爬虫文件放入 `sites_data/` 目录，软件启动时会自动加载。无需手动注册。

**注意**：
- 如果站点名已存在，会被自动过滤（不重复加载）
- 删除 `.py` 文件后重启软件，站点即从列表消失

## 第五步：测试
用脚本直接调用crawler测试，不要依赖GUI：
```python
from crawler import ComicCrawler

BROWSER_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

crawler = ComicCrawler('站点名', BROWSER_PATH, headless=False)
tab = crawler.search_comic('漫画名')
count = crawler.get_chapter_count(tab)
print(f"章节数: {count}")
data = crawler.collect_chapters_images(tab, chapter_start=1, chapter_end=2, max_threads=2)

for chapter in data:
    print(f"第{chapter['chapter_num']}章: {len(chapter['herf_list'])}张图片")

crawler.page.quit()
```

## 常见坑

### DrissionPage xpath相关
- **先取父div再找子元素会失败**：`div.ele('tag:a')` 对列表项内部的子元素经常找不到，应改为xpath一步到位直接取到目标元素：`page.eles('xpath:.../div/a')` ✅ 而非 `page.eles('xpath:.../div')` + `div.ele('tag:a')` ❌
- **xpath层级要精确**：`/html/body/main/div/div[2]/div[3]/div` ✅ vs `/html/body/main/div/div/div[2]/div[3]/div` ❌（多了一层`div/`），用Chrome MCP的`evaluate_script`+getXPath函数计算确保正确
- **xpath对大DOM可能返回0**：如果xpath一步到位仍返回0，CSS选择器做回退方案

### xpath遍历提取的最佳实践（必遵循）
- **完整xpath + 先取数量再遍历**：不直接用`eles()`一次性获取，而是：
  1. 先用完整xpath获取容器元素列表，用`len()`确定最大数量
  2. 再用带索引的完整xpath遍历每个元素，如`xpath:/html/body/.../div[{i}]/a`
- **示例（小包子）**：
  - 章节目录：容器 `/html/body/main/div/div[2]/div[3]/div` → `len()`得数量 → 遍历 `/html/body/main/div/div[2]/div[3]/div[{i}]/a` 取href
  - 章节图片：容器 `/html/body/main/section/div/div/div[4]/div/div[1]/div/div` → `len()`得数量 → 遍历 `/html/body/main/section/div/div/div[4]/div/div[1]/div/div[{i}]/img` 取data-src
- **好处**：避免大DOM场景下`eles()`返回不全（如只返回前40个），逐个索引提取更可靠

### 非懒加载场景的优化规则
- **判断是否懒加载**：
  - 懒加载：滚动页面时才加载新内容，DOM元素数量会增加
  - 非懒加载：所有元素都在HTML中，DOM已完整渲染
- **非懒加载场景**：如果页面是SSR或元素已全部渲染在HTML中：
  - 先获取完整的HTML源码（`page.html` 或等待页面加载完成）
  - 再用xpath在HTML中一次性查找所有元素，避免逐个遍历的开销
  - 示例：`chapter_divs = target_comic_tab.eles('xpath:/html/body/main/div/div[2]/div[3]/div')` 一次性获取所有div，然后遍历取属性
- **懒加载场景**：必须用xpath逐个索引遍历，确保触发加载

### 封面图片
- 封面img可能用`src`而章节img用`data-src`，需重写`get_cover_image`
- `crawler.py`的`get_cover_image`已修复为优先委托给site_crawler的自定义方法

### 页面导航
- 导航到章节目录页后，详情页的xpath失效（HTML已变），所以`get_cover_image`必须在导航前调用
- 章节列表从新到旧排列时需`list(reversed())`

### 框架特性
- Astro/Alpine.js站点章节已在SSR HTML中，不需要等JS渲染
