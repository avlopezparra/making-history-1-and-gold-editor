"""Ports the unit models of MH: The Great War / The Second World War (.nst) to Making History 1 / Gold (.nif + .kf).

- Rigid units (ships, planes, tanks, guns, trains, balloons): convert(). The TGW meshes and textures replace the geometry
  of the MH1 model of the same class, which keeps its nodes, insignia, muzzle flashes and .kf (MH1 bobbing, propellers...).
  Size follows the MH1 model (fit). Both games put the bow at -Z, Y up.
- Skinned units (infantry, cavalry riders...): convert_skinned(). TGW and MH1 infantry come from the same Maya rig
  (same joints, same units: pelvis / NewRig at 40.6 high), so the TGW skeleton is rebuilt in the MH1 template the way MH1
  stores it (node «J» = translate + jointOrient, «J_Base» = rotateZ·rotateY·rotateX, «J_RotateAxis» = the rest) and
  the TGW clips (Move, Idle2, Attack... from InfantrySkeletonN.nst) become an old-style .kf (NiKeyframeController,
  XYZ Euler keys on J_Base, translation keys on J), like MH1's Infantry.kf.
"""
import copy
import os
import re

import numpy as np

import nif as N
import nif_mesh as M
import nst_model

TGW_MODULES = r'D:/SteamLibrary/steamapps/common/The Great War/content/Making History TGW/modules'
SWW_MODULES = r'D:/SteamLibrary/steamapps/common/Making History SWW/content/Making History SWW/modules'
MODELS = 'unit_models/shared'
MAPPINGS = 'unit_model_mappings/shared/mappings/UnitModelTableData.xml'
MH1_3D = r'C:/Program Files (x86)/Steam/steamapps/common/Making History The Calm and The Storm/Modern Europe/system/ui/art/3D'
# TGW parts that are effects or that the MH1 template already has (insignia, muzzle flashes, wake, smoke)
SKIP = ('Firing', 'Frame', 'Smoke', 'Wake', 'NationLogo', 'Shadow', 'Flag')
# subtrees TGW only shows in some modes (shown / hidden by the clips): road and rail transport of guns, bomb and torpedo loads
MODE_TREES = ('Truck', 'Horse', 'Train', 'Bomb', 'Torpedo', 'transit', 'Holders')
# MH1 sequence name -> TGW eGenericAnimation
SEQUENCES = {'Shoot': 'Shoot', 'Move': 'Move', 'Idle': 'Idle'}
EULER = ('rotateX', 'rotateY', 'rotateZ')


def meshes(nst_path, textures_dir=None):
    """TGW / SWW model -> (mesh dicts for nif_mesh.import_meshes without effects, scene)."""
    s = nst_model.scene(nst_path, textures_dir or os.path.join(os.path.dirname(nst_path), 'textures'))
    def mode_part(m):   # a node name with a word of MODE_TREES (Bomb_Set1, Bomb5, Truck_German), not LightBombers1
        return any(re.fullmatch(k + r'\d*', w, re.I) for p in [m['name']] + m['parent_names'] for w in re.split(r'[_|]', p)
                   for k in MODE_TREES)
    out = [m for m in s['meshes'] if not any(k.lower() in m['name'].lower() for k in SKIP) and not mode_part(m)]
    for m in out:
        if m['image'] is None:
            from PIL import Image
            m['image'] = Image.new('RGBA', (8, 8), (130, 130, 130, 255))
    return out, s


def _bounds(points):
    P = np.vstack(points)
    return P.min(0), P.max(0)


