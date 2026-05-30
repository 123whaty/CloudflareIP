import socket
import re
import time
import threading
import random
import ipaddress
from queue import Queue
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Cloudflare节点测试配置参数
TEST_TIMEOUT = 3       # 测试超时时间(秒)
TEST_PORT = 443        # 测试端口
MAX_THREADS = 3        # 最大线程数
TOP_NODES = 30         # 显示和保存前N个最快节点
TXT_OUTPUT_FILE = "DE.txt"    # TXT结果保存文件
SAMPLES_PER_RANGE = 20 # 每个IP段随机抽取的IP数量

# 国家代码到中文国家名称的映射
COUNTRY_CODES = {
    'US': '美国',
    'CN': '中国',
    'JP': '日本',
    'SG': '新加坡',
    'KR': '韩国',
    'GB': '英国',
    'FR': '法国',
    'DE': '德国',
    'AU': '澳大利亚',
    'CA': '加拿大',
    'HK': '中国香港',
    'TW': '中国台湾',
    'IN': '印度',
    'RU': '俄罗斯',
    'BR': '巴西',
    'MX': '墨西哥',
    'NL': '荷兰',
    'SE': '瑞典',
    'CH': '瑞士',
    'IT': '意大利',
    'ES': '西班牙',
    'Unknown': '未知'
}

def get_ip_country(ip):
    """获取IP地址对应的国家信息(返回中文)"""
    try:
        socket.inet_aton(ip)
        import requests
        session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)

        # 尝试 ipwhois.app
        try:
            url = f"https://ipwhois.app/json/{ip}"
            response = session.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if 'country' in data and data['country']:
                    country = data['country']
                    if country == 'United States':
                        return '美国'
                    elif country == 'China':
                        return '中国'
                    elif country == 'Japan':
                        return '日本'
                    elif country == 'Singapore':
                        return '新加坡'
                    elif country == 'South Korea':
                        return '韩国'
                    elif country == 'United Kingdom':
                        return '英国'
                    elif country == 'France':
                        return '法国'
                    elif country == 'Germany':
                        return '德国'
                    elif country == 'Australia':
                        return '澳大利亚'
                    elif country == 'Canada':
                        return '加拿大'
                    elif country == 'Hong Kong':
                        return '中国香港'
                    elif country == 'Taiwan':
                        return '中国台湾'
                    elif len(country) == 2:
                        return COUNTRY_CODES.get(country, country)
                    return country
        except Exception as e:
            print(f"ipwhois.app错误 {ip}: {str(e)}")

        # 尝试 ip-api.com
        try:
            url = f"http://ip-api.com/json/{ip}?fields=countryCode"
            response = session.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success' and 'countryCode' in data:
                    country_code = data['countryCode']
                    return COUNTRY_CODES.get(country_code, country_code)
        except Exception as e:
            print(f"ip-api.com错误 {ip}: {str(e)}")

        # 基于Cloudflare常见IP段的简单判断
        octets = ip.split('.')
        if octets[0] == '104' and octets[1] == '18':
            return '美国'
        elif octets[0] == '108' and octets[1] == '162':
            return '美国'
        elif octets[0] == '162' and octets[1] == '159':
            return '美国'
        elif octets[0] == '172' and octets[1] == '64':
            return '美国'
        return '未知'
    except Exception as e:
        print(f"IP验证错误 {ip}: {str(e)}")
        return '未知'

def clean_ip(ip_str):
    """清理IP字符串，移除可能的冒号或其他字符"""
    ip_str = ip_str.strip().rstrip(':')
    pattern = r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$'
    if re.match(pattern, ip_str):
        parts = ip_str.split('.')
        if all(0 <= int(part) <= 255 for part in parts):
            return ip_str
    return None

