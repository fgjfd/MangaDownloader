import os
import base64
import asyncio
import aiohttp
import aiofiles
import time
import json
import hashlib
import shutil
import threading
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


# 全局代理设置：惰性检测（不再模块导入时同步执行，避免阻塞软件启动；
# 由 GUI 窗口显示后在后台线程预检测，或首次下载时自动检测）
_SYSTEM_PROXY = None
_SYSTEM_PROXY_CHECKED = False
_SYSTEM_PROXY_LOCK = threading.Lock()


def get_active_proxy():
    """获取当前系统代理（惰性检测+缓存，线程安全）

    首次调用时读取注册表并缓存结果；GUI 在窗口显示后启动后台线程
    预检测，下载函数在需要时兜底调用。
    """
    global _SYSTEM_PROXY, _SYSTEM_PROXY_CHECKED
    if not _SYSTEM_PROXY_CHECKED:
        with _SYSTEM_PROXY_LOCK:
            if not _SYSTEM_PROXY_CHECKED:
                _SYSTEM_PROXY = get_system_proxy()
                _SYSTEM_PROXY_CHECKED = True
                if _SYSTEM_PROXY:
                    print(f"检测到系统代理: {_SYSTEM_PROXY}")
                else:
                    print("未检测到系统代理，将直连下载")
    return _SYSTEM_PROXY


# 活跃Referer：部分CDN有防盗链（缺Referer返回500或重定向到占位图），
# 站点在CONFIG声明image_referer后，下载前由流程设置
_ACTIVE_REFERER = None

# 活跃解密器：站点CONFIG声明decrypt后，下载的字节先解密再写盘
# （图片加密但解密可复现的站点，如喜漫漫画：AES-CBC + 固定key）
_ACTIVE_DECRYPTOR = None

# 解密后图片扩展名（无解密器时为jpg）
_ACTIVE_IMAGE_EXT = 'jpg'

# 活跃图片文件名补零位数：0=不补零(1,2,3...)，3=三位补零(001,002,003...)
# 由GUI/CLI在下载前通过set_active_name_padding设置（持久化于config.json）
_ACTIVE_NAME_PADDING = 0

# 活跃章节文件夹命名模式：'number'=数字命名(1,2,3...)；'title'=章节名命名(1 第1话 xxx)
# 由GUI/CLI在下载前通过set_active_chapter_folder_naming设置（持久化于config.json）
_ACTIVE_CHAPTER_FOLDER_NAMING = 'number'


def set_active_name_padding(padding):
    """设置当前下载任务的图片文件名补零位数（传0/None不补零）"""
    global _ACTIVE_NAME_PADDING
    try:
        _ACTIVE_NAME_PADDING = max(0, int(padding or 0))
    except (TypeError, ValueError):
        _ACTIVE_NAME_PADDING = 0


def set_active_chapter_folder_naming(mode):
    """设置当前下载任务的章节文件夹命名模式（'number'/'title'，传None保持默认数字命名）"""
    global _ACTIVE_CHAPTER_FOLDER_NAMING
    _ACTIVE_CHAPTER_FOLDER_NAMING = 'title' if mode == 'title' else 'number'


def sanitize_folder_name(name):
    """清洗文件夹名称：替换Windows非法字符，压缩空白，去除首尾空格/点"""
    import re
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', ' ', str(name))
    name = re.sub(r'\s+', ' ', name).strip(' .')
    return name


def chapter_folder_name(chapter_data):
    """按当前命名规则生成章节文件夹名

    - 'number'模式：返回章节号（如 '3'），与原版行为一致
    - 'title'模式：返回 '章节号 章节名'（如 '3 第3话 初次相遇'），
      章节名为空/非法时自动回退为章节号，避免空名或重名冲突
    """
    num = chapter_data.get('chapter_num', 0)
    if _ACTIVE_CHAPTER_FOLDER_NAMING == 'title':
        title = sanitize_folder_name(chapter_data.get('title') or '')
        if title:
            return f"{num} {title}"
    return str(num)


def format_image_name(index, ext):
    """按当前命名规则生成图片文件名（如 format_image_name(3, '.jpg') -> '003.jpg'）"""
    if _ACTIVE_NAME_PADDING > 0:
        return f"{index:0{_ACTIVE_NAME_PADDING}d}{ext}"
    return f"{index}{ext}"


def set_active_referer(referer):
    """设置当前下载任务的Referer（传None清除）"""
    global _ACTIVE_REFERER
    _ACTIVE_REFERER = referer or None


def set_active_decryptor(decryptor, image_ext='jpg'):
    """设置当前下载任务的解密函数 data->data（传None清除）"""
    global _ACTIVE_DECRYPTOR, _ACTIVE_IMAGE_EXT
    _ACTIVE_DECRYPTOR = decryptor or None
    _ACTIVE_IMAGE_EXT = image_ext or 'jpg'


def _decrypt_content(content):
    """下载字节解密（无解密器时原样返回）。解密失败返回None"""
    if not _ACTIVE_DECRYPTOR:
        return content
    try:
        decrypted = _ACTIVE_DECRYPTOR(content)
        if decrypted and len(decrypted) > 0:
            return decrypted
        print("  ✗ 解密结果为空")
        return None
    except Exception as e:
        print(f"  ✗ 解密失败: {e}")
        return None


