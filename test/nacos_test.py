"""
nacos test
"""
import os
import sys
import time
sys.path.insert(0, os.path.abspath( os.path.join(os.path.dirname(__file__),
    "../src/") ))
from nacos_starter import Nacos



if __name__ == "__main__":
    NACOS_SERVER_ADDR = "127.0.0.1"
    NACOS_USERNAME = "nacos"
    NACOS_PASSWORD = "nacos"
    nacos_server = Nacos(
        host=NACOS_SERVER_ADDR, username=NACOS_USERNAME,
        password=NACOS_PASSWORD)
    nacos_server.register_service(service_ip="1.1.1.1", service_name="service-tag")
    nacos_server.config(app_config={}, env="test")
    nacos_server.healthy_check()
    # 模拟flask启动服务
    while True:
        time.sleep(10)