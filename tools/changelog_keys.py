"""changelog.json keys: written in English and read in English or Spanish (old changelogs).

The rest of the code works with the usual Spanish keys (to_internal on read); to_file turns them into English on write.
Only structural keys are translated; region names (keys of «centros», «equivalencias», «poblacion») are left untouched."""
import json
import os

ENTRY = {'fecha': 'date', 'instalado': 'installed', 'traspasos': 'transfers', 'vecindades_nuevas': 'new_adjacencies', 'centros': 'centers',
         'operaciones': 'operations', 'regiones_nuevas': 'new_regions', 'regiones_eliminadas': 'deleted_regions',
         'equivalencias': 'equivalences', 'renombradas': 'renamed', 'canales': 'channels', 'origen': 'origin', 'nota': 'note',
         'base_equivalencias': 'equivalence_base'}
TRANSFER = {'de': 'from', 'a': 'to'}
RENAMED = {'de': 'from', 'a': 'to', 'texto': 'text', 'interno': 'internal'}
CHANNEL = {'cerrada': 'closed', 'zona': 'zone'}
DELETED = {'nombre': 'name', 'absorbida_por': 'absorbed_by', 'mar': 'sea'}
NEW = {'nombre': 'name', 'texto': 'text', 'madre': 'mother', 'pais': 'owner', 'tipo': 'type', 'controlador': 'controller', 'madres': 'mothers',
       'terreno': 'terrain', 'mar': 'sea', 'poblacion': 'population_fractions', 'historicos': 'historic_countries',
       'poblacion_manual': 'manual_population', 'ciudad': 'city', 'nacion': 'nation', 'equivale': 'equivalent', 'fraccion': 'fraction',
       'poblacion_por_escenario': 'population_by_scenario', 'pais_por_escenario': 'owner_by_scenario'}
# (entry keys holding lists of objects) -> table of their keys
LISTS = {'traspasos': TRANSFER, 'renombradas': RENAMED, 'canales': CHANNEL, 'regiones_eliminadas': DELETED, 'regiones_nuevas': NEW}


def _swap(d, table):
    return {table.get(k, k): v for k, v in d.items()} if isinstance(d, dict) else d


def _inv(t):
    return {v: k for k, v in t.items()}


def _convert(entry, entry_t, list_t):
    out = _swap(entry, entry_t)
    for es, table in LISTS.items():
        key = entry_t.get(es, es)
        if isinstance(out.get(key), list):
            out[key] = [_swap(x, list_t[es]) for x in out[key]]
    return out


def to_file(cl):
    # equivalences («equivale a región vanilla») always refer to World, the game's default regionpack: this is stated in
    # every entry that has them (also in old changelogs, when rewriting them)
    for e in cl:
        if (e.get('equivalencias') or any(x.get('equivale') for x in e.get('regiones_nuevas', []) or [])) and not e.get('base_equivalencias'):
            e['base_equivalencias'] = 'World'
    return [_convert(e, ENTRY, LISTS) for e in cl]


def to_internal(cl):
    inv_lists = {es: _inv(t) for es, t in LISTS.items()}
    return [_convert(e, _inv(ENTRY), inv_lists) for e in cl]


def load(path):
    return to_internal(json.load(open(path, encoding='utf-8'))) if os.path.exists(path) else []


def dump(cl, path):
    json.dump(to_file(cl), open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