def convert(nst_path, template_nif, out_nif, turn=False):
    """Rigid unit: writes out_nif = template_nif with the TGW geometry, centered on the MH1 model (x, z), standing on its
    lowest point and as large as it. turn: half turn about Y (TGW guns aim at -Z, MH1 ones at +Z).
    Returns the import_meshes report."""
    ms, _ = meshes(nst_path)
    if not ms:
        raise ValueError('%s: sin mallas utilizables' % os.path.basename(nst_path))
    for m in ms:    # crews of guns / tanks are skinned: frozen in their bind pose (their vertices already are in model space)
        if m['skin']:
            m['skin'], m['world'] = None, np.eye(4)
    if turn:
        for m in ms:
            m['world'] = np.diag([-1.0, 1, -1, 1]) @ m['world']
    n = N.Nif.load(template_nif)
    sc = M.scene(n)
    tp = [(np.c_[sh['pos'], np.ones(len(sh['pos']))] @ sh['world'].T)[:, :3] for sh in sc['shapes']
          if len(sh['pos']) and not sh['hidden'] and not sh['name'].startswith(M.KEEP_DEFAULT)]
    if tp:
        (a0, a1) = _bounds(tp)
        (b0, b1) = _bounds([(np.c_[m['pos'], np.ones(len(m['pos']))] @ m['world'].T)[:, :3] for m in ms])
        s = (a1 - a0).max() / max((b1 - b0).max(), 1e-9)     # the scale import_meshes(fit) will apply
        d = np.r_[(a0 + a1)[0] / 2 / s - (b0 + b1)[0] / 2, a0[1] / s - b0[1], (a0 + a1)[2] / 2 / s - (b0 + b1)[2] / 2]
        for m in ms:
            m['world'] = np.r_[np.c_[np.eye(3), d], [[0, 0, 0, 1]]] @ m['world']
    rep = M.import_meshes(n, ms, fit=True)
    rep['attachments'] = M.fit_attachments(n)
    os.makedirs(os.path.dirname(out_nif) or '.', exist_ok=True)
    n.save(out_nif)
    return rep


def animations(modules, model):
    """{eGenericAnimation: (animation .nst name, clip)} for a TGW / SWW model, from UnitModelTableData.xml."""
    t = open(os.path.join(modules, MAPPINGS), encoding='utf-8', errors='replace').read()
    out = {}
    for m in re.finditer(r'<UnitModelAnimation eGenericAnimation="(\w+)" model="%s" anim="([^"]+)" clip="([^"]+)"' % re.escape(model), t):
        out[m.group(1)] = (m.group(2), m.group(3))
    return out


def _segments(stack):
    """Joint stack -> (head, euler, tail): what goes on «J», «J_Base» and «J_RotateAxis»."""
    k = [i for i, (_, nm, _) in enumerate(stack) if nm in EULER]
    if not k:
        return stack, [], []
    return stack[:k[0]], stack[k[0]:k[-1] + 1], stack[k[-1] + 1:]


def _node(proto, name, mat):
    t, r, s = M.split(mat)
    b = copy.deepcopy(proto)
    b.update({'Name': N.set_string(name), 'Controller': -1, 'Children': [], 'Translation': M.set_vec(t),
              'Rotation': M.set_rot(r), 'Scale': float(s)})
    return b


def build_skeleton(n, sc, root_joint='NewRig'):
    """Replaces the MH1 skeleton and meshes under «<Unit> NonAccum» with the TGW joints. -> {joint: (J, J_Base, deepest) names}"""
    def nonaccum():
        return next(i for i, b in enumerate(n.blocks) if b['_type'] == 'NiNode' and M.name(b).endswith('NonAccum'))
    n.blocks[nonaccum()]['Children'] = []
    n.compact()     # drop the MH1 skeleton now: the skin binds bones by name and must not find the old nodes
    acc = nonaccum()
    proto = n.blocks[acc]
    kids = {}
    for j, p in sc['parents'].items():
        kids.setdefault(p, []).append(j)
    out = {}

    def add(j, parent_idx):
        head, eul, tail = _segments(sc['stacks'].get(j, []))
        names = [j, j + '_Base'] + ([j + '_RotateAxis'] if tail else [])
        idx = parent_idx
        for nm, seg in zip(names, (head, eul, tail)):
            i = n.add(_node(proto, nm, nst_model.matrix(seg)))
            n.blocks[idx]['Children'].append(i)
            idx = i
        out[j] = (names[0], names[1], names[-1])
        for c in kids.get(j, []):
            add(c, idx)
    add(root_joint, acc)
    return out


def _euler_ok(stack):
    order = [nm for _, nm, _ in _segments(stack)[1]]
    return order == [x for x in ('rotateZ', 'rotateY', 'rotateX') if x in order]


