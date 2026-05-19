#!/usr/bin/env python3
# Globe Radio — Oregon Scientific Horizon Globe (SONiX HID, VID:0x0c45 PID:0x7700)
# Input: pynput keyboard listener using vk codes (layout-independent).
# Tap a country → play a curated or Radio Browser stream.
# Tap an action zone → execute action (e.g. favourite toggle) with TTS feedback.
# Usage: python3 globe.py [--calibrate]

import sys, csv, queue, time, signal, random, logging, subprocess, requests, platform, threading, json, tempfile, os
from pathlib import Path

OS = platform.system()   # 'Darwin' on Mac, 'Linux' on Pi

if OS == 'Darwin':
    from pynput import keyboard as kb

_VK_MAC: dict[int, str] = {
    0x00: 'a', 0x0B: 'b', 0x08: 'c', 0x02: 'd', 0x0E: 'e', 0x03: 'f',
    0x1D: '0', 0x12: '1', 0x13: '2', 0x14: '3', 0x15: '4',
    0x17: '5', 0x16: '6', 0x1A: '7', 0x1C: '8', 0x19: '9',
}
_VK_LINUX: dict[int, str] = {
    30: 'a', 48: 'b', 46: 'c', 32: 'd', 18: 'e', 33: 'f',
    11: '0',  2: '1',  3: '2',  4: '3',  5: '4',
     6: '5',  7: '6',  8: '7',  9: '8', 10: '9',
}
VK_TO_HEX: dict[int, str] = _VK_MAC if OS == 'Darwin' else _VK_LINUX
SEQ_TIMEOUT  = 0.3
_tap_queue: queue.Queue = queue.Queue()
_seq:   list[str] = []
_seq_t: float     = 0.0
SCRIPT_DIR   = Path(__file__).parent
STATIONS_CSV = SCRIPT_DIR / "stations.csv"
FAVS_PATH    = SCRIPT_DIR / "favourites.json"
ACTIONS_FILE = SCRIPT_DIR / "actions.json"
API_SERVERS  = [
    "https://de1.api.radio-browser.info",
    "https://nl1.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
]
MPV_SOCKET   = "/tmp/globe-mpv.sock"
MPV_CMD      = ["mpv", "--no-video", "--really-quiet", "--cache=yes", "--no-input-terminal",
                f"--input-ipc-server={MPV_SOCKET}"]
DEBOUNCE_SEC = 2.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("globe")

