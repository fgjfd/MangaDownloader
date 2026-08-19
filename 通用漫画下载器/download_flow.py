# 公共下载流程 - gui.py 与 main.py 共用，避免两处逻辑重复
import asyncio
import time

from downloader import (download_cover_image, download_all_chapters,
                        download_cover_via_browser, is_browser_render_site,
                        set_active_referer, set_active_decryptor, _build_decryptor,
                        set_active_name_padding, set_active_chapter_folder_naming)
from utils import zip_main_folder


def search_and_open(crawler, comic_name, comic_id=None, log=print):
    """搜索漫画或按ID打开详情页

    Returns:
        (target_comic_tab, comic_name): 详情页标签页与最终漫画名（按ID时可能被站点返回的实际名覆盖）
    """
    if comic_id:
        log("正在通过ID访问漫画...")
        result = crawler.search_comic(comic_name, comic_id)
        if isinstance(result, tuple):
            target_comic_tab, actual_name = result
            log(f"获取到漫画名字: {actual_name}")
            return target_comic_tab, actual_name
        return result, comic_name

    # 站点爬虫内部已打印"正在搜索漫画"日志，此处不重复
    target_comic_tab = crawler.search_comic(comic_name)
    return target_comic_tab, comic_name


async def _run_download_async(crawler, target_comic_tab, comic_name, chapter_start, actual_end,
                              max_threads, download_path, progress_callback,
                              download_thread_count, use_thread_only,
                              first_timeout, retry_timeout,
                              url_progress_callback=None, pre_download_hook=None, log=print,
                              create_zip=False):
    all_chapters_data = crawler.collect_chapters_images(
        target_comic_tab,
        chapter_start=chapter_start,
        chapter_end=actual_end,
        max_threads=max_threads,
        progress_callback=url_progress_callback
    )

    total_images = sum(len(c['herf_list']) for c in all_chapters_data)
    log(f"将下载 {len(all_chapters_data)} 个章节")
    if pre_download_hook:
        pre_download_hook(total_images)

    log("正在获取封面图片...")
    cover_url = crawler.get_cover_image(target_comic_tab)
    if cover_url:
        # 加密站点优先使用浏览器渲染提取封面，失败回退HTTP下载
        # （站点CONFIG声明cover_via_browser=False时封面为明文，直接HTTP下载）
        cover_done = False
        cover_cfg = getattr(crawler.site_crawler, 'CONFIG', {})
        if is_browser_render_site(crawler.site_crawler) and cover_cfg.get('cover_via_browser', True):
            cover_done = download_cover_via_browser(
                target_comic_tab, crawler.site_crawler, comic_name,
                download_path if download_path else None)
        if not cover_done:
            # 封面也需要 Referer/解密（与章节图相同配置）
            cover_cfg = getattr(crawler.site_crawler, 'CONFIG', {})
            set_active_referer(cover_cfg.get('image_referer'))
            decrypt_cfg = cover_cfg.get('decrypt')
            decryptor = _build_decryptor(crawler.site_crawler) if decrypt_cfg else None
            if decryptor:
                set_active_decryptor(decryptor, decrypt_cfg.get('ext', 'jpg'))
            try:
                await download_cover_image(cover_url, comic_name, download_path if download_path else None)
            finally:
                set_active_referer(None)
                set_active_decryptor(None)

    failed_downloads, failed_json_path, should_zip = [], None, True
    if all_chapters_data:
        failed_downloads, failed_json_path, should_zip = await download_all_chapters(
            all_chapters_data,
            comic_name,
            download_path if download_path else None,
            download_thread_count=download_thread_count,
            progress_callback=progress_callback,
            max_retries=3,
            use_thread_only=use_thread_only,
            first_timeout=first_timeout,
            retry_timeout=retry_timeout,
            site_crawler=crawler.site_crawler
        )

    if create_zip and should_zip and all_chapters_data:
        zip_main_folder(comic_name, download_path if download_path else None)

    return {
        'chapters_data': all_chapters_data,
        'total_images': total_images,
        'failed_downloads': failed_downloads,
        'failed_json_path': failed_json_path,
        'should_zip': should_zip,
        'create_zip': create_zip,
    }


