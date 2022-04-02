from re import U
import requests,time
import hashlib
import urllib
import json
import typing as t
from . import util
from .util import HostPool
import logging
from .constants import LOG_FORMAT, DATE_FORMAT, TIME_OUT
from requests import Response

#日志配置
logging.basicConfig(level=logging.INFO,format=LOG_FORMAT,datefmt=DATE_FORMAT)

import threading

class MediaType:
    '''
    http请求参数类型
    '''
    MULTIPART_FORM_DATA_VALUE = 'multipart/form-data'
    APPLICATION_JSON_VALUE = 'application/json'
    APPLICATION_PROBLEM_JSON_VALUE = 'application/problem+json'
    APPLICATION_FORM_URLENCODED_VALUE = 'application/x-www-form-urlencoded'

    APPLICATION_OCTET_STREAM_VALUE = 'application/octet-stream'
    APPLICATION_PDF_VALUE = 'application/pdf'
    TEXT_HTML_VALUE = 'text/html'
    TEXT_PLAIN_VALUE = 'text/plain'
    IMAGE_PNG_VALUE = 'image/png'



class nacos:
    '''
    nacos客户端实例，用于注册、获取服务列表等和注册中心、配置中心做交互
    '''
    def __init__(self,host="127.0.0.1:8848", username='', password=''):
        # host是ip加端口号，多组用逗号分隔，暂不支持多组
        self.host = host
        self.host_pool = HostPool(host)
        self.username = username
        self.password = password
        self.__threadHealthyDict = {}
        self.__configDict = {}
        self.__registerDict = {}
        self.healthy = ""
        self.accessToken = '' # token
        self.accessTokenInvalidTime = -1 # token失效时间
        if username and password:
            loginData = util.get_access_token(host=self.host_pool, username=username, password=password)
            if loginData:
                self.accessToken = loginData['accessToken']
                self.accessTokenInvalidTime = int(time.time()) + loginData['tokenTtl'] - 10 # 设置10秒偏移量
            else:
                logging.error('nacos认证失败，请检查账号密码是否正确')
                exit(1)
    def __get_host(self):
        '''
        获取请求的地址和端口信息，内部通过循环遍历返回一个可用的地址
        '''
        client = self.host_pool.borrow()
        return client

    def __wrapAuthUrl(self, url = ''):
        '''
        包装请求链接，如果需要认证则会拼接accessToken
        '''
        isAuth = False
        if self.accessToken:
            if time.time() < self.accessTokenInvalidTime:
                isAuth = True
            else:
                loginData = util.get_access_token(host=self.host_pool, username=self.username, password=self.password)
                if loginData:
                    self.accessToken = loginData['accessToken']
                    self.accessTokenInvalidTime = int(time.time()) + loginData['tokenTtl'] - 10 # 设置10秒偏移量
                    isAuth = True
                else:
                    logging.error('nacos认证失败，请检查账号密码是否正确')
                    exit(1)
        token = self.accessToken
        if isAuth:
            return url + '&accessToken=' + token if '?' in url else url + '?accessToken=' + token
        return url

    def __healthyCheckThreadRun(self):
        while True:
            time.sleep(5)
            self.healthy = int(time.time())
            #检查configThread
            try:
                for item in self.__configDict:
                    configMsg = item.split("\001")
                    dataId = configMsg[0]
                    group = configMsg[1]
                    tenant = configMsg[2]
                    x = int(time.time()) - self.__threadHealthyDict[dataId + group + tenant]
                    if (x > 50):
                        md5Content = configMsg[3]
                        myConfig = self.__configDict[item]
                        configThread = threading.Thread(target=self.__configListeningThreadRun,
                                                        args=(dataId, group, tenant, md5Content, myConfig))
                        self.__threadHealthyDict[dataId + group + tenant] = int(time.time())
                        configThread.start()
                        logging.info("配置信息监听线程重启成功: dataId=" + dataId + "; group=" + group + "; tenant=" + tenant)
            except:
                logging.exception("配置信息监听线程健康检查错误",exc_info=True)
            #检查registerThread
            try:
                x = int(time.time()) - self.__registerDict["healthy"]
                if (x > 15):
                    serviceIp = self.__registerDict["serviceIp"]
                    servicePort = self.__registerDict["servicePort"]
                    serviceName = self.__registerDict["serviceName"]
                    namespaceId = self.__registerDict["namespaceId"]
                    groupName = self.__registerDict["groupName"]
                    clusterName = self.__registerDict["clusterName"]
                    ephemeral = self.__registerDict["ephemeral"]
                    metadata = self.__registerDict["metadata"]
                    weight = self.__registerDict["weight"]
                    enabled = self.__registerDict["enabled"]
                    self.registerService(serviceIp,servicePort,serviceName,
                                         namespaceId,groupName,clusterName,
                                         ephemeral,metadata,weight,enabled)
            except:
                logging.exception("服务注册心跳进程健康检查失败",exc_info=True)

    def healthyCheck(self):
        '''
        健康检查
        '''
        t = threading.Thread(target=self.__healthyCheckThreadRun)
        t.start()
        logging.info("健康检查线程已启动")

    def __configListeningThreadRun(self,dataId,group,tenant,md5Content,myConfig):
        getConfigUrl = self.__wrapAuthUrl("http://" + self.__get_host().host + "/nacos/v1/cs/configs")
        params = {
            "dataId": dataId,
            "group": group,
            "tenant": tenant
        }

        licenseConfigUrl = self.__wrapAuthUrl("http://" + self.__get_host().host + "/nacos/v1/cs/configs/listener")
        header = {"Long-Pulling-Timeout": "30000"}
        while True:
            self.__threadHealthyDict[dataId + group + tenant] = int(time.time())
            if (tenant == "public"):
                files = {"Listening-Configs": (None, dataId + "\002" + group + "\002" + md5Content + "\001")}
            else:
                files = {"Listening-Configs": (None, dataId + "\002" + group + "\002" + md5Content + "\002" + tenant + "\001")}
            re = requests.post(licenseConfigUrl, files=files, headers=header, timeout=TIME_OUT)
            if (re.text != ""):
                try:
                    re = requests.get(getConfigUrl, params=params)
                    nacosJson = re.json()
                    md5 = hashlib.md5()
                    md5.update(re.content)
                    md5Content = md5.hexdigest()
                    for item in nacosJson:
                        myConfig[item] = nacosJson[item]
                    logging.info("配置信息更新成功: dataId=" + dataId + "; group=" + group + "; tenant=" + tenant)
                except:
                    logging.exception("配置信息更新失败：dataId=" + dataId + "; group=" + group + "; tenant=" + tenant,
                                      exc_info=True)
                    break

    def config(self,myConfig,dataId,group="DEFAULT_GROUP",tenant="public"):
        logging.info("正在获取配置: dataId="+dataId+"; group="+group+"; tenant="+tenant)
        getConfigUrl = self.__wrapAuthUrl("http://" + self.__get_host().host + "/nacos/v1/cs/configs")
        params = {
            "dataId": dataId,
            "group": group,
            "tenant": tenant
        }
        try:
            re = requests.get(getConfigUrl, params=params)
            nacosJson = re.json()
            md5 = hashlib.md5()
            md5.update(re.content)
            md5Content = md5.hexdigest()

            self.__configDict[dataId+"\001"+group+"\001"+tenant+"\001"+md5Content] = myConfig

            for item in nacosJson:
                myConfig[item] = nacosJson[item]
            logging.info("配置获取成功：dataId="+dataId+"; group="+group+"; tenant="+tenant)
            configThread = threading.Thread(target=self.__configListeningThreadRun,args=(dataId,group,tenant,md5Content,myConfig))
            self.__threadHealthyDict[dataId+group+tenant] = int(time.time())
            configThread.start()
        except Exception:
            logging.exception("配置获取失败：dataId="+dataId+"; group="+group+"; tenant="+tenant, exc_info=True)

    def __registerBeatThreadRun(self,serviceIp,servicePort,serviceName,
                                groupName,namespaceId,metadata,weight):
        beatJson = {
            "ip": serviceIp,
            "port": servicePort,
            "serviceName": serviceName,
            "metadata": metadata,
#            "scheduled": "true",
            "weight": weight
        }
        params_beat = {
            "serviceName": serviceName,
            "groupName": groupName,
            "namespaceId": namespaceId,
            "beat": urllib.request.quote(json.dumps(beatJson))
        }
        # for item in params_beat:
        #     beatUrl = beatUrl + f'&{item}={params_beat[item]}'
        while True:
            self.__registerDict["healthy"] = int(time.time())
            try:
                time.sleep(5)
                re = self.__get_host().beat(accessToken=self.accessToken, params=params_beat)
                if re.status_code != 200 or re.json()['code'] != 10200:
                    self.__registerDict["healthy"] = int(time.time())-10
                    logging.info(re.text)
                    break               
            except json.JSONDecodeError:
                self.__registerDict["healthy"] = int(time.time()) - 10
                break
            except :
                logging.exception("服务心跳维持失败！",exc_info=True)
                break

    def registerService(self,serviceIp,servicePort,serviceName,namespaceId="public",
                        groupName="DEFAULT_GROUP",clusterName="DEFAULT",
                        ephemeral=True,metadata={},weight=1,enabled=True):
        serviceIp = serviceIp or util.get_host_ip()
        self.__registerDict["serviceIp"] = serviceIp
        self.__registerDict["servicePort"] = servicePort
        self.__registerDict["serviceName"] = serviceName
        self.__registerDict["namespaceId"] = namespaceId
        self.__registerDict["groupName"] = groupName
        self.__registerDict["clusterName"] = clusterName
        self.__registerDict["ephemeral"] = ephemeral
        self.__registerDict["metadata"] = metadata
        self.__registerDict["weight"] = weight
        self.__registerDict["enabled"] = enabled

        self.__registerDict["healthy"] = int(time.time())


        registerUrl = self.__wrapAuthUrl("http://" + self.__get_host().host + "/nacos/v1/ns/instance")
        params = {
            "ip": serviceIp,
            "port": servicePort,
            "serviceName": serviceName,
            "namespaceId": namespaceId,
            "groupName": groupName,
            "clusterName": clusterName,
            "ephemeral": ephemeral,
            "metadata": json.dumps(metadata),
            "weight": weight,
            "enabled": enabled
        }
        try:
            re = self.__get_host().regist_service(accessToken=self.accessToken, params=params)
            if re == 'ok':
                logging.info("服务注册成功。")
                beatThread = threading.Thread(target=self.__registerBeatThreadRun,
                    args=(serviceIp,servicePort,serviceName,
                    groupName,namespaceId,metadata,weight))
                beatThread.start()
            else:
                logging.error("服务注册失败 "+re)
        except:
            logging.exception("服务注册失败",exc_info=True)

