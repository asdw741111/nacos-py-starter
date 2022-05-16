"""
decorator for service client, same as feign.
"""
import ctypes
import inspect
import threading
import time

from .util import logger


def default_fall_back_func(*args, **kwargs):
    return ("function fallback " +
        "  function info: " + str(args) + " " + str(kwargs))


def default_timeout_fallback_func(ex, *args, **kwargs):
    # raise ex
    return (
        "function time out "
        + str(ex)
        + "  function info: "
        + str(args)
        + " "
        + str(kwargs)
    )


def default_except_fallback_func(ex, *args, **kwargs):
    # raise ex
    logger.error("fallback %s fun info: %s %s", ex, args, kwargs)
    return (
        "function except "
        + str(ex)
        + "  function info: "
        + str(args)
        + " "
        + str(kwargs)
    )


class FuncFuse(object):
    """请求接口装饰器，用于配置一个要请求的服务接口"""

    def __init__(
        self,
        fallback_func=default_fall_back_func,
        timeout_fallback_Func=default_timeout_fallback_func,
        except_fallback_func=default_except_fallback_func,
    ):
        self._func_time = {}
        self.fallback_func = fallback_func  # 熔断回调函数
        self.timeout_fallback_func = timeout_fallback_Func  # 未触发熔断时 超时响应的回调函数
        self.except_fallback_func = except_fallback_func  # 未触发熔断时 异常响应的回调函数
        self._func_fuse = {}  # 存放熔断信息
        self.__kwargs = None
        self.__args = None

    def __async_raise(self, tid, exctype=SystemExit):
        """raises the exception, performs cleanup if needed"""
        tid = ctypes.c_long(tid)
        if not inspect.isclass(exctype):
            exctype = type(exctype)
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(tid,
            ctypes.py_object(exctype))
        if res == 0:
            raise ValueError("invalid thread id")
        elif res != 1:
            # """if it returns a number greater than one, you"re in trouble,
            # and you should call it again with exc=NULL to revert the effect"""
            ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, None)
            raise SystemError("PyThreadState_SetAsyncExc failed")

    def __go_func(self, tid, fn, fuse_status):
        try:
            objs = fn(*self.__args, **self.__kwargs)
            self._func_time[fn.__name__ + str(tid)] = objs
        except Exception as ex:
            fc = self.except_fallback_func(
                ex, fn.__name__, *self.__args, **self.__kwargs
            )
            self._func_time[fn.__name__ + str(tid)] = fc
            ec = self._func_fuse[fn]["error"] + 1
            if fuse_status:
                self._func_fuse[fn]["error"] = ec

    def __is_fuse(self,
        fn, fuse_status, except_percent, time_windows, time_count):
        if fuse_status is False:
            return False
        try:
            self._func_fuse[fn]
        except KeyError:
            self._func_fuse[fn] = {}
            self._func_fuse[fn]["count"] = 0
            self._func_fuse[fn]["error"] = 0
            self._func_fuse[fn]["time_count"] = time.time()
            self._func_fuse[fn]["time_windows"] = 0
        x = time.time() - self._func_fuse[fn]["time_count"]
        if x > time_count:
            time_windows_now = self._func_fuse[fn]["time_windows"]
            if time_windows_now != 0:  # 不等于0则认为触发熔断
                x1 = time.time() - time_windows_now  # 判断是否还在熔断时间窗口期
                if x1 <= time_windows:
                    return True
                else:  # 结束熔断窗口期 重置统计异常窗口期
                    self._func_fuse[fn]["time_count"] = time.time()
                    self._func_fuse[fn]["time_windows"] = 0
                    return False
            else:  # 等于0则判断当前行为是否熔断
                count = self._func_fuse[fn]["count"]
                error = self._func_fuse[fn]["error"]
                self._func_fuse[fn]["count"] = 0  # 取出来以后立刻重置
                self._func_fuse[fn]["error"] = 0
                if count != 0:
                    e = error / count
                    if e > except_percent:
                        self._func_fuse[fn]["time_windows"] = time.time()
                        return True
                    else:  # 未达到触发条件，继续重置统计异常窗口期
                        self._func_fuse[fn]["time_count"] = time.time()
                        return False
                else:  # 没有执行过函数 重置窗口期继续统计
                    self._func_fuse[fn]["time_count"] = time.time()
                    return False
        else:
            return False

    def fuse(
        self,
        timeout=6,
        fuse_status=False,
        except_percent=0.5,
        time_windows=5,
        time_count=2,
    ):
        def get_f(fn):
            def get_args(*args, **kwargs):
                self.__kwargs = kwargs
                self.__args = args
                # 判断是否需要熔断，默认不熔断
                if self.__is_fuse(
                    fn, fuse_status, except_percent, time_windows, time_count
                ):
                    return self.fallback_func(fn.__name__, *args, **kwargs)
                tid = time.time()
                func_thread = threading.Thread(
                    target=self.__go_func, args=(tid, fn, fuse_status)
                )
                func_thread.setDaemon(True)
                func_thread.start()
                func_thread.join(timeout)
                try:
                    self.__async_raise(func_thread.ident)
                    tff = self.timeout_fallback_func(
                        TimeoutError, fn.__name__, *args, **kwargs
                    )
                    self._func_time[fn.__name__ + str(tid)] = tff
                    if fuse_status:
                        ffe = self._func_fuse[fn]["error"] + 1
                        self._func_fuse[fn]["error"] = ffe
                except ValueError:
                    pass
                if fuse_status:
                    ffc = self._func_fuse[fn]["count"] + 1
                    self._func_fuse[fn]["count"] = ffc
                return self._func_time[fn.__name__ + str(tid)]

            get_args.__name__ = fn.__name__
            return get_args

        return get_f


class FuncFlowControl:
    """请求控制，对请求失败进行处理"""

    def __init__(self, fall_back_func=default_fall_back_func):
        self.fall_back_func = fall_back_func
        self._flow_control_msg = {}
        # self.flowControlMsg = self.__flowControlMsg
        self._func_return = None

    def flow_control(self, time_windows, max_count):
        def get_f(fn):
            try:
                self._flow_control_msg[fn]
            except KeyError:
                self._flow_control_msg[fn] = 0
                self._flow_control_msg[str(fn) + "time"] = time.time()

            def get_args(*args, **kwargs):
                x = time.time() - self._flow_control_msg[str(fn) + "time"]
                if x < time_windows:
                    if self._flow_control_msg[fn] >= max_count:
                        return self.fall_back_func(fn.__name__, *args, **kwargs)
                else:
                    self._flow_control_msg[fn] = 0
                    self._flow_control_msg[str(fn) + "time"] = time.time()
                self._flow_control_msg[fn] = self._flow_control_msg[fn] + 1
                self._func_return = fn(*args, **kwargs)
                self._flow_control_msg[fn] = self._flow_control_msg[fn] - 1
                return self._func_return

            get_args.__name__ = fn.__name__
            return get_args

        return get_f
