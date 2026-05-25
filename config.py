DB_CONFIG = {
    'host': 'localhost',
    'dbname': 'Cricket',
    'user': 'postgres',
    'password': 'B@rnat028',
    'port': 5432,
}

TEAM_MAPPING = {
    'IND': 'India',
    'PAK': 'Pakistan',
    'AUS': 'Australia',
    'ENG': 'England',
    'BAN': 'Bangladesh',
    'AFG': 'Afghanistan',
    'IRE': 'Ireland',
    'SA': 'South Africa',
    'SL': 'Sri Lanka',
    'NZ': 'New Zealand',
    'WI': 'West Indies',
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