def convert_skinned(nst_path, template_nif, out_nif, modules=TGW_MODULES, template_kf=None, out_kf=None):
    """Skinned unit (TGW infantry): NIF with the TGW skeleton and meshes + .kf with the TGW clips. Returns a report."""
    ms, sc = meshes(nst_path)
    ms = [m for m in ms if m['skin']]
    if not ms:
        raise ValueError('%s: sin mallas con piel' % os.path.basename(nst_path))
    n = N.Nif.load(template_nif)
    joints = build_skeleton(n, sc)
    bad = [j for j in joints if not _euler_ok(sc['stacks'].get(j, []))]
    for m in ms:    # the skin binds to the deepest node of each joint (its full Maya matrix)
        m['skin']['joints'] = [joints[j][2] for j in m['skin']['joints']]
        _four_bones(m['skin'], m['tris'])
    rep = M.import_meshes(n, ms, keep=('__none__',))
    os.makedirs(os.path.dirname(out_nif) or '.', exist_ok=True)
    n.save(out_nif)
    rep['joints'] = len(joints)
    rep['euler_order_warnings'] = bad
    if out_kf:
        model = os.path.splitext(os.path.basename(nst_path))[0]
        rep['kf'] = build_kf(sc, joints, animations(modules, model), os.path.dirname(nst_path),
                             template_kf or os.path.join(MH1_3D, 'Infantry', 'Infantry.kf'), out_kf)
    return rep


def _four_bones(sk, tris):
    """Gamebryo skin partitions hold 4 bones: a triangle touching more keeps its 4 strongest (weights renormalized)."""
    J, W = sk['J'], sk['W'].copy()
    for t in tris:
        tot = {}
        for v in t:
            for k in range(J.shape[1]):
                if W[v, k] > 0:
                    tot[J[v, k]] = tot.get(J[v, k], 0) + W[v, k]
        if len(tot) <= 4:
            continue
        top = sorted(tot, key=tot.get, reverse=True)[:4]
        for v in t:
            keep = np.isin(J[v], top) & (W[v] > 0)
            if not keep.any():      # none of its bones survive: the triangle's strongest takes it
                J[v, 0], W[v] = top[0], [1, 0, 0, 0]
                continue
            W[v] = np.where(keep, W[v], 0)
            W[v] /= W[v].sum()
    sk['W'] = W


def _clip_tracks(clip):
    """TGW clip -> ({(joint, element[, axis]): [(t, values...)]}, start, end). All clips of a file share one timeline;
    a clip is the range [start, end] of it (start == end: a still pose, as the Idle ones)."""
    t0, t1 = clip['start'], clip['end']
    tr = {}
    for c in clip['channels']:
        if c['element'] is None:
            continue
        # key = time, value(s), and for Bezier samplers the in / out tangents (dropped: linear between keys)
        v = c['values'].reshape(c['nkeys'], -1)[:, :1 + c['dim']].astype(float)
        ts = np.unique(np.r_[t0, v[(v[:, 0] > t0) & (v[:, 0] < t1), 0], t1])
        v = np.column_stack([ts] + [np.interp(ts, v[:, 0], v[:, 1 + d]) for d in range(c['dim'])])
        if c['element'] == 'translate' and c['component'] in (2, 3, 4):
            tr[(c['node'], 'translate', c['component'] - 2)] = v
        else:
            tr[(c['node'], c['element'])] = v
    return tr, float(t0), float(t1)


