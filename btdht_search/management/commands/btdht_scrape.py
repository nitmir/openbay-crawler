# -*- coding: utf-8 -*-
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License version 3 for
# more details.
#
# You should have received a copy of the GNU General Public License version 3
# along with this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# (c) 2016 Valentin Samir
from django.core.management.base import BaseCommand

import re
import binascii
import argparse
import time
import progressbar
import pymongo
import random
import select

from ...settings import settings
from ...utils import getdb, scrape, get_bad_trackers


def _widget(what=""):
    return [
        progressbar.ETA(), ' ', progressbar.Bar('='), ' ', progressbar.SimpleProgress(),
        ' ' if what else "", what
    ]

def _scrape(results, pbar=None):
    hashes = []
    if pbar:
        pbar.start()
    for obj in results:
        #print "%s: %ss since last scrape" % (obj["_id"].encode("hex"), time.time() - obj["last_scrape"])
        hashes.append(obj['_id'])
        if len(hashes) >= 74:
            scrape(hashes, udp_timeout=3, tcp_timeout=2, tracker_retry_nb=5, save_index=2, bad_tracker_timeout=1800, refresh=True)
            if pbar:
                try:
                    pbar.update(pbar.currval + len(hashes))
                except ValueError:
                    pass
                hashes = []
    if hashes:
        scrape(hashes, udp_timeout=3, tcp_timeout=2, tracker_retry_nb=5, save_index=2, bad_tracker_timeout=1800, refresh=True)
    if pbar:
        pbar.finish()

def scrape_new(quiet=False):
    db = getdb()
    results = db.find({'last_scrape': {'$in': [0, None]}}, {'_id': True, 'last_scrape': True})
    print("Scraping %s new torrents" % results.count())
    if not quiet and results.count() > 0:
        pbar = progressbar.ProgressBar(
           widgets=_widget("scraping torrents"),
           maxval=results.count()
        )
    else:
        pbar = None
    _scrape(results, pbar)

def scrape_recent(quiet=False):
    db = getdb()
    results = db.find(
        {
            'added': {'$gt': time.time() - settings.BTDHT_SCRAPE_RECENT},
            'last_scrape': {'$lt': time.time() - settings.BTDHT_SCRAPE_INTERVAL}
        },
        {'_id': True, 'last_scrape': True}
    ).sort([('last_scrape', -1)])
    print("Scraping %s recent torrents" % results.count())
    if not quiet and results.count() > 0:
        pbar = progressbar.ProgressBar(
           widgets=_widget("scraping torrents"),
           maxval=results.count()
        )
    else:
        pbar = None
    _scrape(results, pbar)

def filter_scraped(results, quiet=False):
    if not quiet and results.count() > 0:
        pbar = progressbar.ProgressBar(
           widgets=_widget("filtering torrents"),
           maxval=results.count()
        )
        pbar.start()
    else:
        pbar = None
    objs = []
    for obj in results:
        if obj['last_scrape'] < (time.time() - settings.BTDHT_SCRAPE_INTERVAL):
            objs.append(obj)
        if pbar:
            pbar.update(pbar.currval + 1)
    if pbar:
        pbar.finish()
    return objs

def scrape_top(quiet=False):
    db = getdb()
    now = time.time()
    results = db.find(
        {"seeds_peers": {"$gt": 0}},
        {'_id': True, 'last_scrape': True}
    ).sort([('seeds_peers', -1), ("seeds", -1)]).limit(settings.BTDHT_SCRAPE_TOP_NB)
    objs = filter_scraped(results, quiet)
    print("Scraping %s top torrents" % len(objs))
    if not quiet and len(objs) > 0:
        pbar = progressbar.ProgressBar(
           widgets=_widget("scraping torrents"),
           maxval=len(objs)
        )
    else:
        pbar = None
    _scrape(objs, pbar)



def sleep(sleep, quiet=False):
    if sleep >= 1:
        sleep_widget = [
            progressbar.Bar('>'), ' ', progressbar.ETA(), ' ', progressbar.ReverseBar('<')
        ]
        print("Now spleeping until the next loop")
        if quiet is False:
            pbar = progressbar.ProgressBar(widgets=sleep_widget, maxval=int(sleep)).start()
            for i in xrange(int(sleep)):
                time.sleep(1)
                pbar.update(i+1)
            time.sleep(sleep - int(sleep))
            pbar.finish()
        else:
           time.sleep(sleep)



class Command(BaseCommand):
    args = ''
    help = u"Allow to ban or unban torrent hashes"

    def add_arguments(self, parser):
        parser.add_argument(
            '--scrape-new',
            dest='scrape_new',
            help="Scrape torrent that was never scrapped",
            action="store_true",
        )
        parser.add_argument(
            '--scrape-recent',
            dest='scrape_recent',
            help="Scrape recent torrents (see BTDHT_SCRAPE_RECENT)",
            action="store_true",
        )
        parser.add_argument(
            '--scrape-top',
            dest='scrape_top',
            help="Scrape the most trending (most peers/seeds) torrents (see BTDHT_SCRAPE_TOP_NB)",
            action="store_true",
        )
        parser.add_argument(
            '--quiet', '-q',
            dest='quiet',
            help="be quiet (no progress bar)",
            action="store_true",
        )
        parser.add_argument(
            '--loop',
            dest='loop',
            help="loop",
            type=int,
        )


    def handle(self, *args, **options):
        if options["loop"]:
            while True:
                last = time.time()
                try:
                    self._process(*args, **options)
                except (pymongo.errors.PyMongoError, select.error) as error:
                    print("%r" % error)
                print("%s/%s bad trackers" % (len(get_bad_trackers(save_index=2)[0]), len(settings.BTDHT_TRACKERS) - len(settings.BTDHT_TRACKERS_NO_SCRAPE)))
                sleep(max(options["loop"] - (time.time() - last), 0))
        else:
            self._process(*args, **options)

    def _process(self, *args, **options):
        quiet = options["quiet"]
        functs = [("scrape_new", scrape_new), ("scrape_recent", scrape_recent), ("scrape_top", scrape_top)]
        random.shuffle(functs)
        for name, func in functs:
            if options[name]:
                func(quiet)