class CloudflareNodeTester:
    def __init__(self):
        self.nodes = set()      # 使用集合避免重复
        self.results = []
        self.lock = threading.Lock()

    def fetch_known_nodes(self, samples_per_range=SAMPLES_PER_RANGE):
        """
        从公开的Cloudflare IP段中随机抽取IP地址
        :param samples_per_range: 每个网段抽取的IP数量
        """
        ip_ranges = [
            "188.114.96.0/20",
            "104.21.0.0/24",
            "104.24.0.0/24",
            "104.25.0.0/24",
            "104.27.0.0/24",
            "104.26.0.0/24"
        ]

        for ip_range in ip_ranges:
            network = ipaddress.IPv4Network(ip_range, strict=False)
            all_hosts = list(network.hosts())      # 获取该网段所有可用主机地址
            k = min(samples_per_range, len(all_hosts))
            selected_hosts = random.sample(all_hosts, k)
            for host in selected_hosts:
                self.nodes.add(str(host))

        print(f"已从 {len(ip_ranges)} 个网段随机抽取了 {len(self.nodes)} 个IP地址")

    def test_node_speed(self, ip):
        """测试单个节点的连接速度"""
        try:
            start_time = time.time()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(TEST_TIMEOUT)
                result = s.connect_ex((ip, TEST_PORT))
                if result == 0:
                    response_time = (time.time() - start_time) * 1000
                    return {
                        'ip': ip,
                        'reachable': True,
                        'response_time_ms': int(response_time),
                        'timestamp': datetime.now().isoformat()
                    }
                else:
                    return {
                        'ip': ip,
                        'reachable': False,
                        'response_time_ms': None,
                        'timestamp': datetime.now().isoformat()
                    }
        except Exception as e:
            return {
                'ip': ip,
                'reachable': False,
                'response_time_ms': None,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

    def worker(self, queue):
        """线程工作函数"""
        while not queue.empty():
            ip = queue.get()
            try:
                result = self.test_node_speed(ip)
                with self.lock:
                    self.results.append(result)
                    if len(self.results) % 50 == 0:
                        print(f"已测试 {len(self.results)}/{len(self.nodes)} 个")
            finally:
                queue.task_done()

    def test_all_nodes(self):
        """测试所有节点的速度"""
        queue = Queue()
        for ip in self.nodes:
            queue.put(ip)

        threads = []
        for _ in range(min(MAX_THREADS, len(self.nodes))):
            thread = threading.Thread(target=self.worker, args=(queue,))
            thread.start()
            threads.append(thread)

        for thread in threads:
            thread.join()

    def sort_and_display_results(self):
        """排序并显示测试结果，包含中文国家信息"""
        reachable_nodes = [
            node for node in self.results
            if node['reachable'] and node['response_time_ms'] is not None
        ]
        sorted_nodes = sorted(reachable_nodes, key=lambda x: x['response_time_ms'])

        for i, node in enumerate(sorted_nodes[:TOP_NODES], 1):
            country = get_ip_country(node['ip'])
            print(f"{node['ip']}#de 【德国】 DE")

        return sorted_nodes

    def save_results(self, results):
        """只保存前N个最快节点到TXT文件"""
        try:
            top_results = results[:TOP_NODES]
            with open(TXT_OUTPUT_FILE, 'w', encoding='utf-8') as f:
                for node in top_results:
                    country = get_ip_country(node['ip'])
                    line = f"{node['ip']}#de 【德国】 DE\n"
                    f.write(line)
            print(f"结果已保存到 {TXT_OUTPUT_FILE} (前{TOP_NODES}个节点)")
        except Exception as e:
            print(f"保存结果失败: {e}")

    def run(self):
        """运行完整的测试流程"""
        start_time = time.time()
        print("开始获取节点...")
        self.fetch_known_nodes()

        print("开始速度测试...")
        self.test_all_nodes()

        print("正在排序并生成结果...")
        sorted_nodes = self.sort_and_display_results()

        self.save_results(sorted_nodes)
        total_time = int(time.time() - start_time)
        print(f"全部完成，耗时 {total_time} 秒")

if __name__ == "__main__":
    try:
        tester = CloudflareNodeTester()
        tester.run()
    except KeyboardInterrupt:
        print("\n用户中断了程序")
    except Exception as e:
        print(f"程序出错: {e}")