def build_kf(sc, joints, anims, models_dir, template_kf, out_kf):
    """Old-style .kf (v10.1, like MH1's Infantry.kf) with one sequence per MH1 name (Shoot, Move, Idle)."""
    k = N.Nif.load(template_kf)
    seqs = {N.string(b['Name']): i for i, b in enumerate(k.blocks) if b['_type'] == 'NiControllerSequence'}
    clips_cache = {}
    notes = []
    for seq_name, gen in SEQUENCES.items():
        if seq_name not in seqs or gen not in anims:
            notes.append('%s: sin clip' % seq_name)
            continue
        afile, cname = anims[gen]
        if afile not in clips_cache:
            clips_cache[afile] = {c['name']: c for c in nst_model.Nst(os.path.join(models_dir, afile + '.nst')).clips()}
        clip = clips_cache[afile].get(cname)
        if clip is None:
            notes.append('%s: falta el clip %s en %s' % (seq_name, cname, afile))
            continue
        tr, t0, t1 = _clip_tracks(clip)
        dur = max(t1 - t0, 1e-3)
        sb = k.blocks[seqs[seq_name]]
        proto_c = k.blocks[sb['Controlled Blocks'][0]['Controller']]
        blocks = [cb for cb in sb['Controlled Blocks'] if N.string(cb['Target Name']).startswith(('Infantry', ))]   # accum root: keep
        for j, (jn, jb, _) in joints.items():
            stack = sc['stacks'].get(j, [])
            # J: translation keys (TGW 'translate' channel, else the rest value)
            head = _segments(stack)[0]
            rest_t = M.split(nst_model.matrix(head))[0]
            tv = tr.get((j, 'translate'))
            axes = {a: tr[(j, 'translate', a)] for a in range(3) if (j, 'translate', a) in tr}
            if tv is None and axes:     # separate X / Y / Z curves: merged on the union of their key times
                ts = np.unique(np.concatenate([v[:, 0] for v in axes.values()]))
                tv = np.column_stack([ts] + [np.interp(ts, axes[a][:, 0], axes[a][:, 1]) if a in axes else np.full(len(ts), rest_t[a])
                                             for a in range(3)])
            keys = [(float(r[0]) - t0, r[1:4]) for r in tv] if tv is not None else [(0.0, rest_t), (dur, rest_t)]
            data = {'_type': 'NiKeyframeData', 'Num Rotation Keys': 0, 'Quaternion Keys': [],
                    'Translations': {'Num Keys': len(keys), 'Interpolation': 1,
                                     'Keys': [{'Time': t, 'Value': M.set_vec(v)} for t, v in keys]},
                    'Scales': {'Num Keys': 0, 'Keys': []}}
            blocks.append(_controlled(k, proto_c, jn, data, dur))
            # J_Base: XYZ Euler keys (radians) from rotateX / rotateY / rotateZ
            rest = {nm: v[3] for _, nm, v in _segments(stack)[1]}
            xyz = []
            for ax in EULER:
                v = tr.get((j, ax))
                ks = [(float(r[0]) - t0, float(np.radians(r[1]))) for r in v] if v is not None \
                    else [(0.0, float(np.radians(rest.get(ax, 0.0)))), (dur, float(np.radians(rest.get(ax, 0.0))))]
                xyz.append({'Num Keys': len(ks), 'Interpolation': 1, 'Keys': [{'Time': t, 'Value': a} for t, a in ks]})
            data = {'_type': 'NiKeyframeData', 'Num Rotation Keys': 1, 'Rotation Type': 4, 'Order': 0.0, 'XYZ Rotations': xyz,
                    'Translations': {'Num Keys': 0, 'Keys': []}, 'Scales': {'Num Keys': 0, 'Keys': []}}
            blocks.append(_controlled(k, proto_c, jb, data, dur))
        sb['Controlled Blocks'] = blocks
        sb['Num Controlled Blocks'] = len(blocks)
        if sb.get('Text Keys', -1) >= 0:
            tk = k.blocks[sb['Text Keys']]
            for key in tk['Text Keys']:
                if N.string(key['Value']) == 'end':
                    key['Time'] = dur
        notes.append('%s <- %s/%s (%.2f s, %d canales)' % (seq_name, afile, cname, dur, len(tr)))
    k.compact()
    os.makedirs(os.path.dirname(out_kf) or '.', exist_ok=True)
    k.save(out_kf)
    N.Nif.load(out_kf)     # reads back
    return notes


def _controlled(k, proto_c, target, data, dur):
    c = dict(proto_c)
    c.update({'Next Controller': -1, 'Start Time': 0.0, 'Stop Time': dur, 'Target': -1, 'Data': k.add(data)})
    return {'Target Name': N.set_string(target), 'Controller': k.add(c)}


# ------------------------------------------------------------------ install in a converted scenario
GAME_SYS = os.path.dirname(os.path.dirname(os.path.dirname(MH1_3D)))      # .../Modern Europe/system
# prefix of the MH1 sprite name -> TGW / SWW country set (eCountrySet of UnitModelTableData.xml)
COUNTRY_SETS = {'German': 'German', 'UK': 'British', 'French': 'French', 'USA': 'American', 'US': 'American', 'USSR': 'Russian',
                'Italian': 'Italian', 'Italy': 'Italian', 'Japanese': 'Japanese', 'Japan': 'Japanese', 'Turkey': 'Turkish',
                'Polish': 'Polish', 'Romanian': 'Romanian', 'Romania': 'Romanian', 'Finnish': 'Finnish', 'Anzac': 'Anzac',
                'India': 'Indian', 'South Asian': 'Indian', 'African': 'Senegalese', 'North African': 'Moroccan', 'Com China': 'Chinese',
                'Nat China': 'Chinese', 'Nat Spain': 'Spanish', 'Rep Spain': 'Spanish', 'Czech': 'Czech', 'Dutch': 'Dutch',
                'Generic1': 'Serbian', 'Generic2': 'Belgian', 'Generic3': 'Greek', 'Generic4': 'Bulgarian', 'Generic': 'British'}
