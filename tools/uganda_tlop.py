"""Uganda jugable + tecnología exclusiva «Ugandan Knuckles» en The Limits of Piss 31.12.2021.

    python tools/uganda_tlop.py <carpeta del escenario> <carpeta TMWR (modelo, bandera, textos)>

Edita la carpeta dada en sitio (usar sobre una copia; instalar aparte con copia de seguridad).
"""
import re
import shutil
import sys
import xml.dom.minidom
from pathlib import Path

S = Path(sys.argv[1])
TMWR = Path(sys.argv[2])
C = 'Uganda'
TECH, UNIT, LOCK = 'UgandanKnuckles', 'UgandanKnuckles', 'DaWae'
KAMPALA_IPUS = 10
UNIT_IPUS = 150          # 15 turnos con la fábrica de Kampala (10 IPU)


CRLF = {}


def rd(n):
    raw = (S / n).read_bytes()
    CRLF[n] = b'\r\n' in raw
    return raw.decode('utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8').replace('\r\n', '\n')


def wr(n, t):
    (S / n).write_text(t, encoding='utf-8', newline='\r\n' if CRLF.get(n, True) else '\n')


def block(text, start_pat, opener='<object '):
    """Devuelve (ini, fin) del <object ...> que contiene la línea start_pat."""
    i = text.index(start_pat)
    a = text.rfind('\n', 0, text.rfind(opener, 0, i)) + 1
    depth, j = 0, a
    for m in re.finditer(r'<object\b[^>]*?(/?)>|</object>', text[a:]):
        if m.group(0).startswith('</'):
            depth -= 1
        elif not m.group(1):
            depth += 1
        if depth == 0:
            j = a + m.end()
            break
    j = text.index('\n', j) + 1
    return a, j


def insert_before(text, anchor, new):
    i = text.index(anchor)
    i = text.rfind('\n', 0, i) + 1
    return text[:i] + new + text[i:]


# --- 1. Sacar Uganda (región + ejército) de Reino Unido
uk = rd('countryUnited Kingdom.xml')
a, b = block(uk, '<property name="strName" value="Uganda"/>')
region = uk[a:b]
uk = uk[:a] + uk[b:]
a, b = block(uk, '<property name="strName" value="Uganda Defense Force"/>')
army = uk[a:b]
uk = uk[:a] + uk[b:]
wr('countryUnited Kingdom.xml', uk)

region = region.replace('value="United Kingdom"', 'value="%s"' % C)
region = re.sub(r'\s*<property name="bColony" value="true"/>', '', region)
region = re.sub(r'(<property name="nIPUs" value=")\d+', r'\g<1>%d' % KAMPALA_IPUS, region)
army = army.replace('value="United Kingdom"', 'value="%s"' % C)

country = '''<?xml version="1.0" encoding="UTF-8"?>
<objects name="Object Load" version="0.1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
	<object type="MECountry" name="">
		<property name="strName" value="Uganda"/>
		<property name="strGovType" value="Authoritarian"/>
		<property name="sidName" value="SID.Game.Country.Name.Uganda"/>
		<property name="sidPossessive" value="SID.Game.Country.Possessive.Uganda"/>
		<property name="sidAdjective" value="SID.Game.Country.Adjective.Uganda"/>
		<property name="sidPeople" value="SID.Game.Country.People.Uganda"/>
		<property name="sidAllianceName" value="SID.Game.Country.Alliance.Uganda"/>
		<property name="strHomelands" value="Uganda"/>
		<property name="bNonPlayable" value="false"/>
		<property name="strFlagName" value="Uganda"/>
		<property name="strCapital" value="Kampala"/>
		<property name="strOriginalCapital" value="Kampala"/>
''' + region.replace('\n\t\t', '\n\t\t') + army + '''		<object type="CultureSet" name="objCultureSet">
			<object type="Culture" name="objCultures">
				<property name="strCultureName" value="Bantu"/>
			</object>
		</object>
	</object>
</objects>
'''
wr('countryUganda.xml', country)

# --- 2. Jugador (plantilla: Brasil, jugable) + desbloqueo exclusivo
pl = rd('playerBrazil.xml').replace('value="Brazil"', 'value="%s"' % C)
pl = insert_before(pl, '<object type="DipRelInitialValueList"',
                   '\t\t<object type="ResearchProjectInitRef" name="objInitResearchRefs">\n'
                   '\t\t\t<property name="strProjectName" value="%s"/>\n'
                   '\t\t\t<property name="eResearchState" value="RESEARCH_COMPLETED"/>\n'
                   '\t\t</object>\n' % LOCK)
wr('playerUganda.xml', pl)