# ── Pen code → country/region map ────────────────────────────────────────────
# Each entry: [country_name, ISO_code, city_or_None, lat_or_None, lon_or_None]
CODE_MAP: dict[str, list[list]] = {
    "a0108f": [["Central African Republic","CF",None,None,None]],
    "a0145f": [["China","CN",None,None,None]],
    "a0387f": [["United Kingdom","GB",None,None,None]],
    "a0401f": [["Taiwan","TW",None,None,None]],
    "a0441f": [["Guatemala","GT",None,None,None]],
    "a0465f": [["South Sudan","SS",None,None,None]],
    "a0467f": [["Sudan","SD",None,None,None]],
    "a0499f": [["Brazil","BR",None,None,None]],
    "a0602f": [["United States","US","Hawaii",19.5938015,-155.4283701]],
    "a0612f": [["Honduras","HN",None,None,None]],
    "a0613f": [["Costa Rica","CR",None,None,None]],
    "a0615f": [["Nicaragua","NI",None,None,None]],
    "a0616f": [["Panama","PA",None,None,None]],
    "a0631f": [["United States","US","Texas",30.27,-97.74]],
    "a0632f": [["United States","US","Houston",29.7589382,-95.3676974]],
    "a0638f": [["United States","US","New York",40.7127281,-74.0060152]],
    "a0663f": [["Australia","AU","Derby",-17.3031912,123.6287226]],
    "a0664f": [["Australia","AU",None,None,None]],
    "a0665f": [["Australia","AU",None,None,None]],
    "a0668f": [["Australia","AU",None,None,None]],
    "a0672f": [["Australia","AU",None,None,None]],
    "a0677f": [["Australia","AU","Tasmania",-42.035067,146.6366887]],
    "a0680f": [["Belize","BZ",None,None,None]],
    "a0682f": [["El Salvador","SV",None,None,None]],
    "a0685f": [["Nicaragua","NI",None,None,None]],
    "a0687f": [["Mexico","MX","Tijuana",32.5317397,-117.019529]],
    "a0691f": [["Mexico","MX",None,None,None]],
    "a0692f": [["Mexico","MX",None,None,None]],
    "a0694f": [["Mexico","MX",None,None,None]],
    "a0704f": [["Cuba","CU",None,None,None],["Jamaica","JM",None,None,None]],
    "a0706f": [["Canada","CA","Echo Bay",46.49,-84.06]],
    "a0731f": [["Canada","CA","Quebec",46.81,-71.21]],
    "a0741f": [["Bahamas","BS",None,None,None]],
    "a0743f": [["Cuba","CU",None,None,None]],
    "a0745f": [["Dominican Republic","DO",None,None,None]],
    "a0746f": [["Grenada","GD",None,None,None]],
    "a0747f": [["Haiti","HT",None,None,None]],
    "a0748f": [["Jamaica","JM",None,None,None]],
    "a0749f": [["Barbados","BB",None,None,None]],
    "a0752f": [["Trinidad and Tobago","TT",None,None,None]],
    "a0764f": [["Saint Kitts and Nevis","KN",None,None,None]],
    "a0765f": [["Saint Lucia","LC",None,None,None],["Saint Vincent and the Grenadines","VC",None,None,None]],
    "a0766f": [["Antigua and Barbuda","AG",None,None,None],["Dominica","DM",None,None,None]],
    "a0800f": [["Algeria","DZ",None,None,None]],
    "a0801f": [["Angola","AO",None,None,None]],
    "a0802f": [["Benin","BJ",None,None,None]],
    "a0803f": [["Botswana","BW",None,None,None]],
    "a0804f": [["Burkina Faso","BF",None,None,None]],
    "a0805f": [["Burundi","BI",None,None,None]],
    "a0806f": [["Cameroon","CM",None,None,None]],
    "a0807f": [["Cabo Verde","CV",None,None,None]],
    "a0808f": [["Central African Republic","CF",None,None,None]],
    "a0809f": [["Chad","TD",None,None,None]],
    "a0810f": [["Comoros","KM",None,None,None]],
    "a0812f": [["Congo","CG",None,None,None]],
    "a0813f": [["Congo","CG",None,None,None]],
    "a0814f": [["Côte d'Ivoire","CI",None,None,None]],
    "a0815f": [["Djibouti","DJ",None,None,None]],
    "a0816f": [["Egypt","EG",None,None,None]],
    "a0817f": [["Equatorial Guinea","GQ",None,None,None]],
    "a0818f": [["Cabo Verde","CV",None,None,None]],
    "a0819f": [["Ethiopia","ET",None,None,None]],
    "a0820f": [["Gabon","GA",None,None,None]],
    "a0821f": [["Gambia","GM",None,None,None]],
    "a0822f": [["Ghana","GH",None,None,None]],
    "a0823f": [["Guinea","GN",None,None,None]],
    "a0824f": [["Guinea-Bissau","GW",None,None,None]],
    "a0825f": [["Kenya","KE",None,None,None]],
    "a0826f": [["Lesotho","LS",None,None,None]],
    "a0827f": [["Liberia","LR",None,None,None]],
    "a0828f": [["Libya","LY",None,None,None]],
    "a0829f": [["Madagascar","MG",None,None,None]],
    "a0830f": [["Malawi","MW",None,None,None]],
    "a0831f": [["Mali","ML",None,None,None]],
    "a0832f": [["Mauritania","MR",None,None,None]],
    "a0833f": [["Mauritius","MU",None,None,None]],
    "a0834f": [["Morocco","MA",None,None,None]],
    "a0835f": [["Mozambique","MZ",None,None,None]],
    "a0836f": [["Namibia","NA",None,None,None]],
    "a0837f": [["Niger","NE",None,None,None]],
    "a0838f": [["Nigeria","NG",None,None,None]],
    "a0839f": [["Rwanda","RW",None,None,None]],
    "a0840f": [["Sao Tome and Principe","ST",None,None,None]],
    "a0841f": [["Senegal","SN",None,None,None]],
    "a0842f": [["Seychelles","SC",None,None,None]],
    "a0843f": [["Sierra Leone","SL",None,None,None]],
    "a0844f": [["Somalia","SO",None,None,None]],
    "a0845f": [["South Africa","ZA",None,None,None]],
    "a0847f": [["Eswatini","SZ",None,None,None]],
    "a0848f": [["Tanzania","TZ",None,None,None]],
    "a0849f": [["Togo","TG",None,None,None]],
    "a0850f": [["Tunisia","TN",None,None,None]],
    "a0851f": [["Uganda","UG",None,None,None]],
    "a0852f": [["Zambia","ZM",None,None,None]],
    "a0853f": [["Zimbabwe","ZW",None,None,None]],
    "a0855f": [["Morocco","MA",None,None,None]],
    "a0860f": [["Albania","AL",None,None,None]],
    "a0861f": [["Andorra","AD",None,None,None]],
    "a0862f": [["Armenia","AM",None,None,None]],
    "a0863f": [["Austria","AT",None,None,None]],
    "a0864f": [["Azerbaijan","AZ",None,None,None]],
    "a0865f": [["Belarus","BY",None,None,None]],
    "a0866f": [["Belgium","BE",None,None,None]],
    "a0867f": [["Bosnia and Herzegovina","BA",None,None,None]],
    "a0868f": [["Bulgaria","BG",None,None,None]],
    "a0869f": [["Croatia","HR",None,None,None]],
    "a0870f": [["Cyprus","CY",None,None,None]],
    "a0871f": [["Czechia","CZ",None,None,None]],
    "a0872f": [["Denmark","DK",None,None,None]],
    "a0873f": [["Estonia","EE",None,None,None]],
    "a0875f": [["Finland","FI",None,None,None]],
    "a0876f": [["France","FR",None,None,None],["Luxembourg","LU",None,None,None]],
    "a0877f": [["France","FR","South France",43.45,5.0],["Monaco","MC",None,None,None]],
    "a0878f": [["Georgia","GE",None,None,None]],
    "a0879f": [["Germany","DE",None,None,None]],
    "a0881f": [["Greece","GR",None,None,None]],
    "a0882f": [["Hungary","HU",None,None,None]],
    "a0883f": [["Iceland","IS",None,None,None]],
    "a0884f": [["Ireland","IE",None,None,None]],
    "a0886f": [["Vatican City","VA",None,None,None]],
    "a0888f": [["Latvia","LV",None,None,None]],
    "a0890f": [["Lithuania","LT",None,None,None]],
    "a0892f": [["North Macedonia","MK",None,None,None]],
    "a0893f": [["Malta","MT",None,None,None]],
    "a0894f": [["Moldova","MD",None,None,None]],
    "a0896f": [["Netherlands","NL",None,None,None]],
    "a0899f": [["Norway","NO",None,None,None]],
    "a0900f": [["Poland","PL",None,None,None],["Brazil","BR",None,None,None]],
    "a0902f": [["Portugal","PT",None,None,None]],
    "a0903f": [["Romania","RO",None,None,None]],
    "a0904f": [["Brazil","BR",None,None,None]],
    "a0905f": [["San Marino","SM",None,None,None]],
    "a0907f": [["Slovakia","SK",None,None,None]],
    "a0908f": [["Slovenia","SI",None,None,None]],
    "a0910f": [["Spain","ES",None,None,None]],
    "a0911f": [["Sweden","SE",None,None,None]],
    "a0913f": [["Switzerland","CH",None,None,None]],
    "a0914f": [["Turkey","TR",None,None,None]],
    "a0915f": [["Turkey","TR",None,None,None],["Bolivia","BO",None,None,None]],
    "a0917f": [["Ukraine","UA",None,None,None]],
    "a0918f": [["Italy","IT",None,None,None]],
    "a0932f": [["United Kingdom","GB","Scotland",56.7861112,-4.1140518]],
    "a0936f": [["Serbia","RS",None,None,None]],
    "a0937f": [["Montenegro","ME",None,None,None]],
    "a0940f": [["Argentina","AR",None,None,None]],
    "a0941f": [["Argentina","AR",None,None,None]],
    "a0943f": [["Argentina","AR",None,None,None]],
    "a0956f": [["Chile","CL",None,None,None]],
    "a0958f": [["Chile","CL",None,None,None]],
    "a0959f": [["Chile","CL",None,None,None]],
    "a0960f": [["Chile","CL",None,None,None]],
    "a0961f": [["Colombia","CO",None,None,None]],
    "a0962f": [["Ecuador","EC",None,None,None]],
    "a0964f": [["Paraguay","PY",None,None,None]],
    "a0965f": [["Peru","PE",None,None,None]],
    "a0966f": [["Guyana","GY",None,None,None]],
    "a0967f": [["Suriname","SR",None,None,None]],
    "a0968f": [["Uruguay","UY",None,None,None]],
    "a0969f": [["Venezuela","VE",None,None,None]],
    "a0973f": [["Ecuador","EC","Galapagos",-0.0606899,-90.673898]],
    "a0982f": [["Indonesia","ID",None,None,None]],
    "a0983f": [["Indonesia","ID",None,None,None]],
    "a0994f": [["Indonesia","ID",None,None,None]],
    "a1001f": [["Afghanistan","AF",None,None,None]],
    "a1003f": [["Bahrain","BH",None,None,None]],
    "a1004f": [["Bangladesh","BD",None,None,None]],
    "a1005f": [["Bhutan","BT",None,None,None]],
    "a1006f": [["Brunei","BN",None,None,None]],
    "a1007f": [["Cambodia","KH",None,None,None]],
    "a1009f": [["Timor-Leste","TL",None,None,None]],
    "a1011f": [["India","IN","New Delhi",28.6138954,77.2090057]],
    "a1016f": [["India","IN","Mumbai",19.08,72.88]],
    "a1018f": [["India","IN","Bangalore",12.97,77.59]],
    "a1019f": [["Iran","IR",None,None,None]],
    "a1022f": [["Iran","IR",None,None,None]],
    "a1023f": [["Iraq","IQ",None,None,None]],
    "a1024f": [["Palestine","PS",None,None,None]],
    "a1028f": [["Japan","JP",None,None,None]],
    "a1032f": [["Jordan","JO",None,None,None]],
    "a1033f": [["Kazakhstan","KZ",None,None,None]],
    "a1037f": [["Kazakhstan","KZ",None,None,None]],
    "a1040f": [["North Korea","KP",None,None,None]],
    "a1041f": [["Kuwait","KW",None,None,None]],
    "a1042f": [["Kyrgyzstan","KG",None,None,None]],
    "a1043f": [["Laos","LA",None,None,None]],
    "a1045f": [["Lebanon","LB",None,None,None]],
    "a1048f": [["Malaysia","MY",None,None,None]],
    "a1050f": [["Mongolia","MN",None,None,None]],
    "a1051f": [["Mongolia","MN",None,None,None]],
    "a1052f": [["Mongolia","MN",None,None,None]],
    "a1054f": [["Myanmar","MM",None,None,None]],
    "a1056f": [["Nepal","NP",None,None,None]],
    "a1057f": [["Oman","OM",None,None,None]],
    "a1058f": [["Pakistan","PK",None,None,None]],
    "a1062f": [["Philippines","PH",None,None,None]],
    "a1065f": [["Qatar","QA",None,None,None]],
    "a1066f": [["Saudi Arabia","SA",None,None,None]],
    "a1068f": [["Saudi Arabia","SA",None,None,None]],
    "a1069f": [["Saudi Arabia","SA",None,None,None]],
    "a1070f": [["Singapore","SG",None,None,None]],
    "a1071f": [["Sri Lanka","LK",None,None,None]],
    "a1072f": [["Syria","SY",None,None,None]],
    "a1073f": [["Tajikistan","TJ",None,None,None]],
    "a1074f": [["Thailand","TH",None,None,None]],
    "a1077f": [["Turkmenistan","TM",None,None,None]],
    "a1079f": [["United Arab Emirates","AE",None,None,None]],
    "a1080f": [["Uzbekistan","UZ",None,None,None]],
    "a1082f": [["Vietnam","VN",None,None,None]],
    "a1084f": [["Vietnam","VN",None,None,None]],
    "a1086f": [["Yemen","YE",None,None,None]],
    "a1089f": [["China","CN","Guangzhou",23.1288454,113.2590064]],
    "a1102f": [["China","CN",None,None,None]],
    "a1103f": [["China","CN","Guma",37.2435049,78.5941767]],
    "a1104f": [["China","CN",None,None,None]],
    "a1113f": [["China","CN","Lhasa",29.6542054,91.1173015]],
    "a1122f": [["China","CN",None,None,None]],
    "a1124f": [["China","CN","Beijing",39.9057136,116.3912972]],
    "a1144f": [["Russia","RU",None,None,None]],
    "a1148f": [["Russia","RU","Saint-Petersbourg",59.9606739,30.1586551]],
    "a1149f": [["Russia","RU",None,None,None]],
    "a1150f": [["Russia","RU",None,None,None]],
    "a1155f": [["Russia","RU",None,None,None]],
    "a1156f": [["Russia","RU",None,None,None]],
    "a1162f": [["Russia","RU",None,None,None]],
    "a1166f": [["Russia","RU",None,None,None]],
    "a1167f": [["Russia","RU",None,None,None]],
    "a1168f": [["Russia","RU",None,None,None]],
    "a1170f": [["Russia","RU",None,None,None]],
    "a1173f": [["Russia","RU",None,None,None]],
    "a1174f": [["Russia","RU",None,None,None]],
    "a1175f": [["Russia","RU",None,None,None]],
    "a1176f": [["Russia","RU",None,None,None]],
    "a1178f": [["Russia","RU",None,None,None]],
    "a1179f": [["Russia","RU",None,None,None]],
    "a1180f": [["Russia","RU",None,None,None]],
    "a1181f": [["Russia","RU",None,None,None]],
    "a1182f": [["Russia","RU",None,None,None]],
    "a1187f": [["Russia","RU",None,None,None]],
    "a1189f": [["Russia","RU",None,None,None]],
    "a1196f": [["Russia","RU",None,None,None]],
    "a1202f": [["Kiribati","KI",None,None,None]],
    "a1208f": [["Marshall Islands","MH",None,None,None]],
    "a1209f": [["Marshall Islands","MH",None,None,None]],
    "a1215f": [["Nauru","NR",None,None,None]],
    "a1217f": [["New Zealand","NZ",None,None,None]],
    "a1219f": [["New Zealand","NZ",None,None,None]],
    "a1225f": [["Papua New Guinea","PG",None,None,None]],
    "a1238f": [["American Samoa","AS",None,None,None]],
    "a1248f": [["Palau","PW",None,None,None]],
    "a1301f": [["Costa Rica","CR",None,None,None]],
    "a1303f": [["Guatemala","GT",None,None,None]],
    "a1304f": [["Honduras","HN",None,None,None]],
    "a1305f": [["Mexico","MX","Mexico City",19.3207722,-99.1514678]],
    "a1307f": [["Panama","PA",None,None,None]],
    "a1309f": [["United States","US","New York",40.71,-74.01]],
    "a1310f": [["United States","US","Los Angeles",34.05,-118.24]],
    "a1311f": [["United States","US","San Francisco",37.78,-122.42]],
    "a1312f": [["Canada","CA","Vancouver",49.28,-123.12]],
    "a1313f": [["Canada","CA","Toronto",43.65,-79.38]],
    "a1315f": [["Mexico","MX","Monterrey",25.6802019,-100.315258]],
    "a1320f": [["Argentina","AR","Buenos Aires",-34.6095579,-58.3887904]],
    "a1323f": [["Chile","CL",None,None,None]],
    "a1324f": [["Colombia","CO",None,None,None]],
    "a1325f": [["Ecuador","EC",None,None,None]],
    "a1343f": [["Peru","PE",None,None,None]],
    "a1362f": [["Eritrea","ER",None,None,None]],
    "a1364f": [["Ghana","GH",None,None,None]],
    "a1367f": [["Liberia","LR",None,None,None]],
    "a1369f": [["Madagascar","MG",None,None,None]],
    "a1371f": [["Mali","ML",None,None,None]],
    "a1375f": [["Namibia","NA",None,None,None]],
    "a1377f": [["Nigeria","NG",None,None,None]],
    "a1388f": [["Morocco","MA",None,None,None]],
    "a1407f": [["Ireland","IE",None,None,None]],
    "a1409f": [["Norway","NO",None,None,None]],
    "a1411f": [["Portugal","PT",None,None,None]],
    "a1413f": [["Russia","RU","Moscow",55.625578,37.6063916]],
    "a1415f": [["Sweden","SE",None,None,None]],
    "a1418f": [["United Kingdom","GB",None,None,None]],
    "a1425f": [["Afghanistan","AF",None,None,None]],
    "a1426f": [["Bangladesh","BD",None,None,None]],
    "a1429f": [["India","IN","New Delhi",28.61,77.21]],
    "a1431f": [["Iran","IR",None,None,None]],
    "a1433f": [["Japan","JP",None,None,None]],
    "a1434f": [["Kazakhstan","KZ",None,None,None]],
    "a1435f": [["South Korea","KR",None,None,None]],
    "a1438f": [["Malaysia","MY",None,None,None]],
    "a1439f": [["Maldives","MV",None,None,None]],
    "a1440f": [["Mongolia","MN",None,None,None]],
    "a1443f": [["Pakistan","PK",None,None,None]],
    "a1444f": [["Philippines","PH",None,None,None]],
    "a1445f": [["Saudi Arabia","SA",None,None,None]],
    "a1446f": [["Sri Lanka","LK",None,None,None]],
    "a1454f": [["India","IN","Kanpur",26.45,80.33]],
    "a1466f": [["Fiji","FJ",None,None,None]],
    "a1469f": [["Micronesia","FM",None,None,None]],
    "a1472f": [["Samoa","WS",None,None,None]],
    "a1473f": [["Solomon Islands","SB",None,None,None]],
    "a1474f": [["Tonga","TO",None,None,None]],
    "a1475f": [["Tuvalu","TV",None,None,None]],
    "a1476f": [["Vanuatu","VU",None,None,None]],
    "a1477f": [["Australia","AU","Sydney",-33.87,151.21]],
    "a1478f": [["Australia","AU","Melbourne",-37.81,144.96]],
    "a1479f": [["Australia","AU","Brisbane",-27.47,153.03]],
    "a1480f": [["Australia","AU","Perth",-31.95,115.86]],
}

