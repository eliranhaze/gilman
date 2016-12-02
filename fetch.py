import os
import re
import requests
import time
import urlparse

from datetime import datetime, timedelta

session = requests.Session()
session.headers['User-Agent'] = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/49.0.2623.87 Safari/537.36'

#######################################################################
# cache

cache_max_age = timedelta(days=21)
cache_dir = 'cache'
if not os.path.exists(cache_dir):
    os.makedirs(cache_dir)

def build_path(url):
    url = re.sub('[^\w\s-]', '', url)
    return '%s/%s' % (cache_dir, url)

def get_from_cache(url):
    path = build_path(url)
    if os.path.exists(path):
        age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(path))
        if age < cache_max_age:
            with open(path) as cached:
                return cached.read()

def cache(url, content):
    path = build_path(url)
    with open(path, 'w') as out:
       out.write(content)
 
#######################################################################

def _is_valid_url(url):
    parse = urlparse.urlparse(url)
    return parse.scheme and parse.netloc

def fetch(url, **kwargs):
    cached = get_from_cache(url)
    if cached:
        return cached
    if not _is_valid_url(url):
        return
    try:
        while True:
            response = session.get(url, **kwargs)
            cache(url, response.content)
            return response.content
    except requests.exceptions.ConnectionError:
        time.sleep(1)
    except requests.exceptions.TooManyRedirects:
        return

