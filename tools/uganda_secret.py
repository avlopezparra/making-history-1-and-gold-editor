"""Uganda jugable + investigación secreta «Secret Weapon» (unidad Ugandan Knuckles) en un escenario donde Uganda ya existe.

    python tools/uganda_secret.py <carpeta del escenario> <carpeta con Uganda Knuckles.nif/.kf y su Sprite>

Edita la carpeta dada en sitio (usar sobre una copia; instalar aparte con copia de seguridad).
Los demás países ven «Secret Weapon» y su requisito «Classified», pero el requisito es inalcanzable
y nada dice qué es; solo Uganda empieza con «Classified» completado.
"""
import re
import shutil
import sys
import xml.dom.minidom
from pathlib import Path

S, SRC = Path(sys.argv[1]), Path(sys.argv[2])
TURNS = 15
CRLF = {}


def rd(n):
    raw = (S / n).read_bytes()
    CRLF[n] = b'\r\n' in raw
    return raw.decode('utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8').replace('\r\n', '\n')


def wr(n, t):
    (S / n).write_text(t, encoding='utf-8', newline='\r\n' if CRLF.get(n, True) else '\n')


def block(text, pat):
    i = text.index(pat)
    a = text.rfind('\n', 0, text.rfind('<object ', 0, i)) + 1
    depth = 0
    for m in re.finditer(r'<object\b[^>]*?(/?)>|</object>', text[a:]):
        depth += -1 if m.group(0).startswith('</') else (0 if m.group(1) else 1)
        if depth == 0:
            return a, text.index('\n', a + m.end()) + 1


# --- jugable
c = rd('countryUganda.xml')
c = re.sub(r'(<property name="bNonPlayable" value=")true', r'\1false', c, count=1)
wr('countryUganda.xml', c)
ipus = max(int(x) for x in re.findall(r'<property name="nIPUs" value="(\d+)"', c))

gs = rd('gamestate.xml')
a, b = block(gs, '<property name="strName" value="Uganda" />' if 'value="Uganda" />' in gs else '<property name="strName" value="Uganda"/>')
gs = gs[:a] + re.sub(r'(bNonPlayable" value=")true', r'\1false', gs[a:b]) + gs[b:]
wr('gamestate.xml', gs)

pl = rd('playerUganda.xml')
if 'value="Playable"' not in pl:
    pl = pl.replace('<property name="strHLPDefLists" value="Default"/>',
                    '<property name="strHLPDefLists" value="Default"/>\n\t\t<property name="strHLPDefLists" value="Playable"/>\n'
                    '\t\t<property name="strPLPDefLists" value="Playable"/>', 1)
if 'value="Classified"' not in pl:
    i = pl.find('\t\t<object type="DipRelInitialValueList"')
    i = i if i >= 0 else pl.rindex('\t</object>\n</objects>')
    pl = pl[:i] + ('\t\t<object type="ResearchProjectInitRef" name="objInitResearchRefs">\n'
                   '\t\t\t<property name="strProjectName" value="Classified"/>\n'
                   '\t\t\t<property name="eResearchState" value="RESEARCH_COMPLETED"/>\n'
                   '\t\t</object>\n') + pl[i:]
wr('playerUganda.xml', pl)

# --- textos (sin decir qué es)
st = rd('game/stringTable.xml')
strings = {
    'SID.Game.ResearchProject.Name.Classified': 'Classified',
    'SID.Game.ResearchProject.Desc.Classified': 'Classified.',
    'SID.Game.ResearchProject.Effect.Classified': 'Classified.',
    'SID.Game.ResearchProject.Name.SecretWeapon': 'Secret Weapon',
    'SID.Game.ResearchProject.Desc.SecretWeapon': 'Classified.',
    'SID.Game.ResearchProject.Effect.SecretWeapon': 'Classified.',
    'SID.Game.FactoryOutput.Name.UgandanKnuckles': 'Ugandan Knuckles',
    'SID.Game.FactoryOutput.Desc.UgandanKnuckles': 'Takes %d turns in Kampala. One division wipes out whole armies.' % TURNS,
    'SID.Game.UnitTemplate.Name.UgandanKnuckles': 'Ugandan Knuckles',
}
st = st.replace('</stringTable>', ''.join('\t<string id="%s" value="%s"/>\n' % kv for kv in strings.items()
                                          if 'id="%s"' % kv[0] not in st) + '</stringTable>')
wr('game/stringTable.xml', st)

# --- investigación
rs = rd('sharedDataResearch.xml')
if 'value="SecretWeapon"' not in rs:
    end = '\t\t</object>\n\t</object>\n</objects>'
    assert rs.rstrip('\n').endswith(end)
    rs = rs[:rs.rindex(end)] + '''			<object type="ResearchProjNoOp" name="objResearchProjects">
				<property name="strName" value="Classified"/>
				<property name="strIconName" value="Militia"/>
				<property name="sidDisplayName" value="SID.Game.ResearchProject.Name.Classified"/>
				<property name="sidDescription" value="SID.Game.ResearchProject.Desc.Classified"/>
				<property name="nCost" value="2000000000"/>
				<property name="nResearchPoints" value="99999"/>
				<property name="nNeededIPUs" value="99999"/>
				<property name="strBranchName" value="RESEARCH_BRANCH_LAND"/>
				<property name="strProgramName" value="RESEARCH_PROGRAM_INFANTRY"/>
				<property name="sidEffect" value="SID.Game.ResearchProject.Effect.Classified"/>
			</object>
			<object type="ResearchProjFactoryOutput" name="objResearchProjects">
				<property name="strName" value="SecretWeapon"/>
				<property name="strIconName" value="Militia"/>
				<property name="sidDisplayName" value="SID.Game.ResearchProject.Name.SecretWeapon"/>
				<property name="sidDescription" value="SID.Game.ResearchProject.Desc.SecretWeapon"/>
				<property name="nCost" value="1000000"/>
				<property name="nResearchPoints" value="10"/>
				<property name="nNeededIPUs" value="8"/>
				<property name="strBranchName" value="RESEARCH_BRANCH_LAND"/>
				<property name="strProgramName" value="RESEARCH_PROGRAM_INFANTRY"/>
				<property name="sidEffect" value="SID.Game.ResearchProject.Effect.SecretWeapon"/>
				<object type="ResearchProjectPreReq" name="objPreReqs">
					<property name="strProjectName" value="Classified"/>
				</object>
				<object type="ResearchFactoryOutputAvailableData" name="objAvailableFactoryOutputs">
					<property name="strFactoryOutputName" value="UgandanKnuckles"/>
				</object>
			</object>
''' + end + '\n'
    wr('sharedDataResearch.xml', rs)

