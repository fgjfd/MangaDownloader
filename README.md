# 通用漫画下载器

一个插件化架构的漫画下载工具，支持多站点扩展，提供友好的GUI界面和命令行模式。

## 功能特性

- ✅ **插件化架构**：每个站点独立爬虫文件，易于扩展
- ✅ **GUI界面**：基于Tkinter的图形界面，操作简单直观
- ✅ **多站点支持**：已适配多个漫画站点
- ✅ **章节选择**：支持下载指定范围的章节
- ✅ **并行下载**：多线程加速图片下载
- ✅ **进度显示**：实时显示下载进度和网速
- ✅ **失败重试**：自动重试失败的图片，保存失败列表
- ✅ **站点管理**：支持添加/删除站点，自动检测重复
- ✅ **登录支持**：支持需要登录的站点，Cookie持久化

## 已支持站点

| 站点名称 | 站点URL | 需要登录 | 备注 |
|---------|---------|---------|------|
| 小包子漫画 | https://www.baozimh.com/ | ❌ | 图片下载可能需要代理 |
| G社漫画 | https://m.g-mh.org/ | ❌ | 无需登录，无需代理 |
| 腾讯动漫 | https://ac.qq.com/ | ✅ | 需要Cookie登录 |
| 拷贝漫画 | https://www.mangacopy.com/ | ❌ | 支持账号登录（可选） |
| 更多站点... | | | 可自行开发爬虫扩展 |

> **提示**：站点列表以实际 `sites_data/` 目录中的爬虫文件为准。首次启动时站点列表为空，需要添加爬虫文件。

## 安装

### 环境要求

- Python 3.8+
- Edge 或 Chrome 浏览器

### 安装依赖

```bash
pip install DrissionPage aiohttp requests
```

## 使用方法

### GUI模式（推荐）

直接运行主程序：

```bash
python gui.py
```

或双击 `通用漫画下载器.exe`（如果已打包）

#### 界面操作

1. **选择站点**：从下拉列表选择漫画站点
2. **输入漫画名称**：填写要下载的漫画名
3. **设置章节范围**：起始章节到结束章节（0表示末章）
4. **浏览器设置**：选择浏览器类型和模式（有头/无头）
5. **下载设置**：设置标签页数、下载线程数等参数
6. **开始下载**：点击"开始下载"按钮

#### 站点管理

- **添加文件**：选择单个或多个爬虫文件（`*_crawler.py`）添加
- **添加文件夹**：批量添加文件夹中的所有爬虫文件
- **删除站点**：删除当前选中的站点（确认后无法恢复）
- **刷新列表**：重新扫描 `sites_data/` 目录
- **打开目录**：打开站点文件存储目录

### 命令行模式

运行命令行版本：

```bash
python main.py
```

按照提示依次输入：
- 站点编号
- 漫画名称
- 章节数（0表示全部）
- 浏览器类型
- 浏览器路径（可使用默认）
- 无头模式（y/n）
- 下载路径（可选）

### 下载失败图片

如果下载过程中有图片失败，会生成失败列表JSON文件。在GUI中点击"下载失败图片"按钮，选择JSON文件即可重新下载。

## 站点开发

### 快速开始

要添加新站点支持，只需在 `sites_data/` 目录中创建爬虫文件：

1. 创建文件：`{站点简称}_crawler.py`（如 `newsite_crawler.py`）
2. 定义类：`{站点简称}Crawler`（如 `NewsiteCrawler`）
3. 实现必需方法和配置

### 爬虫模板