def _build_decryptor(site_crawler):
    """根据站点CONFIG['decrypt']构造解密函数，无配置返回None

    支持两种模式：
    - 'aes_cbc': {'mode': 'aes_cbc', 'base64_key': '...', 'iv_prefix': 16}
        密钥 = base64解码(base64_key)；iv = 密文前iv_prefix字节；其余为密文；
        AES-CBC + PKCS7 解密
    - 'site_func': 调用站点爬虫的 get_decryptor() 返回自定义函数
    """
    if site_crawler is None:
        return None
    cfg = getattr(site_crawler, 'CONFIG', {}).get('decrypt')
    if not cfg:
        return None
    mode = cfg.get('mode')
    if mode == 'site_func':
        fn = getattr(site_crawler, 'get_decryptor', None)
        if callable(fn):
            try:
                return fn()
            except Exception as e:
                print(f"构建解密器失败: {e}")
        return None
    if mode == 'aes_cbc':
        try:
            import base64
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import unpad
            key = base64.b64decode(cfg['base64_key'])
            iv_len = cfg.get('iv_prefix', 16)
            convert = cfg.get('convert')  # None / 'jpeg'（转码兼容不支持webp的阅读器）
            def decrypt(data):
                iv = data[:iv_len]
                ciphertext = data[iv_len:]
                cipher = AES.new(key, AES.MODE_CBC, iv)
                plain = unpad(cipher.decrypt(ciphertext), AES.block_size)
                if convert == 'jpeg':
                    try:
                        from PIL import Image
                        import io
                        img = Image.open(io.BytesIO(plain))
                        buf = io.BytesIO()
                        img.convert('RGB').save(buf, 'JPEG', quality=92)
                        return buf.getvalue()
                    except Exception as e:
                        print(f"  ✗ 转码JPEG失败（保留原格式）: {e}")
                        return plain
                return plain
            return decrypt
        except Exception as e:
            print(f"构建AES解密器失败: {e}")
            return None
    print(f"未知解密模式: {mode}")
    return None


def _build_download_headers():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    if _ACTIVE_REFERER:
        headers['Referer'] = _ACTIVE_REFERER
    return headers


# ==================== 浏览器渲染下载（适用于图片加密、HTTP直下无效的站点） ====================

# 从已渲染的img元素提取图片像素数据（canvas导出JPEG）
EXTRACT_JS = """
function(img) {
    if (!img || !img.complete || img.naturalWidth === 0) return '';
    var canvas = document.createElement('canvas');
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    canvas.getContext('2d').drawImage(img, 0, 0);
    try { return canvas.toDataURL('image/jpeg', 0.92); } catch (e) { return ''; }
}
"""


