"""
网站发现模块 - 动态加载和管理所有可用的网站爬虫
"""
import importlib
import os


def discover_sites():
    """
    动态发现所有可用网站
    
    扫描 sites 目录下的所有 *_crawler.py 文件，
    提取类中的 SITE_NAME 元数据，返回站点名称到爬虫类的映射
    
    Returns:
        dict: {站点名称: 爬虫类}
    """
    sites = {}
    sites_dir = os.path.join(os.path.dirname(__file__), 'sites')
    
    if not os.path.exists(sites_dir):
        print(f"sites 目录不存在: {sites_dir}")
        return sites
    
    for file in os.listdir(sites_dir):
        # 只处理 *_crawler.py 文件，排除 __init__.py
        if file.endswith('_crawler.py') and file != '__init__.py':
            module_name = f'sites.{file[:-3]}'
            
            try:
                module = importlib.import_module(module_name)
                
                # 查找以 Crawler 结尾的类
                for attr_name in dir(module):
                    if attr_name.endswith('Crawler'):
                        crawler_class = getattr(module, attr_name)
                        
                        # 检查是否包含 SITE_NAME 元数据
                        if hasattr(crawler_class, 'SITE_NAME'):
                            site_name = crawler_class.SITE_NAME
                            sites[site_name] = crawler_class
                            print(f"已加载站点: {site_name} ({file})")
                            
            except Exception as e:
                print(f"加载 {module_name} 失败: {e}")
    
    return sites


def get_site_crawler_class(site_name):
    """
    获取指定网站的爬虫类
    
    Args:
        site_name (str): 网站名称
        
    Returns:
        class: 爬虫类
        
    Raises:
        ValueError: 如果网站不存在
    """
    sites = discover_sites()
    
    if site_name not in sites:
        available = ', '.join(sites.keys())
        raise ValueError(f"不支持的站点: {site_name}。可用站点: {available}")
    
    return sites[site_name]


def get_all_site_names():
    """
    获取所有可用网站名称列表
    
    Returns:
        list: 网站名称列表
    """
    return list(discover_sites().keys())


def get_sites_requiring_login():
    """
    获取需要登录的网站列表
    
    Returns:
        list: 需要登录的网站名称列表
    """
    sites = discover_sites()
    return [name for name, cls in sites.items() 
            if getattr(cls, 'REQUIRES_LOGIN', False)]


def get_site_config(site_name):
    """
    获取指定网站的配置信息

    Args:
        site_name (str): 网站名称

    Returns:
        dict: 网站配置信息
    """
    crawler_class = get_site_crawler_class(site_name)
    return getattr(crawler_class, 'CONFIG', {})


def get_site_download_mode(site_name):
    """
    获取指定网站的默认下载模式

    Args:
        site_name (str): 网站名称

    Returns:
        str: 下载模式 ('thread_only' 或 'coroutine')，默认 'coroutine'
    """
    config = get_site_config(site_name)
    return config.get('download_mode', 'coroutine')