# ── Action zones ──────────────────────────────────────────────────────────────
# Pen codes mapped to actions instead of stations.
# Loaded from actions.json at startup.
# Format: {"a0xxxf": "favourite_toggle", ...}
ACTION_MAP: dict[str, str] = {}
PRESET_MAP: dict[int, dict] = {}   # slot (1-6) → {name, url, label}
_current_volume: int = 80

def load_actions() -> None:
    if not ACTIONS_FILE.exists():
        return
    try:
        data = json.loads(ACTIONS_FILE.read_text(encoding="utf-8"))
        # New rich schema: {"zones": [...], "presets": [...]}
        if "zones" in data:
            loaded = 0
            for zone in data["zones"]:
                code   = zone.get("code", "")
                action = zone.get("action", "")
                if code and action and not code.startswith("TBD"):
                    ACTION_MAP[code] = action
                    loaded += 1
            log.info(f"Loaded {loaded} action zone(s) from zones list")
            # Load presets
            PRESET_MAP.clear()
            for preset in data.get("presets", []):
                slot = preset.get("slot")
                if isinstance(slot, int):
                    PRESET_MAP[slot] = {
                        "name":  preset.get("name", ""),
                        "url":   preset.get("url", ""),
                        "label": preset.get("label", f"Preset {slot}"),
                    }
            log.info(f"Loaded {len(PRESET_MAP)} preset slot(s)")
        else:
            # Legacy flat format: {"a0xxxf": "action", ...}
            ACTION_MAP.update(data)
            log.info(f"Loaded {len(data)} action zone(s) (legacy format)")
    except Exception as e:
        log.warning(f"Could not load actions.json: {e}")


