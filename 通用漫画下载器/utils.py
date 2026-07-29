import os
import zipfile

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