def _browser_scroll_to_load_all(tab, total_imgs):
    """分步滚动页面，触发所有懒加载图片的解密与渲染"""
    try:
        height = tab.run_js('return document.body.scrollHeight') or 0
        steps = max(10, min(80, total_imgs // 2))
        for i in range(1, steps + 1):
            tab.run_js(f'window.scrollTo(0, {height} * {i} / {steps})')
            time.sleep(0.4)
        tab.run_js('window.scrollTo(0, document.body.scrollHeight)')
        time.sleep(1)
    except Exception as e:
        print(f"滚动页面异常: {e}")


def _browser_extract_single_image(tab, img_ele, max_wait=30):
    """等待单张图片解密渲染完成，通过canvas提取JPEG字节

    Returns:
        bytes或None
    """
    waited = 0.0
    while waited < max_wait:
        try:
            src = img_ele.attr('src') or ''
            # src被站点JS替换为blob:/data:才代表解密完成
            if src.startswith('blob:') or src.startswith('data:image'):
                result = tab.run_js(EXTRACT_JS, img_ele)
                if result and result.startswith('data:image'):
                    b64 = result.split(',', 1)[1]
                    return base64.b64decode(b64)
        except Exception:
            pass
        time.sleep(0.5)
        waited += 0.5
    return None


def _browser_fail_info(chapter_num, index, folder, path, error):
    return {
        'url': '',
        'chapter_num': chapter_num,
        'image_index': index,
        'folder': folder,
        'path': path,
        'error': error
    }


def _browser_extract_chapter_images(chapter_tab, folder_name, chapter_num, img_locator,
                                    progress_callback=None):
    """在章节页内提取所有图片并保存，返回失败列表"""
    failed = []

    img_eles = chapter_tab.eles(img_locator, timeout=15)
    total_imgs = len(img_eles)
    print(f"章节{chapter_num}: 检测到 {total_imgs} 个图片元素，开始滚动加载...")

    _browser_scroll_to_load_all(chapter_tab, total_imgs)

    for i in range(1, total_imgs + 1):
        file_path = os.path.join(folder_name, format_image_name(i, '.jpg'))
        img_ele = chapter_tab.ele(f'{img_locator}[{i}]', timeout=5)
        if not img_ele:
            failed.append(_browser_fail_info(chapter_num, i, folder_name, file_path, '元素不存在'))
            continue

        try:
            img_ele.scroll.to_see()
        except Exception:
            pass

        data = _browser_extract_single_image(chapter_tab, img_ele)
        if data:
            with open(file_path, 'wb') as f:
                f.write(data)
            print(f"  ✓ 章节{chapter_num} 第{i}/{total_imgs}张提取成功 ({len(data)}字节)")
            if progress_callback:
                progress_callback(len(data))
        else:
            print(f"  ✗ 章节{chapter_num} 第{i}/{total_imgs}张提取失败")
            if progress_callback:
                progress_callback(0)
            failed.append(_browser_fail_info(chapter_num, i, folder_name, file_path, '提取失败'))

    return failed


def download_chapters_via_browser(site_crawler, all_chapters_data, comic_name, base_path=None,
                                  progress_callback=None, max_workers=4):
    """浏览器渲染下载：打开章节页等待解密渲染，canvas提取像素保存为JPEG

    适用于CONFIG中browser_render=True的站点，图片xpath取自locators['chapter_image']
    参考collect_chapters_images的多标签页方案，使用ThreadPoolExecutor同时打开多个章节
    标签页并行提取，每个线程只操作自己创建的标签页

    Args:
        site_crawler: 站点爬虫实例（提供CONFIG/locators和浏览器实例）
        max_workers: 并行章节数（同时打开的标签页数量）

    Returns:
        failed_list: 与HTTP下载相同格式的失败列表
    """
    if base_path is None:
        base_path = os.getcwd()

    render_mode = getattr(site_crawler, 'CONFIG', {}).get('render_mode', 'canvas')

    main_folder = os.path.join(base_path, comic_name)
    if not os.path.exists(main_folder):
        os.makedirs(main_folder)

    total_chapters = len(all_chapters_data)
    max_workers = max(1, min(max_workers, total_chapters)) if total_chapters > 0 else 1

    if render_mode == 'blob_hook':
        # blob钩子模式：翻页遍历阅读器捕获解密后blob（无img元素的canvas渲染站点）
        # 强制串行：不可见的后台标签页rAF被节流到~1Hz，阅读器翻页会卡死，
        # 并行多标签无法保证每个标签都在前台，故串行+翻页前激活标签页
        max_workers = 1
        print(f"浏览器blob钩子下载: 共{total_chapters}章，串行标签页模式（阅读器需保持可见）")
        prepare = getattr(site_crawler, 'prepare_blob_download', None)
        if callable(prepare):
            try:
                prepare()
            except Exception as e:
                print(f"下载前置准备失败: {e}")

        all_failed = []
        fail_lock = threading.Lock()
        total_start = time.time()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for chapter_data in all_chapters_data:
                futures.append(executor.submit(
                    _browser_process_chapter_blob,
                    site_crawler, chapter_data, main_folder, progress_callback
                ))
            for future in futures:
                try:
                    failed = future.result()
                except Exception as e:
                    print(f"章节任务异常: {e}")
                    failed = []
                with fail_lock:
                    all_failed.extend(failed)

        all_failed.sort(key=lambda x: (x['chapter_num'], x['image_index']))
        total_elapsed = time.time() - total_start
        print(f"\nblob钩子下载完成！总耗时: {total_elapsed:.1f}秒，失败图片: {len(all_failed)} 张")
        return all_failed

    img_locator = site_crawler.locators.get('chapter_image')
    if not img_locator:
        print("站点未配置chapter_image定位器，无法使用浏览器渲染下载")
        return []

    print(f"浏览器渲染下载: 共{total_chapters}章，并行标签页数: {max_workers}")

    all_failed = []
    fail_lock = threading.Lock()
    total_start = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for chapter_data in all_chapters_data:
            futures.append(executor.submit(
                _browser_process_chapter,
                site_crawler, chapter_data, main_folder, img_locator, progress_callback,
                fail_lock
            ))

        for future in futures:
            try:
                failed = future.result()
            except Exception as e:
                print(f"章节任务异常: {e}")
                failed = []
            with fail_lock:
                all_failed.extend(failed)

    # 按章节、图片序号排序，便于阅读
    all_failed.sort(key=lambda x: (x['chapter_num'], x['image_index']))

    total_elapsed = time.time() - total_start
    print(f"\n浏览器渲染下载完成！总耗时: {total_elapsed:.1f}秒，失败图片: {len(all_failed)} 张")
    return all_failed


def _browser_process_chapter(site_crawler, chapter_data, main_folder, img_locator,
                             progress_callback=None, fail_lock=None):
    """处理单个章节：创建自己的标签页并提取所有图片（仅操作自己创建的标签页）

    Returns:
        failed: 该章节的失败列表
    """
    chapter_num = chapter_data['chapter_num']
    chapter_url = chapter_data.get('url')
    expected_count = len(chapter_data.get('herf_list', []))

    if not chapter_url:
        print(f"[章节{chapter_num}] 无章节URL，跳过")
        return []

    folder_name = os.path.join(main_folder, chapter_folder_name(chapter_data))
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    print(f"[章节{chapter_num}] 开始浏览器渲染提取: {chapter_url}")
    chapter_start = time.time()

    failed = []
    max_retries = 2
    for attempt in range(max_retries + 1):
        chapter_tab = None
        try:
            chapter_tab = site_crawler.crawler.page.new_tab(chapter_url)
            time.sleep(3)

            # 等待图片元素出现
            img_eles = chapter_tab.eles(img_locator, timeout=20)
            if len(img_eles) == 0:
                raise Exception('未检测到图片元素')

            failed = _browser_extract_chapter_images(
                chapter_tab, folder_name, chapter_num, img_locator, progress_callback)

            if not failed:
                break
            print(f"[章节{chapter_num}] 本次提取失败 {len(failed)} 张，重试中...")
        except Exception as e:
            print(f"[章节{chapter_num}] 第{attempt + 1}次尝试异常: {e}")
            failed = [_browser_fail_info(chapter_num, i, folder_name,
                                         os.path.join(folder_name, format_image_name(i, '.jpg')), '章节页加载失败')
                      for i in range(1, expected_count + 1)]
        finally:
            if chapter_tab:
                try:
                    chapter_tab.close()
                except Exception:
                    pass

    elapsed = time.time() - chapter_start
    print(f"[章节{chapter_num}] 完成，耗时{elapsed:.1f}秒，失败{len(failed)}张")

    # 失败列表线程安全合并到全局（保留单章明细供调用方收集）
    if failed and fail_lock is not None:
        with fail_lock:
            print(f"[章节{chapter_num}] {len(failed)}张失败已登记")

    return failed


# ==================== blob钩子模式（加密canvas渲染站点，如哔哩哔哩漫画） ====================

# fetch blob URL并转为base64返回；先createImageBitmap校验尺寸（漫画页宽固定680px，
# 排除UI小图/图标等意外捕获的非页面blob；小体积真实页面不会被尺寸过滤误杀）
BLOB_FETCH_JS = """
async function(url) {
    try {
        var resp = await fetch(url);
        var blob = await resp.blob();
        var bmp = await createImageBitmap(blob);
        if (bmp.width < 300 || bmp.height < 100) {
            bmp.close();
            return '';
        }
        bmp.close();
        var buf = await blob.arrayBuffer();
        var bytes = new Uint8Array(buf);
        var bin = '';
        var chunk = 32768;
        for (var i = 0; i < bytes.length; i += chunk) {
            bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
        }
        return btoa(bin);
    } catch (e) { return ''; }
}
"""


def _blob_image_ext(data):
    """按文件头判断图片格式扩展名"""
    if data[:3] == b'\xff\xd8\xff':
        return '.jpg'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return '.png'
    if data[4:12] in (b'ftypavif', b'ftypavis'):
        return '.avif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return '.webp'
    return '.bin'


def _blob_get_page_info(chapter_tab, page_info_js):
    """读取阅读器当前页码，返回(cur, total)，失败返回(0, 0)"""
    try:
        info = chapter_tab.run_js(page_info_js)
        if isinstance(info, (list, tuple)) and len(info) == 2:
            return int(info[0]), int(info[1])
    except Exception:
        pass
    return 0, 0


def _cdp_real_click(chapter_tab, x_ratio=0.85, y_ratio=0.5):
    """CDP级真实鼠标点击（不执行页面JS，事件isTrusted=true）

    部分阅读器会过滤合成事件(dispatchEvent的isTrusted=false)，
    CDP Input事件与真人点击等价，可穿透此类限制与主线程繁忙期。
    """
    try:
        metrics = chapter_tab.run_cdp('Page.getLayoutMetrics')
        vp = metrics.get('cssVisualViewport') or metrics.get('visualViewport') or {}
        w = vp.get('clientWidth') or 1280
        h = vp.get('clientHeight') or 800
        x, y = int(w * x_ratio), int(h * y_ratio)
        for etype in ('mousePressed', 'mouseReleased'):
            chapter_tab.run_cdp('Input.dispatchMouseEvent', type=etype, x=x, y=y,
                                button='left', clickCount=1)
        return True
    except Exception:
        return False


def _ensure_tab_foreground(chapter_tab):
    """确保标签页所在窗口未最小化且标签页处于前台

    实测：窗口最小化或标签页不可见时，Chrome把rAF节流到~1Hz（启动参数无法禁用，
    属Blink页面级节流），依赖rAF的阅读器翻页/解密会卡死在第1页。
    唯一可靠手段：保持标签页真实可见，被最小化时主动恢复窗口。
    """
    try:
        win_info = chapter_tab.run_cdp('Browser.getWindowForTarget')
        win_id = win_info.get('windowId')
        state = (win_info.get('bounds') or {}).get('windowState')
        if state == 'minimized' and win_id is not None:
            chapter_tab.run_cdp('Browser.setWindowBounds', windowId=win_id,
                                bounds={'windowState': 'normal'})
    except Exception:
        pass
    try:
        chapter_tab.set.activate()
    except Exception:
        pass


def _blob_extract_and_save(chapter_tab, folder_name, chapter_num, cfg, total_pages,
                           progress_callback=None):
    """提取已捕获的blob并保存，内容MD5去重（双缓冲/预加载会产生重复）

    Returns:
        (failed, saved_count): 缺失页的失败列表、实际保存张数
    """
    failed = []
    min_size = cfg.get('min_blob_size', 30000)

    blobs = chapter_tab.run_js("return window.__captured_blobs || []")
    if not isinstance(blobs, list):
        blobs = []

    # 按URL去重，只保留大图；按捕获时间排序保证页面顺序
    # （双缓冲/预加载可能提前解码后续页，捕获顺序非严格页码序）
    seen_urls = set()
    uniq = []
    for b in blobs:
        if b.get('size', 0) >= min_size and b.get('url') and b['url'] not in seen_urls:
            seen_urls.add(b['url'])
            uniq.append(b)
    uniq.sort(key=lambda b: b.get('at') or 0)
    print(f"[章节{chapter_num}] 捕获大blob {len(uniq)} 个（总页数 {total_pages}），开始提取...")

    saved_md5 = set()
    idx = 0
    for b in uniq:
        try:
            b64 = chapter_tab.run_js(BLOB_FETCH_JS, b['url'])
        except Exception:
            b64 = ''
        if not b64:
            continue
        data = base64.b64decode(b64)
        h = hashlib.md5(data).hexdigest()
        if h in saved_md5:
            continue  # 同一页的重复解码产物
        saved_md5.add(h)
        idx += 1
        ext = _blob_image_ext(data)
        file_path = os.path.join(folder_name, format_image_name(idx, ext))
        with open(file_path, 'wb') as f:
            f.write(data)
        print(f"  ✓ 章节{chapter_num} 第{idx}张提取成功 ({len(data)}字节)")
        if progress_callback:
            progress_callback(len(data))

    # 保存数量不足总页数时登记缺失
    if total_pages > 0 and idx < total_pages:
        for i in range(idx + 1, total_pages + 1):
            failed.append(_browser_fail_info(chapter_num, i, folder_name,
                                             os.path.join(folder_name, format_image_name(i, '.jpg')), 'blob缺失'))
    return failed, idx


def _browser_process_chapter_blob(site_crawler, chapter_data, main_folder,
                                  progress_callback=None):
    """blob钩子模式处理单个章节：注入钩子→打开章节页→翻页遍历→提取blob

    Returns:
        failed: 该章节的失败列表
    """
    cfg = getattr(site_crawler, 'CONFIG', {}).get('blob_hook', {})
    chapter_num = chapter_data['chapter_num']
    chapter_url = chapter_data.get('url')

    if not chapter_url:
        print(f"[章节{chapter_num}] 无章节URL，跳过")
        return []

    folder_name = os.path.join(main_folder, chapter_folder_name(chapter_data))
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    print(f"[章节{chapter_num}] 开始blob钩子提取: {chapter_url}")
    chapter_start = time.time()

    page_info_js = cfg.get('page_info_js') or "return [0, 0];"
    prev_page_js = cfg.get('prev_page_js') or ''
    next_page_js = cfg.get('next_page_js') or ''
    # 翻页停滞时的兜底翻页方式（默认键盘事件，阅读器普遍支持方向键）
    stuck_next_js = cfg.get('stuck_next_js') or (
        "document.dispatchEvent(new KeyboardEvent('keydown',"
        "{key:'ArrowRight',keyCode:39,which:39,bubbles:true}));")
    ready_wait = cfg.get('ready_wait', 8)
    page_interval = cfg.get('page_interval', 0.8)
    max_stuck = cfg.get('max_stuck', 3)
    # 单个停滞点的最大等待秒数（下一页可能仍在解密/下载，需给它足够时间）
    stuck_timeout = cfg.get('stuck_timeout', 30)

    failed = []
    max_retries = 2
    prev_saved = -1
    for attempt in range(max_retries + 1):
        chapter_tab = None
        try:
            # 先开空白标签页注入钩子，再导航到章节页（钩子必须在页面脚本前生效）
            chapter_tab = site_crawler.crawler.page.new_tab('about:blank')
            chapter_tab.run_cdp('Page.addScriptToEvaluateOnNewDocument',
                                source=site_crawler.BLOB_HOOK_JS)
            # 强制标签页保持active生命周期：并行下载时非激活标签页会被节流
            # （rAF降到~1Hz），依赖rAF的阅读器翻页/解密会卡死在第1页
            try:
                chapter_tab.run_cdp('Page.setWebLifecycleState', state='active')
            except Exception:
                pass
            # 阅读器依赖rAF渲染，标签页必须真实可见：窗口被最小化/标签在后台时
            # rAF被节流到~1Hz导致翻页卡死，故加载前就确保其在前台
            _ensure_tab_foreground(chapter_tab)
            chapter_tab.get(chapter_url)

            # 条件等待阅读器就绪，替代固定sleep(ready_wait)：
            # 1) 首页blob已被钩子捕获（最可靠，说明解密渲染已开始）；
            # 2) 或页码total>=2（骨架期显示的1/1占位不可信，不作就绪依据）；
            # 3) total恒为1持续ready_wait秒（兼容真实单页章节的兜底）。
            cur, total = 0, 0
            waited = 0.0
            stable_one = 0
            ready_timeout = ready_wait * 2
            while waited < ready_timeout:
                cur, total = _blob_get_page_info(chapter_tab, page_info_js)
                blobs = chapter_tab.run_js('return (window.__captured_blobs || []).length') or 0
                if blobs > 0 or total >= 2:
                    break
                if total == 1:
                    stable_one += 1
                    if stable_one >= max(2, int(ready_wait / 0.5)):
                        break
                else:
                    stable_one = 0
                time.sleep(0.5)
                waited += 0.5
            # 就绪后再读一次页码，拿到异步刷新后的真实总页数
            cur, total = _blob_get_page_info(chapter_tab, page_info_js)

            if total <= 0:
                raise Exception('未检测到阅读器页码（章节可能被锁定或加载失败）')

            # 诊断翻页箭头是否存在（JS查询可穿透完整渲染树，比CDP DOM浅树可靠）：
            # 新版阅读器可能无.arrow-right或过滤合成事件，提前告警供排查
            try:
                arrow_info = chapter_tab.run_js(
                    "var els=['arrow-right','right-arrow','pagedown'].map(function(c){"
                    "var e=document.querySelector('.'+c);"
                    "return e?[c,e.offsetParent!==null]:null;}).filter(Boolean);"
                    "return els;", timeout=8)
                if not arrow_info or not any(v[0] == 'arrow-right' for v in arrow_info):
                    print(f"[章节{chapter_num}] 警告: 未检测到.arrow-right，"
                          f"现有导航元素: {arrow_info}")
            except Exception:
                pass

            # 若不在第1页（阅读进度恢复），先回退到第1页
            stuck = 0
            while cur > 1 and stuck < max_stuck and prev_page_js:
                prev = cur
                chapter_tab.run_js(prev_page_js)
                time.sleep(page_interval)
                cur, total = _blob_get_page_info(chapter_tab, page_info_js)
                stuck = stuck + 1 if cur == prev else 0

            # 前翻遍历到末页，触发所有页面解密
            # 停滞超过max_stuck次后切换兜底翻页方式并在停滞点持续等待（下一页可能仍在解密），
            # 单点等待超过stuck_timeout秒才放弃，避免点击暂时失效时整章后段缺页
            stuck = 0
            stuck_waited = 0.0
            while cur < total:
                prev = cur
                if stuck >= max_stuck:
                    # 停滞优先恢复前台（用户可能中途最小化了窗口，rAF节流导致翻页失效）
                    _ensure_tab_foreground(chapter_tab)
                    # 兜底方式交替：JS事件与CDP真实点击
                    # （新版阅读器可能过滤isTrusted=false的合成事件，真实点击可穿透）
                    if (stuck - max_stuck) % 2 == 0:
                        chapter_tab.run_js(stuck_next_js)
                    else:
                        _cdp_real_click(chapter_tab, 0.85, 0.5)
                    time.sleep(page_interval * 2)
                    stuck_waited += page_interval * 2
                    if stuck_waited >= stuck_timeout:
                        break
                else:
                    chapter_tab.run_js(next_page_js)
                    time.sleep(page_interval)
                cur, _ = _blob_get_page_info(chapter_tab, page_info_js)
                if cur == prev:
                    stuck += 1
                else:
                    stuck = 0
                    stuck_waited = 0.0

            # 到底后尾部页面可能仍在异步解码：停在底部持续等待，
            # 直到去重大blob数达到总页数才提前退出，否则等满tail_wait秒
            # （"数量稳定"不可靠：解码未完成时数量同样稳定，会提前误退出）
            tail_wait = cfg.get('tail_wait', 20)
            tail_deadline = time.time() + tail_wait
            tail_min_size = cfg.get('min_blob_size', 30000)
            tail_js = ("var bs=(window.__captured_blobs||[]);var seen={};var n=0;"
                       "for(var i=0;i<bs.length;i++){var b=bs[i];"
                       "if(b.size>=%d&&b.url&&!seen[b.url]){seen[b.url]=1;n++;}}"
                       "return n;" % tail_min_size)
            while time.time() < tail_deadline:
                time.sleep(1.5)
                try:
                    n = chapter_tab.run_js(tail_js) or 0
                except Exception:
                    n = -1
                if n >= total:
                    break
            time.sleep(2)

            if cur < total:
                print(f"[章节{chapter_num}] 翻页停滞于 {cur}/{total}")

            traversal_done = cur >= total
            failed, saved_count = _blob_extract_and_save(
                chapter_tab, folder_name, chapter_num, cfg, total, progress_callback)

            if not failed:
                break
            # 翻页已完整遍历到底，且解码张数稳定：仅在差距极小（≤2张）时按"尾部
            # 占位页"接受——真正缺页时差距较大，保持失败列表如实上报，避免静默漏图
            if traversal_done and saved_count == prev_saved and saved_count > 0 \
                    and total - saved_count <= 2:
                print(f"[章节{chapter_num}] 阅读器报{total}页，实际解码{saved_count}张"
                      f"（差距≤2，尾页占位，非缺图），按{saved_count}张完成")
                failed = []
                break
            prev_saved = saved_count
            if attempt < max_retries:
                print(f"[章节{chapter_num}] 本次缺失 {len(failed)} 张，重试中...")
        except Exception as e:
            print(f"[章节{chapter_num}] 第{attempt + 1}次尝试异常: {e}")
            failed = [_browser_fail_info(chapter_num, 1, folder_name,
                                         os.path.join(folder_name, format_image_name(1, '.jpg')), f'章节提取失败: {e}')]
        finally:
            if chapter_tab:
                try:
                    chapter_tab.close()
                except Exception:
                    pass

    elapsed = time.time() - chapter_start
    print(f"[章节{chapter_num}] 完成，耗时{elapsed:.1f}秒，失败{len(failed)}张")
    return failed


def download_cover_via_browser(target_comic_tab, site_crawler, comic_name, base_path=None):
    """通过浏览器渲染提取封面图片，失败返回False由调用方回退HTTP下载"""
    if base_path is None:
        base_path = os.getcwd()

    try:
        img_ele = target_comic_tab.ele(site_crawler.locators['cover_image'], timeout=15)
        if not img_ele:
            return False
        try:
            img_ele.scroll.to_see()
        except Exception:
            pass
        time.sleep(2)

        data = _browser_extract_single_image(target_comic_tab, img_ele, max_wait=20)
        if not data:
            print("封面浏览器提取失败")
            return False

        folder_name = os.path.join(base_path, comic_name, "0")
        if not os.path.exists(folder_name):
            os.makedirs(folder_name)
        file_path = os.path.join(folder_name, "cover.jpg")
        with open(file_path, 'wb') as f:
            f.write(data)
        print(f"封面浏览器提取成功 ({len(data)}字节)")
        return True
    except Exception as e:
        print(f"封面浏览器提取异常: {e}")
        return False


def is_browser_render_site(site_crawler):
    """判断站点是否需要浏览器渲染下载（图片加密站点）"""
    if site_crawler is None:
        return False
    return bool(getattr(site_crawler, 'CONFIG', {}).get('browser_render', False))


async def download_with_aiohttp(url, file_path, timeout=10, proxy=None):
    """使用aiohttp下载（代理返回5xx时自动直连重试一次：部分CDN拒绝代理出口IP）"""
    # 使用传入的代理或全局代理（惰性检测）
    active_proxy = get_active_proxy()
    proxy_url = proxy or (active_proxy.get('https') if active_proxy else None)
    attempts = [proxy_url, None] if proxy_url else [None]
    last_info = "未知错误"

    for attempt_proxy in attempts:
        try:
            connector = aiohttp.TCPConnector(
                limit=1,
                enable_cleanup_closed=True,
                force_close=True,
                ssl=False
            )

            async with aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=timeout),
                headers=_build_download_headers()
            ) as session:
                async with session.get(url, allow_redirects=True, proxy=attempt_proxy) as response:
                    if response.status == 200:
                        content = await response.read()
                        # 解密后写盘（站点CONFIG声明decrypt时）
                        if _ACTIVE_DECRYPTOR:
                            content = _decrypt_content(content)
                            if content is None:
                                return False, "解密失败"
                        # 只要有内容就算成功（即使是空白图片）
                        if len(content) > 0:
                            async with aiofiles.open(file_path, 'wb') as f:
                                await f.write(content)
                            return True, len(content)
                        else:
                            return False, "内容为空"
                    else:
                        if 500 <= response.status < 600:
                            last_info = f"服务端错误(状态码{response.status})，源站文件可能已损坏，非客户端问题"
                            if attempt_proxy:
                                # 可能是CDN拒绝代理出口IP，改用直连重试
                                continue
                            return False, last_info
                        return False, f"状态码{response.status}"
        except asyncio.TimeoutError:
            last_info = "超时"
            if attempt_proxy:
                continue
        except Exception as e:
            last_info = str(e)[:50]
            if attempt_proxy:
                continue

    return False, last_info


