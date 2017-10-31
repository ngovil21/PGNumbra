import logging
import os
import sys
from multiprocessing.pool import ThreadPool
from threading import Lock

from mrmime.utils import get_spinnable_pokestops

from pgnumbra.config import cfg_get, cfg_init
from pgnumbra.proxy import init_proxies
# ===========================================================================
from pgnumbra.spin import spin_pokestop
from pgnumbra.utils import load_accounts

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s [%(threadName)16s][%(module)14s][%(levelname)8s] %(message)s')

log = logging.getLogger(__name__)

# Silence some loggers
logging.getLogger('pgoapi').setLevel(logging.WARNING)

# ===========================================================================

FILE_PREFIX = 'accounts'
ACC_INFO_FILE = FILE_PREFIX + '-info.txt'

acc_stats = {
    'good': 0,
    'blind': 0,
    'captcha': 0,
    'banned': 0,
    'error': 0
}

# ===========================================================================


def remove_account_file(suffix):
    fname = '{}-{}.csv'.format(FILE_PREFIX, suffix)
    if os.path.isfile(fname):
        os.remove(fname)


def check_account(acc):
    try:
        try:
            response = acc.scan_once()

            lvl = acc.get_stats('level')
            if response:
                spin_below_level = cfg_get("spin_below_level")
                max_spins = cfg_get("max_spins")
                if lvl < spin_below_level:
                    step_location = (acc.latitude, acc.longitude)
                    stops = get_spinnable_pokestops(response, step_location)
                    acc.log_info("Account is level {}. Trying to spin {} Pokestop(s) for XP.".format(lvl, min(max_spins,
                                                                                                              len(stops))))
                    spins = 0
                    for stop in stops:
                        if spin_pokestop(acc, stop, step_location):
                            spins += 1
                        if spins >= max_spins:
                            break
                else:
                    acc.log_info(
                        "Account already reached level {}. Not spinning any Pokestop.".format(spin_below_level))
        except Exception as e:
            log.exception("Error checking account {}: {}".format(acc.username, repr(e)))

        try:
            if acc.seen_pokemon:
                if is_blind(acc):
                    log.info("Account {} is shadowbanned. :-(".format(acc.username))
                    save_to_file(acc, 'blind')
                else:
                    log.info("Account {} is good. :-)".format(acc.username))
                    save_to_file(acc, 'good')
            else:
                if acc.is_banned():
                    save_to_file(acc, 'banned')
                elif acc.has_captcha():
                    save_to_file(acc, 'captcha')
                else:
                    save_to_file(acc, 'error')
            save_account_info(acc)
        except Exception as e:
            log.exception(
                "Error saving checked account {} to file: {}".format(acc.username, repr(e)))
    finally:
        acc.release(reason="Checked with PGNumbra")
        del acc


def write_line_to_file(fname, line):
    # Poor mans locking. Only 1 thread at any time, please. Super-defensive!
    if not hasattr(write_line_to_file, 'lock'):
        write_line_to_file.lock = Lock()
    write_line_to_file.lock.acquire()
    with open(fname, 'a') as f:
        f.write(line)
        f.close()
    write_line_to_file.lock.release()


def save_account_info(acc):
    global acc_info_tmpl

    def bool(x):
        return '' if x is None else ('Yes' if x else 'No')

    km_walked_f = acc.get_stats('km_walked')
    if km_walked_f:
        km_walked_str = '{:.1f} km'.format(km_walked_f)
    else:
        km_walked_str = ''
    line = acc_info_tmpl.format(
        acc.username,
        bool(acc.is_warned()),
        bool(acc.is_banned()),
        bool(acc.get_state('banned')),
        bool(acc.has_captcha()),
        bool(is_blind(acc)),
        acc.get_stats('level', ''),
        acc.get_stats('experience', ''),
        acc.get_stats('pokemons_encountered', ''),
        acc.get_stats('pokeballs_thrown', ''),
        acc.get_stats('pokemons_captured', ''),
        acc.get_stats('poke_stop_visits', ''),
        km_walked_str
    )
    write_line_to_file(ACC_INFO_FILE, line)


def init_account_info_file(accounts):
    global acc_info_tmpl

    max_username_len = 4
    for t in accounts:
        max_username_len = max(max_username_len, len(t.username))
    acc_info_tmpl = '{:' + str(
        max_username_len) + '} | {:4} | {:3} | {:4} | {:7} | {:5} | {:3} | {:8} | {:6} | {:5} | {:5} | {:5} | {:10}\n'
    line = acc_info_tmpl.format(
        'Username',
        'Warn',
        'Ban',
        'BanF',
        'Captcha',
        'Blind',
        'Lvl',
        'XP',
        'Enc',
        'Thr.',
        'Cap',
        'Spins',
        'Walked'
    )
    write_line_to_file(ACC_INFO_FILE, line)


def save_to_file(acc, suffix):
    global acc_stats
    acc_stats[suffix] = acc_stats.get(suffix, 0) + 1
    fname = "{}-{}.csv".format(FILE_PREFIX, suffix)
    line = '{},{},{}\n'.format(acc.auth_service, acc.username, acc.password)
    write_line_to_file(fname, line)


def is_blind(acc):
    # We don't know if we did not search/find ANY Pokemon
    if not acc.seen_pokemon:
        return None

    return acc.rareless_scans != 0


def log_results(key):
    if acc_stats[key]:
        log.info("{:7}: {}".format(key.upper(), acc_stats[key]))

# ===========================================================================

cfg_init(shadowcheck=True)

log.info("PGNumbra ShadowCheck starting up.")

# Delete result files.
remove_account_file('good')
remove_account_file('blind')
remove_account_file('captcha')
remove_account_file('banned')
remove_account_file('error')

if os.path.isfile(ACC_INFO_FILE):
    os.remove(ACC_INFO_FILE)

init_proxies()

accounts = load_accounts(min_level=cfg_get('min_level'), max_level=cfg_get('max_level'))

init_account_info_file(accounts)

num_threads = cfg_get('threads')
log.info("Checking {} accounts with {} threads.".format(len(accounts), num_threads))
pool = ThreadPool(num_threads)
pool.map_async(check_account, accounts).get(sys.maxint)
pool.close()
pool.join()

log.info("All {} accounts processed.".format(len(accounts)))
log_results('good')
log_results('blind')
log_results('captcha')
log_results('banned')
log_results('error')

if acc_stats['good'] == 0 and acc_stats['blind'] > 0:
    log.warning("================= WARNING =================")
    log.warning("NONE of the accounts saw ANY rare Pokemon.")
    log.warning("Either they are all blind or there are in fact")
    log.warning("no rare Pokemon near this location right now.")
    log.warning("Try again with a different location to be sure.")
