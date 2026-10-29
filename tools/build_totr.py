"""Build the MH Gold scenario "Triumph of the Reich REMADE" from "Conclusion of the War".

Alternate 1942: the Axis has won in Europe, Asia and Africa; the USSR has dissolved,
Britain has a puppet government (British Union) and the US leads the last free nations.
Run: python build_totr.py  (writes a new scenario folder next to the source one)
"""
import copy
import os
import shutil
import sys
import xml.etree.ElementTree as ET

import mhmap
from shapely.geometry import Point, Polygon
from shapely.ops import nearest_points
from shapely.validation import make_valid

GOLD = r'C:\Program Files (x86)\Steam\steamapps\common\Making History Gold\Modern Europe\system'
SRC = os.path.join(GOLD, 'scenarios', 'Conclusion of the War')
NAME = 'Triumph of the Reich REMADE'
DST = os.path.join(GOLD, 'scenarios', NAME)
REGIONS_BIN = os.path.join(GOLD, 'DisplayLibraries', 'Maps', 'World', 'xml', 'regions.bin')

DESCRIPTION = (
    "Now's your chance to play as the US against a stronger enemy. In this scenario, the Axis has won "
    "Europe, Asia and Africa, and only the US and its few remaining allies can stop them from total "
    "domination!\n\nWhen the Axis captured Moscow in 1941, Stalin's subsequent assassination led to the "
    "dissolution of the USSR. By January 1942, a demoralized English government, fearing renewed bombing, "
    "capitulates to the Axis powers. Many escape to Canada, including much of the Army and Navy. Hitler "
    "establishes a puppet government renamed the British Union. Fascist loyalists use this momentum to seize "
    "power across the Middle East, in South Africa, and in India.\n\nJapan prepares to finish off the last "
    "remnants of the old European empires in Southeast Asia. It plans to consolidate its new territory in "
    "Russia, and finish off China quickly. The Fascist Alliance is already drawing up plans for the conquest "
    "of the Americas, along with their new ally Argentina.\n\nCan the US and her few remaining allies stop them?")
COMPARISON = (
    "This scenario proposes an alternate history where Germany and the Axis alliance have captured Europe, key "
    "parts of Africa, and Asia. The defeated USSR has dissolved into several new nations (Muscovy, White Russia, "
    "the Khanate of Khiva and Ukraine), Great Britain has installed a puppet government, the British Union, and "
    "fascist powers are bent on capturing the only remaining adversary, the USA.\n\nThe scenario gives players a "
    "rare chance to play the US at a distinct disadvantage.")

SEPARATISTS = ['Ural Republic', 'Western Siberia', 'Siberian Republic', 'Buryatia', 'Yakutia', 'Astrakhan',
               'Chechnya']
AXIS = ['Germany', 'Japan', 'Italy', 'British Union', 'Muscovy', 'White Russia', 'Khanate of Khiva', 'Ukraine',
        'France', 'Spain', 'Hungary', 'Romania', 'Bulgaria', 'Finland', 'Siam', 'Manchuria', 'Argentina',
        'Egypt', 'South Africa', 'India', 'Iraq', 'Persia', 'Syria', 'Saudi Arabia', 'Yemen', 'Oman', 'Kuwait',
        'Afghanistan', 'Greece', 'Croatia', 'Portugal'] + SEPARATISTS
AXIS_PRINCIPAL = {'Germany', 'Japan', 'Italy'}
ALLIES = ['United States', 'United Kingdom', 'Canada', 'Australia', 'New Zealand', 'China', 'Brazil', 'Mexico', 'Cuba',
          'Netherlands', 'Iceland', 'Panama', 'Liberia']
ALLIES_PRINCIPAL = {'United States', 'United Kingdom', 'China'}
PLAYABLE = ['United States', 'United Kingdom', 'Canada', 'China', 'Germany', 'Japan', 'Italy', 'British Union', 'Muscovy']
SURRENDERED = ['USSR']
EXILE = 'United Kingdom'   # government in exile in Newfoundland

FASCIST = ['Croatia', 'Portugal', 'Greece', 'Saudi Arabia', 'Yemen', 'Oman', 'Kuwait', 'Afghanistan', 'Germany', 'Japan', 'Italy', 'British Union', 'Muscovy', 'White Russia', 'Ukraine', 'France', 'Spain',
           'Manchuria', 'Argentina', 'Egypt', 'South Africa', 'India', 'Iraq', 'Persia', 'Syria']

NEW_NATIONS = {
    # name: (government, homelands, capital, cultures, colour, flag)
    'Muscovy': ('Fascist', 'USSR', 'Moscow', ['Russian'], '#5C3A2EFF'),
    'White Russia': ('Fascist', 'USSR', 'Minsk', ['Byelorussian', 'Russian'], '#B8B8A0FF'),
    'Khanate of Khiva': ('Authoritarian', 'USSR', 'Khiva', ['Turkic'], '#2E8B7AFF'),
    # Russian separatist states, imported from The Modern World (same names and flags)
    'Ural Republic': ('Authoritarian', 'USSR', 'Sverdlovsk', ['Russian'], '#13A30FFF'),
    'Western Siberia': ('Authoritarian', 'USSR', 'Omsk', ['Russian'], '#CC6C06FF'),
    'Siberian Republic': ('Authoritarian', 'USSR', 'Novo-Sibirsk', ['Russian'], '#96965AFF'),
    'Buryatia': ('Authoritarian', 'USSR', 'Irkutsk', ['Russian'], '#464E6DFF'),
    'Yakutia': ('Authoritarian', 'USSR', 'Yakutsk', ['Russian'], '#7A5BA8FF'),
    'Astrakhan': ('Authoritarian', 'USSR', 'Astrakhan', ['Russian'], '#0AE0CBFF'),
    'Chechnya': ('Authoritarian', 'USSR', 'Grozny', ['Caucasian', 'Russian'], '#2B7338FF'),
    'British Union': ('Fascist', 'United Kingdom', 'London', ['English', 'Anglo-Celtic', 'Scottish', 'Welsh'],
                      '#3C1E46FF'),
}

# Region -> new owner (controller follows unless listed in CONTROL).
OWNERS = {}


def give(owner, *regions):
    for r in regions:
        OWNERS[r] = owner


# --- The dissolved USSR
give('Muscovy', 'Muscovy', 'Tver', 'Vladmir', 'Ryazan', 'Chernigov', 'Vologda', 'Archangelsk', 'Pechora',
     'Middle Volga', 'Volgograd', 'Kola', 'Ladoga Karelia', 'Ingermanland', 'Pskov', 'Novgorod')
