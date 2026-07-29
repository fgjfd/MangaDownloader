import os
import asyncio
import aiohttp
import aiofiles
import time
import json
import requests
from concurrent.futures import ThreadPoolExecutor
import winreg


def get_system_proxy():
    """获取 Windows 系统代理设置"""
    try:
        # 打开注册表
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            0,
            winreg.KEY_READ
        )

        # 检查是否启用代理
        proxy_enable = winreg.QueryValueEx(key, "ProxyEnable")[0]

        if proxy_enable:
            # 获取代理服务器地址
            proxy_server = winreg.QueryValueEx(key, "ProxyServer")[0]
            winreg.CloseKey(key)

            # 格式化代理地址（支持 http 和 https）
            if '=' not in proxy_server:
                # 格式: 127.0.0.1:7890
                return {
                    'http': f'http://{proxy_server}',
                    'https': f'http://{proxy_server}'
                }
            else:
                # 格式: http=127.0.0.1:7890;https=127.0.0.1:7890
                proxies = {}
                for item in proxy_server.split(';'):
                    if '=' in item:
                        proto, addr = item.split('=')
                        proxies[proto] = f'http://{addr}'
                return proxies

        winreg.CloseKey(key)
    except Exception as e:
        print(f"获取系统代理失败: {e}")

    return None


# 全局代理设置（启动时获取一次）
_SYSTEM_PROXY = get_system_proxy()
if _SYSTEM_PROXY:
    print(f"检测到系统代理: {_SYSTEM_PROXY}")
else:
    print("未检测到系统代理，将直连下载")


async def download_with_aiohttp(url, file_path, timeout=10, proxy=None):
    """使用aiohttp下载"""
    try:
        connector = aiohttp.TCPConnector(
            limit=1,
            enable_cleanup_closed=True,
            force_close=True,
            ssl=False
        )

        # 使用传入的代理或全局代理
        proxy_url = proxy or (_SYSTEM_PROXY.get('https') if _SYSTEM_PROXY else None)

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.get(url, allow_redirects=True, proxy=proxy_url) as response:
                if response.status == 200:
                    content = await response.read()
                    # 只要有内容就算成功（即使是空白图片）
                    if len(content) > 0:
                        async with aiofiles.open(file_path, 'wb') as f:
                            await f.write(content)
                        return True, len(content)
                    else:
                        return False, "内容为空"
                else:
                    return False, f"状态码{response.status}"
    except asyncio.TimeoutError:
        return False, "超时"
    except Exception as e:
        return False, str(e)[:50]


def download_with_requests(url, file_path, timeout=10, proxy=None):
    """使用requests下载（同步）"""
    try:
        # 使用传入的代理或全局代理
        proxies = proxy or _SYSTEM_PROXY

        response = requests.get(url, stream=True, timeout=timeout, proxies=proxies)
        response.raise_for_status()
        
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
        
        # 只要有内容就算成功（即使是空白图片）
        file_size = os.path.getsize(file_path)
        if file_size > 0:
            return True, file_size
        else:
            return False, "内容为空"
    except Exception as e:
        return False, str(e)[:50]


async def download_image(url, index, folder_name, chapter_num, progress_callback=None, timeout=10):
    """
    下载单张图片
    先用aiohttp下载，失败则返回错误信息（不立即重试）
    
    Args:
        timeout: 下载超时时间（秒）
    """
    file_path = os.path.join(folder_name, f"{index}.jpg")
    
    success, info = await download_with_aiohttp(url, file_path, timeout=timeout)
    if success:
        print(f"  ✓ 第{index}张图片下载成功")
        if progress_callback:
            progress_callback(info)
        return None  # 成功，无失败信息
    
    # 下载失败，返回错误信息（不立即重试，最后统一处理）
    print(f"  ✗ 第{index}张下载失败: {info}")
    if progress_callback:
        progress_callback(0)
    
    return {
        'url': url,
        'chapter_num': chapter_num,
        'image_index': index,
        'folder': folder_name,
        'path': file_path,
        'error': info
    }


