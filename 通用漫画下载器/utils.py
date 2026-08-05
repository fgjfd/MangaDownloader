import os
import sys
import zipfile

def ensure_console_safe():
    """入口加固：
    1. GBK控制台下打印✓/⚠等非GBK字符会抛UnicodeEncodeError导致下载中断，
       统一设置 errors='replace' 避免崩溃；
    2. 无控制台打包环境(console=False)中 stdout/stderr 为None，print会抛AttributeError，
       用空写入器兜底。
    应在程序入口(gui.py/main.py)最开头调用。
    """
    class _NullWriter:
        def write(self, s):
            pass
        def flush(self):
            pass

    if sys.stdout is None:
        sys.stdout = _NullWriter()
    if sys.stderr is None:
        sys.stderr = sys.stdout
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure:
            try:
                reconfigure(errors='replace')
            except Exception:
                pass


def is_normal_url(url):
    """检查URL是否有效"""
    return url and ('http' in url or 'https' in url)


def zip_main_folder(comic_name, base_path=None):
    """压缩主文件夹"""
    import shutil
    
    if base_path is None:
        base_path = os.getcwd()
    
    main_folder = os.path.join(base_path, comic_name)
    zip_file = os.path.join(base_path, f"{comic_name}.zip")
    
    print(f"\n正在压缩文件夹: {main_folder}")
    
    with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(main_folder):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, base_path)
                zipf.write(file_path, arcname)
    
    print(f"压缩完成: {zip_file}")
    
    print(f"已保留原文件夹: {main_folder}")
