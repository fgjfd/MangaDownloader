# 通用配置文件 - 只包含全局配置，不包含网站特定信息

EXPORT_FORMATS = {
    'original': '原始图片格式',
    'pdf': 'pdf格式'
}

PDF_MODES = {
    'per_chapter': '每个章节一个PDF',
    'single': '每张图片单独转PDF'
}

DEFAULT_EXPORT_FORMAT = 'original'
DEFAULT_PDF_MODE = 'per_chapter'

# 图片文件名补零位数：0=不补零(1,2,3...)，3=三位补零(001,002,003...)
DEFAULT_IMAGE_NAME_PADDING = 3

# 章节文件夹命名模式：'number'=保持数字命名(1,2,3...)；'title'=使用章节名命名(1 第1话 xxx)
DEFAULT_CHAPTER_FOLDER_NAMING = 'number'

BROWSER_PATHS = {
    'edge': r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    'chrome': r"C:\Program Files\Google\Chrome\Application\chrome.exe"
}

DEFAULT_SITE = '拷贝漫画'

DEFAULT_COOKIES_DIR = 'cookies'

CONFIG_FILE = 'config.json'