async def download_batch_coroutine(images_to_download, concurrent_limit, progress_callback=None, timeout=10):
    """
    协程模式批量下载图片，控制并发数
    images_to_download: [(url, index, folder_name, chapter_num), ...]
    
    所有失败都收集返回，最后统一重试
    
    Args:
        timeout: 下载超时时间（秒）
    """
    semaphore = asyncio.Semaphore(concurrent_limit)
    failed_list = []

    async def download_with_semaphore(url, index, folder_name, chapter_num):
        async with semaphore:
            failed_info = await download_image(url, index, folder_name, chapter_num, progress_callback, timeout=timeout)
            if failed_info:
                failed_list.append(failed_info)
            await asyncio.sleep(0.3)

    tasks = [
        download_with_semaphore(url, index, folder, chapter_num)
        for url, index, folder, chapter_num in images_to_download
    ]

    await asyncio.gather(*tasks)
    
    return failed_list


def retry_failed_batch(failed_list, progress_callback=None, max_workers=8, timeout=15):
    """
    使用多线程批量重试失败的图片
    
    Args:
        failed_list: 失败图片列表
        progress_callback: 进度回调
        max_workers: 最大线程数
        timeout: 下载超时时间（秒）
    """
    def retry_single(img_info):
        url = img_info['url']
        file_path = img_info['path']
        index = img_info['image_index']
        
        # 尝试requests下载
        success, info = download_with_requests(url, file_path, timeout=timeout)
        if success:
            print(f"  ✓ 第{index}张重试成功")
            if progress_callback:
                progress_callback(info)
            return None
        else:
            print(f"  ✗ 第{index}张重试失败: {info}")
            if progress_callback:
                progress_callback(0)
            return img_info
    
    still_failed = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = executor.map(retry_single, failed_list)
        for result in results:
            if result:
                still_failed.append(result)
    
    print(f"重试完成: 成功 {len(failed_list) - len(still_failed)} 张，失败 {len(still_failed)} 张")
    return still_failed


def download_batch_thread_only(images_to_download, thread_count=8, progress_callback=None, timeout=10):
    """
    纯多线程模式批量下载图片（不使用协程）
    
    Args:
        images_to_download: [(url, index, folder_name, chapter_num), ...]
        thread_count: 线程数
        progress_callback: 进度回调函数
        timeout: 下载超时时间（秒）
    """
    failed_list = []
    
    def download_single(args):
        url, index, folder_name, chapter_num = args
        file_path = os.path.join(folder_name, f"{index}.jpg")
        
        # 使用requests直接下载
        success, info = download_with_requests(url, file_path, timeout=timeout)
        
        if success:
            print(f"  ✓ 第{index}张下载成功")
            if progress_callback:
                progress_callback(info)
            return None
        else:
            print(f"  ✗ 第{index}张下载失败: {info}")
            if progress_callback:
                progress_callback(0)
            
            return {
                'url': url,
                'chapter_num': chapter_num,
                'image_index': index,
                'folder': folder_name,
                'path': file_path,
                'error': info
            }
    
    print(f"\n使用纯多线程模式下载，线程数: {thread_count}")
    with ThreadPoolExecutor(max_workers=thread_count) as executor:
        results = executor.map(download_single, images_to_download)
        for result in results:
            if result:
                failed_list.append(result)
    
    return failed_list