give('White Russia', 'Wilno', 'Turov', 'Polatsk', 'Smolensk Oblast')
give('Khanate of Khiva', 'Bactria', 'Kara Kum', 'Ust Urt', 'Semipalatinsk')
give('Ukraine', 'Kursk', 'Donetska', 'Jedisan', 'Kherson', 'Podelia', 'Poltava', 'Ukraina', 'Kuban', 'Crimea',
     'Rostov Oblast')
give('Germany', 'Harrien', 'Wierland', 'Circassia', 'South Caucasus')
give('Ural Republic', 'Urals')
give('Western Siberia', 'Tobolsk', 'Tyumen')
give('Siberian Republic', 'Tomsk', 'Yenisisk', 'Siberia')
give('Buryatia', 'Irkutsk Oblast', 'Chita')
give('Yakutia', 'Yakutsk')
give('Astrakhan', 'Astrakhan Oblast')
give('Chechnya', 'Daghestan')
# Japan keeps only the Pacific coast of Russia
give('Japan', 'Amur', 'Chukota', 'Kamchatka', 'Magadan', 'North Sakhalin', 'Sikhote')
# --- The fallen British Empire
give('British Union', 'Faroe Islands', 'Northern Ireland', 'Shetlands', 'Cornwall', 'East Anglia', 'Lancashire',
     'Lincoln', 'Midlands', 'Northumberland', 'Sussex', 'Yorkshire', 'Scotland', 'Wales', 'St. Helena', 'Seychelles',
     'Cyprus', 'Mauritius')
give('India', 'Assam', 'Baluchistan', 'Bengal', 'Andhra Pradesh', 'Madras', 'Mysore', 'Gujarat', 'Bihar Orissa',
     'Central India', 'Kashmir', 'Punjab', 'Rajputana', 'United Provinces', 'Maharashtra', 'Sind', 'Ceylon')
give('Italy', 'Cyrenacia', 'Tripolitania', 'Fezzan', 'Ethiopia', 'Italian Somaliland', 'Eritrea', 'Malta',
     'Illyria', 'Dalmatia', 'Montenegro')
give('Egypt', 'Sudan', 'Suez Canal Zone')
# German Mittelafrika: the Congo basin, the British east and west African colonies and French Equatorial Africa
give('Germany', 'Belgian Congo', 'Cameroon', 'Gabon', 'Middle Congo', 'Ubangi Shari', 'Tanganyika', 'Kenya', 'Uganda',
     'Nigeria', 'Gold Coast', 'Togo Dahomey', 'Sierra Leone', 'Gambia', 'South West Africa')
# Italy completes its African empire; Spain takes Morocco; France keeps the rest
give('Italy', 'Tunisia', 'Chad', 'Somaliland', 'French Somaliland', 'Socotra')
give('Spain', 'Morocco')
# Fascist France rules metropolitan France (minus Alsace-Lorraine) and what is left of its African empire
give('France', 'Brittany', 'Burgundy', 'Champagne', 'Gascony', 'Il de France', 'La Marche', 'Languedoc', 'Normandy',
     'Picardy', 'Poitou', 'Provence', 'Corsica')
# Fascist Croatia (Ustase) with Slovenia and Serbia
give('Croatia', 'Croatia', 'Carniola', 'Serbia')
# Fascist Greece
give('Greece', 'Aegean Islands', 'Crete', 'Ionian Islands', 'Macedonia', 'Peloponnesus', 'Thessaly', 'Thrace')
give('Yemen', 'South Yemen')
give('Oman', 'Trucial States')
give('Iraq', 'Jordan', 'Palestine')
give('South Africa', 'Bechuanaland', 'Northern Rhodesia', 'Southern Rhodesia', 'Nyasaland')
give('Spain', 'Gibraltar Proper')
give('Japan', 'Chin', 'Shan', 'Tenasserim', 'Kowloon', 'Andaman Islands', 'East Malaysia', 'Nauru Island')
# Malaya and Singapore are still holding out under the Free British (now Australian) command.
give('Australia', 'Malaya', 'Singapore Island', 'Papua', 'Solomon Islands', 'New Hebrides', 'Fiji')
give('New Zealand', 'Cook Islands', 'Tonga', 'Western Samoa', 'Tuvalu', 'Wallis Futuna', 'Gilbert Islands',
     'Phoenix Islands')
give('United Kingdom', 'Bahamas', 'Bermuda', 'British Guiana', 'Jamaica', 'Leeward Isles', 'Trinidad',
     'Windward Isles', 'British Honduras', 'Falklands', 'Labrador', 'Newfoundland')
# --- Vichy France loses the Levant to fascist Syria
give('Syria', 'Syria', 'Lebanon')
# --- Japanese conquests in China, Manchukuo, the Dutch East Indies and the Philippines
give('Manchuria', 'Feng Tien', 'Kirin', 'Heilungkiang', 'Jehol')
give('Japan', 'Anhui', 'Fujian', 'Guangdong', 'Hainan', 'Hebei', 'Henan', 'Hubei', 'Jiangsu', 'Shandong',
     'Shanghai Proper', 'Shanxi', 'Zhejiang', 'Formosa', 'Dutch Timor', 'East Borneo', 'Java', 'Lesser Sunda',
     'North Sumatra', 'Riau Islands', 'South Sumatra', 'West Borneo', 'Banda Islands', 'Celebes', 'Moluccas',
     'Guam', 'Wake Island', 'Cambodia', 'Laos', 'Annam', 'Cochin-China', 'Tonking')
# --- Italy back in German hands is reversed: fascist Italy rules its own soil again
give('Italy', 'Dodecanse', 'Emilia Romagna', 'Istria', 'Lombardy', 'Piedmont', 'Trentino', 'Tuscany', 'Veneto')

# Regions whose controller differs from the new owner (front lines).
CONTROL = {
    'Luzon': 'Japan', 'Mindanao': 'Japan', 'Southern Tagalog': 'Japan', 'Visayas': 'Japan',
    'West New Guinea': 'Japan',
}
# Regions that stay with their owner but are now controlled by the owner itself.
OWN_CONTROL = ['Marshall Islands']

IPU_FACTOR = {'China': 0.7, 'Communist China': 0.8, 'Germany': 1.15, 'Japan': 1.3, 'Italy': 1.25, 'Muscovy': 0.8, 'British Union': 0.7, 'India': 1.0,
              'Canada': 1.6, 'Manchuria': 1.0, 'Ukraine': 0.8}
IPU_MIN = {'Saudi Arabia': 2, 'Yemen': 1, 'Oman': 1, 'Afghanistan': 2, 'India': 4, 'Egypt': 3, 'South Africa': 4, 'Iraq': 4, 'Persia': 4, 'Argentina': 2, 'Khanate of Khiva': 2,
           'White Russia': 3, 'Syria': 3}