def download_with_requests(url, file_path, timeout=10, proxy=None):
    """使用requests下载（同步，代理返回5xx时自动直连重试一次）"""
    # 使用传入的代理或全局代理（惰性检测）
    proxies = proxy or get_active_proxy()
    attempts = [proxies, {'http': None, 'https': None}] if proxies else [None]
    last_info = "未知错误"

    for attempt_proxies in attempts:
        try:
            response = requests.get(url, stream=True, timeout=timeout, proxies=attempt_proxies,
                                    headers=_build_download_headers())
            try:
                response.raise_for_status()
            except requests.HTTPError:
                if 500 <= response.status_code < 600:
                    last_info = f"服务端错误(状态码{response.status_code})，源站文件可能已损坏，非客户端问题"
                    if attempt_proxies:
                        # 可能是CDN拒绝代理出口IP，改用直连重试
                        continue
                    return False, last_info
                return False, f"状态码{response.status_code}"

            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)

            # 解密后重写（站点CONFIG声明decrypt时）
            if _ACTIVE_DECRYPTOR:
                with open(file_path, 'rb') as f:
                    raw = f.read()
                decrypted = _decrypt_content(raw)
                if decrypted is None:
                    return False, "解密失败"
                with open(file_path, 'wb') as f:
                    f.write(decrypted)

            # 只要有内容就算成功（即使是空白图片）
            file_size = os.path.getsize(file_path)
            if file_size > 0:
                return True, file_size
            else:
                return False, "内容为空"
        except Exception as e:
            last_info = str(e)[:50]
            if attempt_proxies:
                continue

    return False, last_info


