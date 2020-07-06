"""
Proxy Service Scrapy Downloader Middleware
"""

import logging
import random
import base64
from itertools import cycle
from urllib.parse import urlparse
from scrapy import signals
from proxy_service_scrapy.api import ProxyServiceAPI
from twisted.internet.error import TimeoutError as ServerTimeoutError
from twisted.internet.error import ConnectionRefusedError
from twisted.internet.error import ConnectionDone
from twisted.internet.error import ConnectError
from twisted.internet.error import ConnectionLost
from twisted.internet.error import TCPTimedOutError
from twisted.internet.defer import TimeoutError as UserTimeoutError


logger = logging.getLogger(__name__)


def extract_auth_from_url(url):
    '''If the proxy URL has user:password information it will extract that data'''
    url_parts = urlparse(url)
    new_url = ('{}://{}'
               .format(url_parts.scheme,
                       url_parts.hostname))
    if url_parts.port is not None:
        new_url += ':{}'.format(url_parts.port)
    return (url_parts.username, url_parts.password, new_url)


def add_auth_header_to_request(user, password, request):
    '''Add the Basic Auth header to the request'''
    if not user:
        return
    authstr = (base64.b64encode('{user}:{pswd}'
                                .format(user=user,
                                        pswd=password)))
    request.headers['Proxy-Authorization'] = 'Basic ' + authstr


class ProxyServiceMiddlewareError(Exception):
    '''Something went wrong'''


class ProxyServiceMiddleware(object):
    def __init__(self, crawler):
        self.api_client = None
        self.use_proxies = set()
        self.target_bucket = {}

        self.blocked_http_codes = [503, 403, 504]
        self.blocked_exceptions = (
            ServerTimeoutError, UserTimeoutError,
            ConnectionRefusedError, ConnectionDone, ConnectError,
            ConnectionLost, TCPTimedOutError, IOError)

    @classmethod
    def from_crawler(cls, crawler):
        '''Init the middleware and return it'''
        middleware = cls(crawler)
        api_config = {}
        middleware.set_api_config_from_settings(crawler.settings, api_config)
        middleware.api_client = ProxyServiceAPI(**api_config)

        crawler.signals.connect(middleware.spider_opened, signals.spider_opened)
        crawler.signals.connect(middleware.spider_closed, signals.spider_closed)
        return middleware

    @staticmethod
    def set_api_config_from_settings(settings, config: dict):
        '''Set the middleware config from settings.py'''
        config['api_url'] = settings.get('PROXY_SERVICE_API_URL', '')
        config['api_key'] = settings.get('PROXY_SERVICE_API_KEY', '')

    @staticmethod
    def get_next_proxy_method(spider):
        '''Get the method selected to return the next proxy (random or cycle)'''
        default = 'random'
        method = getattr(spider, 'ps_method', default)
        if method not in ('random', 'cycle'):
            logger.warning('PS: Unknown method selected `%s` using defaul `%s`', method, default)
            method = default
        return method

    @staticmethod
    def load_api_filters_spider(spider, filters):
        '''Read the attributes on the spider and set the API filters'''
        filter_keys = ['ps_len', 'ps_type', 'ps_loc', 'ps_prov', 'ps_plan']
        for f_key in filter_keys:
            f_val = getattr(spider, f_key, None)
            if f_val is not None:
                # ie: ps_len => len
                filters[f_key.split('_', 1)[-1]] = f_val

    def next_proxy(self, spider):
        '''Return the next proxy in the bucket
        @return: <proxy ID>, <proxy URL>'''
        method = self.get_next_proxy_method(spider)
        if method == 'random':
            next_proxy = random.choice(
                self.target_bucket[spider.ps_target])
        else:
            next_proxy = next(self.target_bucket[spider.ps_target])
        return next_proxy['id'], next_proxy['url']

    def load_spider_bucket(self, spider, blocked: list = None):
        '''Load the bucket for the spider'''
        target = spider.ps_target
        should_load_proxies =  blocked is not None or not self.target_bucket.get(target)
        if should_load_proxies:
            filters = {}
            self.load_api_filters_spider(spider, filters)
            if blocked is not None:
                filters['blocked'] = '|'.join(blocked)
            proxy_list_resp = self.api_client.get_proxies(target, **filters)
            proxy_list = [proxy for proxy in proxy_list_resp['pool']]
            logger.info('PS: Proxy List found for target %s: %r', target, proxy_list)
            method = self.get_next_proxy_method(spider)
            if method == 'random':
                self.target_bucket[target] = list(proxy_list)
            else:
                self.target_bucket[target] = cycle(proxy_list)

    def is_blocked_response(self, response, spider):
        '''Check if the response is blocked'''
        callback = None
        if hasattr(spider, 'ps_check_response'):
            if callable(spider.ps_check_response):
                callback = spider.ps_check_response
        if response.status in self.blocked_http_codes:
            return True
        if callback is not None:
            return callback(response)
        return False

    def replace_proxy(self, request, spider):
        '''Given a request it will replace the proxy'''
        proxy_id, proxy_url = self.next_proxy(spider)
        if not proxy_id and not proxy_url:
            logger.error('PS: no proxy found for the given target')
        else:
            # extract user and password from url
            user, password, new_url = extract_auth_from_url(proxy_url)
            request.meta['proxy'] = new_url
            request.meta['proxy_id'] = proxy_id
            add_auth_header_to_request(user, password, request)
            logger.info('PS: Processing request to %s using proxy %s',
                        request.url, request.meta['proxy'])

    def spider_opened(self, spider):
        '''When the spider is opened check if PS is enabled and load the bucket'''
        if hasattr(spider, 'ps_target'):
            self.use_proxies.add(spider.name)
            self.load_spider_bucket(spider)

    def spider_closed(self, spider):
        '''When the spiders is closed...'''
        if spider.name in self.use_proxies:
            self.use_proxies.remove(spider.name)

    def process_request(self, request, spider):
        '''If PS is enabled it will be used'''
        disabled = (request.meta.get('ps_disabled', False) or False)
        if (spider.name in self.use_proxies) and (not disabled):
            self.replace_proxy(request, spider)

    def process_response(self, request, response, spider):
        '''If PS is enabled it will be used. Check the Response to see if it's blocked'''
        disabled = (request.meta.get('ps_disabled', False) or False)
        if (spider.name in self.use_proxies) and (not disabled):
            mark_as_blocked = (
                self.is_blocked_response(response, spider) and
                'proxy_id' in request.meta)
            if mark_as_blocked:
                self.load_spider_bucket(
                    spider, blocked=[int(request.meta['proxy_id'])])
        return response

    def process_exception(self, request, exception, spider):
        '''If PS is enabled. It will check the Exceptions and mark the proxy as blocked
        in case it is due to blocking. Also it will replace the current proxy in the request
        and reschedule the request'''
        disabled = (request.meta.get('ps_disabled', False) or False)
        if (spider.name in self.use_proxies) and (not disabled):
            mark_as_blocked = (
                isinstance(exception, self.blocked_exceptions) and
                'proxy_id' in request.meta)
            if mark_as_blocked:
                self.load_spider_bucket(spider,
                                        blocked=[int(request.meta['proxy_id'])])
                self.replace_proxy(request, spider)
                request.dont_filter = True
                return request
