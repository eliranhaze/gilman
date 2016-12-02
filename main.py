import re
import readline
import requests
import sys
import time

from bs4 import BeautifulSoup as bsoup
from threading import Thread, RLock
from Queue import Queue, Empty

from fetch import fetch

s = requests.Session()

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

    def __init__(self):
        self.all_data = []
        self.concurrent = 50
        self.q = Queue()
        self.lock = RLock()
        self.url_count = 0
        self.read_count = 0
        self.processing = False

    def run(self):
        try:
            print 'getting data...'
            t1 = time.time()
            self.start()
            self.join()
            print 'got %d data in %.1fms' % (len(self.all_data), (time.time()-t1)*1000.)
        except KeyboardInterrupt:
            print
            print 'exiting'
            sys.exit(1)

    def start(self):
        # populate the q first, since the tasks use get_nowait
        for url in self.gen_urls():
            self.q.put(url)
        for _ in xrange(self.concurrent):
            t = Thread(target=self.task)
            t.daemon = True
            t.start()

    def join(self):
        # wait for the q to empty (not using join since it cannot be interrupted)
        while self.read_count < self.url_count:
            time.sleep(0.1)
    
    def gen_urls(self):
        year = '2016' 
        deps = get_deps()
        self.url_count = len(deps)
        for dep in deps:
            yield 'http://www2.tau.ac.il/yedion/syllabus/?deployment=10&dep=%s&year=%s' % (dep, year)
   
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
                sys.stdout.write('reading data... %d/%d           \r' % (self.read_count, self.url_count))
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
                match = re.search('\d{4}-\d{4}', td.text)
                if match:
                    hours = match.group().split('-')
                    if all('0700' < h < '2100' for h in hours):
                        is_schedule = True
                        break 
            if is_schedule and len(tds) > 6:
                building = tds[2].text.strip()
                room = tds[3].text.strip()
                day = tds[4].text.strip()
                semester = tds[6].text.strip()
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

def normalize_hours(hours):
    # e.g. 1630,1800 -> 16,17; 1600,1830 -> 16,17,18
    hours = sorted(hours)
    h1 = int(hours[0][:2])
    h2 = int(hours[1][:2])
    if hours[1][2:] == '00':
        h2 -= 1
    return range(h1, h2+1)

def process(data):
    # all rooms: building -> room
    all_rooms = {}
    for d in data:
        all_rooms.setdefault(d['building'], set()).add(d['room'])
    # all data: building -> sem -> day -> hour -> occupied rooms
    all_data = {}
    for d in data:
        day_data = all_data.setdefault(d['building'], {}).setdefault(d['semester'], {}).setdefault(d['day'], {})
        for h in  normalize_hours(d['hours']):
            day_data.setdefault(h, []).append(d['room'])
    return all_rooms, all_data

def interact(rooms, data):
    print '%d rooms in %d buildings' % (sum(len(v) for v in rooms.itervalues()), len(rooms))
    while True:
        building = print_and_select_from_list('select building', sorted(data.keys()))
        if building:
            semester = print_and_select_from_list('select semester', sorted(data[building].keys()))
            if semester:
                day = print_and_select_from_list('select day', sorted(data[building][semester].keys()))
                if day:
                    hour = print_and_select_from_list('select hour', sorted(data[building][semester][day].keys()))
                    if hour:
                        occupied = data[building][semester][day][hour]
                        free = [r for r in rooms[building] if r not in occupied]
                        print 'occupied: %s' % occupied
                        print 'free: %s' % free

###############################################################################
# Utils

QUIT_STRING = '\\q'

def print_and_select_from_list(msg, lst):
    print_list(lst)
    return select_from_list(msg, lst)

def print_list(lst):
    i = 1
    for item in lst:
        print_item(i, unicode(item))
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
    inp = raw_input(msg + ': ')
    if not inp:
        print 'Cancelled.'
    elif inp == QUIT_STRING:
        exit()
    return inp

if __name__ == '__main__':
    try:
        g = Gilman()
        g.run()
        rooms, data = process(g.all_data)
        interact(rooms, data)
    except KeyboardInterrupt:
        print
        print 'exiting'
        sys.exit(0)