async def download_image(url, index, folder_name, chapter_num, progress_callback=None, timeout=10):
    """
    下载单张图片
    先用aiohttp下载，失败则返回错误信息（不立即重试）
    
    Args:
        timeout: 下载超时时间（秒）
    """
    file_path = os.path.join(folder_name, format_image_name(index, f".{_ACTIVE_IMAGE_EXT}"))
    
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
        file_path = os.path.join(folder_name, format_image_name(index, f".{_ACTIVE_IMAGE_EXT}"))
        
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
        file_path = os.path.join(folder_name, format_image_name(i, f".{_ACTIVE_IMAGE_EXT}"))
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
            "folder_name": chapter_folder_name(chapter_data),
            "title": chapter_data.get('title', ''),
            "url": chapter_data.get('url', ''),
            "total_images": len(herf_list),
            "images": []
        }
        
        for i, url in enumerate(herf_list, 1):
            chapter_info["images"].append({
                "index": i,
                "filename": format_image_name(i, f".{_ACTIVE_IMAGE_EXT}"),
                "url": url
            })
        
        url_mapping["chapters"].append(chapter_info)
    
    json_path = os.path.join(main_folder, "image_urls.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(url_mapping, f, ensure_ascii=False, indent=2)
    
    print(f"\n图片URL映射已保存到: {json_path}")
    return json_path


async def download_all_chapters(all_chapters_data, comic_name, base_path=None, save_json_only=False, concurrent_limit=3, download_thread_count=4, use_thread_coroutine=True, progress_callback=None, max_retries=3, use_thread_only=False, first_timeout=8, retry_timeout=15, site_crawler=None):
    """下载所有章节，可选只保存JSON不下载
    
    Args:
        max_retries: 失败后重试次数，默认3次
        use_thread_only: 是否使用纯多线程模式（不使用协程）
        first_timeout: 首次下载超时时间（秒）
        retry_timeout: 重试超时时间（秒）
        site_crawler: 站点爬虫实例，若其CONFIG声明browser_render=True则走浏览器渲染下载（并发数复用download_thread_count）
    
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

    # 按站点CONFIG设置Referer（CDN防盗链站点需要），流程结束后清除
    set_active_referer(getattr(site_crawler, 'CONFIG', {}).get('image_referer') if site_crawler else None)

    # 按站点CONFIG设置解密器（图片加密可复现的站点），流程结束后清除
    decrypt_cfg = getattr(site_crawler, 'CONFIG', {}).get('decrypt') if site_crawler else None
    if decrypt_cfg:
        decryptor = _build_decryptor(site_crawler)
        if decryptor:
            set_active_decryptor(decryptor, decrypt_cfg.get('ext', 'jpg'))
            print(f"该站点启用解密下载（模式: {decrypt_cfg.get('mode')}，扩展名: {decrypt_cfg.get('ext', 'jpg')}）")

    total_start = time.time()
    all_failed = []  # 收集所有失败图片

    if is_browser_render_site(site_crawler):
        # 站点图片经过加密，HTTP直下无法获得有效图片，改由浏览器渲染后提取
        print(f"\n{'='*50}")
        print("该站点启用浏览器渲染下载模式（图片加密，需浏览器解密后提取）")
        print(f"{'='*50}")
        loop = asyncio.get_event_loop()
        all_failed = await loop.run_in_executor(
            None,
            download_chapters_via_browser,
            site_crawler,
            all_chapters_data,
            comic_name,
            base_path,
            progress_callback,
            download_thread_count
        )
    else:
        for chapter_data in all_chapters_data:
            chapter_num = chapter_data['chapter_num']
            herf_list = chapter_data['herf_list']

            if not herf_list:
                print(f"[章节{chapter_num}] 无图片链接，跳过")
                continue

            folder_name = os.path.join(main_folder, chapter_folder_name(chapter_data))
            # 使用协程+多线程下载，收集所有失败
            failed = await download_chapter_images(herf_list, folder_name, chapter_num, concurrent_limit, download_thread_count, use_thread_coroutine, progress_callback, use_thread_only, timeout=first_timeout)
            # 收集所有失败图片
            all_failed.extend(failed)

    total_elapsed = time.time() - total_start
    print(f"\n{'='*50}")
    print(f"首次下载完成！总耗时: {total_elapsed:.1f}秒")
    print(f"失败图片: {len(all_failed)} 张")
    
    # 所有章节下载完成后，统一多线程重试所有失败图片（浏览器模式无法HTTP重试，跳过）
    use_browser_mode = is_browser_render_site(site_crawler)
    if all_failed and not use_browser_mode:
        print(f"\n{'='*50}")
        print(f"开始统一重试所有失败图片: {len(all_failed)} 张")
        print(f"{'='*50}")
        
        # 使用多线程批量重试
        still_failed = retry_failed_batch(all_failed, progress_callback, max_workers=download_thread_count, timeout=retry_timeout)
        success_count = len(all_failed) - len(still_failed)
        print(f"\n统一重试完成: 成功 {success_count} 张，失败 {len(still_failed)} 张")
        
        all_failed = still_failed
    
    # 保存失败列表到JSON（附带站点信息，供浏览器模式重试使用）
    if all_failed:
        print(f"\n失败的图片URL列表:")
        for failed in all_failed:
            print(f"  章节{failed['chapter_num']}-第{failed['image_index']}张: {failed['url']}")
        
        site_name = getattr(site_crawler, 'SITE_NAME', None) if site_crawler else None
        render_mode = None
        if use_browser_mode:
            render_mode = getattr(site_crawler, 'CONFIG', {}).get('render_mode', 'canvas')
        failed_json_path = save_failed_json(all_failed, comic_name, base_path,
                                                site_name=site_name, render_mode=render_mode)
        print(f"{'='*50}")
        set_active_referer(None)
        set_active_decryptor(None)
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
    set_active_referer(None)
    set_active_decryptor(None)
    return [], None, True  # 全部成功，可以压缩


def save_failed_json(failed_list, comic_name, base_path=None, site_name=None, render_mode=None):
    """保存失败列表到JSON文件（附带站点信息，供浏览器模式重试使用）"""
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
        "site_name": site_name,
        "render_mode": render_mode,
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

    # 按失败列表记录的站点设置Referer（CDN防盗链站点需要）
    try:
        if data.get('site_name'):
            from site_discovery import get_site_config
            set_active_referer(get_site_config(data['site_name']).get('image_referer'))
    except Exception:
        pass
    
    if not failed_images:
        print("没有需要重试的图片")
        set_active_referer(None)
        set_active_decryptor(None)
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
            # 统计文件夹中的图片文件
            actual_count = len([f for f in os.listdir(folder) if f.endswith(f'.{_ACTIVE_IMAGE_EXT}')])
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
        
        # 保存更新后的失败列表（保留原站点信息，供浏览器模式重试使用）
        failed_json_path = save_failed_json(all_failed, comic_name, base_path,
                                            site_name=data.get('site_name'),
                                            render_mode=data.get('render_mode'))
        print(f"\n更新后的失败列表已保存到: {failed_json_path}")
        
        print(f"{'='*50}")
        set_active_referer(None)
        set_active_decryptor(None)
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
    set_active_referer(None)
    set_active_decryptor(None)
    return [], True


def retry_failed_chapters_via_browser(json_path, site_name, browser_path, headless=False,
                                      cookies_dir=None, progress_callback=None, max_workers=4):
    """浏览器渲染模式失败重试：按失败列表重跑整个章节的浏览器提取

    HTTP重试对加密站点无效，必须重新走浏览器渲染提取。
    章节URL从同目录image_urls.json读取；重跑前清空对应章节文件夹避免新旧文件混杂。

    Args:
        json_path: failed_images.json路径
        site_name: 站点名称（用于创建ComicCrawler）
        cookies_dir: Cookie目录（登录态站点需要）

    Returns:
        (still_failed, all_success)
    """
    from crawler import ComicCrawler

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    comic_name = data['comic_name']
    main_folder = data['base_path']
    base_path = os.path.dirname(main_folder.rstrip(os.sep))
    failed_images = data['failed_images']

    failed_chapter_nums = sorted({img['chapter_num'] for img in failed_images})
    print(f"浏览器模式重试: 漫画《{comic_name}》失败章节 {failed_chapter_nums}")

    # 从image_urls.json读取章节URL/标题/实际文件夹名
    url_map = {}
    image_urls_json = os.path.join(main_folder, "image_urls.json")
    if os.path.exists(image_urls_json):
        try:
            with open(image_urls_json, 'r', encoding='utf-8') as f:
                url_data = json.load(f)
            for chapter in url_data.get('chapters', []):
                if chapter.get('url'):
                    url_map[chapter['chapter_num']] = chapter
        except Exception as e:
            print(f"读取image_urls.json失败: {e}")

    chapters_data = []
    for num in failed_chapter_nums:
        chapter = url_map.get(num)
        if not chapter:
            print(f"章节{num}: 无章节URL，无法重试（需重新完整下载）")
            continue
        url = chapter.get('url')
        # 使用原下载时实际使用的文件夹名（与章节命名模式一致），清空残留文件后重跑
        folder = os.path.join(main_folder, chapter.get('folder_name') or str(num))
        shutil.rmtree(folder, ignore_errors=True)
        chapters_data.append({
            'chapter_num': num, 'url': url,
            'title': chapter.get('title', ''), 'herf_list': []
        })

    if not chapters_data:
        print("没有可重试的章节")
        return failed_images, False

    print(f"正在启动浏览器，重试 {len(chapters_data)} 个章节...")
    crawler = ComicCrawler(site_name, browser_path, headless, cookies_dir=cookies_dir)
    try:
        still_failed = download_chapters_via_browser(
            crawler.site_crawler, chapters_data, comic_name, base_path,
            progress_callback, max_workers)
    finally:
        try:
            crawler.page.close()
        except Exception:
            pass

    if not still_failed:
        # 全部成功，删除失败列表
        try:
            if os.path.exists(json_path):
                os.remove(json_path)
                print(f"全部重试成功，已删除失败列表: {json_path}")
        except Exception as e:
            print(f"删除失败列表文件失败: {e}")
        return [], True

    # 保存更新后的失败列表（保留站点信息）
    save_failed_json(still_failed, comic_name, base_path,
                       site_name=data.get('site_name'),
                       render_mode=data.get('render_mode'))
    return still_failed, False


async def download_cover_image(url, comic_name, base_path=None):
    """下载封面图片"""
    if base_path is None:
        base_path = os.getcwd()

    main_folder = os.path.join(base_path, comic_name)
    folder_name = os.path.join(main_folder, "0")

    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    print(f"\n开始下载封面...")
    file_path = os.path.join(folder_name, f"cover.{_ACTIVE_IMAGE_EXT}")
    
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
