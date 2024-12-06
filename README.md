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

## 如果只注册上去不想让别的服务调用，例如本地开发的时候，可以在register_service中加入enabled=False，默认会注册上去被别的服务发现

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

### 调用其他服务
新建一个文件，例如`file_feign.py`
```python
from nacos_starter import NacosBalanceClient

# 定义失败回调
def error_fun(*args):
    for item in args:
        print(item)
    return "自定义错误"

# 新建客户端实例
nacos_client = NacosBalanceClient(host=NACOS_SERVER_ADDR,
                                       service_name="service-file", username=NACOS_USERNAME, password=NACOS_PASSWORD,
                                       timeout=3)

@nacos_client.put_mapping(url="/api/file/upload")
def upload():
    pass

@nacos_client.request_mapping(method="GET", url="/api/file/get", consumers = MediaType.APPLICATION_PROBLEM_JSON_VALUE, produces = MediaType.APPLICATION_OCTET_STREAM_VALUE)
def get(type: str = 'public', fileName: str = ''):
    pass


@nacos_client.post_mapping(url="/demo/test3")
def apiTest3(formData):
    pass


@nacos_client.request_mapping(method="POST", url="/demo/test4", request_param_json=True)
def apiTest4(jsonData):
    pass

@nacos_client.request_mapping(method="GET", url="/demo/test5")
def apiTest5(*args,**kwargs):
    pass
```

使用
```python
import file_feign

file_feign.get('dns', '/a/b/c/a.png')
```

### 熔断和流控
熔断控制通过在flask接口位置加入装饰器来达到熔断，使用方法：
```python
import nacos_starter.func_fuse as funcFuse
from flask import Blueprint

SimpleFuncFuse1 = funcFuse.DegradeRule()

bp = Blueprint('api', __name__, url_prefix='/api')

@bp.route("/test1", methods=['GET'])
@SimpleFuncFuse1.hystrix(timeout=2)
def fuseTest1():#超时返回自定义超时错误返回函数
    time.sleep(3)
    return "ok"
```
### TODO
- 简化配置
- 基于flask插件快速集成