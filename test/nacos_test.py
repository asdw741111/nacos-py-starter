"""
nacos test
"""
import os
import sys
sys.path.insert(0, os.path.abspath( os.path.join(os.path.dirname(__file__),
    "../src/") ))

from nacos_starter import Nacos


if __name__ == "__main__":
    NACOS_SERVER_ADDR = "62.234.204.235"
    # NACOS_SERVER_ADDR = "115.231.34.84:80"
    NACOS_USERNAME = "nacos"
    NACOS_PASSWORD = "Hlth81l&1"
    nacos_server = Nacos(
        host=NACOS_SERVER_ADDR, username=NACOS_USERNAME,
        password=NACOS_PASSWORD)
    nacos_server.register_service(service_ip="1.1.1.1", service_name="service-tag")
    nacos_server.config(app_config={}, env="test")
    nacos_server.healthy_check()