# --- fábrica, plantilla, gráficos
fa = rd('sharedDataFactories.xml')
if 'value="UgandanKnuckles"' not in fa:
    _, b = block(fa, '<property name="strUnitType" value="Militia"/>')
    fa = fa[:b] + '''			<object type="FactoryOutputUnit" name="objFactoryOutputs">
				<property name="strName" value="UgandanKnuckles"/>
				<property name="strIconName" value="Infantry"/>
				<property name="strDisplayCategory" value="Infantry Division"/>
				<property name="sidDisplayName" value="SID.Game.FactoryOutput.Name.UgandanKnuckles"/>
				<property name="sidDescription" value="SID.Game.FactoryOutput.Desc.UgandanKnuckles"/>
				<property name="nTechLevel" value="1"/>
				<property name="nIPUsRequired" value="%d"/>
				<property name="nMPUsRequired" value="10"/>
				<property name="nBuildCost" value="3000000"/>
				<property name="eDisplayFlags" value="FACTORY_OUTPUT_DISPLAY_LAND_UNIT"/>
				<property name="strUnitType" value="UgandanKnuckles"/>
			</object>
''' % (TURNS * ipus) + fa[b:]
    wr('sharedDataFactories.xml', fa)

ut = rd('sharedDataUnitTemplates.xml')
if 'value="UgandanKnuckles"' not in ut:
    _, b = block(ut, '<property name="strName" value="Militia"/>')
    ut = ut[:b] + '''			<object type="UnitTemplate" name="objUnitTemplates">
				<property name="strName" value="UgandanKnuckles"/>
				<property name="strIconName" value="Infantry"/>
				<property name="sidDisplayName" value="SID.Game.UnitTemplate.Name.UgandanKnuckles"/>
				<property name="eType" value="UNIT_TYPE_ARMY"/>
				<property name="eUnitCategory" value="UNIT_CATEGORY_INFANTRY"/>
				<property name="nSpeed" value="300"/>
				<property name="nHitPoints" value="40"/>
				<property name="nAttackPower" value="30"/>
				<property name="nAirHitPercent" value="60"/>
				<property name="nLandHitPercent" value="100"/>
				<property name="nResistance" value="90"/>
				<property name="nMen" value="10"/>
				<property name="nSupplyArms" value="1"/>
				<property name="nActiveArms" value="1"/>
				<property name="nMaintenanceCost" value="300000"/>
			</object>
''' + ut[b:]
    wr('sharedDataUnitTemplates.xml', ut)

us = rd('sharedDataUnitTemplateSprites.xml')
if 'UgandanKnuckles' not in us:
    us = re.sub(r'(\n(\s*)<property name="strTemplateNames" value="Militia" ?/>)',
                r'\1\n\2<property name="strTemplateNames" value="UgandanKnuckles"/>', us)
    wr('sharedDataUnitTemplateSprites.xml', us)

node = '''		<object type="MKDNode" name="objNodes">
			<property name="strKey" value="UgandanKnuckles"/>
			<object type="SpriteRefName" name="objDefault">
				<property name="strSpriteName" value="%s"/>
			</object>
		</object>
'''
for f, spr in (('MKDTableUnitTemplatesLand.xml', 'Uganda Knuckles'), ('MKDTableUnitTemplatesLandCombat.xml', 'Uganda Knuckles'),
               ('MKDTableUnitTemplatesLandDecals.xml', 'Infantry Base')):
    f = 'DisplayLibraries/' + f
    t = rd(f)
    if 'UgandanKnuckles' not in t:
        a, _ = block(t, re.search(r'<property name="strKey" value="Militia" ?/>', t).group(0))
        wr(f, t[:a] + node % spr + t[a:])

sl = rd('DisplayLibraries/SpriteLibLandUnits.xml')
if 'Uganda Knuckles' not in sl:
    tm = (SRC / 'DisplayLibraries/SpriteLibLandUnits.xml').read_text(encoding='utf-8').replace('\r\n', '\n')
    a, b = block(tm, '<property name="strName" value="Uganda Knuckles"/>')
    i = sl.rfind('\n', 0, sl.index('<object type="Sprite"')) + 1
    wr('DisplayLibraries/SpriteLibLandUnits.xml', sl[:i] + '<!-- Uganda Knuckles -->\n' + tm[a:b] + sl[i:])

(S / 'ui/art/3D/Custom').mkdir(parents=True, exist_ok=True)
for ext in ('nif', 'kf'):
    shutil.copy2(SRC / ('ui/art/3D/Custom/Uganda Knuckles.' + ext), S / 'ui/art/3D/Custom')

for f in list(CRLF):
    xml.dom.minidom.parse(str(S / f))
print('OK  Kampala %d IPU -> %d IPU por unidad' % (ipus, TURNS * ipus))
