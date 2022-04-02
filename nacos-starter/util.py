import socket
from numpy import result_type
import requests
from requests.exceptions import ConnectTimeout
import logging
import time as dt
import json
from requests import Response
from typing import List, Any

# 默认请求超时时间 5秒
DEFAULT_TIMEOUT = 5

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
    # 原始response对象
    ORIGIN_RESPONSE = 'response'


def do_request(method,url, response_type=MediaType.APPLICATION_JSON_VALUE, *args,**kwargs) :
    method = str.upper(method or 'GET')
    resp: Response
    logging.debug('[nacos] 请求 - [%s] - %s', method, url)
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
        logging.debug(f'请求接口 {url}')
        resp = requests.get(url, *args, **kwargs)
    if method == "POST":
        resp = requests.post(url, *args, **kwargs)
    if method == "PUT":
        return requests.put(url, *args, **kwargs)
    if resp:
        try:
            if MediaType.ORIGIN_RESPONSE == response_type:
                return resp
            if not response_type or response_type == MediaType.TEXT_PLAIN_VALUE or response_type == MediaType.TEXT_HTML_VALUE:
                return resp.text
            if response_type == MediaType.APPLICATION_OCTET_STREAM_VALUE:
                return resp.content
            if response_type == MediaType.APPLICATION_JSON_VALUE:
                return resp.json()
        finally:
            resp.close()
    return 'Request Error'


class HostClient:
    '''
    nacos连接客户端，提供基本的操作方法，每个客户端对应一个host地址
    '''
    host = ''
    protocol = 'http'
    # 失败尝试次数
    trys = 5
    is_valid = True

    def __init__(self, host='127.0.0.1:8848', protocol='http', trys=5):
        self.host = host
        self.trys = trys

    def __get_prefix_uri(self): return f'{self.protocol}://{self.host}/nacos/v1'

    def __request(self, uri: str, method: str, data=None, response_type=MediaType.APPLICATION_JSON_VALUE, *args, **kwargs):
        url = self.__get_prefix_uri() + uri
        try:
            return do_request(method=method, url=url, data=data, response_type=response_type, *args, **kwargs)
        except Exception as e:
            self.trys = self.trys - 1
            logging.warn('[Nacos] URL [%s] 请求失败：%s', url, str(e))


    def login(self, username: str, password: str) -> Any:
        '''
        登录
        '''
        data = self.__request('/auth/login', 'post', data={
            'username': username,
            'password': password
        })
        return data

    def regist_service(self, accessToken='', params = {}):
        ''''
        注册服务
        '''
        return self.__request('/ns/instance?accessToken=' + accessToken, 'post', response_type=MediaType.TEXT_PLAIN_VALUE, params=params) or '请求失败'

    def beat(self, accessToken='', params = {}) -> Response:
        '''
        维持心跳
        '''
        uri = '/ns/instance/beat?accessToken=' + accessToken
        for item in params:
            uri = uri + f'&{item}={params[item]}'
        resp = self.__request(uri, 'put', response_type=MediaType.ORIGIN_RESPONSE)
        return resp

class HostPool:
    '''
    host管理器，后续继承接口请求，并对请求错误做标记

    一组ip每次获取下一个，如果网络请求失败会标记次数，次数到了阈值会临时移除，并在一点时间后重新加入
    '''
    idx = 0
    hosts: List[HostClient] = []

    # 失败次数，到达次数后会将ip移动到失败数据中，并且标记失败时间
    __fallback_count = 5
    # 失败后将host放回的间隔
    __fallback_init_sec = 600
    # host和上次失败时间映射
    __fallback_time_dict = {}
    # host和失败次数映射
    __fallback_count_dict = {}
    # 失败恢复时间系数
    __fallback_factor_dict = {}

    def __init__(self, host="127.0.0.1:8848"):
        ar = [str.strip(x) for x in host.split(',')]
        hosts = [x if ':' in x else f'{x}:8848' for x in ar]
        self.hosts = [HostClient(host=x, trys=self.__fallback_count) for x in hosts]
        self.size = len(self.hosts)

    def borrow(self) -> HostClient:
        ''''
        获取一个客户端
        '''
        now = dt.time()
        hosts = []
        for h in self.hosts:
            if h.is_valid and h.trys <= 0:
                h.is_valid = False
                self.__fallback_time_dict[h.host] = now
            elif not h.is_valid:
                fac = dict.get(self.__fallback_factor_dict, h.host, 1)
                if (now - dict.get(self.__fallback_time_dict, h.host, 0)) > fac * self.__fallback_init_sec :
                    h.is_valid = True
                    # 恢复的时候把时间系数加一
                    self.__fallback_factor_dict[h.host] = dict.get(self.__fallback_factor_dict, h.host, 1) + 1
            else:
                hosts.append(h)

        size = len(hosts)
        if not size:
            raise Exception('[Nacos] 没有可用的服务地址')
        i = min(self.idx, size - 1)
        logging.debug('[Nacos] Borrow Client : Total [%s], Now [%s]', size, self.idx)
        try:
            return hosts[i]
        finally:
            self.idx = (i+1) % size
'''
获取本机ip
'''
def get_host_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    return ip
'''
获取登录token

返回数据结果：
  如果成功：{'accessToken': 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJuYWNvcyIsImV4cCI6MTY0Njg5MzYzMH0.5ZeE0htGExkKrnp99sVKetue02obkx7OsJ85rHFMZIY', 'tokenTtl': 18000, 'globalAdmin': True, 'username': 'nacos'}
  如果失败：None
'''
def get_access_token(host:HostPool, username='', password='') -> Any:
    data = None
    try:
        data = host.borrow().login(username=username, password=password)
    except ConnectTimeout as e:
        logging.error('连接超时 %s', str(e))
    except Exception as e:
        logging.error(e)
    return data
