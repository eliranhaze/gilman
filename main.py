# -*- coding: utf-8 -*-
import os
import cPickle as pkl
import re
import readline
import requests
import sys
import time

from bs4 import BeautifulSoup as bsoup
from collections import OrderedDict
from threading import Thread, RLock
from Queue import Queue, Empty

from fetch import fetch

###################################################################################
# constants

HOURS = {
    (7,8,9): 1,
    (10,11): 2,
    (12,13): 3,
    (14,15): 4,
    (16,17): 5,
    (18,19): 6,
}

DAYS = {
    u'א': 1,
    u'ב': 2,
    u'ג': 3,
    u'ד': 4,
    u'ה': 5,
    u'ו': 6,
}

SEMESTERS = {
    u'א': 1,
    u'ב': 2,
    u'קיץ': 3,
}

###################################################################################
# requests

def gen_request_data(semester, day, hour):
    data = OrderedDict([
        ('MfcISAPICommand', 'but'),
        ('year',''),
        ('semester',semester),
        ('hour',hour),
        ('yom',day),
        ('department1','08'), # all art
        ('department2','05'), # all engineering
        ('department3','10'), # all social
        ('department4','04'), # all life
        ('department5','06'), # all humanities
        ('department6','03'), # all exact
        ('department7','14'), # all law
        ('course_nam',''),
        ('teach_nam',''),
        ('department8','12'), # all management
        ('department9','01'), # all medicine
        ('department10','11'), # social work (others needed)
        ('department11','21712172'), # english + foreign languages
        ('department12','188018821883'), # all whatever this is
        ('department13','1843'), # all cyber
    ])
    if not semester:
        data.pop('semester')
    if not day:
        data.pop('yom')
    if not hour:
        data.pop('hour')
    yield data
    # clear deps 
    for key in data.keys():
        if key.startswith('department'):
            data[key] = ''
    additional_dep10 = ['11', '07', '09', '15']
    for dep10 in additional_dep10:
        data['department10'] = dep10
        yield data

def make_request(data, func):
    return fetch('http://yedion.tau.ac.il/yed/yednew.dll', data=data, post=True, processor=func)

def get_data(semester, day, hour):
    all_data = []
    for data in gen_request_data(semester=semester, day=day, hour=hour):
        content = make_request(data, minify)
        all_data.extend(parse(content))
    return process(all_data)

def process(data):
    # all rooms: building -> room
    all_rooms = {}
    for d in data:
        all_rooms.setdefault(d['building'], set()).add(d['room'])
    return all_rooms

all_hours = range(7,21)

def normalize_hours(hours):
    # e.g. 1630,1800 -> 16,17; 1600,1830 -> 16,17,18
    hours = sorted(hours)
    h1 = int(hours[0][:2])
    h2 = int(hours[1][:2])
    if hours[1][2:] == '00':
        h2 -= 1
    return range(h1, h2+1)

###################################################################################
# parsing

def parse(response):
    data = []
    soup = bsoup(response) 
    for tr in soup.findAll('tr'):
        tds = tr.findAll('td')
        hours = hours_from_schedule_row(tds)
        if hours:
            parsed = parse_schedule_row(tds, hours)
            if parsed:
                data.append(parsed)
    return data

def hours_from_schedule_row(td_list):
    for td in td_list:
        match = re.search('\d{4} *- *\d{4}', td.text)
        if match:
            hours = [h.strip() for h in match.group().split('-')]
            if all('0700' < h < '2100' for h in hours):
                return hours

def parse_schedule_row(td_list, hours):
    if len(td_list) > 4:
        building = get_heb(td_list[4].text)
        room = td_list[3].text.strip()
        day = get_heb(td_list[2].text)
        semester = get_heb(td_list[0].text)
        if building and room:
            return dict(
                building = building,
                room = room,
                day = day,
                hours = hours,
                semester = semester,
            )

