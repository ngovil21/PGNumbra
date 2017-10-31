import json
import logging
import os
import sys

import requests

from pgnumbra.SingleLocationScanner import SingleLocationScanner
from pgnumbra.config import cfg_get, get_pgpool_system_id
from pgnumbra.proxy import get_new_proxy

log = logging.getLogger(__name__)


def get_pokemon_name(pokemon_id):
    fmt = cfg_get('pokemon_format')
    if fmt == 'id':
        return "{:3}".format(pokemon_id)

    if not hasattr(get_pokemon_name, 'pokemon'):
        file_path = os.path.join('pokemon.json')

        with open(file_path, 'r') as f:
            get_pokemon_name.pokemon = json.loads(f.read())
    name = get_pokemon_name.pokemon[str(pokemon_id)]

    return shorten(name) if fmt == 'short' else name


def shorten(s):
    # Remove vowels and return only 3 chars
    for ch in ['a', 'e', 'i', 'o', 'u']:
        if ch in s:
            s = s.replace(ch, '')
    return s[:3]


def load_accounts(min_level=0, max_level=0):
    accounts = []
    if cfg_get('accounts_file'):
        log.info("Loading accounts from file {}.".format(cfg_get('accounts_file')))
        with open(cfg_get('accounts_file'), 'r') as f:
            for num, line in enumerate(f, 1):
                if str.strip(line) == "":
                    continue
                fields = line.split(",")
                if len(fields) == 3:
                    auth = str.strip(fields[0])
                    usr = str.strip(fields[1])
                    pwd = str.strip(fields[2])
                elif len(fields) == 2:
                    auth = 'ptc'
                    usr = str.strip(fields[0])
                    pwd = str.strip(fields[1])
                elif len(fields) == 1:
                    fields = line.split(":")
                    auth = 'ptc'
                    usr = str.strip(fields[0])
                    pwd = str.strip(fields[1])
                accounts.append(
                    SingleLocationScanner(auth, usr, pwd, cfg_get('latitude'), cfg_get('longitude'),
                                          cfg_get('hash_key_provider'), get_new_proxy()))
    elif cfg_get('pgpool_url') and cfg_get('pgpool_num_accounts') > 0:
        log.info("Trying to load {} accounts from PGPool.".format(cfg_get('pgpool_num_accounts')))
        request = {
            'system_id': get_pgpool_system_id(),
            'count': cfg_get('pgpool_num_accounts'),
            'banned_or_new': True
        }

        if min_level>0:
            request['min_level'] = min_level
        if max_level>0:
            request['max_level'] = max_level

        r = requests.get("{}/account/request".format(cfg_get('pgpool_url')), params=request)

        acc_json = r.json()
        if isinstance(acc_json, dict):
            acc_json = [acc_json]

        if len(acc_json) > 0:
            log.info("Loaded {} accounts from PGPool.".format(len(acc_json)))
            for acc in acc_json:
                accounts.append(
                    SingleLocationScanner(acc['auth_service'], acc['username'], acc['password'], cfg_get('latitude'),
                                          cfg_get('longitude'), cfg_get('hash_key_provider'), get_new_proxy()))

    if len(accounts) == 0:
        log.error("Could not load any accounts. Nothing to do. Exiting.")
        sys.exit(1)
    return accounts