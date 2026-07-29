# 通用漫画下载器

一个基于 Python 的通用漫画下载器，支持多站点插件式架构。

## 功能特点

- **插件式架构**：每个网站爬虫独立为 Python 模块，松耦合设计
- **动态加载**：站点文件放入 `sites_data/` 目录即可自动识别
- **多线程/协程下载**：支持多种下载模式，高效稳定
- **GUI 界面**：基于 Tkinter 的图形界面，操作简单
- **站点管理**：支持 GUI 添加/删除站点，自动过滤重复
- **断点续传**：支持失败重试，保存失败列表到 JSON
- **代理支持**：自动检测系统代理，解决部分站点访问问题

## 支持站点

| 站点 | 状态 | 备注 |
|------|------|------|
| 小包子漫画 | ✅ | 无需登录 |
| G社漫画 | ✅ | 无需登录 |
| 包子漫画 | ✅ | 无需登录，纯多线程模式 |
| 拷贝漫画 | ✅ | 无需登录，支持懒加载 |
| 菠萝包 | ✅ | 需要登录 |
| 快看漫画 | ✅ | 需要登录 |
| 好多漫 | ✅ | 无需登录 |
| 腾讯动漫 | ✅ | 需要登录，支持漫画ID |

## 安装

### 依赖

```bash
pip install DrissionPage aiohttp aiofiles requests lxml PyExecJS
```

### 运行

```bash
python gui.py
```

或使用命令行版本：

```bash
python main.py
```

## 添加新站点

将爬虫文件 (`xxx_crawler.py`) 放入 `sites_data/` 目录，软件启动时会自动加载。

详见 [新站点爬虫开发Skill.md](新站点爬虫开发Skill.md)

## 项目结构

```
通用漫画下载器/
├── config.py           # 全局配置
├── crawler.py          # 核心爬虫框架
├── downloader.py       # 下载器模块
├── gui.py              # GUI界面
├── main.py             # 命令行入口
├── site_discovery.py   # 站点发现模块
├── utils.py            # 工具函数
├── sites_data/         # 站点爬虫目录
│   ├── baozimh_crawler.py
│   ├── gmh_crawler.py
│   └── ...
└── 新站点爬虫开发Skill.md  # 开发文档
```

## 许可证

MIT License
