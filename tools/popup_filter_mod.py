"""Optional popups mod for Making History I / Gold.

Informational pop-out notifications (FeedbackRefPopOut) that are not in the "important" list are marked as read
without opening a window; they stay visible in the End Turn panel on the right (their End_of_Turn twin, or a new
"Other notices" list for types that have no twin). Treaty proposals / decision points and scripted player decisions
always pop up.

The mod is one generated file, UI/PopupFilterMod.xml, plus one line in UI/namespace.xml. It is built from the
game's own installed UI files, so nothing from the game is shipped and the originals are never modified.

    python tools/popup_filter_mod.py install   [--game mh1|gold|all] [--keep TYPE ...] [--drop TYPE ...] [--title TEXT]
    python tools/popup_filter_mod.py uninstall [--game ...]
    python tools/popup_filter_mod.py list      # every pop-out type and whether it pops up
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gamepaths  # noqa: E402

MOD_FILE = 'PopupFilterMod.xml'
NS_LINE = '\t<file name="%s"/>\r\n' % MOD_FILE

# Pop-out types that still open a window by default: things done *to* the player.
IMPORTANT = [
    'GENERIC_WarDeclareCountryToCountry_PlayerTargetted',
    'GENERIC_WarDeclareAllianceToCountry_PlayerTargetted',
    'GENERIC_WarDeclareCountryToAlliance_PlayerAllianceTargetted',
    'GENERIC_WarDeclareAllianceToAlliance_PlayerAllianceTargetted',
    'War_Declare_SelfAlliance_Target',
    'GENERIC_JoinAlliance_CountryJoiningEnemyAlliance',
    'GENERIC_Embargo_PlayerTargetted',
    'GENERIC_CityNuked_CityController',
    'GENERIC_CityNuked_CityOwner',
    'GENERIC_IndependenceGranted_PlayerTargetted',
]


def systems(which):
    keys = ['mh1', 'gold'] if which == 'all' else [which]
    return [(k, os.path.join(gamepaths.path(k), 'Modern Europe', 'system')) for k in keys if gamepaths.installed(k)]


def read(path):
    with open(path, encoding='utf-8', newline='') as f:  # keep the game's CRLF
        return f.read()


def object_def(text, name):
    """Return the full <objectDef type="name" ...>...</objectDef> block (objectDefs are not nested)."""
    m = re.search(r'[ \t]*<objectDef type="%s"[^>]*>.*?</objectDef>' % re.escape(name), text, re.S)
    if not m:
        raise SystemExit('objectDef %s not found' % name)
    return m.group(0)


def popout_types(system):
    """{type: has End_of_Turn twin} from ScenarioDefaults/sharedData.xml."""
    s = read(os.path.join(system, 'ScenarioDefaults', 'sharedData.xml'))
    sets = {}
    for t, ts in re.findall(r'name="strType" value="([^"]+)"/>\s*<property name="strTemplateSet" value="([^"]+)"/>', s):
        sets.setdefault(t, set()).add(ts)
    return {t: 'End_of_Turn' in v for t, v in sets.items() if 'PopOut' in v}


def any_of(var, types):
    return ' OR '.join("%s == '%s'" % (var, t) for t in types) or 'false'


def build(system, important, title):
    ui = os.path.join(system, 'UI')
    twinned = sorted(t for t, twin in popout_types(system).items() if twin)

    # 1. Event notification popup: only build the window for important types, auto-read the rest.
    en = object_def(read(os.path.join(ui, 'UI2DEventNotification', 'UI2DEventNotification.xml')), 'UI2DEventNotification')
    anchor = '<propertyDef name="objNamedUIPanel" type="Object" subType="NamedUIPanel"/>'
    assert anchor in en, 'UI2DEventNotification changed; update the mod'
    en = en.replace(anchor, anchor + '\n\t\t<propertyDef name="bImportant" type="bool"/>\n'
                    '\t\t<property name="bImportant" computeFrom="%s"/>'
                    % any_of('this.objEventNotification.strDerivedType', important), 1)
    en = en.replace('computeFrom="exists(this.objNamedUIPanel)"', 'computeFrom="this.bImportant AND exists(this.objNamedUIPanel)"')
    en = en.replace('computeFrom="!exists(this.objNamedUIPanel)"', 'computeFrom="this.bImportant AND !exists(this.objNamedUIPanel)"')
    assert en.count('this.bImportant AND') == 2, 'UI2DEventNotification changed; update the mod'
    en = en[:en.rindex('</objectDef>')].rstrip() + '''

\t\t<!-- PopupFilterMod: not important -> mark read at once, no window -->
\t\t<object name="objPopupFilterDismiss" type="CmdCreateAction">
\t\t\t<property name="bExecute" value="true"/>
\t\t\t<property name="bShouldExecute" computeFrom="!this.bImportant"/>
\t\t\t<object name="objAction" type="ActToggleFeedbackRead">
\t\t\t\t<property name="strManagerName" inheritFrom="objEventNotification.strDerivedSet"/>
\t\t\t\t<property name="nID" inheritFrom="objEventNotification.nID"/>
\t\t\t\t<property name="nFeedbackRefID" inheritFrom="objFeedbackRef.nID"/>
\t\t\t\t<property name="bRead" value="true"/>
\t\t\t</object>
\t\t</object>
\t</objectDef>'''

    # 2. "Other notices" list on the End Turn panel: suppressed pop-outs without an End_of_Turn twin.
    endturn_src = read(os.path.join(ui, 'UI2DPolicyAreaEndTurn.xml'))
    lst = object_def(endturn_src, 'UI2DInternationalEventList')
    lst = lst.replace('type="UI2DInternationalEventList"', 'type="UI2DPopupFilterNoticeList"', 1)
    lst = re.sub(r'\s*<object type="Selection" name="objSelectFeedbackRefs">.*?</object>', '', lst, count=1, flags=re.S)
    where = '{Object}input ISA FeedbackInstance AND !(%s)' % any_of('input.strDerivedType', important + twinned)
    lst, n = re.subn(
        r'(<object type="Selection" name="objTempSelection">\s*<property name="pathInput" value=")[^"]+'
        r'("/>\s*<property name="pathOutput" value="objNotifications"/>\s*<property name="expWhere" value=")[^"]+(")',
        lambda m: m.group(1) + '.objDriver.objMyAvatar.objPlayer.objData.objCurrentNotificationList.objPopOutFeedback'
        + m.group(2) + where + m.group(3), lst, count=1, flags=re.S)
    assert n == 1, 'UI2DInternationalEventList changed; update the mod'
    lst = lst.replace('computeFrom="getString(SID.UI.UI2DPolicyAreaEndTurn.UI2DInternationalEventList.Title)"',
                      'value="%s"' % title.replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;'), 1)

    endturn = object_def(endturn_src, 'UI2DPolicyAreaEndTurn')
    anchor = '<object type="UI2DNationalEventList" name="objElements">'
    assert anchor in endturn, 'UI2DPolicyAreaEndTurn changed; update the mod'
    endturn = endturn.replace(anchor, '<object type="UI2DPopupFilterNoticeList" name="objElements">\n\t\t\t\t</object>\n\n\t\t\t\t' + anchor, 1)

    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!-- PopupFilterMod: generated by MHEditor tools/popup_filter_mod.py from this install\'s UI files. -->\n'
            '<objectDefs name="core" version="0.1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n\n'
            + en + '\n\n' + lst + '\n\n' + endturn + '\n\n</objectDefs>\n')


def install(system, important, title):
    ui = os.path.join(system, 'UI')
    with open(os.path.join(ui, MOD_FILE), 'w', encoding='utf-8') as f:
        f.write(build(system, important, title))
    ns_path = os.path.join(ui, 'namespace.xml')
    ns = read(ns_path)
    if MOD_FILE not in ns:
        # the schema wants every <file> before <stringTable>/<defEnum>: insert after the last <file .../>
        last = list(re.finditer(r'<file [^>]*/>[^\n]*\n', ns))[-1]
        with open(ns_path, 'w', encoding='utf-8', newline='') as f:
            f.write(ns[:last.end()] + NS_LINE + ns[last.end():])


def uninstall(system):
    ui = os.path.join(system, 'UI')
    ns_path = os.path.join(ui, 'namespace.xml')
    ns = read(ns_path)
    if MOD_FILE in ns:
        with open(ns_path, 'w', encoding='utf-8', newline='') as f:
            f.write(re.sub(r'[ \t]*<file name="%s"/>\r?\n?' % re.escape(MOD_FILE), '', ns))
    p = os.path.join(ui, MOD_FILE)
    if os.path.exists(p):
        os.remove(p)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('action', choices=['install', 'uninstall', 'list'])
    ap.add_argument('--game', choices=['mh1', 'gold', 'all'], default='all')
    ap.add_argument('--keep', nargs='*', default=[], help='extra pop-out types that still open a window')
    ap.add_argument('--drop', nargs='*', default=[], help='default-important types to send to the panel instead')
    ap.add_argument('--title', default='Other notices', help='title of the new list on the End Turn panel')
    a = ap.parse_args()
    important = [t for t in IMPORTANT if t not in a.drop] + [t for t in a.keep if t not in IMPORTANT]
    found = systems(a.game)
    if not found:
        raise SystemExit('game not found')
    for key, system in found:
        if a.action == 'list':
            for t, twin in sorted(popout_types(system).items()):
                print('%-6s %-11s %s' % ('POPUP' if t in important else 'panel', 'end-of-turn' if twin else 'other-list', t))
            print('(scenario-specific pop-outs go to the other list; proposals and decisions always pop up)')
            return
        install(system, important, a.title) if a.action == 'install' else uninstall(system)
        print('%s: %s (%s)' % (a.action, key, system))


if __name__ == '__main__':
    main()
