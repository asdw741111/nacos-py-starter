"""
nacos module.
"""
import hashlib
import json
import logging
import threading
import time
import typing as t
import urllib

import requests
import yaml
from requests import Response

from . import util
from .constants import BEAT_TIME, REGISTER_DICT_KEY, TIME_OUT
from .exception import ForbiddenException
from .util import HostPool, logger


def info(msg, *args, **kwargs):
    logger.info("[Nacos] " + msg, *args, **kwargs)

class MediaType:
    """
    http请求参数类型
    """
    MULTIPART_FORM_DATA_VALUE = "multipart/form-data"
    APPLICATION_JSON_VALUE = "application/json"
    APPLICATION_PROBLEM_JSON_VALUE = "application/problem+json"
    APPLICATION_FORM_URLENCODED_VALUE = "application/x-www-form-urlencoded"

    APPLICATION_OCTET_STREAM_VALUE = "application/octet-stream"
    APPLICATION_PDF_VALUE = "application/pdf"
    TEXT_HTML_VALUE = "text/html"
    TEXT_PLAIN_VALUE = "text/plain"
    IMAGE_PNG_VALUE = "image/png"



class Nacos:
    """
    nacos客户端实例，用于注册、获取服务列表等和注册中心、配置中心做交互
    """
    def __init__(self,host="127.0.0.1:8848", username="", password=""):
        # host是ip加端口号，多组用逗号分隔，暂不支持多组
        self.host = host
        self.host_pool = HostPool(host)
        self.username = username
        self.password = password
        self._thread_healthy_dict = {}
        self._config_dict = {}
        self._register_dict = {}
        self.healthy = ""
        self.access_token = "" # token
        self.access_token_invalid_time = -1 # token失效时间
        if username and password:
            login_data = util.get_access_token(
                host=self.host_pool, username=username, password=password)
            if login_data:
                self.access_token = login_data["accessToken"]
                vt = int(time.time()) + login_data["tokenTtl"] - 10 # 设置10秒偏移量
                self.access_token_invalid_time = vt
            else:
                logging.error("nacos认证失败，请检查账号密码是否正确")
                exit(1)
    def __get_host(self):
        """
        获取请求的地址和端口信息，内部通过循环遍历返回一个可用的地址

        Returns
        -------
        nacos客户端
        """
        client = self.host_pool.borrow()
        return client

    def __refresh_token(self):
        """刷新token
        """
        login_data = util.get_access_token(
            host=self.host_pool,
            username=self.username, password=self.password)
        if login_data:
            self.access_token = login_data["accessToken"]
            self.access_token_invalid_time = (int(time.time()) +
                login_data["tokenTtl"] - 10) # 设置10秒偏移量
            return self.access_token
        else:
            logger.error("nacos认证失败，请检查账号密码是否正确")
            exit(1)

    def __get_token(self):
        """检查并获取token
        """
        if self.access_token:
            if time.time() < self.access_token_invalid_time:
                return self.access_token
            else:
                return self.__refresh_token()
        return self.__refresh_token()

    def __wrap_auth_url(self, url = ""):
        """
        包装请求链接，如果需要认证则会拼接accessToken
        """
        token = self.__get_token()
        if token:
            return (url + "&accessToken=" +
                token if "?" in url else url + "?accessToken=" + token)
        return url

    def __healthy_check_thread_run(self):
        """启动健康检查

        register_service注册服务以及config获取配置后，这两个方法会分别启动线程维持心跳,
        本方法用于做异常处理，多次心跳失败后会重新进行注册和配置获取
        """
        while True:
            time.sleep(5)
            self.healthy = int(time.time())
            #检查configThread
            try:
                for item in self._config_dict:
                    config_msg = item.split("\001")
                    data_id = config_msg[0]
                    group = config_msg[1]
                    tenant = config_msg[2]
                    ht = self._thread_healthy_dict[data_id + group + tenant]
                    x = int(time.time()) - ht
                    if x > 50 and self.config_thread is None:
                        md5_content = config_msg[3]
                        app_config = self._config_dict[item]
                        self.config_thread = threading.Thread(
                            target=self.__config_listening_thread_run,
                            args=(data_id, group, tenant,
                            md5_content, app_config))
                        hk = data_id + group + tenant
                        self._thread_healthy_dict[hk] = int(time.time())
                        self.config_thread.start()
                        logger.info(
                            "配置信息监听线程重启成功: dataId=%s; group=%s; tenant=%s",
                            data_id, group, tenant)
            except Exception:
                logger.exception("配置信息监听线程健康检查错误",exc_info=True)
            # 检查registerThread
            try:
                x = int(time.time()) - self._register_dict["healthy"]
                if x > 15:
                    service_ip = self._register_dict["serviceIp"]
                    service_port = self._register_dict["servicePort"]
                    service_name = self._register_dict["serviceName"]
                    namespace_id = self._register_dict["namespaceId"]
                    group_name = self._register_dict["groupName"]
                    cluster_name = self._register_dict["clusterName"]
                    ephemeral = self._register_dict["ephemeral"]
                    metadata = self._register_dict["metadata"]
                    weight = self._register_dict["weight"]
                    enabled = self._register_dict["enabled"]
                    self.register_service(service_ip,service_name,service_port,
                                         namespace_id,group_name,cluster_name,
                                         ephemeral,metadata,weight,enabled)
            except Exception:
                logger.exception("服务注册心跳进程健康检查失败",exc_info=True)

    def healthy_check(self):
        """健康检查
        """
        th = threading.Thread(target=self.__healthy_check_thread_run)
        th.start()
        logger.info("健康检查线程已启动")

    def __config_listening_thread_run(self,
        data_id,group,tenant,md5_content,app_config):
        """监听配置修改

        Args:
            dataId: str 服务id
            group: str
            group，默认 DEFAULT_GROUP
            tenant: str 租户
            md5Content: str 内容md5，用于快速比较是否配置有修改
            myConfig: dict 应用当前配置字典
        """
        params = {
            "dataId": data_id,
            "group": group,
            "tenant": tenant
        }

        # 设置长连接30秒，接口会在30秒后返回结果
        header = {"Long-Pulling-Timeout": "30000"}
        dk = data_id + group + tenant
        while True:
            try:
                time.sleep(BEAT_TIME)
            except Exception:
                break
            if not self.config_thread:
                break
            # URL
            get_config_url = self.__wrap_auth_url("http://" +
                self.__get_host().host + "/nacos/v1/cs/configs")
            license_config_url = self.__wrap_auth_url(
                "http://" + self.__get_host().host +
                "/nacos/v1/cs/configs/listener")
            self._thread_healthy_dict[dk] = int(time.time())
            if tenant == "public":
                lck = data_id + "\002" + group + "\002" + md5_content + "\001"
            else:
                lck = "{}\002{}\002{}\002{}\001".format(
                    data_id, group, md5_content, tenant)
            re = requests.post(
                license_config_url,
                data={"Listening-Configs": lck},
                timeout=50,
                headers=header)
            if re.status_code == 403:
                # relogin
                info("获取配置token失效, 准备重新获取")
                self.__refresh_token()
            elif re.status_code == 200:
                if re.text != "":
                    try:
                        re = requests.get(get_config_url, params=params)
                        info("获取更新配置内容为\n%s", re.text)
                        nacos_json = self.__get_config_dict(re.text)
                        md5 = hashlib.md5()
                        md5.update(re.content)
                        md5_content = md5.hexdigest()
                        for item in nacos_json:
                            app_config[item] = nacos_json[item]
                        info(
                            "配置信息更新成功: dataId=%s; group=%s; tenant=%s",
                                data_id, group, tenant)
                    except Exception:
                        logger.exception(
                            "配置信息更新失败：dataId=" + data_id + "; group=" +
                            group + "; tenant=" + tenant,
                            exc_info=True)
                        self.config_thread = None
                        break
            else:
                info("获取配置失败终止监听,status_code-%s, message-%s",
                    re.status_code, re.text)
                break
    def __get_data_id(self, env="",file_type="yaml"):
        """获取dataId，用于定位到nacos配置文件
        """
        if env:
            env = "-" + env
        return "{}{}.{}".format(self._register_dict["serviceName"],
            env, file_type)

    def __get_config_dict(self, content: str, file_type="yaml"):
        """获取配置信息转换为字典

        Args:
          content: 内容
          type: 配置类型
        """
        try:
            if file_type == "yaml":
                return yaml.load(content, Loader=yaml.Loader)
            if file_type == "json":
                return json.loads(content)
        except Exception:
            return {}

    def config(self,app_config,env="",file_type="yaml",
        group="DEFAULT_GROUP",tenant="public"):
        """开始执行配置读取

        Args:
          app_config: 应用配置字典
          env: 环境，用于拼接data_id，生成格式为：SERVICE_NAME-env.file_type
          file_type: 文件类型，对应nacos可配置的文件类型，例如json、text、yaml等，默认yaml
          group: group，和nacos中配置对应，默认 DEFAULT_GROUP
          tenant: 租户，和nacos中配置对应，默认 public
        """
        data_id = self.__get_data_id(env=env, file_type=file_type)
        logger.info("正在获取配置: dataId="+
            data_id+"; group="+group+"; tenant="+tenant)
        get_config_url = self.__wrap_auth_url(
            "http://" + self.__get_host().host + "/nacos/v1/cs/configs")
        params = {
            "dataId": data_id,
            "group": group,
            "tenant": tenant
        }
        try:
            re = requests.get(get_config_url, params=params)
            if re.status_code != 200:
                logger.warning("配置获取失败：dataId="+
                    data_id+"; group="+group+"; tenant="+tenant)
                return
            logging.info("[Nacos] config: %s", re.text)
            nacos_json = self.__get_config_dict(re.text, file_type=file_type)
            md5 = hashlib.md5()
            md5.update(re.content)
            md5_content = md5.hexdigest()
            dk = data_id+"\001"+group+"\001"+tenant+"\001"+md5_content
            self._config_dict[dk] = app_config

            for item in nacos_json:
                app_config[item] = nacos_json[item]
            logger.info("配置获取成功：dataId=%s; group=%s; tenant=%s",
                data_id, group, tenant)
            self.config_thread = threading.Thread(
                target=self.__config_listening_thread_run,
                args=(data_id,group,tenant,md5_content,app_config))
            self._thread_healthy_dict[data_id+group+tenant] = int(time.time())
            self.config_thread.start()
        except Exception:
            logger.exception("配置获取失败：dataId="+
                data_id+"; group="+group+"; tenant="+tenant, exc_info=True)

    def __register_beat_thread_run(self,service_ip,service_port,service_name,
                                group_name,namespace_id,metadata,weight):
        """"
        注册心跳检测
        """
        beat_json = {
            "ip": service_ip,
            "port": service_port,
            "serviceName": service_name,
            "metadata": metadata,
#            "scheduled": "true",
            "weight": weight
        }
        params_beat = {
            "serviceName": service_name,
            "groupName": group_name,
            "namespaceId": namespace_id,
            "beat": urllib.request.quote(json.dumps(beat_json))
        }

        while True:
            self._register_dict[REGISTER_DICT_KEY] = int(time.time())
            try:
                time.sleep(BEAT_TIME)
                re = self.__get_host().beat(
                    access_token=self.access_token, params=params_beat)
                if (re is None or re.status_code != 200
                    or re.json()["code"] != 10200):
                    self._register_dict[REGISTER_DICT_KEY] = int(time.time())-10
                    logger.warning("[Nacos] 心跳请求失败: %s", (re and re.text))

                if re is not None and re.status_code == 403:
                    self.__refresh_token()
                    logger.info("[Nacos] 重新刷新token结果: %s", self.access_token)
            except json.JSONDecodeError:
                self._register_dict[REGISTER_DICT_KEY] = int(time.time()) - 10
                break
            except Exception:
                logger.exception("服务心跳维持失败！", exc_info=True)
                break

    def register_service(self,service_ip,
                        service_name,service_port=80,namespace_id="public",
                        group_name="DEFAULT_GROUP",cluster_name="DEFAULT",
                        ephemeral=True,metadata=None,weight=1,enabled=True):
        """注册服务

        将当前服务注册到nacos

        Args:
          service_ip: 当前服务的ip，会注册到nacos被其他服务来调用
          service_name: 服务名称
          service_port: 当前服务的端口号，用于被其他服务调用
          namespace_id: 命名空间，默认 public
          group_name: 注册的group 默认 DEFAULT_GROUP
          cluster_name: nacos集群名称，默认 DEFAULT
          ephemeral: 默认True
          metadata: 注册到nacos时携带的元数据
          weight: 权重 默认1
          enabled: 是否启用 默认True
        """
        service_ip = service_ip or util.get_host_ip()
        self._register_dict["serviceIp"] = service_ip
        self._register_dict["servicePort"] = service_port
        self._register_dict["serviceName"] = service_name
        self._register_dict["namespaceId"] = namespace_id
        self._register_dict["groupName"] = group_name
        self._register_dict["clusterName"] = cluster_name
        self._register_dict["ephemeral"] = ephemeral
        self._register_dict["metadata"] = metadata or {}
        self._register_dict["weight"] = weight
        self._register_dict["enabled"] = enabled

        self._register_dict["healthy"] = int(time.time())

        params = {
            "ip": service_ip,
            "port": service_port,
            "serviceName": service_name,
            "namespaceId": namespace_id,
            "groupName": group_name,
            "clusterName": cluster_name,
            "ephemeral": ephemeral,
            "metadata": json.dumps(metadata),
            "weight": weight,
            "enabled": enabled
        }
        try:
            re = self.__get_host().regist_service(
                access_token=self.access_token, params=params)
            if re == "ok":
                logger.info("服务注册成功。")
                beat_thread = threading.Thread(
                    target=self.__register_beat_thread_run,
                    args=(service_ip,service_port,service_name,
                    group_name,namespace_id,metadata,weight))
                beat_thread.start()
            else:
                logger.error("服务注册失败 %s", re)
        except ForbiddenException:
            self.__refresh_token()
        except Exception:
            logger.exception("服务注册失败",exc_info=True)