# New formations: (country, kind, name, region, city-or-None, [(template, number)])
INF = 'SmallArmsInfantry'
NEW_UNITS = [
    # India: Azad Hind armies (additional troops)
    ('India', 'Army', '1st Azad Hind Army', 'Rajputana', None, [(INF, 4), ('FieldArtillery', 2), ('LightTank', 1)]),
    ('India', 'Army', '2nd Azad Hind Army', 'Punjab', None, [(INF, 4), ('FieldArtillery', 1), ('40mmGun', 1)]),
    ('India', 'Army', '3rd Azad Hind Army', 'Bengal', None, [(INF, 4), ('PreWarInfantry', 2), ('FieldArtillery', 1)]),
    ('India', 'Army', '4th Azad Hind Army', 'Maharashtra', None, [(INF, 3), ('PreWarInfantry', 2), ('LightTank', 1)]),
    ('India', 'Army', '5th Azad Hind Army', 'Madras', None, [(INF, 3), ('PreWarInfantry', 2)]),
    ('India', 'Army', '6th Azad Hind Army', 'United Provinces', None, [(INF, 3), ('Militia', 3)]),
    ('India', 'Army', '7th Azad Hind Army', 'Sind', None, [(INF, 3), ('Militia', 2), ('FieldArtillery', 1)]),
    ('India', 'Army', 'Ceylon Garrison', 'Ceylon', None, [(INF, 2), ('Militia', 2)]),
    ('India', 'Army', 'Kashmir Rifles', 'Kashmir', None, [(INF, 2), ('Militia', 2)]),
    ('India', 'Army', 'Deccan Corps', 'Andhra Pradesh', None, [(INF, 3), ('Cavalry', 2)]),
    ('India', 'AirForce', 'Azad Hind Air Force', 'Rajputana', None, [('PreWarFighters', 2), ('LightBombers', 2)]),
    ('India', 'Fleet', 'Azad Hind Navy', 'Maharashtra', 'Bombay', [('Destroyer', 3), ('HeavyCruiser', 1)]),
    # British Union
    ('British Union', 'Army', 'Legion of St. George', 'Sussex', None, [(INF, 4), ('FieldArtillery', 1)]),
    ('British Union', 'Army', 'BU Home Guard', 'Scotland', None, [('Militia', 4), (INF, 2)]),
    # Muscovy
    ('Muscovy', 'Army', 'Moscow Guard', 'Muscovy', None, [(INF, 5), ('FieldArtillery', 2), ('EarlyTank', 2)]),
    ('Muscovy', 'Army', 'Volga Army', 'Volgograd', None, [(INF, 4), ('PreWarInfantry', 2)]),
    ('Muscovy', 'Army', 'Leningrad Army', 'Ingermanland', None, [(INF, 4), ('FieldArtillery', 2), ('LightTank', 2)]),
    ('Ural Republic', 'Army', 'Ural Defence Army', 'Urals', None, [(INF, 4), ('FieldArtillery', 1)]),
    ('Western Siberia', 'Army', 'Omsk Army', 'Tobolsk', None, [(INF, 3), ('Militia', 2)]),
    ('Siberian Republic', 'Army', 'Siberian Rifles', 'Tomsk', None, [(INF, 3), ('Militia', 2)]),
    ('Buryatia', 'Army', 'Baikal Army', 'Irkutsk Oblast', None, [(INF, 2), ('Cavalry', 2)]),
    ('Yakutia', 'Army', 'Yakut Rifles', 'Yakutsk', None, [('Militia', 3)]),
    ('Astrakhan', 'Army', 'Astrakhan Cossacks', 'Astrakhan Oblast', None, [('Cavalry', 2), ('Militia', 2)]),
    ('Chechnya', 'Army', 'Mountain Legion', 'Daghestan', None, [(INF, 2), ('Militia', 2)]),
    ('Muscovy', 'Army', 'Archangel Garrison', 'Archangelsk', None, [(INF, 2), ('Militia', 2)]),
    ('Muscovy', 'AirForce', 'Muscovite Air Corps', 'Muscovy', None, [('PreWarFighters', 3), ('LightBombers', 2)]),
    # White Russia
    ('White Russia', 'Army', 'Belarusian Home Defence', 'Polatsk', None, [(INF, 3), ('Militia', 3)]),
    ('White Russia', 'Army', 'Smolensk Legion', 'Smolensk Oblast', None, [(INF, 2), ('Militia', 2)]),
    # Khanate of Khiva
    ('Khanate of Khiva', 'Army', 'Khivan Horde', 'Kara Kum', None, [('Cavalry', 4), ('Militia', 3)]),
    ('Khanate of Khiva', 'Army', 'Turkestan Legion', 'Bactria', None, [(INF, 2), ('Cavalry', 2)]),
    # Ukraine
    ('Ukraine', 'Army', 'Ukrainian Liberation Army', 'Ukraina', None, [(INF, 4), ('FieldArtillery', 1)]),
    ('Ukraine', 'Army', 'Kuban Cossacks', 'Kuban', None, [('Cavalry', 3), (INF, 2)]),
    ('Ukraine', 'Army', 'Donets Corps', 'Donetska', None, [(INF, 3), ('Militia', 2)]),
    # Germany: occupation of Russia and Britain, Atlantic fleet
    ('Germany', 'Army', 'Army Group North', 'Harrien', None, [(INF, 5), ('88mmGun', 2), ('MediumTank', 2)]),
    ('Germany', 'Army', 'Army Group Caucasus', 'South Caucasus', None, [(INF, 4), ('MediumTank', 3), ('88mmGun', 1)]),
    ('Germany', 'Army', 'Kuban Bridgehead', 'Circassia', None, [(INF, 4), ('FieldArtillery', 2)]),
    ('Germany', 'Army', 'Crimea Army', 'Jedisan', None, [(INF, 3), ('FieldArtillery', 2)]),
    ('Germany', 'Army', 'Occupation Army Britain', 'Midlands', None, [(INF, 5), ('MediumTank', 2), ('88mmGun', 2)]),
    ('Germany', 'Army', 'Channel Guard', 'Cornwall', None, [(INF, 3), ('FieldArtillery', 2)]),
    ('Germany', 'Fleet', 'Atlantic Battle Group', 'Brittany', None, [('PreWarBattleship', 2), ('HeavyCruiser', 2),
                                                                       ('Destroyer', 4)]),
    ('Germany', 'Fleet', 'U-Boat Flotilla West', 'Brittany', None, [('ElectricDieselSubmarine', 8)]),
    ('Germany', 'AirForce', 'Luftflotte Britain', 'Sussex', None, [('ImprovedFighters', 3), ('MediumBombers', 3)]),
    # Japan: Siberia and the drive on China
    ('Japan', 'Army', 'Siberian Army', 'Amur', None, [(INF, 4), ('FieldArtillery', 2), ('LightTank', 1)]),
    ('Japan', 'Army', 'Amur Army', 'Sikhote', None, [(INF, 4), ('FieldArtillery', 1)]),
    ('Japan', 'Army', 'Malaya Expeditionary Army', 'Kra Isthmus', None, [(INF, 5), ('LightTank', 2), ('FieldArtillery', 2)]),
    ('Japan', 'Army', 'Hunan Offensive Army', 'Hubei', None, [(INF, 6), ('FieldArtillery', 2), ('LightTank', 2)]),
    ('Japan', 'Army', 'Sichuan Offensive Army', 'Henan', None, [(INF, 6), ('FieldArtillery', 2)]),
    ('Japan', 'Fleet', 'Southern Expeditionary Fleet', 'Cochin-China', 'Saigon',
     [('PreWarBattleship', 2), ('HeavyCruiser', 3), ('Destroyer', 6), ('EarlyCarrier', 1)]),
    ('Japan', 'Army', 'Kwantung Army', 'Hebei', None, [(INF, 6), ('MediumTank', 2), ('FieldArtillery', 2)]),
    ('Japan', 'Army', 'Yangtze Army', 'Hubei', None, [(INF, 5), ('FieldArtillery', 2)]),
    ('Japan', 'Army', 'South China Army', 'Guangdong', None, [(INF, 5), ('LightTank', 1)]),
    ('Japan', 'Army', 'Shaanxi Expeditionary Army', 'Shanxi', None, [(INF, 5), ('FieldArtillery', 2)]),
    ('Japan', 'Army', 'Burma Area Army', 'Shan', None, [(INF, 5), ('LightTank', 1), ('FieldArtillery', 1)]),
    ('Japan', 'Army', 'Okhotsk Garrison', 'Magadan', None, [(INF, 2), ('Militia', 1)]),
    ('Japan', 'Army', 'Kamchatka Garrison', 'Kamchatka', None, [(INF, 2)]),
    ('Japan', 'Army', 'Sakhalin Garrison', 'North Sakhalin', None, [(INF, 2)]),
    ('Japan', 'Army', '16th Army', 'Java', None, [(INF, 4), ('FieldArtillery', 1)]),
    ('Japan', 'Army', '25th Army', 'Kra Isthmus', None, [(INF, 5), ('LightTank', 2)]),
    ('Japan', 'AirForce', '3rd Air Army', 'Cochin-China', None, [('ImprovedFighters', 3), ('MediumBombers', 3)]),
    ('Japan', 'AirForce', 'China Air Army', 'Hubei', None, [('PreWarFighters', 3), ('LightBombers', 3)]),
    # Mittelafrika and the new fascist Middle East
    ('Germany', 'Army', 'Mittelafrika Corps', 'Belgian Congo', None, [(INF, 3), ('Militia', 2)]),
    ('Germany', 'Army', 'East Africa Corps', 'Kenya', None, [(INF, 3), ('LightTank', 1)]),
    ('Germany', 'Army', 'West Africa Corps', 'Nigeria', None, [(INF, 3), ('Militia', 2)]),
    ('Germany', 'Fleet', 'South Atlantic Raiders', 'Togo Dahomey', 'Lome', [('HeavyCruiser', 2),
                                                                          ('ElectricDieselSubmarine', 6)]),
    ('Italy', 'Army', 'Tunisia Army', 'Tunisia', None, [(INF, 3), ('FieldArtillery', 1)]),
    ('Spain', 'Army', 'Army of Morocco', 'Morocco', None, [(INF, 3), ('Cavalry', 2)]),
    ('Saudi Arabia', 'Army', 'Royal Saudi Army', 'Najd', None, [(INF, 2), ('Cavalry', 3)]),
    ('Yemen', 'Army', 'Aden Garrison', 'South Yemen', None, [(INF, 2), ('Militia', 2)]),
    ('Afghanistan', 'Army', 'Royal Afghan Army', 'Afghanistan', None, [(INF, 3), ('Cavalry', 2)]),
    ('France', 'Army', 'Army of Paris', 'Il de France', None, [(INF, 4), ('FieldArtillery', 2), ('LightTank', 2)]),
    ('France', 'Army', 'Army of the Atlantic', 'Brittany', None, [(INF, 3), ('FieldArtillery', 1)]),
    ('France', 'Army', 'Army of the Alps', 'Provence', None, [(INF, 3), ('Militia', 2)]),
    ('France', 'Fleet', 'French Mediterranean Fleet', 'Provence', None, [('PreWarBattleship', 2), ('HeavyCruiser', 3),
                                                                           ('Destroyer', 6)]),
    ('Greece', 'Army', 'Hellenic National Army', 'Thessaly', None, [(INF, 3), ('FieldArtillery', 1)]),
    ('Greece', 'Army', 'Army of Macedonia', 'Macedonia', None, [(INF, 3), ('Militia', 2)]),
    ('Greece', 'Fleet', 'Hellenic Navy', 'Thessaly', None, [('HeavyCruiser', 1), ('Destroyer', 4)]),
    ('Germany', 'Army', 'Sudwest Afrika Corps', 'South West Africa', None, [(INF, 2), ('Militia', 2)]),
    ('Croatia', 'Army', 'Ustase Army', 'Croatia', None, [(INF, 3), ('Militia', 2)]),
    ('Croatia', 'Army', 'Serbian Garrison', 'Serbia', None, [(INF, 2), ('Militia', 2)]),
    # Manchukuo
    ('Manchuria', 'Army', 'Manchukuo Imperial Army', 'Feng Tien', None, [(INF, 4), ('Cavalry', 2)]),
    ('Manchuria', 'Army', 'Kirin Garrison', 'Kirin', None, [(INF, 2), ('Militia', 2)]),
    # Italy
    ('Italy', 'Army', '1st Italian Army', 'Piedmont', None, [(INF, 4), ('FieldArtillery', 2), ('LightTank', 2)]),
    ('Italy', 'Army', '2nd Italian Army', 'Veneto', None, [(INF, 4), ('FieldArtillery', 1)]),
    ('Italy', 'Army', 'Army of Africa', 'Cyrenacia', None, [(INF, 4), ('LightTank', 2), ('FieldArtillery', 1)]),
    ('Italy', 'Army', 'East Africa Army', 'Ethiopia', None, [(INF, 3), ('Militia', 3)]),
    ('Italy', 'Army', 'Balkan Army', 'Dalmatia', None, [(INF, 3), ('Militia', 2)]),
    ('Italy', 'Fleet', 'Regia Marina', 'Puglia', 'Taranto', [('PreWarBattleship', 4), ('HeavyCruiser', 4),
                                                            ('Destroyer', 8), ('ElectricDieselSubmarine', 6)]),
    ('Italy', 'Fleet', 'Tyrrhenian Squadron', 'Napoli', 'Naples', [('HeavyCruiser', 2), ('Destroyer', 4)]),
    ('Italy', 'AirForce', 'Regia Aeronautica', 'Lazio Umbria', None, [('PreWarFighters', 3), ('LightBombers', 3),
                                                                     ('MediumBombers', 2)]),
    # Spain and Vichy France
    ('Spain', 'Army', 'Gibraltar Force', 'Gibraltar Proper', None, [(INF, 3), ('FieldArtillery', 1)]),
    ('Spain', 'Army', 'Blue Division', 'Castile', None, [(INF, 4), ('FieldArtillery', 1)]),
    # Middle East and Africa
    ('Egypt', 'Army', 'Royal Egyptian Army', 'Lower Egypt', None, [(INF, 4), ('FieldArtillery', 1), ('LightTank', 1)]),
    ('Egypt', 'Army', 'Suez Guard', 'Suez Canal Zone', None, [(INF, 3), ('40mmGun', 1)]),
    ('Egypt', 'Army', 'Sudan Corps', 'Sudan', None, [(INF, 2), ('Militia', 2)]),
    ('Iraq', 'Army', 'Golden Square Army', 'Iraq', None, [(INF, 4), ('FieldArtillery', 1)]),
    ('Iraq', 'Army', 'Levant Legion', 'Palestine', None, [(INF, 3), ('Militia', 2)]),
    ('Persia', 'Army', 'Imperial Persian Army', 'Northern Persia', None, [(INF, 4), ('Cavalry', 2)]),
    ('Syria', 'Army', 'Syrian National Army', 'Syria', None, [(INF, 3), ('Militia', 2)]),
    ('South Africa', 'Army', 'Ossewabrandwag Army', 'Transval', None, [(INF, 4), ('FieldArtillery', 1),
                                                                       ('LightTank', 1)]),
    ('South Africa', 'Army', 'Rhodesian Corps', 'Southern Rhodesia', None, [(INF, 2), ('Militia', 2)]),
    ('South Africa', 'Fleet', 'South African Squadron', 'Cape Province', 'Cape Town', [('HeavyCruiser', 1),
                                                                                        ('Destroyer', 3)]),
    # Argentina
    ('Argentina', 'Army', '1st Argentine Army', 'Pampas', None, [(INF, 4), ('FieldArtillery', 2), ('LightTank', 1)]),
    ('Argentina', 'Army', '2nd Argentine Army', 'Gran Chaco', None, [(INF, 3), ('Cavalry', 2)]),
    ('Argentina', 'Army', 'Patagonia Army', 'Patagonia', None, [(INF, 2), ('Militia', 2)]),
    ('Argentina', 'Fleet', 'Argentine Sea Fleet', 'Pampas', 'Buenos Aires', [('PreWarBattleship', 2),
                                                                             ('HeavyCruiser', 3), ('Destroyer', 6)]),
    ('Argentina', 'AirForce', 'Argentine Air Force', 'Pampas', None, [('PreWarFighters', 2), ('LightBombers', 2)]),
    # The free world
    ('United Kingdom', 'Army', 'Free British Army', 'Ontario', None, [(INF, 5), ('FieldArtillery', 2), ('LightTank', 2)]),
    ('United Kingdom', 'Army', 'Newfoundland Guard', 'Newfoundland', None, [(INF, 2), ('40mmGun', 1)]),
    ('United Kingdom', 'Army', 'Caribbean Garrison', 'Jamaica', None, [(INF, 2), ('Militia', 1)]),
    ('United Kingdom', 'Army', 'Guiana Garrison', 'British Guiana', None, [(INF, 2), ('Militia', 2)]),
    ('United Kingdom', 'Army', 'Falklands Garrison', 'Falklands', None, [(INF, 1), ('Militia', 1)]),
    ('Australia', 'Army', 'Malaya Command', 'Singapore Island', None, [(INF, 4), ('FieldArtillery', 2),
                                                                       ('40mmGun', 1)]),
    ('Australia', 'Army', 'New Guinea Force', 'Papua', None, [(INF, 2), ('Militia', 2)]),
    ('China', 'Army', 'Yunnan Army', 'Yunnan', None, [('PreWarInfantry', 4), ('Militia', 3)]),
    ('China', 'Army', 'Hunan Army', 'Hunan', None, [('PreWarInfantry', 4), ('Militia', 3), ('FieldArtillery', 1)]),
    ('Brazil', 'Army', 'Brazilian Expeditionary Force', 'Nordeste', None, [(INF, 3), ('FieldArtillery', 1)]),
    ('Mexico', 'Army', 'Mexican Army of the North', 'Northern Mexico', None, [(INF, 3), ('Cavalry', 2)]),
]