# --- 3. game.xml: cargar archivos + vista «minor»
g = rd('game.xml')
g = insert_before(g, 'fromFile="countryBurma.xml"',
                  '\t\t<object type="GO" name="objGOs" fromFile="countryUganda.xml">\n\t\t</object>\n'
                  '\t\t<object type="GO" name="objGOs" fromFile="playerUganda.xml">\n\t\t</object>\n')
g = insert_before(g, '<property name="strAliases" value="Burma"/>',
                  '\t\t\t<property name="strAliases" value="Uganda"/>\n')
wr('game.xml', g)

# --- 4. gamestate.xml: jugable en el lobby
gs = rd('gamestate.xml')
a, _ = block(gs, '<property name="strName" value="Burma"/>')
gs = gs[:a] + '''		<object type="Player" name="objPlayers">
			<property name="strName" value="Uganda"/>
			<property name="sidShortDescription" value="SID.Game.Country.Description.TheLimitsOfPiss31122021.Uganda"/>
			<property name="bNonPlayable" value="false"/>
			<property name="colCountryColor" value="#FCDC04FF"/>
		</object>
''' + gs[a:]
wr('gamestate.xml', gs)

# --- 5. Textos
st = rd('game/stringTable.xml')
strings = {
    'SID.Game.Country.Name.Uganda': 'Uganda',
    'SID.Game.Country.Possessive.Uganda': "Uganda's",
    'SID.Game.Country.Adjective.Uganda': 'Ugandan',
    'SID.Game.Country.People.Uganda': 'Ugandans',
    'SID.Game.Country.Alliance.Uganda': 'Ugandan Alliance',
    'SID.Game.Country.Description.TheLimitsOfPiss31122021.Uganda':
        'Leader: Da Queen. Unique tech: Ugandan Knuckles / Tecnología única: Ugandan Knuckles',
    'SID.Game.ResearchProject.Name.DaWae': 'Da Wae',
    'SID.Game.ResearchProject.Desc.DaWae': 'Only Uganda knows da wae. / Solo Uganda conoce da wae.',
    'SID.Game.ResearchProject.Effect.DaWae': 'Unlocks Ugandan Knuckles research. / Desbloquea Ugandan Knuckles.',
    'SID.Game.ResearchProject.Name.UgandanKnuckles': 'Ugandan Knuckles',
    'SID.Game.ResearchProject.Desc.UgandanKnuckles':
        'Uganda-only super soldiers. / Supersoldados exclusivos de Uganda.',
    'SID.Game.ResearchProject.Effect.UgandanKnuckles': 'Can build Ugandan Knuckles. / Permite construir Ugandan Knuckles.',
    'SID.Game.FactoryOutput.Name.UgandanKnuckles': 'Ugandan Knuckles',
    'SID.Game.FactoryOutput.Desc.UgandanKnuckles':
        'Takes 15 turns in Kampala; one division wipes out whole armies. / '
        '15 turnos en Kampala; una división aniquila ejércitos enteros.',
    'SID.Game.UnitTemplate.Name.UgandanKnuckles': 'Ugandan Knuckles',
}
add = ''.join('\t<string id="%s" value="%s"/>\n' % (k, v.replace("'", '&apos;'))
              for k, v in strings.items() if 'id="%s"' % k not in st)
st = st.replace('</stringTable>', add + '</stringTable>')
wr('game/stringTable.xml', st)

# --- 6. Investigación: «Da Wae» (inalcanzable para el resto) -> Ugandan Knuckles
rs = rd('sharedDataResearch.xml')
rs = rs.replace('\t\t</object>\n\t</object>\n</objects>', '''			<object type="ResearchProjNoOp" name="objResearchProjects">
				<property name="strName" value="DaWae"/>
				<property name="strIconName" value="Militia"/>
				<property name="sidDisplayName" value="SID.Game.ResearchProject.Name.DaWae"/>
				<property name="sidDescription" value="SID.Game.ResearchProject.Desc.DaWae"/>
				<property name="nCost" value="2000000000"/>
				<property name="nResearchPoints" value="99999"/>
				<property name="nNeededIPUs" value="99999"/>
				<property name="strBranchName" value="RESEARCH_BRANCH_LAND"/>
				<property name="strProgramName" value="RESEARCH_PROGRAM_INFANTRY"/>
				<property name="sidEffect" value="SID.Game.ResearchProject.Effect.DaWae"/>
			</object>
			<object type="ResearchProjFactoryOutput" name="objResearchProjects">
				<property name="strName" value="UgandanKnuckles"/>
				<property name="strIconName" value="Militia"/>
				<property name="sidDisplayName" value="SID.Game.ResearchProject.Name.UgandanKnuckles"/>
				<property name="sidDescription" value="SID.Game.ResearchProject.Desc.UgandanKnuckles"/>
				<property name="nCost" value="1000000"/>
				<property name="nResearchPoints" value="10"/>
				<property name="nNeededIPUs" value="8"/>
				<property name="strBranchName" value="RESEARCH_BRANCH_LAND"/>
				<property name="strProgramName" value="RESEARCH_PROGRAM_INFANTRY"/>
				<property name="sidEffect" value="SID.Game.ResearchProject.Effect.UgandanKnuckles"/>
				<object type="ResearchProjectPreReq" name="objPreReqs">
					<property name="strProjectName" value="DaWae"/>
				</object>
				<object type="ResearchFactoryOutputAvailableData" name="objAvailableFactoryOutputs">
					<property name="strFactoryOutputName" value="UgandanKnuckles"/>
				</object>
			</object>
		</object>
	</object>
</objects>''', 1)
assert 'value="DaWae"' in rs
wr('sharedDataResearch.xml', rs)

