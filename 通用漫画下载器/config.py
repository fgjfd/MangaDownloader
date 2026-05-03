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

BROWSER_PATHS = {
    'edge': r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    'chrome': r"C:\Program Files\Google\Chrome\Application\chrome.exe"
}

DEFAULT_SITE = '拷贝漫画'

SITES_REQUIRING_LOGIN = ['快看', '腾讯动漫', '菠萝包']

DEFAULT_COOKIES_DIR = 'cookies'

CONFIG_FILE = 'config.json'

SITES = {
    '快看': {
        'site_url': 'https://www.kuaikanmanhua.com/',
        'locators': {
            'search_input': 'xpath:/html/body/div[1]/div/div/div/div[1]/div[2]/div/div[1]/input',
            'search_button': 'xpath:/html/body/div[1]/div/div/div/div[1]/div[2]/div/div[1]/a',
            'search_result': 'xpath:/html/body/div[1]/div/div/div/div[3]/div[1]/div[1]/div[1]/a',
            'cover_image': 'xpath:/html/body/div[1]/div/div/div/div[2]/div/div[1]/div/div[1]/img[3]',
            'chapter_list': 'xpath:/html/body/div[1]/div/div/div/div[2]/div/div[2]/div[1]/div[1]/div/div[3]/div',
            'chapter_group_button': 'xpath:/html/body/div[1]/div/div/div/div[2]/div/div[2]/div[1]/div[1]/div/div[2]/div',
            'chapter_image_parent': 'xpath:/html/body/div[1]/div/div/div/div[4]/div[1]/div[1]/div',
            'chapter_image': 'xpath:/html/body/div[1]/div/div/div/div[4]/div[1]/div[1]/div[num]/img'
        },
        'image_attr': 'data-src',
        'chapter_group_size': 50
    },
    '好多漫': {
        'site_url': 'https://www.haoduoman.com/',
        'locators': {
            'search_input': 'xpath:/html/body/header/div[2]/div/div[2]/div/form/div/p[1]/input',
            'search_button': 'xpath:/html/body/header/div[2]/div/div[2]/div/form/div/p[2]/button',
            'search_result': 'xpath:/html/body/main/div/div[2]/div/div[1]/div/div/div[2]/a',
            'cover_image': 'xpath:/html/body/main/div/div[2]/div[1]/div/div/div/div[1]/img',
            'chapter_list': 'xpath:/html/body/main/div/div[3]/div[2]/ul/li',
            'chapter_link': 'xpath:/html/body/main/div/div[3]/div[2]/ul/li[num]/a',
            'chapter_image_parent': 'xpath:/html/body/main/div[1]/div/div[1]/div',
            'chapter_image_data_original': 'xpath:/html/body/main/div[1]/div/div[1]/div[num]'
        },
        'image_attr': 'data-original',
        'chapter_group_size': None
    },
    '拷贝漫画': {
        'site_url': 'https://www.mangacopy.com/comics',
        'locators': {
            'search_result': 'xpath:/html/body/main/div[2]/div/div/div[1]/div[1]/div[1]/a',
            'cover_image': 'xpath:/html/body/main/div[1]/div/div[1]/div/img',
            'chapter_list': 'xpath:/html/body/main/div[2]/div[3]/div/div[2]/div/div[1]/ul[1]/a',
            'chapter_link': 'xpath:/html/body/main/div[2]/div[3]/div/div[2]/div/div[1]/ul[1]/a[num]',
            'chapter_image_parent': 'xpath:/html/body/div[2]/div/ul/li',
            'chapter_image': 'xpath:/html/body/div[2]/div/ul/li[num]/img'
        },
        'image_attr': 'data-src',
        'chapter_group_size': None
    },
    '腾讯动漫': {
        'site_url': 'https://ac.qq.com/',
        'locators': {
            'search_input': '@tag()=input',
            'search_button': '@tag()=button',
            'search_result': 'xpath:/html/body/div[3]/ul/li[1]/a',
            'cover_image': 'xpath:/html/body/div[3]/div[3]/div/div/div[1]/a/img',
            'chapter_list_container': 'xpath:/html/body/div[3]/em/div[2]/div[2]/div/div[2]/ol[1]/li',
            'chapter_image_parent': 'xpath:/html/body/div[5]/ul/li',
            'chapter_image': 'xpath:/html/body/div[5]/ul/li[num]/img'
        },
        'image_attr': 'src',
        'chapter_group_size': None
    },
    '菠萝包': {
        'site_url': 'https://www.sfacg.com/',
        'locators': {
            'search_input': '@tag()=input',
            'search_button': 'xpath:/html/body/div[1]/div[2]/div/div[1]/div[1]/span',
            'search_result': 'xpath:/html/body/form/table[5]/tbody/tr/td/ul/li[2]/strong/a',
            'cover_image': 'xpath:/html/body/div[2]/div[3]/ul[2]/li[1]/img',
            'chapter_list': 'xpath:/html/body/div[3]/div[1]/div[3]/div[1]/a',
            'chapter_link': 'xpath:/html/body/div[3]/div[1]/div[3]/div[1]/a[num]'
        },
        'image_attr': 'src',
        'chapter_group_size': None,
        'api_mode': True
    }
}