HOME_ISLES = {'Northern Ireland', 'Shetlands', 'Cornwall', 'East Anglia', 'Lancashire', 'Lincoln', 'Midlands',
              'Northumberland', 'Sussex', 'Yorkshire', 'Scotland', 'Wales', 'Faroe Islands'}
BRITISH_SEAS = {'English Channel', 'Irish Sea', 'North Sea', 'Dogger Bank', 'Fair Isle'}
CANADA_ARMY_REGIONS = ['Maritime Provinces', 'Quebec', 'Ontario', 'Laurentian', 'Newfoundland', 'British Columbia']
CANADA_PORTS = [('Maritime Provinces', 'Halifax'), ('Quebec', 'Quebec City'), ('British Columbia', 'Vancouver')]


# ------------------------------------------------------------------ xml helpers

def prop(el, name, default=None):
    for p in el.findall('property'):
        if p.get('name') == name:
            return p.get('value')
    return default


def set_prop(el, name, value, after=None):
    for p in el.findall('property'):
        if p.get('name') == name:
            p.set('value', value)
            return p
    p = ET.Element('property', {'name': name, 'value': value})
    props = el.findall('property')
    idx = list(el).index(props[-1]) + 1 if props else 0
    if after is not None:
        for q in props:
            if q.get('name') == after:
                idx = list(el).index(q) + 1
    el.insert(idx, p)
    return p