def download_batch_thread_coroutine(images_to_download, concurrent_limit, thread_count=4, progress_callback=None, timeout=10):
    """
    多线程+协程模式批量下载图片
    线程数控制章节级并发，协程控制图片级并发
    images_to_download: [(url, index, folder_name, chapter_num), ...]
    
    所有失败都收集返回，最后统一重试
    
    Args:
        timeout: 下载超时时间（秒）
    """
    def process_chunk(chunk):
        """在线程中运行协程下载"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                download_batch_coroutine(chunk, concurrent_limit, progress_callback, timeout=timeout)
            )
            return result
        finally:
            loop.close()

    # 将图片分成thread_count个块
    chunk_size = max(1, len(images_to_download) // thread_count)
    chunks = []
    for i in range(thread_count):
        start = i * chunk_size
        end = (i + 1) * chunk_size if i < thread_count - 1 else len(images_to_download)
        chunks.append(images_to_download[start:end])

    failed_list = []
    with ThreadPoolExecutor(max_workers=thread_count) as executor:
        results = executor.map(process_chunk, chunks)
        for result in results:
            failed_list.extend(result)

    return failed_list


async def download_batch(images_to_download, concurrent_limit, thread_count=4, use_thread_coroutine=True, progress_callback=None, use_thread_only=False, timeout=10):
    """
    批量下载图片，可选择使用纯协程、多线程+协程或纯多线程
    
    所有失败都收集返回，最后统一重试
    
    Args:
        use_thread_only: 是否使用纯多线程模式（不使用协程）
        timeout: 下载超时时间（秒）
    """
    if use_thread_only:
        # 纯多线程模式
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            download_batch_thread_only,
            images_to_download,
            thread_count,
            progress_callback,
            timeout
        )
    elif use_thread_coroutine and thread_count > 1:
        # 多线程+协程模式
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            download_batch_thread_coroutine,
            images_to_download,
            concurrent_limit,
            thread_count,
            progress_callback,
            timeout
        )
    else:
        # 纯协程模式
        return await download_batch_coroutine(images_to_download, concurrent_limit, progress_callback, timeout=timeout)


async def download_chapter_images(herf_list, folder_name, chapter_num, concurrent_limit=3, thread_count=4, use_thread_coroutine=True, progress_callback=None, use_thread_only=False, timeout=10):
    """下载单个章节的图片
    
    所有失败都收集返回，最后统一重试
    
    Args:
        timeout: 下载超时时间（秒）
    """
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    print(f"\n[章节{chapter_num}] 开始下载 {len(herf_list)} 张图片...")
    start_time = time.time()

    images_to_download = [(url, i, folder_name, chapter_num) for i, url in enumerate(herf_list, 1)]
    failed = await download_batch(images_to_download, concurrent_limit, thread_count, use_thread_coroutine, progress_callback, use_thread_only, timeout=timeout)

    elapsed = time.time() - start_time
    print(f"[章节{chapter_num}] 完成，耗时{elapsed:.1f}秒，失败{len(failed)}张")

    return failed


def check_missing_images(herf_list, folder_name, chapter_num):
    """检查哪些图片缺失或损坏"""
    missing = []
    for i, url in enumerate(herf_list, 1):
        file_path = os.path.join(folder_name, f"{i}.jpg")
        if not os.path.exists(file_path):
            missing.append({
                'url': url,
                'chapter_num': chapter_num,
                'image_index': i,
                'folder': folder_name,
                'path': file_path,
                'error': '文件不存在'
            })
        elif os.path.getsize(file_path) == 0:
            # 只检查文件是否为空，不再限制最小字节数
            missing.append({
                'url': url,
                'chapter_num': chapter_num,
                'image_index': i,
                'folder': folder_name,
                'path': file_path,
                'error': '文件为空'
            })
    return missing


def save_image_urls_to_json(all_chapters_data, comic_name, base_path=None):
    """保存图片URL映射到JSON文件"""
    if base_path is None:
        base_path = os.getcwd()
    
    main_folder = os.path.join(base_path, comic_name)
    
    url_mapping = {
        "comic_name": comic_name,
        "base_path": main_folder,
        "total_chapters": len(all_chapters_data),
        "chapters": []
    }
    
    for chapter_data in all_chapters_data:
        chapter_num = chapter_data['chapter_num']
        herf_list = chapter_data['herf_list']
        
        chapter_info = {
            "chapter_num": chapter_num,
            "folder_name": str(chapter_num),
            "total_images": len(herf_list),
            "images": []
        }
        
        for i, url in enumerate(herf_list, 1):
            chapter_info["images"].append({
                "index": i,
                "filename": f"{i}.jpg",
                "url": url
            })
        
        url_mapping["chapters"].append(chapter_info)
    
    json_path = os.path.join(main_folder, "image_urls.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(url_mapping, f, ensure_ascii=False, indent=2)
    
    print(f"\n图片URL映射已保存到: {json_path}")
    return json_path


async def download_all_chapters(all_chapters_data, comic_name, base_path=None, save_json_only=False, concurrent_limit=3, download_thread_count=4, use_thread_coroutine=True, progress_callback=None, max_retries=3, use_thread_only=False, first_timeout=8, retry_timeout=15):
    """下载所有章节，可选只保存JSON不下载
    
    Args:
        max_retries: 失败后重试次数，默认3次
        use_thread_only: 是否使用纯多线程模式（不使用协程）
        first_timeout: 首次下载超时时间（秒）
        retry_timeout: 重试超时时间（秒）
    
    Returns:
        tuple: (failed_list, failed_json_path, should_zip)
            - failed_list: 失败的图片列表（空列表表示全部成功）
            - failed_json_path: 失败JSON的保存路径（全部成功时返回None）
            - should_zip: 是否应该压缩文件（有失败图片时返回False）
    """
    print(f"\n{'='*50}")
    print(f"开始处理漫画: {comic_name}")
    print(f"首次超时: {first_timeout}秒, 重试超时: {retry_timeout}秒")
    print(f"{'='*50}")
    
    if base_path is None:
        base_path = os.getcwd()

    main_folder = os.path.join(base_path, comic_name)
    if not os.path.exists(main_folder):
        os.makedirs(main_folder)
    
    json_path = save_image_urls_to_json(all_chapters_data, comic_name, base_path)
    
    if save_json_only:
        print(f"仅保存JSON，跳过下载")
        return [], None, True
    
    total_start = time.time()
    all_failed = []  # 收集所有失败图片

    for chapter_data in all_chapters_data:
        chapter_num = chapter_data['chapter_num']
        herf_list = chapter_data['herf_list']

        if not herf_list:
            print(f"[章节{chapter_num}] 无图片链接，跳过")
            continue
        
        folder_name = os.path.join(main_folder, str(chapter_num))
        # 使用协程+多线程下载，收集所有失败
        failed = await download_chapter_images(herf_list, folder_name, chapter_num, concurrent_limit, download_thread_count, use_thread_coroutine, progress_callback, use_thread_only, timeout=first_timeout)
        # 收集所有失败图片
        all_failed.extend(failed)

    total_elapsed = time.time() - total_start
    print(f"\n{'='*50}")
    print(f"首次下载完成！总耗时: {total_elapsed:.1f}秒")
    print(f"失败图片: {len(all_failed)} 张")
    
    # 所有章节下载完成后，统一多线程重试所有失败图片
    if all_failed:
        print(f"\n{'='*50}")
        print(f"开始统一重试所有失败图片: {len(all_failed)} 张")
        print(f"{'='*50}")
        
        # 使用多线程批量重试
        still_failed = retry_failed_batch(all_failed, progress_callback, max_workers=download_thread_count, timeout=retry_timeout)
        success_count = len(all_failed) - len(still_failed)
        print(f"\n统一重试完成: 成功 {success_count} 张，失败 {len(still_failed)} 张")
        
        all_failed = still_failed
    
    # 保存失败列表到JSON
    if all_failed:
        print(f"\n失败的图片URL列表:")
        for failed in all_failed:
            print(f"  章节{failed['chapter_num']}-第{failed['image_index']}张: {failed['url']}")
        
        failed_json_path = save_failed_json(all_failed, comic_name, base_path)
        print(f"{'='*50}")
        return all_failed, failed_json_path, False  # 有失败图片，不压缩
    else:
        # 全部成功，删除JSON文件
        json_path = os.path.join(main_folder, "image_urls.json")
        if os.path.exists(json_path):
            os.remove(json_path)
            print(f"已删除image_urls.json（无缺页）")
        
        # 删除可能存在的失败列表文件
        failed_json_path = os.path.join(main_folder, "failed_images.json")
        if os.path.exists(failed_json_path):
            os.remove(failed_json_path)
            print(f"已删除failed_images.json（全部成功）")
    
    print(f"{'='*50}")
    return [], None, True  # 全部成功，可以压缩


def save_failed_json(failed_list, comic_name, base_path=None):
    """保存失败列表到JSON文件"""
    if base_path is None:
        base_path = os.getcwd()
    
    # 如果base_path已经以comic_name结尾，则不再拼接
    if base_path.endswith(comic_name) or base_path.endswith(comic_name + os.sep):
        main_folder = base_path
    else:
        main_folder = os.path.join(base_path, comic_name)
    
    # 确保文件夹存在
    os.makedirs(main_folder, exist_ok=True)
    
    failed_data = {
        "comic_name": comic_name,
        "base_path": main_folder,
        "total_failed": len(failed_list),
        "failed_images": failed_list
    }
    
    failed_json_path = os.path.join(main_folder, "failed_images.json")
    with open(failed_json_path, 'w', encoding='utf-8') as f:
        json.dump(failed_data, f, ensure_ascii=False, indent=2)
    
    print(f"失败列表已保存到: {failed_json_path}")
    return failed_json_path


async def download_from_failed_json(json_path, concurrent_limit=3, download_thread_count=4, use_thread_coroutine=True, progress_callback=None, max_retries=3, first_timeout=8, retry_timeout=15):
    """从失败的JSON文件重新下载图片
    
    Args:
        json_path: 失败列表JSON文件路径
        concurrent_limit: 协程并发数
        download_thread_count: 线程数
        use_thread_coroutine: 是否使用多线程+协程
        progress_callback: 进度回调函数
        max_retries: 失败后重试次数
        first_timeout: 首次下载超时时间（秒）
        retry_timeout: 重试超时时间（秒）
    
    Returns:
        tuple: (still_failed, all_success)
            - still_failed: 仍然失败的图片列表
            - all_success: 是否全部成功
    """
    print(f"\n{'='*50}")
    print(f"从失败列表重新下载")
    print(f"首次超时: {first_timeout}秒, 重试超时: {retry_timeout}秒")
    print(f"{'='*50}")
    
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    comic_name = data['comic_name']
    base_path = data['base_path']
    failed_images = data['failed_images']
    
    print(f"漫画名称: {comic_name}")
    print(f"基础路径: {base_path}")
    print(f"待重试: {len(failed_images)} 张")
    
    if not failed_images:
        print("没有需要重试的图片")
        return [], True
    
    images_to_download = [
        (img['url'], img['image_index'], img['folder'], img['chapter_num'])
        for img in failed_images
    ]
    
    all_failed = []
    
    # 首次下载（协程+多线程）
    start_time = time.time()
    all_failed = await download_batch(images_to_download, concurrent_limit, download_thread_count, use_thread_coroutine, progress_callback, timeout=first_timeout)
    
    # 所有失败后，统一多线程重试
    if all_failed:
        print(f"\n{'='*50}")
        print(f"开始统一重试所有失败图片: {len(all_failed)} 张")
        print(f"{'='*50}")
        
        # 使用多线程批量重试
        still_failed = retry_failed_batch(all_failed, progress_callback, max_workers=download_thread_count, timeout=retry_timeout)
        success_count = len(all_failed) - len(still_failed)
        print(f"\n统一重试完成: 成功 {success_count} 张，失败 {len(still_failed)} 张")
        
        all_failed = still_failed
    
    elapsed = time.time() - start_time
    
    print(f"\n{'='*50}")
    print(f"重试完成！耗时: {elapsed:.1f}秒")
    print(f"成功: {len(failed_images) - len(all_failed)} 张")
    print(f"仍然失败: {len(all_failed)} 张")
    
    # 核查章节图片数
    print(f"\n{'='*50}")
    print("核查章节图片数...")
    print(f"{'='*50}")

    # 从image_urls.json读取每个章节的总图片数
    chapter_stats = {}
    image_urls_json = os.path.join(base_path, "image_urls.json")
    if os.path.exists(image_urls_json):
        try:
            with open(image_urls_json, 'r', encoding='utf-8') as f:
                url_data = json.load(f)
            for chapter in url_data.get('chapters', []):
                chapter_num = chapter['chapter_num']
                chapter_stats[chapter_num] = {
                    'expected': chapter['total_images'],
                    'actual': 0,
                    'folder': os.path.join(base_path, str(chapter_num))
                }
        except Exception as e:
            print(f"读取image_urls.json失败: {e}")

    # 如果没有image_urls.json，从failed_images推断
    if not chapter_stats:
        for img in failed_images:
            chapter_num = img['chapter_num']
            if chapter_num not in chapter_stats:
                chapter_stats[chapter_num] = {'expected': 0, 'actual': 0, 'folder': img['folder']}
            chapter_stats[chapter_num]['expected'] += 1

    # 检查实际文件数
    for chapter_num, stats in chapter_stats.items():
        folder = stats['folder']
        if os.path.exists(folder):
            # 统计文件夹中的.jpg文件
            actual_count = len([f for f in os.listdir(folder) if f.endswith('.jpg')])
            stats['actual'] = actual_count

            if actual_count != stats['expected']:
                print(f"⚠️ 章节 {chapter_num}: 期望 {stats['expected']} 张，实际 {actual_count} 张")
            else:
                print(f"✓ 章节 {chapter_num}: {actual_count} 张 (正确)")
        else:
            print(f"✗ 章节 {chapter_num}: 文件夹不存在 {folder}")

    print(f"{'='*50}")
    
    if all_failed:
        print(f"\n仍然失败的图片:")
        for failed in all_failed:
            print(f"  章节{failed['chapter_num']}-第{failed['image_index']}张: {failed['url']}")
        
        # 保存更新后的失败列表
        failed_json_path = save_failed_json(all_failed, comic_name, base_path)
        print(f"\n更新后的失败列表已保存到: {failed_json_path}")
        
        print(f"{'='*50}")
        return all_failed, False
    else:
        # 全部成功，删除失败列表文件
        if os.path.exists(json_path):
            os.remove(json_path)
            print(f"\n全部下载成功，已删除失败列表: {json_path}")
        
        # 删除图片URL的JSON文件
        image_urls_json = os.path.join(base_path, "image_urls.json")
        if os.path.exists(image_urls_json):
            os.remove(image_urls_json)
            print(f"已删除图片URL文件: {image_urls_json}")
    
    print(f"{'='*50}")
    return [], True


async def download_cover_image(url, comic_name, base_path=None):
    """下载封面图片"""
    if base_path is None:
        base_path = os.getcwd()

    main_folder = os.path.join(base_path, comic_name)
    folder_name = os.path.join(main_folder, "0")

    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    print(f"\n开始下载封面...")
    file_path = os.path.join(folder_name, "cover.jpg")
    
    success, info = await download_with_aiohttp(url, file_path)
    if not success:
        loop = asyncio.get_event_loop()
        success, info = await loop.run_in_executor(None, download_with_requests, url, file_path, 10)
    
    if success:
        print("封面下载成功")
        return True
    else:
        print(f"封面下载失败: {info}")
        print(f"URL: {url}")
        return False
