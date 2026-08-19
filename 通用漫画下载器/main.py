# 主脚本文件 - 通用漫画下载器
from utils import ensure_console_safe
ensure_console_safe()  # 入口加固：防GBK打印崩溃，须在其他导入前执行

import os
import json
from crawler import ComicCrawler
from download_flow import run_download_flow
from config import DEFAULT_SITE, BROWSER_PATHS, DEFAULT_IMAGE_NAME_PADDING, DEFAULT_CHAPTER_FOLDER_NAMING
from site_discovery import get_all_site_names


def main():
    """主函数"""
    print("=" * 50)
    print("通用漫画下载器")
    print("=" * 50)
    
    site_names = get_all_site_names()
    print("\n可用站点:")
    for i, name in enumerate(site_names, 1):
        print(f"  {i}. {name}")
    
    try:
        default_index = site_names.index(DEFAULT_SITE) + 1 if DEFAULT_SITE in site_names else 1
        site_choice = input(f"\n请选择站点 (1-{len(site_names)}, 默认:{default_index}): ").strip()
        if site_choice:
            site_index = int(site_choice) - 1
            site_name = site_names[site_index]
        else:
            site_name = DEFAULT_SITE
    except (ValueError, IndexError):
        print("无效的选择，使用默认站点")
        site_name = DEFAULT_SITE
    
    print(f"\n已选择站点: {site_name}")
    
    comic_name = input("请输入漫画名称: ").strip()
    if not comic_name:
        print("漫画名称不能为空")
        return
    
    try:
        comic_num = int(input("请输入要下载的章节数(0表示全部): ").strip() or "0")
    except ValueError:
        print("章节数必须是数字")
        return
    
    print("\n浏览器类型:")
    print("  1. Edge")
    print("  2. Chrome")
    browser_choice = input("请选择浏览器 (1-2, 默认:1): ").strip() or "1"
    
    browser_type = 'edge' if browser_choice == '1' else 'chrome'
    browser_path = BROWSER_PATHS[browser_type]
    
    custom_browser_path = input(f"请输入浏览器路径(直接回车使用默认: {browser_path}): ").strip()
    if custom_browser_path:
        browser_path = custom_browser_path
    
    headless = input("是否使用无头模式(y/n, 默认n): ").strip().lower() == 'y'
    
    download_path = input("请输入下载路径(直接回车使用当前目录): ").strip()
    if not download_path:
        download_path = None
    
    print("\n正在启动浏览器...")
    crawler = ComicCrawler(site_name, browser_path, headless)
    
    # 图片命名规则/章节文件夹命名：优先读取GUI保存的config.json，缺省使用默认值
    image_name_padding = DEFAULT_IMAGE_NAME_PADDING
    chapter_folder_naming = DEFAULT_CHAPTER_FOLDER_NAMING
    try:
        with open('config.json', encoding='utf-8') as f:
            saved_cfg = json.load(f)
        image_name_padding = int(saved_cfg.get('image_name_padding', DEFAULT_IMAGE_NAME_PADDING))
        chapter_folder_naming = saved_cfg.get('chapter_folder_naming', DEFAULT_CHAPTER_FOLDER_NAMING)
    except Exception:
        pass
    
    try:
        result = run_download_flow(
            crawler, comic_name, chapter_end=comic_num,
            download_path=download_path, log=print,
            image_name_padding=image_name_padding,
            chapter_folder_naming=chapter_folder_naming
        )

        failed_downloads = result['failed_downloads']
        if failed_downloads:
            print(f"\n⚠️  注意：以下图片最终下载失败（共 {len(failed_downloads)} 张）:")
            for failed in failed_downloads:
                print(f"  - 文件: {failed['path']}")
                print(f"    URL: {failed['url']}")

        if result['chapters_data']:
            print(f"\n✓ 漫画《{result['comic_name']}》下载完成！")
        else:
            print("没有获取到任何章节数据")
        
    except Exception as e:
        print(f"\n下载过程中出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        crawler.page.close()
        print("浏览器已关闭")


if __name__ == "__main__":
    main()
