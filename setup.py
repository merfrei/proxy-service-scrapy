"""
Setup for Proxy Service Scrapy
"""

from setuptools import setup


setup(name='proxy-service-scrapy',
      version='1.0',
      description='Utilities to use Proxy Service with Scrapy',
      url='https://github.com/merfrei/proxy-service-scrapy',
      author='Emiliano M. Rudenick',
      author_email='erude@merfrei.com',
      license='MIT',
      packages=['proxy_service_scrapy'],
      install_requires=[
          'w3lib',
          'requests',
      ],
      zip_safe=False)