def del_prop(el, name):
    for p in el.findall('property'):
        if p.get('name') == name:
            el.remove(p)


def obj(type_, name, props=(), children=()):
    e = ET.Element('object', {'type': type_, 'name': name})
    for k, v in props:
        ET.SubElement(e, 'property', {'name': k, 'value': v})
    e.extend(children)
    return e


def load(path):
    return ET.parse(path)


def save(tree, path):
    ET.indent(tree, space='\t')
    tree.write(path, encoding='UTF-8', xml_declaration=True)


def unit_obj(kind, name, owner, region, city, units):
    props = [('strName', name), ('strOwner', owner), ('strRegion', region)]
    if city:
        props.append(('strCity', city))
    return obj(kind, 'objGOs', props, [obj('UnitSummary', 'objUnits', [('strName', t), ('nNumber', str(n))])
                                       for t, n in units])


# ------------------------------------------------------------------ build

def main():
    if os.path.exists(DST):
        sys.exit('Destination exists, remove it first: ' + DST)
    shutil.copytree(SRC, DST)
    # images are made by the author; the source scenario's ones are kept only as placeholders
    countries = {}
    for f in os.listdir(DST):
        if f.startswith('country') and f.endswith('.xml'):
            t = load(os.path.join(DST, f))
            countries[prop(t.getroot()[0], 'strName')] = t

    # new nations
    for name, (gov, home, cap, cultures, _col) in NEW_NATIONS.items():
        root = ET.Element('objects', {'name': 'Object Load', 'version': '0.1',
                                      'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance'})
        c = obj('MECountry', '', [('strName', name), ('strGovType', gov), ('strHomelands', home),
                                  ('eCountryType', 'COUNTRYTYPE_FEATURED'), ('bNonPlayable', 'true'),
                                  ('strFlagName', name), ('strCapital', cap), ('strOriginalCapital', cap)])
        c.append(obj('CultureSet', 'objCultureSet', (), [obj('Culture', 'objCultures', [('strCultureName', x)])
                                                          for x in cultures]))
        root.append(c)
        countries[name] = ET.ElementTree(root)

    # move regions
    regions = {}
    for cname, t in countries.items():
        for r in t.getroot()[0].findall("object[@type='Region']"):
            regions[prop(r, 'strName')] = (cname, r)
    missing = [r for r in OWNERS if r not in regions]
    if missing:
        sys.exit('Unknown regions: %s' % missing)
    for rname, new in OWNERS.items():
        old, r = regions[rname]
        if old != new:
            countries[old].getroot()[0].remove(r)
            croot = countries[new].getroot()[0]
            last = croot.findall("object[@type='Region']")
            idx = list(croot).index(last[-1]) + 1 if last else len(croot.findall('property'))
            croot.insert(idx, r)
            regions[rname] = (new, r)
        for e in r.iter('object'):
            if prop(e, 'strOwner') is not None:
                set_prop(e, 'strOwner', new)
        set_prop(r, 'strController', new)
    for rname, ctl in CONTROL.items():
        set_prop(regions[rname][1], 'strController', ctl)
    for rname in OWN_CONTROL:
        set_prop(regions[rname][1], 'strController', regions[rname][0])
    # every other region: drop leftover occupations by countries that are now allied with the owner
    bloc = {c: 'axis' for c in AXIS}
    bloc.update({c: 'allies' for c in ALLIES})
    for rname, (owner, r) in regions.items():
        ctl = prop(r, 'strController')
        if rname not in CONTROL and ctl != owner and (bloc.get(ctl) == bloc.get(owner) or ctl in SURRENDERED):
            set_prop(r, 'strController', owner)

    # Khiva needs a capital city: place it on the map inside Kara Kum, as close as possible to the real Khiva
    add_city(regions['Kara Kum'][1], 'Khanate of Khiva', 'Khiva', (60.36, 41.38), 95000, 3, 'Kara Kum')
    add_city(regions['Yakutsk'][1], 'Yakutia', 'Yakutsk', (129.73, 62.03), 53000, 2, 'Yakutsk')
    add_city(regions['Newfoundland'][1], 'United Kingdom', "St. John's", (-52.71, 47.56), 40000, 6, 'Newfoundland')
    add_city(regions['Bactria'][1], 'Khanate of Khiva', 'Tashkent', (69.24, 41.30), 585000, 4, 'Bactria')

    # countries' properties
    for cname, t in countries.items():
        c = t.getroot()[0]
        if cname in FASCIST:
            set_prop(c, 'strGovType', 'Fascist')
        if cname in SURRENDERED:
            set_prop(c, 'bSurrendered', 'true')
        elif c.find("object[@type='Region']") is not None:
            del_prop(c, 'bSurrendered')
        else:
            set_prop(c, 'bSurrendered', 'true')
        if cname in PLAYABLE:
            set_prop(c, 'eCountryType', 'COUNTRYTYPE_PLAYABLE')
            set_prop(c, 'bCanPlay', 'true')
            set_prop(c, 'bNonPlayable', 'false')
            set_prop(c, 'bIsScored', 'true')
        elif prop(c, 'bCanPlay') == 'true':
            set_prop(c, 'bCanPlay', 'false')
            set_prop(c, 'bNonPlayable', 'true')
            set_prop(c, 'eCountryType', 'COUNTRYTYPE_FEATURED')
    # capitals of countries that lost theirs
    set_prop(countries['Italy'].getroot()[0], 'strCapital', 'Rome')
    set_prop(countries['United Kingdom'].getroot()[0], 'strCapital', "St. John's")
    del_prop(countries['United Kingdom'].getroot()[0], 'bSurrendered')
    set_prop(countries['France'].getroot()[0], 'strCapital', 'Paris')

    move_units(countries, regions, bloc)
    for c, kind, name, region, city, units in NEW_UNITS:
        r = regions[region][1]
        owner = prop(r, 'strController')
        if owner != c and bloc.get(owner) != bloc.get(c):
            sys.exit('Unit %s placed in hostile region %s' % (name, region))
        if kind == 'Fleet' and city is None:
            city = port_city(r)
        croot = countries[c].getroot()[0]
        croot.insert(insert_index(croot), unit_obj(kind, name, c, region, city, units))

    # IPUs
    for cname, t in countries.items():
        f, mn = IPU_FACTOR.get(cname, 1.0), IPU_MIN.get(cname, 0)
        for city in t.getroot()[0].iter('object'):
            if city.get('type') != 'City':
                continue
            fac = city.find("object[@type='Factory']")
            if fac is None:
                continue
            n = int(prop(fac, 'nIPUs', '0'))
            set_prop(fac, 'nIPUs', str(max(mn, int(round(n * f)))))

    for cname, t in countries.items():
        save(t, os.path.join(DST, 'country%s.xml' % cname))

    write_players(countries)
    write_gamestate()
    write_game()
    write_treaties()
    write_scenario()
    print('Built', DST)