def minify(response):
    response = response.replace('<A ', '<a ').replace('</A>', '</a>').replace('&nbsp;','').replace('\n','')
    response = re.sub('<a [\s\S]*?</a>', '', response)
    response = re.sub('<img [\s\S]*?>', '', response)
    response = re.sub('<th [\s\S]*?</th>', '', response)
    response = re.sub('colspan=".*?"', '', response)
    response = re.sub('class=".*?"', '', response)
    response = re.sub('bgcolor=".*?"', '', response)
    response = response.replace('align="right"','').replace('dir="rtl"','').replace('align ="right"','')
    response = response.replace('  ',' ')
    return response

###################################################################################
# interaction

def get_heb(s):
    return s.strip() # not reversing - [::-1]

def sorted_heb(slist):
    return sorted(slist)#, key=lambda s: s[::-1])

def nice_hour(h):
    return '%02d:00' % h

def get_all_rooms():
    cache_path = '.allrooms'
    if os.path.exists(cache_path):
        return pkl.load(open(cache_path, 'rb'))
    print 'loading rooms for the first time...'
    rooms = get_data('', '', '')
    pkl.dump(rooms, open(cache_path, 'wb'))
    return rooms

def interact():
    all_rooms = get_all_rooms()
    while True:
        semester = print_and_select_from_list('select semester', sorted_heb(SEMESTERS.keys()))
        if semester:
            day = print_and_select_from_list('select day', sorted_heb(DAYS.keys()))
            if day:
                hours_list = sorted([h for h_list in HOURS for h in h_list])
                hour = print_and_select_from_list('select hour', hours_list, printer=nice_hour)
                if hour:
                    print 'fetching data...'
                    occupied_rooms = get_data(
                        semester = SEMESTERS[semester],
                        day = DAYS[day],
                        hour = [v for k, v in HOURS.iteritems() if hour in k][0],
                    )
                    free_rooms = {} # building -> rooms
                    for building, rooms in all_rooms.iteritems():
                        if building in occupied_rooms:
                            for room in rooms:
                                if room not in occupied_rooms[building]:
                                    free_rooms.setdefault(building, []).append(room)
                        else:
                            free_rooms[building] = rooms.copy()
                    final_interact(semester, day, hour, free_rooms)
                    if not yesno('continue?'):
                        break

def final_interact(semester, day, hour, free_rooms):
    while True:
        print '---'
        print 'buildings with available rooms at %s/%s:' % (nice_hour(hour), day)
        print '---'
        building = print_and_select_from_list(
            'select building to view available rooms',
            sorted_heb(free_rooms.keys()),
            printer=lambda b: '%s (%d)' % (b, len(free_rooms[b]))
        )
        if not building:
            return
        print 'available rooms in %s in semester-%s, at %s/%s:' % (building, semester, nice_hour(hour), day)
        print ','.join(sorted(list(free_rooms[building])))
        if not yesno('view other buildings?'):
            return

###################################################################################
# utils

QUIT_STRING = '\\q'

def print_and_select_from_list(msg, lst, printer=None):
    print_list(lst, printer)
    return select_from_list(msg, lst, printer)

def print_list(lst, printer=None):
    i = 1
    for item in lst:
        item_str = printer(item) if printer else item
        print_item(i, item_str)
        i += 1

def print_item(i, item):
    print '%s. %s' % (i, item)

def select_from_list(msg, lst, printer=None):
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
            print 'selected:', printer(selection) if printer else selection
            print '---'
            return selection
        except ValueError:
            print 'invalid input'
        except IndexError:
            print 'out of range'

def read_input(msg):
    inp = raw_input("%s: " % msg)
    if not inp:
        print 'cancelled.'
    elif inp == QUIT_STRING:
        sys.exit(0)
    return inp

def yesno(msg):
    inp = None
    y = ['y', 'yes', 'yy', 'yyy', 'ye', 'yea', 'yeah', '']
    n = ['n', 'no', 'nn', 'nnn','nah', 'nope', 'sorry']
    while inp not in y + n:
        inp = raw_input(msg + ' ([y]/n) ').lower()
        if inp == QUIT_STRING:
            sys.exit(0)
    return inp in y

if __name__ == '__main__':
    try:
        interact()
    except KeyboardInterrupt:
        print
        print 'exiting'
        sys.exit(0)
