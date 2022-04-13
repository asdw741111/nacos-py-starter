# nacos sdk for python

用户接入nacos，进行注册、配置获取等。基于nacos的web接口实现操作。

支持nacos版本
- 1.4
- 2.0

## 使用
### 注册到nacos
```python
from nacos_starter import Nacos

# 创建初始nacos连接对象
nacos_server = Nacos(host=NACOS_SERVER_ADDR, username=NACOS_USERNAME, password=NACOS_PASSWORD)

# 配置服务注册的参数
nacos_server.register_service(service_ip=NACOS_IP,service_port=NACOS_SERVER_PORT,service_name=SERVER_NAME)

# 开启监听配置的线程和服务注册心跳进程的健康检查进程
nacos_server.healthy_check()


#### 如果在flask环境启用远程配置，建议如下用法：
flask_env = {}
# 将本地配置注入到nacos对象中即可获取远程配置，并监听配置变化实时变更
nacos_server.config(env="test",app_config=flask_env)
for item in flask_env:
  app.config[item] = flask_env[item]

"""
参数说明：
  service_ip: 本机ip，用于让其他服务调用自己，如果是docker启动或者有内外网ip需要手动指定，否则自动获取本机ip
  service_port: 指定本服务端口号
  service_name: 本服务名称，用于注册到nacos以及让其他服务调用自己
  env: 远程配置时用于区分环境，例如service-a-test.yaml，表示test环境，也可以不指定
  app_config: 用于指定要接收的配置变量，字典类型，读取的远程配置会放到这里
"""
```
### TODO
- 简化配置
- 基于flask插件快速集成