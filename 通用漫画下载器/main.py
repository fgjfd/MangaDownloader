# 主脚本文件 - 通用漫画下载器
import os
import asyncio
from crawler import ComicCrawler
from downloader import download_cover_image, download_all_chapters
from utils import zip_main_folder
from config import DEFAULT_SITE, BROWSER_PATHS
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
        print("章节数必须4是数字")
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
    
    try:
        print(f"正在搜索漫画: {comic_name}")
        target_comic_tab = crawler.search_comic(comic_name)
        print("成功打开漫画详情页")
        
        print("正在获取封面图片...")
        cover_url = crawler.get_cover_image(target_comic_tab)
        
        print("正在收集章节图片链接...")
        if comic_num == 0:
            comic_num = 999999
        all_chapters_data = crawler.collect_chapters_images(target_comic_tab, chapter_end=comic_num)
        
        print(f"将下载 {len(all_chapters_data)} 个章节")
        
        total_images = sum(len(c['herf_list']) for c in all_chapters_data)
        print(f"总计 {total_images} 张图片")
        
        if cover_url:
            print("\n正在下载封面...")
            asyncio.run(download_cover_image(cover_url, comic_name, download_path))
        
        if all_chapters_data:
            print("\n开始下载章节图片...")
            failed_downloads, failed_json_path, _ = asyncio.run(
                download_all_chapters(
                    all_chapters_data, 
                    comic_name, 
                    download_path
                )
            )
            
            if failed_downloads:
                print(f"\n⚠️  注意：以下图片最终下载失败（共 {len(failed_downloads)} 张）:")
                for failed in failed_downloads:
                    print(f"  - 文件: {failed['path']}")
                    print(f"    URL: {failed['url']}")
            
            print("\n正在压缩文件夹...")
            zip_main_folder(comic_name, download_path)
            
            print(f"\n✓ 漫画《{comic_name}》下载完成！")
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