COUNTRY_TO_ISO: dict[str, str] = {
    "UK": "GB", "United Kingdom": "GB",
    "Ireland": "IE", "France": "FR", "Belgium": "BE",
    "Netherlands": "NL", "Germany": "DE", "Portugal": "PT", "Spain": "ES",
    "Italy": "IT", "Poland": "PL", "Czechia": "CZ", "Denmark": "DK",
    "Sweden": "SE", "Estonia": "EE", "Ukraine": "UA", "Greece": "GR",
    "Georgia": "GE", "Palestine": "PS", "Ghana": "GH", "Nigeria": "NG",
    "India": "IN", "South Korea": "KR", "Japan": "JP", "Australia": "AU",
    "New Zealand": "NZ", "USA": "US", "Canada": "CA", "Brazil": "BR",
    "Argentina": "AR", "Chile": "CL", "Ecuador": "EC", "Colombia": "CO",
    "Peru": "PE", "Bolivia": "BO", "Paraguay": "PY", "Venezuela": "VE",
    "Suriname": "SR", "French Guyana": "GF", "French Guiana": "GF",
    "Guyana": "GY", "Syria": "SY", "Bali": "ID", "La Paz": "BO",
    "Thailand": "TH", "Indonesia": "ID", "Nicaragua": "NI", "Nicaragüa": "NI",
    "Panama": "PA", "Costa Rica": "CR", "Honduras": "HN", "Guatemala": "GT",
    "Jamaica": "JM", "Cuba": "CU", "Haiti": "HT",
    "Dominican Republic": "DO", "El Salvador": "SV", "Malaysia": "MY",
}


