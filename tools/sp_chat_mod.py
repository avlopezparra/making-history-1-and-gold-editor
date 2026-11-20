"""Single-player chat UI mod for Making History I / Gold.

The diplomatic chat bar is hidden unless another human (or an observer) is in the game: UI2DChat.bVisible is
'sizeOf(this.objChatAvatarInfos) GT 0' (UI/chat.xml), and the avatars listed are the non-AI players' only. This mod
redefines UI2DChat with the bar always visible, so in a single-player game "Contact leader" opens a chat; sp_chat.py
then answers there as the CPU nations (it adds a nation to the chat when the player names it).

Like popup_filter_mod: one generated file, UI/SPChatMod.xml (built from this install's own chat.xml), plus one line in
UI/namespace.xml. The game's files are never modified otherwise; 'uninstall' removes both.

    python tools/sp_chat_mod.py install|uninstall [--game mh1|gold|all]
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from popup_filter_mod import object_def, read, systems  # noqa: E402

MOD_FILE = 'SPChatMod.xml'
NS_LINE = '\t<file name="%s"/>\r\n' % MOD_FILE
HIDDEN = 'computeFrom="sizeOf(this.objChatAvatarInfos) GT 0"'


# UI2DOpenChat: the right-hand column lists the CPU nations that can be played (not only other humans' avatars)
# when there are no other humans, in a scroll pane (one row each, mouse wheel / slider); a click adds the nation
# to the chat, as the original list does for avatars.
LIST_ANCHOR = '<object type="UI2DListElement" name="objScrollable">'
PROP_ANCHOR = '<propertyDef name="objNonAIPlayers" type="Object" subType="Player" number="variable"/>'
CPU_LIST = '''<object type="Selection" name="objSelectCPUPlayers">
			<property name="pathInput" value=".objDriver.objMyAvatar.objGameState.objPlayers"/>
			<property name="pathOutput" value="objCPUPlayers"/>
			<property name="expWhere" value="{Object}input ISA Player AND input.bAIControlled AND !input.bNonPlayable"/>
		</object>

		<!-- SPChatMod: CPU nations, scrollable, when no other human is in the game -->
		<object type="UI2DScrollPane" name="objCPUPane">
			<property name="nX" value="382"/>
			<property name="nY" value="19"/>
			<property name="nWidth" value="137"/>
			<property name="nHeight" value="96"/>
			<property name="bVisible" computeFrom="sizeOf(this.objChatAvatarInfos) == 0"/>
			<object type="MLSliderInfo" name="objVertInfo">
				<property name="nLength" value="96"/>
			</object>
			<object type="UI2DListElement" name="objScrollable">
				<property name="nSpacing" value="0"/>
				<property name="nEltWidth" value="120"/>
				<property name="nEltHeight" value="16"/>
				<property name="nX" value="0"/>
				<property name="nY" value="0"/>
				<object name="objElements" type="UI2DSPChatCPUItem" tiedTo="objCPUPlayers">
					<property name="objChat" inheritFrom="objChat"/>
					<property name="objPlayer" computeFrom="tiedTo"/>
				</object>
			</object>
		</object>

		'''
CPU_ITEM = '''	<objectDef type="UI2DSPChatCPUItem" superType="UI2DElement">
		<propertyDef name="objPlayer" type="Object" subType="Player"/>
		<propertyDef name="objChat" type="Object" subType="Chat"/>
		<propertyDef name="strDisplayName" type="String"/>
		<propertyDef name="bIncluded" type="bool"/>
		<propertyDef name="bTempIncluded" type="bool"/>
		<property name="nX" value="0"/>
		<property name="nY" value="0"/>
		<property name="nWidth" value="120"/>
		<property name="nHeight" value="16"/>
		<property name="bVisible" value="true"/>
		<property name="strDisplayName" inheritFrom="objPlayer.strName"/>
		<property name="bIncluded" computeFrom="contains(extractProperties(String, this.objChat.objPlayers, WrappedString, 'strString'), this.strDisplayName)"/>

		<object type="CountryLookup" name="objCountryLookup">
			<property name="objPlayer" inheritFrom=".objDriver.objMyAvatar.objPlayer"/>
			<property name="strCountry" inheritFrom="strDisplayName"/>
		</object>
		<object name="objChatFlag" type="UI2DImage">
			<property name="nWidth" value="15"/>
			<property name="nHeight" value="15"/>
			<property name="nX" value="0"/>
			<property name="nY" value="0"/>
			<property name="nDepth" value="5"/>
			<property name="fileSource" computeFrom="cast(String, .objUI.filePerCountryArtDir) + this.objCountryLookup.objCountry.strFlagName + '/multichat_flag.bmp'"/>
		</object>
		<object name="objNameButton" type="UI2DChatCountryMenuButton">
			<property name="nX" value="1"/>
			<property name="nY" value="1"/>
			<property name="nWidth" value="120"/>
			<property name="nHeight" value="13"/>
			<property name="haXAlign" value="RIGHT"/>
			<property name="bButtonPressed" inheritFrom="bIncluded"/>
			<property name="strCountryName" computeFrom="getString(this.objCountryLookup.objCountry.sidName)"/>
			<object name="objImageSet" type="ButtonImageSet">
				<property name="colUpColor" value="#2B485F00"/>
				<property name="fileUpImageFile" value="art\\2D\\chat\\2X2transparent.tga"/>
				<property name="fileDownImageFile" value="art\\2D\\chat\\multichat_button_nation_background_hl.tga"/>
				<property name="fileHighlightImageFile" value="art\\2D\\chat\\multichat_button_nation_background_hl.tga"/>
			</object>
		</object>
		<!-- the click goes to a transparent button on top, as in UI2DMultiChatNationalItem (the name button
		     itself never reports bButtonClicked) -->
		<object name="objAddRemoveButton" type="UI2DButton">
			<property name="nX" value="0"/>
			<property name="nY" value="1"/>
			<property name="nWidth" value="120"/>
			<property name="nHeight" value="12"/>
			<property name="nDepth" value="3"/>
			<object name="objImageSet" type="ButtonImageSet">
				<property name="colUpColor" value="#2B485F00"/>
				<property name="fileUpImageFile" value="art\\2D\\chat\\2X2transparent.tga"/>
				<property name="fileDownImageFile" value="art\\2D\\chat\\2X2transparent.tga"/>
				<property name="fileHighlightImageFile" value="art\\2D\\chat\\2X2transparent.tga"/>
			</object>
		</object>
		<object name="objAddActions" type="CmdBlock">
			<property name="bExecute" inheritFrom="objAddRemoveButton.bButtonClicked"/>
			<object name="objCommands" type="CmdSetPropFromExp">
				<property name="pathDest" value="bTempIncluded"/>
				<property name="expRession" value="this.bIncluded"/>
			</object>
			<object name="objCommands" type="CmdCreateAction">
				<property name="bShouldExecute" computeFrom="!this.bTempIncluded AND (this.objChat.nGameObject != -1)"/>
				<object name="objAction" type="ActAddPlayerToChat">
					<property name="nChatGOID" inheritFrom="objChat.nGameObject"/>
					<property name="strPlayerToAdd" inheritFrom="strDisplayName"/>
				</object>
			</object>
		</object>
	</objectDef>
'''


def build(system):
    ui = os.path.join(system, 'UI')
    chat = object_def(read(os.path.join(ui, 'chat.xml')), 'UI2DChat')
    assert chat.count(HIDDEN) == 1, 'UI2DChat changed in this install; update the mod'
    chat = chat.replace(HIDDEN, 'value="true"')
    opn = object_def(read(os.path.join(ui, 'openchat.xml')), 'UI2DOpenChat')
    assert opn.count(LIST_ANCHOR) == 1 and opn.count(PROP_ANCHOR) == 1, 'UI2DOpenChat changed; update the mod'
    opn = opn.replace(PROP_ANCHOR, PROP_ANCHOR + '\n\t\t<propertyDef name="objCPUPlayers" type="Object" '
                                                'subType="Player" number="variable"/>')
    opn = opn.replace(LIST_ANCHOR, CPU_LIST + LIST_ANCHOR)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!-- SPChatMod: generated by MHEditor tools/sp_chat_mod.py from this install\'s UI/chat.xml and '
            'UI/openchat.xml. -->\n'
            '<objectDefs name="core" version="0.1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n\n'
            + chat + '\n\n' + CPU_ITEM + '\n' + opn + '\n\n</objectDefs>\n')


def install(system):
    ui = os.path.join(system, 'UI')
    with open(os.path.join(ui, MOD_FILE), 'w', encoding='utf-8') as f:
        f.write(build(system))
    ns_path = os.path.join(ui, 'namespace.xml')
    ns = read(ns_path)
    if MOD_FILE not in ns:
        last = list(re.finditer(r'<file [^>]*/>[^\n]*\n', ns))[-1]    # every <file> before <stringTable>/<defEnum>
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


def installed(system):
    return MOD_FILE in read(os.path.join(system, 'UI', 'namespace.xml'))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('action', choices=['install', 'uninstall', 'show'])
    ap.add_argument('--game', choices=['mh1', 'gold', 'all'], default='all')
    a = ap.parse_args()
    for key, system in systems(a.game):
        if a.action == 'show':
            print(build(system))
            continue
        (install if a.action == 'install' else uninstall)(system)
        print('%s: %s' % (key, 'installed' if installed(system) else 'not installed'))


if __name__ == '__main__':
    main()