# kind at the end of the MH1 sprite name -> TGW / SWW unit templates (sd.X; the first one the game has); infantry is skinned
# (own .kf), the rest rigid
SPRITE_KINDS = [('Idle Infantry', ('Infantry1',)), ('Marching Infantry', ('Infantry1',)), ('Infantry', ('Infantry1',)),
                ('Early Tanks', ('Tanks1', 'EarlyTanks')), ('Light Tanks', ('Tanks1', 'LightTanks1')),
                ('Heavy Tanks', ('Tanks2', 'HeavyTanks1')), ('Advanced Tanks', ('Tanks3', 'MediumTanks2')),
                ('Light Artillery', ('FieldArtillery', 'LightHowitzers1')), ('Field Artillery', ('FieldArtillery', 'FieldArtillery1')),
                ('Heavy Artillery', ('HeavySiegeGuns', 'HeavyArtillery1')),
                ('Basic Fighters', ('Fighters1',)), ('Improved Fighters', ('Fighters3',)), ('Advanced Fighters', ('Fighters5',)),
                ('Light Bombers', ('LightBombers1',)), ('Medium Bombers', ('Bombers1', 'MediumBombers1')),
                ('Heavy Bombers', ('HeavyBombers1',)), ('Strategic Bombers', ('StrategicBombers1', 'HeavyBombers1')),
                ('Basic Battleship', ('PreDreadnoughtBattleship',)), ('Fast Battleship', ('FastBattleship', 'Dreadnought')),
                ('Advanced Battleship', ('StandardBattleship',)), ('Battle Cruiser', ('Battlecruiser', 'Battlecruiser2')),
                ('Large Cruiser', ('LargeCruiser', 'HeavyCruiser')), ('Heavy Cruiser', ('ArmoredCruiser', 'HeavyCruiser1')),
                ('Escort Destroyer', ('TorpedoBoatDestroyer', 'EarlyDestroyer')), ('Corvette Destroyer', ('EscortDestroyer', 'Corvette')),
                ('Destroyer', ('Destroyer', 'Destroyer1')), ('Early Carrier', ('EarlyCarrier',)),
                ('Basic Submarine Submerged', ('CoastalSubmarine', 'EarlySubmarine')), ('Transport', ('Troopship',)),
                ('Escort Group', ('TorpedoBoatDestroyer', 'EarlyDestroyer'))]
SKINNED = ('Infantry1',)
INFANTRY_TEMPLATE = os.path.join(MH1_3D, 'Infantry', 'German-Infantry.nif')
SPRITE_FILES = ('SpriteLibLandUnits.xml', 'SpriteLibAirUnits.xml', 'SpriteLibSeaUnits.xml')
_SPRITE = r'<object type="Sprite" name="objSprites">\s*<property name="strName" value="%s"/>\s*<property name="fileName" value="([^"]+)"/>'


def model_for(modules, tmpl, cset):
    """TGW / SWW model for unit template sd.<tmpl> of a country set (the Generic one if the set has none), or None."""
    t = open(os.path.join(modules, MAPPINGS), encoding='utf-8', errors='replace').read()
    for s in (cset, 'Generic'):
        m = re.search(r'tmplUnit="sd\.%s" eCountrySet="%s" base="([^"]+)"' % (re.escape(tmpl), re.escape(s)), t)
        if m and os.path.isfile(os.path.join(modules, MODELS, m.group(1) + '.nst')):
            return m.group(1)
    return None