def insert_index(croot):
    kids = list(croot)
    for i, k in enumerate(kids):
        if k.get('type') in ('TriggerCountry', 'CultureSet'):
            return i
    return len(kids)


def port_city(region):
    for c in region.findall("object[@type='City']"):
        if prop(c, 'strPortForRegion'):
            return prop(c, 'strName')
    return None


def add_city(region, owner, name, lonlat, pop, ipus, map_region):
    regs = mhmap.read_regions_bin(open(REGIONS_BIN, 'rb').read())
    poly = next(make_valid(Polygon(r.points)) for r in regs if r.name == map_region)
    pt = Point(*lonlat)
    if not poly.contains(pt):
        inner = poly.buffer(-0.3)
        pt = nearest_points(inner if not inner.is_empty else poly, pt)[0]
    city = obj('City', 'objGOs', [('strName', name), ('strOwner', owner),
                                  ('vecPosition', '[%.4f, %.4f, 0]' % (pt.x, pt.y)), ('nDirection', '0'),
                                  ('nPopulation', str(pop)), ('strInitialWorkOrder', '')],
               [obj('Factory', 'objFactory', [('nIPUs', str(ipus))])])
    region.append(city)


def move_units(countries, regions, bloc):
    """Hand every formation to whoever now holds its region; the Royal Navy and part of the army flee to Canada."""
    moves = []
    for cname, t in countries.items():
        c = t.getroot()[0]
        for u in c.findall('object'):
            if u.get('type') in ('Army', 'Fleet', 'AirForce'):
                moves.append((cname, c, u))
    uk_i = {'Army': 0, 'Fleet': 0, 'AirForce': 0}
    for cname, c, u in moves:
        kind, rname = u.get('type'), prop(u, 'strRegion')
        land = rname in regions
        owner, r = regions[rname] if land else (None, None)
        ctl = prop(r, 'strController') if land else None
        new_owner, new_region, new_city = cname, rname, prop(u, 'strCity')
        if cname == 'United Kingdom' and (not land or rname in HOME_ISLES):
            i = uk_i[kind]
            uk_i[kind] += 1
            # most of the fleet, half the army and the air force escape to Canada
            to_canada = (kind == 'Fleet' and i % 4 != 3) or (kind != 'Fleet' and i % 2 == 0)
            if to_canada:
                new_owner = EXILE
                if kind == 'Fleet':
                    new_region, new_city = CANADA_PORTS[i % len(CANADA_PORTS)]
                else:
                    new_region, new_city = CANADA_ARMY_REGIONS[i % len(CANADA_ARMY_REGIONS)], None
            elif land:
                new_owner = 'British Union'
            else:
                new_owner = 'British Union'
                new_region, new_city = 'Scotland', 'Glasgow'
        elif cname == EXILE and land and owner != EXILE:
            # colonial garrisons pass to the new Axis-aligned owner; those in free lands stay British
            if bloc.get(owner) == 'axis':
                new_owner = owner
            elif ctl != cname and bloc.get(ctl) == 'axis':
                new_region, new_city = 'Newfoundland', None
            else:
                continue
        elif cname in SURRENDERED:
            if land:
                new_owner = owner
                # the Wehrmacht keeps half of the captured Red Army stock in its new puppets
                if cname == 'USSR' and owner in ('Ukraine', 'White Russia'):
                    uk_i['ussr'] = uk_i.get('ussr', 0) + 1
                    if uk_i['ussr'] % 2:
                        new_owner = 'Germany'
            else:
                new_owner = 'Muscovy' if cname == 'USSR' else 'British Union'
                if cname == 'USSR':
                    new_region, new_city = 'Archangelsk', 'Archangel'
        elif (land and ctl != cname and bloc.get(ctl) != bloc.get(cname)) or                 (not land and rname in BRITISH_SEAS and bloc.get(cname) != 'axis'):
            # stranded behind enemy lines: back to the capital region
            cap = prop(c, 'strCapital')
            home = next((rn for rn, (o, rr) in regions.items() if o == cname and
                         any(prop(x, 'strName') == cap for x in rr.findall("object[@type='City']"))), None)
            if home is None:
                home = next(rn for rn, (o, rr) in regions.items() if o == cname)
            new_region = home
            new_city = port_city(regions[home][1]) if kind == 'Fleet' else None
            if kind == 'Fleet' and new_city is None:
                new_region, new_city = next((rn, port_city(rr)) for rn, (o, rr) in regions.items()
                                            if o == cname and port_city(rr))
        if (new_owner, new_region) == (cname, rname):
            continue
        c.remove(u)
        set_prop(u, 'strOwner', new_owner)
        set_prop(u, 'strRegion', new_region)
        if new_city:
            set_prop(u, 'strCity', new_city)
        else:
            del_prop(u, 'strCity')
        dst = countries[new_owner].getroot()[0]
        dst.insert(insert_index(dst), u)


