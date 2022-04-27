"""
nacos test
"""
import os
import sys
sys.path.insert(0, os.path.abspath( os.path.join(os.path.dirname(__file__),
    "../src/") ))

from nacos_starter import Nacos


if __name__ == "__main__":
    NACOS_SERVER_ADDR = "1.2.3.4"
    NACOS_USERNAME = "nacos"
    NACOS_PASSWORD = "123"
    nacos_server = Nacos(
        host=NACOS_SERVER_ADDR, username=NACOS_USERNAME,
        password=NACOS_PASSWORD)
    nacos_server.register_service(service_ip="1.1.1.1", service_name="ss-name")
    nacos_server.healthy_check()