def fallbackFun():
    return "request Error"
def timeOutFun():
    return "request time out"





class nacosBalanceClient:
    '''
    用于调用其他服务接口
    '''
    def __init__(self,host="127.0.0.1:8848",serviceName="", username='', password='',
                      group="DEFAULT_GROUP",namespaceId="public",timeout=TIME_OUT,
                      fallbackFun=fallbackFun, timeOutFun=timeOutFun):
        self.host = host
        self.host_pool = HostPool(host)
        self.serviceName = serviceName
        self.group = group
        self.namespaceId = namespaceId
        self.__LoadBalanceDict = {}
        self.timeout = timeout or TIME_OUT
        self.fallbackFun = fallbackFun
        self.timeOutFun  = timeOutFun
        self.username = username
        self.password = password
        self.accessToken = '' # token
        self.accessTokenInvalidTime = -1 # token失效时间
        if username and password:
            loginData = util.get_access_token(host=self.host_pool, username=username, password=password)
            if loginData:
                self.accessToken = loginData['accessToken']
                self.accessTokenInvalidTime = int(time.time()) + loginData['tokenTtl'] - 10 # 设置10秒偏移量
            else:
                logging.error('nacos认证失败，请检查账号密码是否正确')
                exit(1)
    def __get_host(self):
        '''
        获取请求的地址和端口信息，内部通过循环遍历返回一个可用的地址
        '''
        client = self.host_pool.borrow()
        return client

    def __wrapAuthUrl(self, url = ''):
        '''
        包装请求链接，如果需要认证则会拼接accessToken
        '''
        isAuth = False
        if self.accessToken:
            if time.time() < self.accessTokenInvalidTime:
                isAuth = True
            else:
                loginData = util.get_access_token(host=self.host_pool, username=self.username, password=self.password)
                if loginData:
                    self.accessToken = loginData['accessToken']
                    self.accessTokenInvalidTime = int(time.time()) + loginData['tokenTtl'] - 10 # 设置10秒偏移量
                    isAuth = True
                else:
                    logging.error('nacos认证失败，请检查账号密码是否正确')
                    exit(1)
        token = self.accessToken
        if isAuth:
            return url + '&accessToken=' + token if '?' in url else url + '?accessToken=' + token
        return url

    def __doRequest(self,method,url,requestParamJson, consumers=MediaType.APPLICATION_JSON_VALUE, produces=MediaType.TEXT_PLAIN_VALUE, *args,**kwargs) :
        method = str.upper(method or 'GET')
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
            logging.debug(f'feign请求接口 {url}')
            resp = requests.get(url, timeout=self.timeout)
        if method == "POST":
            if requestParamJson:
                header = {"Content-type": "application/json;charset=utf-8"}
                data = None
                for item in args:
                    data = item
                resp = requests.post(url,headers=header,data=json.dumps(data,ensure_ascii=False).encode("utf-8"), timeout=self.timeout)
            else:
                files = {}
                for map in args:
                    for key in map:
                        files[key] = (None,map[key])
                resp = requests.post(url,files=files, timeout=self.timeout)
        if method == "PUT":
            if requestParamJson:
                header = {"Content-type": "application/json;charset=utf-8"}
                data = None
                for item in args:
                    data = item
                resp = requests.put(url,headers=header,data=json.dumps(data,ensure_ascii=False).encode("utf-8"), timeout=self.timeout)
            else:
                files = {}
                for map in args:
                    for key in map:
                        files[key] = (None,map[key])
                resp = requests.put(url,files=files, timeout=self.timeout)
        if resp:
            if not produces or produces == MediaType.TEXT_PLAIN_VALUE or produces == MediaType.TEXT_HTML_VALUE:
                return resp.text
            if produces == MediaType.APPLICATION_OCTET_STREAM_VALUE:
                return resp.content
            if produces == MediaType.APPLICATION_JSON_VALUE:
                return resp.json()
        return 'Request Error'


    def __getAddress(self,serviceName,group,namespaceId):
        getProviderUrl = "http://" + self.__get_host().host + "/nacos/v1/ns/instance/list"
        params = {
            "serviceName": serviceName,
            "groupName": group,
            "namespaceId": namespaceId
        }
        getProviderUrl = self.__wrapAuthUrl(getProviderUrl)
        re = requests.get(getProviderUrl, params=params)
        if re.status_code != 200:
            logging.error(f'nacos返回状态码[{re.status_code}], 信息：{re.text}')
            exit(0)
        try:
            msg = re.json()['hosts']
        except json.JSONDecodeError:
            msg = []
        hosts = []
        for item in msg:
            hosts.append({
                'ip': item['ip'],
                'port': item['port'],
                'healthy': item['healthy']
            })
        md5 = hashlib.md5()
        md5.update(json.dumps(hosts,ensure_ascii=False).encode("utf-8"))
        md5Content = md5.hexdigest()
        try:
            oldMd5 = self.__LoadBalanceDict[serviceName + group + namespaceId + "md5"]
        except KeyError:
            self.__LoadBalanceDict[serviceName + group + namespaceId + "md5"] = md5Content
            oldMd5 = ""
        if oldMd5 != md5Content:
            healthyHosts = []
            for host in msg:
                if host['healthy'] == True:
                    healthyHosts.append(host)
            self.__LoadBalanceDict[serviceName + group + namespaceId] = healthyHosts
            self.__LoadBalanceDict[serviceName + group + namespaceId + "index"] = 0

    def __loadBalanceClient(self,serviceName,group,namespaceId):
        try:
            x = int(time.time()) - self.__LoadBalanceDict[serviceName + group + namespaceId + "time"]
        except KeyError:
            x = 11
        if x > 10:
            self.__getAddress(serviceName,group,namespaceId)
            self.__LoadBalanceDict[serviceName + group + namespaceId + "time"] = int(time.time())

        index = self.__LoadBalanceDict[serviceName + group + namespaceId + "index"]
        l = len(self.__LoadBalanceDict[serviceName + group + namespaceId])
        if l == 0:
            logging.error("无可用服务 serviceName: "+serviceName+";group: "+group+";namespaceId: "+namespaceId)
            return ""
        if index >= l:
            self.__LoadBalanceDict[serviceName + group + namespaceId + "index"] = 1
            return self.__LoadBalanceDict[serviceName + group + namespaceId][0]['ip']+":"+str(self.__LoadBalanceDict[serviceName + group + namespaceId][0]['port'])
        else:
            self.__LoadBalanceDict[serviceName + group + namespaceId + "index"] = index + 1
            return  self.__LoadBalanceDict[serviceName + group + namespaceId][index]['ip'] + ":" + str(self.__LoadBalanceDict[serviceName + group + namespaceId][index]['port'])

    def requestMapping(self,method,url,
                            requestParamJson=False,https=False, consumers=MediaType.APPLICATION_JSON_VALUE, produces=MediaType.TEXT_PLAIN_VALUE) -> t.Callable:
        '''
        接口映射配置，同java feign，默认请求参数为json格式，返回结果为文本
        '''
        def decorator(f: t.Callable):
            def mainPro(*args, **kwargs):
                address = self.__loadBalanceClient(self.serviceName, self.group, self.namespaceId)
                if address == "":
                    return
                else:
                    if https:
                        requestUrl = "https://" + address + url
                    else:
                        requestUrl = "http://" + address + url
                    try:
                        return self.__doRequest(method, requestUrl, requestParamJson, consumers=consumers, produces=produces, *args, **kwargs)
                    except requests.ConnectTimeout:
                        logging.exception("链接超时   ",exc_info=True)
                        return self.timeOutFun(self.serviceName,self.group,self.namespaceId,method,url)
                    except Exception as ex:
                        logging.exception("链接失败   ", exc_info=True)
                        return self.fallbackFun(self.serviceName,self.group,self.namespaceId,method,url,ex)
            mainPro.__name__ = f.__name__
            return mainPro
        return decorator
    
    def putMapping(self, **kwargs) -> t.Callable:
        return self.requestMapping(method='PUT', **kwargs)

    def postMapping(self, **kwargs) -> t.Callable:
        return self.requestMapping(method='POST', **kwargs)

    def getMapping(self, **kwargs) -> t.Callable:
        return self.requestMapping(method='GET', **kwargs)

    

