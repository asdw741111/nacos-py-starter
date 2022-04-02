r"""
nacos for python

"""
__version__ = '1.0.1'

name = 'nacos-starter'

__author__ = 'chizongyang'

__all__ = ['nacos', 'nacosBalanceClient', 'funcFuse']

from .nacos import nacos, nacosBalanceClient
from . import funcFuse