"""Sell-units mod: adds a "Sell" button to the military unit pop-up (army, fleet, air force).

The buyer is picked from a flag list (countries not at war with the seller); on confirm the
game runs ActIncTreasury (buyer pays, seller cashes in) and ActAlterProperty (unit owner).
Price = one year (52 weeks) of the unit's maintenance cost.

Patches Modern Europe/system/UI/UI2DPopUpMilitaryUnit/UI2DPopUpUnit.xml in place between
marker comments, so uninstall just strips them (no backup copy needed).

  python tools/mod_sell_units.py install|uninstall|status [mh1|gold]
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gamepaths  # noqa: E402

B, E = '<!-- MHE-SELLUNITS-BEGIN -->', '<!-- MHE-SELLUNITS-END -->'
PRICE_WEEKS = 52

# shortcut: labels are English literals (no SID entries), add SIDs if the game text must be localized.
BUTTON = '''%s
		<object type="UI2DRoundedWhiteFlatButton" name="objSellButton">
			<property name="nX" value="205"/>
			<property name="nY" value="40"/>
			<property name="nWidth" value="60"/>
			<property name="strKey" value="Sell"/>
			<property name="strButtonText" value="Sell"/>
			<property name="bVisible" computeFrom="this.objUnit.nOwnerID == .objDriver.objMyAvatar.objPlayer.objCountry.nCountryID AND !this.objUnit.bInCombat"/>
		</object>
		<object name="objCreateSell" type="CmdCreateObject">
			<property name="bExecute" inheritFrom="objSellButton.bButtonClicked"/>
			<property name="pathDest" value="objActionPanel"/>
			<property name="strObjectDef" value="UI2DUnitActionPanelSell"/>
			<object type="UnitActionPanelBindings" name="objBindings">
				<property name="objUnit" inheritFrom="objUnit"/>
			</object>
		</object>
		%s
''' % (B, E)

DEFS = '''%s
	<objectDef type="UI2DUnitActionPanelSell" superType="UI2DUnitActionPanel">
		<propertyDef name="objBuyers" type="Object" subType="Country" number="variable"/>
		<propertyDef name="nPrice" type="int"/>
		<property name="nPrice" computeFrom="this.objUnit.nMaintenanceCost * %d"/>
		<property name="strTitle" value="Sell unit"/>
		<property name="strDesc" computeFrom="'Price ' + cast(String, this.nPrice) + ' - click the buyer'"/>

		<object type="DiplomaticPartnersLookup" name="objDipLookup">
			<property name="objPlayer" inheritFrom=".objDriver.objMyAvatar.objPlayer"/>
			<property name="strCountry" inheritFrom="objUnit.strOwner"/>
			<property name="bGetAtWar" value="true"/>
		</object>

		<object type="Selection" name="objSelectBuyers">
			<property name="pathInput" value=".objDriver.objMyAvatar.objPlayer.objView.objCountries"/>
			<property name="pathOutput" value="objBuyers"/>
			<property name="expWhere" value="{Object}input ISA Country AND !input.bSurrendered AND !input.bNonPlayable AND input.nCountryID != this.objUnit.nOwnerID AND !contains(this.objDipLookup.objAtWar, input)"/>
		</object>

		<object type="UI2DFlagButtons" name="objFlagButtons">
			<property name="nX" value="45"/>
			<property name="nY" value="36"/>
			<property name="nDepth" value="3"/>
			<property name="nWidth" value="213"/>
			<property name="nHeight" value="230"/>
			<property name="nMaxEltsPerRow" value="6"/>
			<object name="objFlagButtons" type="UI2DFlagButtonSellUnit" tiedTo="objBuyers">
				<property name="objCountry" computeFrom="tiedTo"/>
				<property name="objUnit" inheritFrom="objUnit"/>
				<property name="nPrice" inheritFrom="nPrice"/>
			</object>
		</object>

		<object type="UI2DUnitActionButtonLayout" name="objActionButtons">
			<property name="nX" value="0"/>
			<property name="nY" value="5"/>
			<property name="vaYAlign" value="BOTTOM"/>
			<property name="haXAlign" value="CENTER"/>
			<object type="UI2DRoundedWhiteFlatButton" name="objButtons">
				<property name="nWidth" value="87"/>
				<property name="strKey" value="Cancel"/>
				<property name="strButtonText" value="Cancel"/>
			</object>
		</object>

		<object type="CmdSetPropFromExp" name="objCancel">
			<property name="bExecute" inheritFrom="objActionButtons.objButtons{Cancel}.bButtonPressed"/>
			<property name="pathDest" value="objSelfDestruct.bDestroy"/>
			<property name="expRession" value="true"/>
		</object>
	</objectDef>

	<objectDef type="UI2DFlagButtonSellUnit" superType="UI2DFlagButton">
		<propertyDef name="objUnit" type="Object" subType="Unit"/>
		<propertyDef name="nPrice" type="int"/>
		<propertyDef name="objRoot" type="Object" subType="UI2DMERoot"/>
		<property name="objRoot" inheritFrom=".objUI.objRoot"/>
		<property name="strToolTip" computeFrom="getString(this.objCountry.sidName) + ' - ' + cast(String, this.nPrice)"/>

		<object type="CmdBlock" name="objSell">
			<property name="bExecute" inheritFrom="bButtonClicked"/>
			<object type="CmdCreateConfirmation" name="objCommands">
				<object type="ConfirmationArgs" name="objConfirmationArgs">
					<property name="strTitle" value="Sell unit"/>
					<property name="strDesc" computeFrom="'Sell ' + this.objUnit.strName + ' to ' + getString(this.objCountry.sidName) + ' for ' + cast(String, this.nPrice) + '?'"/>
					<property name="strRight" value="No"/>
					<property name="strLeft" value="Sell"/>
					<property name="nX" inheritFrom="objRoot.objPopUps.objCurrentPopUp.nScreenX"/>
					<property name="nY" inheritFrom="objRoot.objPopUps.objCurrentPopUp.nScreenY"/>
					<property name="nWidth" inheritFrom="objRoot.objPopUps.objCurrentPopUp.nWidth"/>
					<property name="nHeight" inheritFrom="objRoot.objPopUps.objCurrentPopUp.nHeight"/>
					<object type="CmdBlock" name="objCmdLeft">
						<object type="CmdCreateAction" name="objCommands">
							<object type="ActIncTreasury" name="objAction">
								<property name="strCountry" inheritFrom="objCountry.strName"/>
								<property name="nIncrement" computeFrom="-this.nPrice"/>
							</object>
						</object>
						<object type="CmdCreateAction" name="objCommands">
							<object type="ActIncTreasury" name="objAction">
								<property name="strCountry" inheritFrom="objUnit.strOwner"/>
								<property name="nIncrement" inheritFrom="nPrice"/>
							</object>
						</object>
%s
					</object>
				</object>
			</object>
		</object>
	</objectDef>
	%s
'''

# Owner fields of a GO (see GO objectDef): country name for str*, country ID for n*.
OWNER_PROPS = [('strOwner', 'objCountry.strName'), ('strController', 'objCountry.strName'),
               ('nOwnerID', 'objCountry.nCountryID'), ('nControllerID', 'objCountry.nCountryID')]
ALTER = '''						<object type="CmdCreateAction" name="objCommands">
							<object type="ActAlterProperty" name="objAction">
								<property name="nGOID" inheritFrom="objUnit.nGameObject"/>
								<property name="strPropName" value="%s"/>
								<property name="strNewValue" computeFrom="cast(String, this.%s)"/>
							</object>
						</object>'''

DEFS = DEFS % (B, PRICE_WEEKS, '\n'.join(ALTER % p for p in OWNER_PROPS), E)


def ui_file(game=None):
    return os.path.join(gamepaths.path(game), 'Modern Europe', 'system', 'UI',
                        'UI2DPopUpMilitaryUnit', 'UI2DPopUpUnit.xml')


def strip(text):
    return re.sub(re.escape(B) + r'.*?' + re.escape(E) + r'\n', '', text, flags=re.S)


def apply(text):
    text = strip(text)
    head = text.index('<objectDef type="UI2DPopUpUnit" ')
    # insert at line starts so strip() removes exactly what was added
    end = text.rindex('\n', 0, text.index('</objectDef>', head)) + 1   # end of the base pop-up def
    text = text[:end] + BUTTON.strip() + '\n' + text[end:]
    last = text.rindex('\n', 0, text.rindex('</objectDefs>')) + 1
    return text[:last] + DEFS.strip() + '\n' + text[last:]


def _rw(game, fn):
    p = ui_file(game)
    with open(p, encoding='utf-8') as f:
        old = f.read()
    new = fn(old)
    if new != old:
        with open(p, 'w', encoding='utf-8', newline='') as f:
            f.write(new)
    return p


def install(game=None):
    return _rw(game, apply)


def uninstall(game=None):
    return _rw(game, strip)


def installed(game=None):
    with open(ui_file(game), encoding='utf-8') as f:
        return B in f.read()


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    game = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == 'install':
        print('installed:', install(game))
    elif cmd == 'uninstall':
        print('removed:', uninstall(game))
    else:
        print('installed' if installed(game) else 'not installed')