def plan(modules=TGW_MODULES, sprite_dir=None):
    """[(MH1 sprite, its .nif path relative to system/, TGW model, skinned)] for every MH1 unit sprite with a TGW model."""
    sprite_dir = sprite_dir or os.path.join(GAME_SYS, 'DisplayLibraries', 'SpriteLibraries')
    out = []
    for f in SPRITE_FILES:
        t = open(os.path.join(sprite_dir, f), encoding='utf-8', errors='replace').read()
        for m in re.finditer(_SPRITE % '([^"]+)', t):
            name, fn = m.group(1), m.group(2)
            kind = None if name.endswith('Wake') else next(((k, tm) for k, tm in SPRITE_KINDS if name.endswith(' ' + k)), None)
            prefix = kind and name[:-len(kind[0]) - 1]
            if not kind or prefix not in COUNTRY_SETS or '/system/' not in fn:     # e.g. «German Mounted Infantry»: not this kind
                continue
            model = next((m for m in (model_for(modules, tm, COUNTRY_SETS[prefix]) for tm in kind[1]) if m), None)
            if model:
                out.append((name, fn.replace('\\', '/').split('/system/', 1)[1], model, kind[1][0] in SKINNED))
    return out


def install(scen_dir, modules=TGW_MODULES, progress=None):
    """Gives a converted scenario the TGW / SWW unit models: writes ui/art/3D/TGW/<model>.nif (+ .kf for infantry) inside
    the scenario and its own DisplayLibraries (copy of the game's if it has none) with the matched sprites pointing there.
    Only touches scen_dir. Returns notes."""
    import shutil
    tick = progress or (lambda pct, msg: None)
    dl = os.path.join(scen_dir, 'DisplayLibraries')
    notes = []
    if not os.path.isfile(os.path.join(dl, 'SpriteLibraries.xml')):
        os.makedirs(dl, exist_ok=True)
        src = os.path.join(GAME_SYS, 'DisplayLibraries')
        for root, _, files in os.walk(src):
            for f in files:
                if f.lower().endswith('.xml'):
                    shutil.copy2(os.path.join(root, f), os.path.join(dl, f))
        notes.append('DisplayLibraries copiadas del juego')
    out3d = os.path.join(scen_dir, 'ui', 'art', '3D', 'TGW')
    rows = plan(modules, dl)
    done = {}
    for k, (sprite, rel, model, skinned) in enumerate(rows):
        tick(5 + 90 * k // max(len(rows), 1), 'Modelo %s' % model)
        if model not in done:
            nst = os.path.join(modules, MODELS, model + '.nst')
            nif_out = os.path.join(out3d, model + '.nif')
            try:
                if skinned:     # the Idle / Marching infantry .nif of MH1 are static or partial: always the full one
                    convert_skinned(nst, INFANTRY_TEMPLATE, nif_out, modules, out_kf=os.path.join(out3d, model + '.kf'))
                else:
                    convert(nst, os.path.join(GAME_SYS, rel), nif_out, turn='Artillery' in sprite)
                done[model] = True
            except Exception as e:     # one bad model must not stop the rest
                done[model] = False
                notes.append('%s: no convertido (%r)' % (model, e))
        if done[model]:
            _point_sprite(dl, sprite, model, skinned)
    notes.append('%d sprites con modelo TGW (%d modelos)' % (sum(done[m] for _, _, m, _ in rows), sum(done.values())))
    return notes


def _point_sprite(dl, sprite, model, skinned):
    """Sprite «sprite» of the scenario's SpriteLib*.xml -> ui/art/3D/TGW/<model>.nif (and its .kf for infantry)."""
    base = '/../Modern Europe/system/ui/art/3D/TGW/' + model
    for f in SPRITE_FILES:
        p = os.path.join(dl, f)
        t = open(p, encoding='utf-8', errors='replace').read()
        m = re.search(_SPRITE % re.escape(sprite), t)
        if not m:
            continue
        end = t.find('\n\t</object>', m.end())
        body = t[m.end():end]
        if skinned:     # the sprite's animations (none for Idle, «March» for Marching) -> the three sequences of the TGW .kf
            body = re.sub(r'\s*<object type="AnimationData".*?</object>', '', body, flags=re.S) + ''.join(
                '\n\t\t<object type="AnimationData" name="objAnimations">\n\t\t\t<property name="strName" value="%s"/>\n'
                '\t\t\t<property name="fileName" value="%s.kf"/>\n\t\t\t<property name="strSequenceName" value="%s"/>\n\t\t</object>'
                % (a, base, s) for a, s in (('Attack', 'Shoot'), ('Move', 'Move'), ('Idle', 'Idle')))
        t = t[:m.start(1)] + base + '.nif' + t[m.end(1):m.end()] + body + t[end:]
        open(p, 'w', encoding='utf-8').write(t)
        return