# --- 7. Fábrica
fa = rd('sharedDataFactories.xml')
a, b = block(fa, '<property name="strUnitType" value="Militia"/>')
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
''' % UNIT_IPUS + fa[b:]
wr('sharedDataFactories.xml', fa)

# --- 8. Plantilla de unidad (ultra poderosa)
ut = rd('sharedDataUnitTemplates.xml')
a, b = block(ut, '<property name="strName" value="Militia"/>')
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
us = us.replace('<property name="strTemplateNames" value="Militia"/>',
                '<property name="strTemplateNames" value="Militia"/>\n\t\t\t\t'
                '<property name="strTemplateNames" value="UgandanKnuckles"/>')
wr('sharedDataUnitTemplateSprites.xml', us)

# --- 9. Gráfico: plantilla -> sprite «Uganda Knuckles» directo
node = '''		<object type="MKDNode" name="objNodes">
			<property name="strKey" value="UgandanKnuckles"/>
			<object type="SpriteRefName" name="objDefault">
				<property name="strSpriteName" value="Uganda Knuckles"/>
			</object>
		</object>
'''
for f in ('DisplayLibraries/MKDTableUnitTemplatesLand.xml', 'DisplayLibraries/MKDTableUnitTemplatesLandCombat.xml'):
    t = rd(f)
    a, _ = block(t, '<property name="strKey" value="Militia"/>')
    wr(f, t[:a] + node + t[a:])

dec = rd('DisplayLibraries/MKDTableUnitTemplatesLandDecals.xml')
if 'UgandanKnuckles' not in dec:
    a, _ = block(dec, '<property name="strKey" value="Militia"/>')
    wr('DisplayLibraries/MKDTableUnitTemplatesLandDecals.xml',
       dec[:a] + node.replace('Uganda Knuckles', 'Infantry Base') + dec[a:])

tm = (TMWR / 'DisplayLibraries/SpriteLibLandUnits.xml').read_text(encoding='utf-8')
a, b = block(tm, '<property name="strName" value="Uganda Knuckles"/>')
sl = rd('DisplayLibraries/SpriteLibLandUnits.xml')
if 'Uganda Knuckles' not in sl:
    a3 = sl.rfind('\n', 0, sl.index('<object type="Sprite"')) + 1
    sl = sl[:a3] + '<!-- Uganda Knuckles -->\n' + tm[a:b] + sl[a3:]
    wr('DisplayLibraries/SpriteLibLandUnits.xml', sl)

# --- 10. Modelo y bandera
(S / 'ui/art/3D/Custom').mkdir(parents=True, exist_ok=True)
for ext in ('nif', 'kf'):
    shutil.copy2(TMWR / ('ui/art/3D/Custom/Uganda Knuckles.' + ext), S / 'ui/art/3D/Custom')
if not (S / 'ui/art/2D/countries/Uganda').exists():
    shutil.copytree(TMWR / 'ui/art/2D/countries/Uganda', S / 'ui/art/2D/countries/Uganda')

# --- Validar XML
for f in ['countryUnited Kingdom.xml', 'countryUganda.xml', 'playerUganda.xml', 'game.xml', 'gamestate.xml',
          'game/stringTable.xml', 'sharedDataResearch.xml', 'sharedDataFactories.xml',
          'sharedDataUnitTemplates.xml', 'sharedDataUnitTemplateSprites.xml',
          'DisplayLibraries/MKDTableUnitTemplatesLand.xml', 'DisplayLibraries/MKDTableUnitTemplatesLandCombat.xml',
          'DisplayLibraries/SpriteLibLandUnits.xml']:
    xml.dom.minidom.parse(str(S / f))
print('OK')