def _handle_keycode(vk: int) -> None:
    global _seq, _seq_t
    now = time.monotonic()
    ch  = VK_TO_HEX.get(vk)
    if ch is None:
        return
    if now - _seq_t > SEQ_TIMEOUT:
        _seq = []
    _seq.append(ch)
    _seq_t = now
    if len(_seq) == 6:
        _tap_queue.put(''.join(_seq))
        _seq = []
    elif len(_seq) > 6:
        _seq = _seq[-6:]


def _on_press(key) -> None:
    vk = getattr(key, 'vk', None)
    if vk is not None:
        _handle_keycode(vk)


PEN_VID, PEN_PID = 0x0c45, 0x7700

def _evdev_reader() -> None:
    import evdev
    while True:
        pen = None
        while pen is None:
            for path in evdev.list_devices():
                try:
                    d = evdev.InputDevice(path)
                    if d.info.vendor == PEN_VID and d.info.product == PEN_PID:
                        pen = d
                        break
                except Exception:
                    pass
            if pen is None:
                log.warning("Pen not found — retrying in 2 s…  (plug in the globe USB)")
                time.sleep(2)
        log.info(f"Pen: {pen.name}  ({pen.path})")
        try:
            pen.grab()
            for event in pen.read_loop():
                if event.type == evdev.ecodes.EV_KEY and event.value == 1:
                    _handle_keycode(event.code)
        except Exception as e:
            log.error(f"Pen read error: {e} — reconnecting in 2 s…")
            time.sleep(2)


