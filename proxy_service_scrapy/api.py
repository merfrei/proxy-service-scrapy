"""
Proxy Service API Client
"""

import requests
from w3lib.url import urljoin
from w3lib.url import add_or_replace_parameter


API_ENDPOINT = 'proxy_list'


class ProxyServiceAPIError(Exception):
    '''Something went wrong'''


class ProxyServiceAPI:
    '''Proxy Service API Client to ask for a list of proxies'''

    def __init__(self, api_url, api_key):
        self.api_url = api_url
        self.api_key = api_key

    def get_proxies(self, target, *, timeout=30, **filters):
        '''Get a list of proxies for the target.
        **filters will be passed to the API:
        - len: bucket length
        - loc: location
        - type: proxy type
        - prov: proxy provider
        - plan: provider plan
        - blocked: blocked IDs (<id1>|<id2>|...)'''
        api_url = self.get_api_url(self.api_url, self.api_key, target, **filters)
        resp = requests.get(api_url, timeout=timeout)
        if resp.status_code != 200:
            raise ProxyServiceAPIError('API returned unexpected code {}'.format(resp.status_code))
        data = resp.json()
        return data['data']

    @staticmethod
    def get_api_url(api_url, api_key, target, **filters):
        '''Build the API URL to query a list of proxies'''
        api_url = urljoin(api_url, API_ENDPOINT)
        api_url = urljoin(api_url + '/', target)
        api_url = add_or_replace_parameter(api_url, 'api_key', api_key)
        for f_key, f_val in filters.items():
            api_url = add_or_replace_parameter(api_url, f_key, f_val)
        return api_url