def write_players(countries):
    tmpl = load(os.path.join(SRC, 'playerUkraine.xml'))
    for name in NEW_NATIONS:
        t = copy.deepcopy(tmpl)
        p = t.getroot()[0]
        set_prop(p, 'strOwner', name)
        set_prop(p, 'strFoggees', name)
        for dv in p.iter('object'):
            if dv.get('type') == 'DipRelInitialValueList':
                for x in dv.findall('object'):
                    dv.remove(x)
        save(t, os.path.join(DST, 'player%s.xml' % name))
    for f in os.listdir(DST):
        if not (f.startswith('player') and f.endswith('.xml')):
            continue
        t = load(os.path.join(DST, f))
        p = t.getroot()[0]
        name = prop(p, 'strOwner')
        if name in AXIS:
            agg = name in AXIS_PRINCIPAL or name in ('British Union', 'Argentina', 'Muscovy')
            set_prop(p, 'strDipRelProcListName', 'Expansionist' if agg else 'StatusQuo')
            set_prop(p, 'strAITreatyEvalListName', 'Expansionist_Interventionist' if agg else 'StatusQuo_Interventionist')
            set_prop(p, 'eInternationalPosition', 'PLAYER_INTERNATIONAL_POSITION__EXPANSIONIST' if agg
                     else 'PLAYER_INTERNATIONAL_POSITION__STATUSQUO')
        elif name in ALLIES:
            set_prop(p, 'strDipRelProcListName', 'StatusQuo')
            set_prop(p, 'strAITreatyEvalListName', 'StatusQuo_Interventionist')
            set_prop(p, 'eInternationalPosition', 'PLAYER_INTERNATIONAL_POSITION__STATUSQUO')
        if name in PLAYABLE:
            lists = [x.get('value') for x in p.findall("property[@name='strHLPDefLists']")]
            if 'Playable' not in lists:
                ref = p.findall("property[@name='strHLPDefLists']")[-1]
                i = list(p).index(ref) + 1
                p.insert(i, ET.Element('property', {'name': 'strHLPDefLists', 'value': 'Playable'}))
                p.insert(i + 1, ET.Element('property', {'name': 'strPLPDefLists', 'value': 'Playable'}))
        # mutual hostility between the blocs
        dl = p.find("object[@type='DipRelInitialValueList']")
        if dl is not None and (name in AXIS or name in ALLIES):
            enemies = ALLIES if name in AXIS else AXIS
            friends = AXIS if name in AXIS else ALLIES
            for x in dl.findall("object[@type='DipRelInitialValue']"):
                if prop(x, 'strTargetCountry') in enemies or prop(x, 'strTargetCountry') in friends:
                    dl.remove(x)
            for e in enemies:
                dl.append(obj('DipRelInitialValue', 'objDipRelInitialValues', [('strTargetCountry', e),
                                                                              ('nValue', '0')]))
            for fr in friends:
                if fr != name:
                    dl.append(obj('DipRelInitialValue', 'objDipRelInitialValues', [('strTargetCountry', fr),
                                                                                  ('nValue', '900')]))
        save(t, os.path.join(DST, f))