```python
import time
import threading
from utils import is_normal_url


class NewsiteCrawler:
    """新站点爬虫 (https://example.com)"""

    # 元数据
    SITE_NAME = '新站点'
    SITE_URL = 'https://example.com/'
    REQUIRES_LOGIN = False

    # 配置
    CONFIG = {
        'site_url': 'https://example.com/',
        'locators': {
            'search_result': 'xpath:/html/body/...',      # 搜索结果第一个链接
            'cover_image': 'xpath:/html/body/...',        # 封面图片
            'chapter_item': 'xpath:/html/body/...',       # 章节列表项
        },
        'image_attr': 'data-src',  # 图片URL属性
        'chapter_group_size': None,
    }

    def __init__(self, crawler):
        self.crawler = crawler
        self.locators = crawler.locators
        self.image_attr = crawler.image_attr

    def search_comic(self, comic_name, comic_id=None):
        """搜索漫画并打开详情页"""
        search_url = f"https://example.com/search/{comic_name}"
        self.crawler.tab.get(search_url)
        time.sleep(2)

        result_ele = self.crawler.tab.ele(self.locators['search_result'], timeout=10)
        href = result_ele.attr('href')

        target_comic_tab = self.crawler.page.new_tab(href)
        return target_comic_tab

    def get_chapter_count(self, target_comic_tab):
        """获取章节数量"""
        chapter_divs = target_comic_tab.eles(self.locators['chapter_item'], timeout=10)
        return len(chapter_divs)

    def collect_chapters_images(self, target_comic_tab, chapter_start=1, chapter_end=0, max_threads=5, progress_callback=None):
        """收集章节图片URL"""
        # 实现章节图片收集逻辑
        # 详见：新站点爬虫开发Skill.md
        pass
```

### 开发规范

1. **定位元素推荐使用XPath**：也可以选择其它dp支持的定位语法
2. **文件命名**：`{站点简称}_crawler.py`，如 `gmh_crawler.py`
3. **类命名**：`{站点简称}Crawler`，如 `GmhCrawler`
4. **必需方法**：
   - `__init__(self, crawler)`
   - `search_comic(self, comic_name, comic_id=None)`
   - `get_chapter_count(self, target_comic_tab)`
   - `collect_chapters_images(...)`

详细开发指南请参考：[新站点爬虫开发Skill.md](新站点爬虫开发Skill.md)

## 项目结构

```
通用漫画下载器/
├── main.py                 # 命令行入口
├── gui.py                  # GUI界面
├── crawler.py              # 核心爬虫框架
├── downloader.py           # 图片下载器
├── site_discovery.py       # 站点发现与加载
├── config.py               # 配置文件
├── utils.py                # 工具函数
├── sites_data/             # 站点爬虫目录
│   ├── baozimh_crawler.py  # 小包子漫画爬虫
│   ├── gmh_crawler.py      # G社漫画爬虫
│   └── ...                 # 其他站点爬虫
└── dist/                   # 打包输出目录
    ├── 通用漫画下载器.exe
    └── sites_data/         # 打包后的站点目录
```

## 配置说明

### 站点配置文件

站点信息存储在爬虫文件的 `CONFIG` 字典中：

```python
CONFIG = {
    'site_url': 'https://...',           # 站点URL
    'locators': {                        # XPath定位器
        'search_result': 'xpath:...',    # 搜索结果
        'cover_image': 'xpath:...',      # 封面图片
        'chapter_item': 'xpath:...',     # 章节项
    },
    'image_attr': 'data-src',            # 图片属性
    'chapter_group_size': None,          # 章节分组（通常None）
}
```

### 下载参数

- **标签页数**：同时打开的浏览器标签页数量（推荐5）
- **下载线程**：图片下载并发线程数（推荐4）
- **超时时间**：首次下载超时和重试超时（秒）
- **浏览器模式**：
  - 有头模式：可见浏览器窗口，便于调试
  - 无头模式：后台运行，不显示窗口

## 注意事项

### 浏览器要求

- 支持Edge或Chrome浏览器
- 需要指定浏览器可执行文件路径
- Windows默认路径：
  - Edge: `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`
  - Chrome: `C:\Program Files\Google\Chrome\Application\chrome.exe`

### 站点管理

- 首次启动站点列表为空，需要添加爬虫文件
- 添加重复站点会自动过滤（根据站点名判断）
- 删除站点会永久移除 `.py` 文件，重启后生效
- 可通过"打开目录"按钮直接管理 `sites_data/` 文件夹

## 开源协议

本项目采用 MIT 协议开源。

## 致谢

感谢以下开源项目：

- [DrissionPage](https://github.com/g1879/DrissionPage) - 优秀的浏览器自动化库

---

**免责声明**：本项目仅供学习交流使用，请勿用于商业用途。下载的内容请支持正版！