def _bootstrap_favs_from_csv() -> None:
    """On first run, seed favourites.json from the CSV 'Favourite' column."""
    if FAVS_PATH.exists():
        return
    if not STATIONS_CSV.exists():
        return
    favs: list[str] = []
    try:
        with open(STATIONS_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("Favourite", "").strip().lower() == "yes":
                    name = row.get("Radio Station", "").strip()
                    if name:
                        favs.append(name)
        FAVS_PATH.write_text(
            __import__("json").dumps(favs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info(f"Bootstrapped favourites.json from CSV ({len(favs)} favourite(s))")
    except Exception as e:
        log.warning(f"Could not bootstrap favourites.json: {e}")


def _read_favs() -> set[str]:
    try:
        return set(__import__("json").loads(FAVS_PATH.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _write_favs(names: set[str]) -> None:
    import json as _json
    tmp = Path(str(FAVS_PATH) + ".tmp")
    tmp.write_text(_json.dumps(sorted(names), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(FAVS_PATH)


def load_stations(path: Path) -> dict[str, list[dict]]:
    _bootstrap_favs_from_csv()
    if not path.exists():
        log.warning("stations.csv not found — API-only mode")
        return {}
    favs = _read_favs()
    stations: dict[str, list[dict]] = {}
    skipped = 0
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            iso = COUNTRY_TO_ISO.get(row.get("Country", "").strip())
            if not iso:
                skipped += 1
                continue
            url = row.get("URL Link", "").strip()
            name = row.get("Radio Station", "").strip()
            stations.setdefault(iso, []).append({
                "name":      name,
                "url":       url,
                "favourite": name in favs,
            })
    total = sum(len(v) for v in stations.values())
    log.info(f"Loaded {total} stations across {len(stations)} countries ({skipped} skipped)")
    return stations


def pick_curated(stations: dict[str, list[dict]], iso: str) -> dict | None:
    pool          = stations.get(iso, [])
    favs_with_url = [s for s in pool if s["favourite"] and s["url"]]
    any_with_url  = [s for s in pool if s["url"]]
    if favs_with_url: return random.choice(favs_with_url)
    if any_with_url:  return random.choice(any_with_url)
    return None


def get_stream_from_api(iso: str) -> str | None:
    for server in API_SERVERS:
        try:
            r = requests.get(
                f"{server}/json/stations/bycountrycodeexact/{iso.upper()}",
                params={"hidebroken": "true", "order": "clickcount", "reverse": "true", "limit": 10},
                timeout=6,
            )
            pool = [s for s in r.json() if s.get("url_resolved")]
            if pool:
                pick = random.choice(pool[:5])
                log.info(f"  ♪  {pick['name']}  [Radio Browser]")
                return pick["url_resolved"]
            log.warning(f"  No API streams for {iso}")
            return None
        except Exception as e:
            log.warning(f"  {server} failed: {e}")
    log.error("  All API servers unreachable")
    return None


def resolve_stream(iso_list: list[str], curated: dict[str, list[dict]]) -> tuple[str | None, str | None]:
    """Returns (url, station_name)."""
    for iso in iso_list:
        s = pick_curated(curated, iso)
        if s:
            log.info(f"  ♪  {s['name']}  {'★ ' if s['favourite'] else ''}[curated]")
            return s["url"], s["name"]
    url = get_stream_from_api(iso_list[0])
    return url, None


_mpv: subprocess.Popen | None = None
_current_station: str | None = None  # name of currently playing station

def play(url: str, name: str | None = None) -> None:
    global _mpv, _current_station
    if _mpv and _mpv.poll() is None:
        _mpv.terminate(); _mpv.wait()
    _mpv = subprocess.Popen(MPV_CMD + [url], stdin=subprocess.DEVNULL)
    _current_station = name

def stop() -> None:
    global _mpv, _current_station
    if _mpv and _mpv.poll() is None:
        _mpv.terminate(); _mpv.wait()
    _mpv = None
    _current_station = None


# ── Volume control via mpv IPC ────────────────────────────────────────────────
def _mpv_set_volume(vol: int) -> None:
    try:
        import socket as _socket, json as _json
        with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            s.connect(MPV_SOCKET)
            s.sendall((_json.dumps({"command": ["set_property", "volume", vol]}) + "\n").encode())
    except Exception:
        pass


# ── TTS ───────────────────────────────────────────────────────────────────────
def speak(text: str) -> None:
    """Blocking TTS with auto-dim: lowers mpv volume while speaking, then restores."""
    playing = _mpv is not None and _mpv.poll() is None
    if playing:
        _mpv_set_volume(15)
    try:
        cmd = ["say", text] if OS == 'Darwin' else ["espeak-ng", "-v", "en", "-s", "140", text]
        subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        log.warning(f"TTS not available (tried {'say' if OS == 'Darwin' else 'espeak-ng'})")
    if playing:
        _mpv_set_volume(100)


# ── Favourite toggle ──────────────────────────────────────────────────────────
def toggle_favourite(curated: dict[str, list[dict]]) -> None:
    """Toggle favourite for the currently playing station in favourites.json."""
    if not _current_station:
        speak("Nothing is playing")
        log.info("Favourite toggle: nothing playing")
        return

    name = _current_station
    # Only allow toggling stations that are known in curated
    known = any(s["name"] == name for pool in curated.values() for s in pool)
    if not known:
        speak("Station not in list")
        log.info(f"Favourite toggle: '{name}' not found in curated stations")
        return

    try:
        favs = _read_favs()
        new_fav = name not in favs
        if new_fav:
            favs.add(name)
        else:
            favs.discard(name)
        _write_favs(favs)

        # Keep CSV Favourite column in sync so admin.py reads correctly
        if STATIONS_CSV.exists():
            try:
                rows = []
                with open(STATIONS_CSV, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    fieldnames = reader.fieldnames
                    for row in reader:
                        if row.get("Radio Station", "").strip() == name:
                            row["Favourite"] = "yes" if new_fav else ""
                        rows.append(row)
                tmp = STATIONS_CSV.with_suffix(".tmp")
                with open(tmp, "w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=fieldnames)
                    w.writeheader()
                    w.writerows(rows)
                tmp.replace(STATIONS_CSV)
            except Exception as csv_e:
                log.warning(f"CSV sync failed (non-fatal): {csv_e}")

        # Update in-memory curated dict
        for pool in curated.values():
            for s in pool:
                if s["name"] == name:
                    s["favourite"] = new_fav

        msg = "Favourite" if new_fav else "Not favourite anymore"
        log.info(f"★  {name} → {'favourite' if new_fav else 'not favourite'}")
        speak(msg)

    except Exception as e:
        log.error(f"Favourite toggle error: {e}")
        speak("Error")


# ── Action dispatcher ─────────────────────────────────────────────────────────
def dispatch_action(action: str, curated: dict[str, list[dict]]) -> None:
    global _current_volume

    if action == "favourite_toggle":
        toggle_favourite(curated)

    elif action == "stop":
        stop()
        speak("Stopped")

    elif action == "volume_up":
        _current_volume = min(100, _current_volume + 10)
        _mpv_set_volume(_current_volume)
        speak("volume up")
        log.info(f"Volume → {_current_volume}")

    elif action == "volume_down":
        _current_volume = max(0, _current_volume - 10)
        _mpv_set_volume(_current_volume)
        speak("volume down")
        log.info(f"Volume → {_current_volume}")

    elif action == "random":
        # Pick from all curated stations that have a URL
        all_stations: list[dict] = [
            s for pool in curated.values() for s in pool if s.get("url")
        ]
        if not all_stations:
            speak("no stations available")
            return
        station = random.choice(all_stations)
        log.info(f"Random pick: {station['name']}")
        play(station["url"], station.get("name"))
        speak(station.get("name") or "random station")

    elif action.startswith("preset_"):
        try:
            slot = int(action.split("_")[1])
        except (IndexError, ValueError):
            log.warning(f"Malformed preset action: {action}")
            return
        preset = PRESET_MAP.get(slot)
        if not preset or not preset.get("url"):
            speak("preset not set")
            log.info(f"Preset {slot}: not configured")
            return
        label = preset.get("label") or f"Preset {slot}"
        log.info(f"Preset {slot}: {preset['name']} — {preset['url']}")
        play(preset["url"], preset.get("name") or label)
        speak(label)

    else:
        log.warning(f"Unknown action: {action}")


def _entries_to_label(entries: list[list]) -> str:
    parts = []
    for e in entries:
        name, iso, city = e[0], e[1], e[2]
        parts.append(f"{city} ({iso})" if city else f"{name} ({iso})")
    return " / ".join(parts)


def _entries_to_tts(entries: list[list]) -> str:
    """Spoken label — no ISO codes: 'New York, United States' or 'France'."""
    e = entries[0]
    name, city = e[0], e[2]
    return f"{city}, {name}" if city else name


def calibrate() -> None:
    print("\n── Calibration mode ──  Tap countries, Ctrl+C to finish.\n")
    print(f"{'':5}{'code':12}  {'×':>3}  location")
    print("─" * 62)

    tap_count: dict[str, int]  = {}
    first_seen: list[str]      = []
    unknowns:  list[str]       = []

    try:
        while True:
            try:
                code = _tap_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            is_new = code not in tap_count
            tap_count[code] = tap_count.get(code, 0) + 1
            n = tap_count[code]

            if is_new:
                first_seen.append(code)

            entries = CODE_MAP.get(code)
            action  = ACTION_MAP.get(code)
            if action:
                label = f"ACTION: {action}"
            elif entries:
                label = _entries_to_label(entries)
            else:
                label = "⚠ NOT IN CODE_MAP"

            if is_new:
                if not entries and not action:
                    unknowns.append(code)
                    marker = "NEW→ "
                else:
                    marker = "     "
                print(f"{marker}{code:12}  ×{n:<3}  {label}")
            elif not entries and not action:
                print(f"     {code:12}  ×{n:<3}  {label}")

    except KeyboardInterrupt:
        pass

    total = sum(tap_count.values())
    print(f"\n── Done — {total} tap(s) on {len(tap_count)} unique code(s) ──")

    if unknowns:
        print(f"\n⚠  {len(unknowns)} unknown code(s) — fill in and paste into CODE_MAP in globe.py:\n")
        for code in unknowns:
            n = tap_count[code]
            print(f'    "{code}": [["COUNTRY_NAME", "XX", None, None, None]],  # tapped ×{n}')
        print()
    else:
        print("All codes recognised. ✓\n")

    print("Done.")


def main() -> None:
    calibrate_mode = "--calibrate" in sys.argv

    def shutdown(sig, _frame):
        log.info("Shutting down…"); stop(); sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    curated = load_stations(STATIONS_CSV)
    load_actions()

    if OS == 'Darwin':
        listener = kb.Listener(on_press=_on_press)
        listener.start()
    else:
        threading.Thread(target=_evdev_reader, daemon=True).start()
    log.info("Globe ready ✓  — tap a country")

    if calibrate_mode:
        calibrate(); return

    last_code:    str | None = None
    last_trigger: float      = 0.0

    while True:
        try:
            code = _tap_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        now = time.monotonic()
        if code == last_code and (now - last_trigger) < DEBOUNCE_SEC:
            continue

        last_code    = code
        last_trigger = now

        # Check action zones first
        action = ACTION_MAP.get(code)
        if action:
            log.info(f"Tap → ACTION:{action}  ({code})")
            dispatch_action(action, curated)
            continue

        entries = CODE_MAP.get(code)
        if not entries:
            log.debug(f"Unknown code {code}"); continue

        iso_list = [e[1] for e in entries]
        label    = _entries_to_label(entries)

        log.info(f"Tap → {label}  ({code})")
        speak(_entries_to_tts(entries))

        url, name = resolve_stream(iso_list, curated)
        if url:
            play(url, name)
        else:
            log.warning(f"No stream for {label}")


if __name__ == "__main__":
    main()