def default_fallback_fun():
    return "request Error"
def default_time_out_fun():
    return "request time out"





class NacosBalanceClient:
    """
    用于调用其他服务接口
    """
    def __init__(self,host="127.0.0.1:8848",service_name="", username="",
        password="",
        group="DEFAULT_GROUP",namespace_id="public",timeout=TIME_OUT,
        fallback_fun=default_fallback_fun, time_out_fun=default_time_out_fun):
        self.host = host
        self.host_pool = HostPool(host)
        self.service_name = service_name
        self.group = group
        self.namespace_id = namespace_id
        self._load_balance_dict = {}
        self.timeout = timeout or TIME_OUT
        self.fallback_fun = fallback_fun
        self.time_out_fun  = time_out_fun
        self.username = username
        self.password = password
        self.access_token = "" # token
        self.access_token_invalid_time = -1 # token失效时间
        if username and password:
            login_data = util.get_access_token(host=self.host_pool,
                username=username, password=password)
            if login_data:
                self.access_token = login_data["accessToken"]
                it = login_data["tokenTtl"] - 10 # 设置10秒偏移量
                self.access_token_invalid_time = int(time.time()) + it
            else:
                logger.error("nacos认证失败，请检查账号密码是否正确")
                exit(1)
    def __get_host(self):
        """
        获取请求的地址和端口信息，内部通过循环遍历返回一个可用的地址
        """
        client = self.host_pool.borrow()
        return client

    def __refresh_token(self):
        """刷新token
        """
        login_data = util.get_access_token(
            host=self.host_pool,
            username=self.username, password=self.password)
        if login_data:
            self.access_token = login_data["accessToken"]
            self.access_token_invalid_time = (int(time.time()) +
                login_data["tokenTtl"] - 10) # 设置10秒偏移量
            return self.access_token
        else:
            logger.error("nacos认证失败，请检查账号密码是否正确")
            exit(1)

    def __get_token(self):
        """检查并获取token
        """
        if self.access_token:
            if time.time() < self.access_token_invalid_time:
                return self.access_token
            else:
                return self.__refresh_token()
        return self.__refresh_token()


    def __wrap_auth_url(self, url = ""):
        """
        包装请求链接，如果需要认证则会拼接accessToken
        """
        token = self.__get_token()

        if token:
            return (url + "&accessToken=" +
                token if "?" in url else url + "?accessToken=" + token)
        return url

    def __do_request(self,
        method,url,request_param_json,
        *args,
        produces=MediaType.TEXT_PLAIN_VALUE,
        **kwargs) :
        method = str.upper(method or "GET")
        resp: Response
        if method == "GET":
            url = url + "/"
            for item in args:
                url = url + str(item) + "/"
            url = url[:-1]
            if kwargs.__len__() != 0:
                url = url + "?"
                for item in kwargs:
                    url = url + str(item) + "=" + str(kwargs[item]) + "&"
                url = url[:-1]
            logger.debug("feign请求接口 %s", url)
            resp = requests.get(url, timeout=self.timeout)
        if method == "POST":
            if request_param_json:
                header = {"Content-type": "application/json;charset=utf-8"}
                data = None
                for item in args:
                    data = item
                resp = requests.post(url,headers=header,
                    data=json.dumps(data,ensure_ascii=False).encode("utf-8"),
                    timeout=self.timeout)
            else:
                files = {}
                for arg in args:
                    for key in arg:
                        files[key] = (None,arg[key])
                resp = requests.post(url,files=files, timeout=self.timeout)
        if method == "PUT":
            if request_param_json:
                header = {"Content-type": "application/json;charset=utf-8"}
                data = None
                for item in args:
                    data = item
                resp = requests.put(url,headers=header,
                    data=json.dumps(data,ensure_ascii=False).encode("utf-8"),
                    timeout=self.timeout)
            else:
                files = {}
                for arg in args:
                    for key in arg:
                        files[key] = (None,arg[key])
                resp = requests.put(url,files=files, timeout=self.timeout)
        if resp:
            if resp.status_code == 403:
                self.__refresh_token()
                return "Token forbidden, refreshed now"
            if (not produces or produces == MediaType.TEXT_PLAIN_VALUE
                or produces == MediaType.TEXT_HTML_VALUE):
                return resp.text
            if produces == MediaType.APPLICATION_OCTET_STREAM_VALUE:
                return resp.content
            if produces == MediaType.APPLICATION_JSON_VALUE:
                return resp.json()
        return "Request Error"


    def __get_address(self,service_name,group,namespace_id):
        get_provider_url = ("http://" + self.__get_host().host +
            "/nacos/v1/ns/instance/list")
        params = {
            "serviceName": service_name,
            "groupName": group,
            "namespaceId": namespace_id
        }
        get_provider_url = self.__wrap_auth_url(get_provider_url)
        re = requests.get(get_provider_url, params=params)
        if re.status_code != 200:
            logger.error("nacos返回状态码[%s], 信息：%s", re.status_code, re.text)
            exit(0)
        try:
            msg = re.json()["hosts"]
        except json.JSONDecodeError:
            msg = []
        hosts = []
        for item in msg:
            hosts.append({
                "ip": item["ip"],
                "port": item["port"],
                "healthy": item["healthy"]
            })
        md5 = hashlib.md5()
        md5.update(json.dumps(hosts,ensure_ascii=False).encode("utf-8"))
        md5_content = md5.hexdigest()
        try:
            old_md5 = self._load_balance_dict[
                service_name + group + namespace_id + "md5"]
        except KeyError:
            self._load_balance_dict[
                service_name + group + namespace_id + "md5"] = md5_content
            old_md5 = ""
        if old_md5 != md5_content:
            healthy_hosts = []
            for host in msg:
                if host["healthy"] is True:
                    healthy_hosts.append(host)
            self._load_balance_dict[
                service_name + group + namespace_id] = healthy_hosts
            self._load_balance_dict[
                service_name + group + namespace_id + "index"] = 0

    def __load_balance_client(self,service_name,group,namespace_id):
        try:
            x = int(time.time()) - self._load_balance_dict[
                service_name + group + namespace_id + "time"]
        except KeyError:
            x = 11
        if x > 10:
            self.__get_address(service_name,group,namespace_id)
            self._load_balance_dict[
                service_name + group + namespace_id + "time"] = int(time.time())

        index = self._load_balance_dict[
            service_name + group + namespace_id + "index"]
        l = len(self._load_balance_dict[service_name + group + namespace_id])
        if l == 0:
            logger.error("无可用服务 serviceName: %s;group: %s;namespaceId: %s",
                service_name, group, namespace_id)
            return ""
        if index >= l:
            ip = str(self._load_balance_dict[
                service_name + group + namespace_id][0]["port"])
            self._load_balance_dict[
                service_name + group + namespace_id + "index"] = 1
            return self._load_balance_dict[
                service_name + group + namespace_id][0]["ip"]+":"+ip
        else:
            self._load_balance_dict[
                service_name + group + namespace_id + "index"] = index + 1
            ip = str(self._load_balance_dict[
                service_name + group + namespace_id][index]["port"])
            return  self._load_balance_dict[
                service_name + group + namespace_id][index]["ip"] + ":" + ip

    def request_mapping(self,method,url,
                            request_param_json=False,https=False,
                            consumers=MediaType.APPLICATION_JSON_VALUE,
                            produces=MediaType.TEXT_PLAIN_VALUE) -> t.Callable:
        """
        接口映射配置，同java feign，默认请求参数为json格式，返回结果为文本
        """
        def decorator(f: t.Callable):
            def main_pro(*args, **kwargs):
                address = self.__load_balance_client(
                    self.service_name, self.group, self.namespace_id)
                if address == "":
                    return
                else:
                    if https:
                        request_url = "https://" + address + url
                    else:
                        request_url = "http://" + address + url
                    try:
                        return self.__do_request(
                            method, request_url, request_param_json,
                            consumers=consumers, produces=produces,
                            *args, **kwargs)
                    except requests.ConnectTimeout:
                        logger.exception("链接超时   ",exc_info=True)
                        return self.time_out_fun(self.service_name,
                            self.group,self.namespace_id,method,url)
                    except Exception as ex:
                        logger.exception("链接失败   ", exc_info=True)
                        return self.fallback_fun(self.service_name,
                            self.group,self.namespace_id,method,url,ex)
            main_pro.__name__ = f.__name__
            return main_pro
        return decorator

    def put_mapping(self, **kwargs) -> t.Callable:
        return self.request_mapping(method="PUT", **kwargs)

    def post_mapping(self, **kwargs) -> t.Callable:
        return self.request_mapping(method="POST", **kwargs)

    def get_mapping(self, **kwargs) -> t.Callable:
        return self.request_mapping(method="GET", **kwargs)
