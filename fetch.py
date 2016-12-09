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

use_cache = True
cache_max_age = timedelta(days=40)
cache_dir = '.cache'
metafile = '%s/%s' % (cache_dir, '.metadata')
sep = ' # '

if not os.path.exists(cache_dir):
    os.makedirs(cache_dir)
if not os.path.exists(metafile):
    open(metafile,'a').close()

def create_entry_path(entry):
    with open(metafile, 'a+') as f:
        lines = f.read().splitlines()
        name = int(lines[-1].split(sep)[-1])+1 if lines else 0
        f.write('%s%s%s\n' % (entry, sep, name))
        return '%s/%s' % (cache_dir, name)

def get_entry_path(entry, create=False):
    sep = ' # '
    lookfor = '%s%s' % (entry, sep)
    with open(metafile) as f:
        for line in f.read().splitlines():
            if line.startswith(lookfor):
                name = line.split(sep)[-1]
                return '%s/%s' % (cache_dir, name)
    # not found
    if create:
        return create_entry_path(entry)

def to_entry(url, params):
    url = re.sub('[^\w\s-]', '', url)
    params = params_to_string(params)
    return '%s%s' % (url, params)

def build_path(url, params, create=False):
    return get_entry_path(to_entry(url, params), create=create)

def params_to_string(params):
    name = ''
    if params:
        for k, v in params.iteritems():
            name += '%s%s' % (k, v)
    return name

def is_cached(url, params):
    if not use_cache:
        return False
    path = build_path(url, params)
    if path and os.path.exists(path):
        age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(path))
        if age < cache_max_age:
            return True
    return False

def get_from_cache(url, params):
    if is_cached(url, params):
        path = build_path(url, params)
        with open(path) as cached:
            return cached.read()

def cache(url, params, content):
    path = build_path(url, params, create=True)
    with open(path, 'w') as out:
       out.write(content)

def cached_pct(urls):
    return sum(1. for u in urls if is_cached(u))/len(urls)

#######################################################################

def _is_valid_url(url):
    parse = urlparse.urlparse(url)
    return parse.scheme and parse.netloc

def fetch(url, post=False, processor=None, **kwargs):
    params = kwargs.get('data') if post else kwargs.get('params')
    cached = get_from_cache(url, params)
    if cached:
        return cached
    if not _is_valid_url(url):
        return
    try:
        while True:
            if post:
                response = session.post(url, **kwargs)
            else:
                response = session.get(url, **kwargs)
            content = processor(response.content) if processor else response.content
            cache(url, params, content)
            return content
    except requests.exceptions.ConnectionError:
        time.sleep(1)
    except requests.exceptions.TooManyRedirects:
        return

