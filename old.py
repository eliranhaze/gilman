import re
import readline
import sys
import time

from bs4 import BeautifulSoup as bsoup
from threading import Thread, RLock
from Queue import Queue, Empty

from fetch import fetch, cached_pct

def split_in_n(x, n):
    return [x[i:i+n] for i in range(0, len(x), n)]

def get_deps():
    soup = bsoup(fetch('http://www20.tau.ac.il/yedion/yedion.html'))
    deps = []
    for option in soup.findAll('option'):
        value = option.get('value')
        if value:
            deps.extend([d for d in split_in_n(value, 4) if len(d) == 4])
    return list(set(deps))

#############################################

class Gilman(object):

    MAX_THREADS = 32

    def __init__(self):
        self.all_data = []
        self.q = Queue()
        self.lock = RLock()
        self.url_count = 0
        self.read_count = 0

    def run(self):
        try:
            self.init()
            print 'getting data (%.0f%% cached, %d threads)' % (self.cached_pct*100, self.concurrent)
            self.start()
            self.join()
        except KeyboardInterrupt:
            print
            print 'exiting'
            sys.exit(1)

    def init(self):
        # populate the q first, since the tasks use get_nowait
        urls = []
        for url in self.gen_urls():
            self.q.put(url)
            urls.append(url)
        self.cached_pct = cached_pct(urls)
        self.concurrent = self.MAX_THREADS - int(((self.MAX_THREADS - 1) * self.cached_pct))

    def start(self):
        for _ in xrange(self.concurrent):
            t = Thread(target=self.task)
            t.daemon = True
            t.start()

    def join(self):
        # wait for the q to empty (not using join since it cannot be interrupted)
        while self.read_count < self.url_count:
            time.sleep(0.1)
    
    def gen_urls(self):
        deps = get_deps()
        self.url_count = len(deps)
        for dep in deps:
            yield 'http://www2.tau.ac.il/yedion/syllabus/?deployment=10&dep=%s' % dep
   
    def get_from_q(self):
        try:
            return self.q.get_nowait()
        except Empty:
            pass
 
    def task(self):
        while True:
            url = self.get_from_q()
            if url is None:
                return
            response = fetch(url)
            self.parse(response)
            with self.lock:
                self.read_count += 1
                sys.stdout.write('fetching %d/%d pages        \r' % (self.read_count, self.url_count))
                sys.stdout.flush()
            self.q.task_done()
    
    def update_data(self, data):
        with self.lock:
            self.all_data.extend(data)
   
    def parse(self, response):
        data = []
        soup = bsoup(response) 
        for tr in soup.findAll('tr'):
            is_schedule = False
            tds = tr.findAll('td')
            for td in tds:
                match = re.search('\d{4} *- *\d{4}', td.text)
                if match:
                    hours = [h.strip() for h in match.group().split('-')]
                    if all('0700' < h < '2100' for h in hours):
                        is_schedule = True
                        break 
            if is_schedule and len(tds) > 6:
                building = get_heb(tds[2].text)
                room = tds[3].text.strip()
                day = get_heb(tds[4].text)
                semester = get_heb(tds[6].text)
                if building and room:
                    data.append(dict(
                        building = building,
                        room = room,
                        day = day,
                        hours = hours,
                        semester = semester,
                    ))
        self.update_data(data)

#############################################################################

def get_heb(s):
    return s.strip()[::-1]

def sorted_heb(slist):
    return sorted(slist, key=lambda s: s[::-1])

all_hours = range(7,21)

def normalize_hours(hours):
    # e.g. 1630,1800 -> 16,17; 1600,1830 -> 16,17,18
    hours = sorted(hours)
    h1 = int(hours[0][:2])
    h2 = int(hours[1][:2])
    if hours[1][2:] == '00':
        h2 -= 1
    return range(h1, h2+1)

def nice_hour(h):
    return '%02d:00' % h

def process(data):
    # all rooms: building -> room
    all_rooms = {}
    for d in data:
        all_rooms.setdefault(d['building'], set()).add(d['room'])
    # all data: building -> sem -> day -> hour -> occupied rooms
    all_data = {}
    for d in data:
        day_data = all_data.setdefault(d['building'], {}).setdefault(d['semester'], {}).setdefault(d['day'], {})
        for h in all_hours:
            day_data.setdefault(h, [])
        for h in normalize_hours(d['hours']):
            day_data[h].append(d['room'])
    return all_rooms, all_data

def interact(rooms, data):
    print '%d rooms in %d buildings' % (sum(len(v) for v in rooms.itervalues()), len(rooms))
    while True:
        building = print_and_select_from_list('select building', sorted_heb(data.keys()))
        if building:
            semester = print_and_select_from_list('select semester', sorted_heb(data[building].keys()))
            if semester:
                day = print_and_select_from_list('select day', sorted_heb(data[building][semester].keys()))
                if day:
                    hours_list = [h for h in sorted(data[building][semester][day].iterkeys())]
                    hour = print_and_select_from_list('select hour', hours_list, printer=nice_hour)
                    if hour:
                        occupied = data.get(building, {}).get(semester, {}).get(day, {}).get(hour, {})
                        free = sorted([r for r in rooms[building] if r not in occupied])
                        print '---'
                        print 'free rooms in %s at %s, %s:' % (building, nice_hour(hour), day)
                        print '---'
                        for f in free:
                            print f
                        print '---'
                        if not yesno('continue?'):
                            break

###############################################################################
# Utils

QUIT_STRING = '\\q'

def print_and_select_from_list(msg, lst, printer=None):
    print_list(lst, printer)
    return select_from_list(msg, lst)

def print_list(lst, printer=None):
    i = 1
    for item in lst:
        item_str = printer(item) if printer else item
        print_item(i, item_str)
        i += 1

def print_item(i, item):
    print str(i) + '. ' + item

def select_from_list(msg, lst):
    while True:
        try:
            inp = read_input(msg + ' (1-' + str(len(lst)) + ')')
            if not inp:
                return
            choice = int(inp) - 1
            if choice < 0:
                raise IndexError
            selection = lst[choice]
            print '---'
            print 'Selected:', selection
            print '---'
            return selection
        except ValueError:
            print 'Invalid input.'
        except IndexError:
            print 'Out of range.'

def read_input(msg):
    inp = raw_input("%s ['\q' to quit]: " % msg)
    if not inp:
        print 'Cancelled.'
    elif inp == QUIT_STRING:
        exit()
    return inp

def yesno(msg):
    inp = None
    y = ['y', 'yes', 'yy', 'yyy', 'ye', 'yea', 'yeah', '']
    n = ['n', 'no', 'nn', 'nnn','nah', 'nope', 'sorry']
    while inp not in y + n:
        inp = raw_input(msg + ' ([y]/n) ').lower()
        if inp == QUIT_STRING:
            exit()
    return inp in y

if __name__ == '__main__':
    try:
        g = Gilman()
        t1 = time.time()
        g.run()
        print
        print 'got data in %.2fs' % (time.time()-t1)
        rooms, data = process(g.all_data)
        interact(rooms, data)
    except KeyboardInterrupt:
        print
        print 'exiting'
        sys.exit(0)