def write_gamestate():
    path = os.path.join(DST, 'gamestate.xml')
    t = load(path)
    gs = t.getroot()[0]
    players = gs.findall("object[@type='Player']")
    am = gs.find("object[@type='AllianceManager']")
    by_name = {prop(p, 'strName'): p for p in players}
    for name, (_g, _h, _c, _cu, col) in NEW_NATIONS.items():
        p = obj('Player', 'objPlayers', [('strName', name), ('bNonPlayable', 'true'), ('colCountryColor', col)])
        gs.insert(list(gs).index(am), p)
        by_name[name] = p
    # Gold's updated palette (Southern Star / The Modern World) for every nation that has one
    for ref in ('The Modern World', 'Southern Star'):
        rt = load(os.path.join(GOLD, 'scenarios', ref, 'gamestate.xml')).getroot()[0]
        for rp in rt.findall("object[@type='Player']"):
            n = prop(rp, 'strName')
            if n in by_name and n not in NEW_NATIONS and prop(rp, 'colCountryColor'):
                set_prop(by_name[n], 'colCountryColor', prop(rp, 'colCountryColor'))
    for name, p in by_name.items():
        if name in PLAYABLE:
            set_prop(p, 'bNonPlayable', 'false')
            del_prop(p, 'bAIDisabled')
        else:
            set_prop(p, 'bNonPlayable', 'true')
        if name in AXIS or name in ALLIES:
            del_prop(p, 'bAIDisabled')
    for x in list(am):
        am.remove(x)

    def alliance(display, key, members, owner, principals):
        a = obj('Alliance', 'objAllAlliances', [('strDisplayName', display), ('strINITAllianceName', key)])
        for m in members:
            props = []
            if m == owner:
                props.append(('bOwner', 'true'))
            if m in principals:
                props.append(('bPrincipal', 'true'))
            props.append(('strINITCountryName', m))
            a.append(obj('AllianceMember', 'objAllMembers', props))
        return a

    am.append(alliance('Fascist Alliance', 'axis', AXIS, 'Germany', AXIS_PRINCIPAL))
    am.append(alliance('Free Nations', 'allies', ALLIES, 'United States', ALLIES_PRINCIPAL))
    am.append(obj('War', 'objAllWars', [('strDisplayName', 'World War II'), ('strINITOffenseAllianceName', 'axis'),
                                        ('strINITDefenseAllianceName', 'allies'),
                                        ('strINITAttackerCountryName', 'Germany'),
                                        ('strINITDefenderCountryName', 'United States')]))
    am.append(obj('War', 'objAllWars', [('strDisplayName', 'Sino-Japanese War'),
                                        ('strINITOffenseAllianceName', 'axis'), ('strINITDefenseAllianceName', ''),
                                        ('strINITAttackerCountryName', 'Japan'),
                                        ('strINITDefenderCountryName', 'Communist China')]))
    save(t, path)


def write_game():
    path = os.path.join(DST, 'game.xml')
    t = load(path)
    g = t.getroot()[0]
    set_prop(g, 'strScenario', NAME)
    blocked = set(SURRENDERED)
    market = g.find("object[@type='WorldMarket']")
    bloc = {c: 'axis' for c in AXIS}
    bloc.update({c: 'allies' for c in ALLIES})
    for fl in market.findall("object[@type='Flow']"):
        a, b = prop(fl, 'strFromCountry'), prop(fl, 'strToCountry')
        if a in blocked or b in blocked or (bloc.get(a) and bloc.get(b) and bloc[a] != bloc[b]):
            market.remove(fl)
    last = [e for e in g.findall('object') if (e.get('fromFile') or '').startswith('player')][-1]
    i = list(g).index(last) + 1
    for name in NEW_NATIONS:
        for kind in ('country', 'player'):
            g.insert(i, ET.Element('object', {'type': 'GO', 'name': 'objGOs', 'fromFile': '%s%s.xml' % (kind, name)}))
            i += 1
    view = g.find("object[@type='View']")
    if view is not None:
        for name in NEW_NATIONS:
            view.append(ET.Element('property', {'name': 'strAliases', 'value': name}))
    save(t, path)


def write_treaties():
    path = os.path.join(DST, 'treaties.xml')
    t = load(path)
    tl = t.getroot()[0]
    for tr in tl.findall('object'):
        if {prop(tr, 'strToCountry'), prop(tr, 'strFromCountry')} & set(SURRENDERED):
            tl.remove(tr)
    save(t, path)


def write_scenario():
    path = os.path.join(DST, 'scenario.xml')
    t = load(path)
    s = t.getroot()[0]
    for k, v in (('strName', NAME), ('strDescription', DESCRIPTION), ('strVersion', '1.0'),
                 ('nScenarioDuration', '200'), ('nStartYear', '1942'), ('nStartMonth', '1'), ('nStartDay', '1')):
        set_prop(s, k, v)
    save(t, path)
    path = os.path.join(DST, 'scenarioinfo.xml')
    t = load(path)
    s = t.getroot()[0]
    for k, v in (('strName', NAME), ('strDescription', DESCRIPTION), ('strVersion', '1.0'),
                 ('nStartYear', '1942'), ('nStartMonth', '1'), ('nStartDay', '1'), ('nEndYear', '1945'),
                 ('nEndMonth', '12'), ('nEndDay', '31'), ('strHistoricalComparison', COMPARISON),
                 ('nScenarioNumber', '30')):
        set_prop(s, k, v)
    for x in s.findall("object[@type='WrappedString']"):
        s.remove(x)
    for name in PLAYABLE:
        s.append(obj('WrappedString', 'objPlayableCountries', [('strString', name)]))
    save(t, path)


if __name__ == '__main__':
    main()
