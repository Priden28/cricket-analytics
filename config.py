import os
from dotenv import load_dotenv

# Load .env file when running locally. In Cloud Run, env vars are injected
# directly by the platform so load_dotenv() simply finds nothing and moves on.
load_dotenv()

DB_CONFIG = {
    'host':     os.environ.get('DB_HOST',     'localhost'),
    'dbname':   os.environ.get('DB_NAME',     'Cricket'),
    'user':     os.environ.get('DB_USER',     'postgres'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'port':     int(os.environ.get('DB_PORT', '5432')),
}

# ML model path
MODEL_PATH = os.environ.get('MODEL_PATH', 'cricket_match_predictor.pkl')

# CORS origins
_raw_origins = os.environ.get(
    'ALLOWED_ORIGINS',
    'http://localhost:5173,http://localhost:3000'
)
ALLOWED_ORIGINS: list[str] = [o.strip() for o in _raw_origins.split(',') if o.strip()]

TEAM_MAPPING = {
    'IND': 'India',
    'PAK': 'Pakistan',
    'AUS': 'Australia',
    'ENG': 'England',
    'BAN': 'Bangladesh',
    'AFG': 'Afghanistan',
    'IRE': 'Ireland',
    'SA':  'South Africa',
    'SL':  'Sri Lanka',
    'NZ':  'New Zealand',
    'WI':  'West Indies',
    'ZIM': 'Zimbabwe',
}

DATASET_CONFIGS = {
    'team': {
        'min_columns': 11,
        'columns': [
            "Team", "ScoreDescending", "Overs", "RPO", "Lead", "Inns",
            "Result", "", "Opposition", "Ground", "Start Date"
        ],
    },
    'batting': {
        'min_columns': 12,
        'columns': [
            "Player", "RunsDescending", "Mins", "BF", "4s", "6s", "SR",
            "Inns", "", "Opposition", "Ground", "Start Date"
        ],
    },
    'bowling': {
        'min_columns': 12,
        'columns': [
            "Player", "Overs", "Mdns", "Runs", "WktsDescending", "Econ",
            "Inns", "", "Opposition", "Ground", "Start Date"
        ],
    },
}

URL_TEMPLATES = {
    'team': (
        "/ci/engine/stats/index.html?class=1;home_or_away=1;home_or_away=2;"
        "home_or_away=3;result=1;result=2;result=3;result=4;"
        "spanmin1={start_date};spanmax1=13+Aug+2050;spanval1=span;"
        "template=results;type=team;view=innings"
    ),
    'batting': (
        "/ci/engine/stats/index.html?class=1;home_or_away=1;home_or_away=2;"
        "home_or_away=3;result=1;result=2;result=3;result=4;"
        "spanmin1={start_date};spanmax1=13+Aug+2050;spanval1=span;"
        "template=results;type=batting;view=innings"
    ),
    'bowling': (
        "/ci/engine/stats/index.html?class=1;home_or_away=1;home_or_away=2;"
        "home_or_away=3;result=1;result=2;result=3;result=4;"
        "spanmin1={start_date};spanmax1=13+Aug+2050;spanval1=span;"
        "template=results;type=bowling;view=innings"
    ),
}

BASE_URL = "https://stats.espncricinfo.com"