def run_download_flow(crawler, comic_name, comic_id=None, chapter_start=1, chapter_end=0,
                      max_threads=5, download_path=None, log=print,
                      progress_callback=None,
                      download_thread_count=4, use_thread_only=False,
                      first_timeout=8, retry_timeout=15,
                      url_progress_callback=None, pre_download_hook=None,
                      pre_collect_hook=None, create_zip=False, image_name_padding=None,
                      chapter_folder_naming=None):
    """执行完整下载流程：搜索→章节数→收集→封面→下载→（可选）压缩

    Args:
        crawler: ComicCrawler实例
        log: 日志输出函数（GUI传append_status，CLI用print）
        progress_callback: 图片下载进度回调
        url_progress_callback: 章节收集进度回调
        pre_download_hook: 下载开始前回调，参数为total_images（供调用方重置进度条）
        pre_collect_hook: 收集前回调，参数为实际下载章节数（供调用方重置URL进度条）
        create_zip: 下载完成后是否生成压缩包，默认False不生成
        image_name_padding: 图片文件名补零位数（0=不补零，3=001格式），None表示保持当前全局设置
        chapter_folder_naming: 章节文件夹命名模式（'number'=数字命名，'title'=章节名命名），
                               None表示保持当前全局设置（默认数字命名）

    Returns:
        dict: {comic_name, total_chapters, actual_start, actual_end,
               chapters_data, total_images, failed_downloads, failed_json_path,
               should_zip, create_zip}
    """
    if image_name_padding is not None:
        set_active_name_padding(image_name_padding)
    if chapter_folder_naming is not None:
        set_active_chapter_folder_naming(chapter_folder_naming)

    target_comic_tab, comic_name = search_and_open(crawler, comic_name, comic_id, log)
    if not target_comic_tab:
        raise RuntimeError("未找到漫画，请检查名称/ID是否正确")
    log("成功打开漫画详情页")

    log("正在获取章节数量...")
    total_chapters = crawler.get_chapter_count(target_comic_tab)

    # 章节计数稳定性校验：部分站点章节列表懒加载/折叠，首次计数可能偏低
    # （如gmh折叠态只渲染约10章、baozimh页面元素未就绪）。连续重读，直到
    # 两次一致或达到最大重读次数，取稳定值（以更大值为准，避免误把部分列表当全部）。
    # 纯requests站点（无需浏览器）章节数来自缓存，恒稳定，跳过校验省时
    if chapter_end <= 0 and getattr(crawler, 'needs_browser', True):  # "到所有章"模式才校验（指定范围时无需关心总数是否偏小）
        max_retries = 3
        last_count = total_chapters
        for attempt in range(max_retries):
            time.sleep(1.5)
            re_count = crawler.get_chapter_count(target_comic_tab)
            if re_count == last_count:
                total_chapters = re_count
                break
            if re_count > last_count:
                last_count = re_count
                total_chapters = re_count
                log(f"章节数变化: {re_count}（等待页面加载完成）")
            if attempt == max_retries - 1:
                total_chapters = max(total_chapters, re_count)
        log(f"章节数稳定: {total_chapters}")

    actual_start = chapter_start
    actual_end = min(chapter_end, total_chapters) if chapter_end > 0 else total_chapters
    actual_count = actual_end - actual_start + 1

    log(f"总章节数: {total_chapters}, 将下载: {actual_start}-{actual_end} 共{actual_count}章")
    if pre_collect_hook:
        pre_collect_hook(actual_count)

    log("正在收集章节图片链接...")
    result = asyncio.run(_run_download_async(
        crawler, target_comic_tab, comic_name, actual_start, actual_end,
        max_threads, download_path, progress_callback,
        download_thread_count, use_thread_only, first_timeout, retry_timeout,
        url_progress_callback=url_progress_callback, pre_download_hook=pre_download_hook, log=log,
        create_zip=create_zip))

    result.update({
        'comic_name': comic_name,
        'total_chapters': total_chapters,
        'actual_start': actual_start,
        'actual_end': actual_end,
    })
    return result
