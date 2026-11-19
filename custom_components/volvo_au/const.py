"""Constants for Volvo (AU) integration."""

DOMAIN = "volvo_au"

# Config entry keys
CONF_VIN = "vin"
CONF_DPOP_PRIVATE_KEY_PEM = "dpop_private_key_pem"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_ID_TOKEN = "id_token"
CONF_APP_INSTALLATION_ID = "app_installation_id"
CONF_MODEL_NAME = "model_name"
CONF_MODEL_YEAR = "model_year"
CONF_REGISTRATION_PLATE = "registration_plate"

# Cadence (seconds)
POLL_IDLE = 300       # 5 min when the car is dormant
POLL_ACTIVE = 60      # 1 min when "interesting" (charging, doors open, recent command)
POLL_POST_CMD_FAST = 5  # 5 s polls for the first minute after a command
POLL_POST_CMD_WINDOW = 60

# Live-push streams (battery, exterior, parking climatization, pre-cleaning):
# the REST poll above still runs as a fallback, but these update as the
# backend reports them rather than waiting for the next poll.
#
# It isn't yet known, for a given endpoint, whether the backend keeps a
# subscription open and pushes further frames on its own, or sends one frame
# and closes (observed on Polestar's equivalent C3 streams, which replay
# their snapshot and close every ~120s). STREAM_MIN_RESUBSCRIBE_INTERVAL
# covers the second case: a clean close is followed by a short wait, then a
# resubscribe, rather than being treated as a failure. Tune this down if logs
# show the backend closing cleanly every time (i.e. this becomes the de facto
# poll interval for these four), or up if Volvo's gateway complains about
# reconnect frequency.
STREAM_MIN_RESUBSCRIBE_INTERVAL = 15  # seconds, after a clean close with data
STREAM_RETRY_DELAY = 10  # seconds (initial backoff after an error, doubles each retry)
STREAM_MAX_RETRIES = 10  # consecutive failures before giving up on a stream for this session

# Volvo OAuth / API
ISSUER = "https://volvoid.eu.volvocars.com"
TOKEN_URL = f"{ISSUER}/as/token.oauth2"
AUTHORIZE_URL = f"{ISSUER}/as/authorization.oauth2"
CLIENT_ID = "nxpwptn_10"
REDIRECT_URI = "volvooncall://auth/callback"
USER_AGENT = "vca-ios/6.9.0"

SCOPES = (
    "openid email profile phone address "
    "care_by_volvo:financial_information:invoice:read "
    "care_by_volvo:financial_information:payment_method "
    "care_by_volvo:subscription:read "
    "customer:attributes customer:attributes:write "
    "vehicle:attributes order:attributes "
    "account_link:link:admin:read "
    "volvo_on_call:all"
)
ACR_VALUES = "urn:volvoid:aal:bronze:2sv"
UI_LOCALES = "en-GB"

API_BASE = "https://cepmobtoken.kr.prod.c3.volvocars.com"
# Wait for a car command reply. A normal reply takes under 1 s; a stalled one did not come in 120 s (15 Nov 2026).
COMMAND_TIMEOUT_S = 60.0
DEFAULT_APP_INSTALLATION_ID = "2EE3A7A9-870F-4B74-BA09-E6BFB713CDA7"

# Car connectivity (16 Nov 2026). The car went offline at 19:32 (weak mobile signal),
# but Volvo's server still answered every command with HTTP 200, so HA believed the commands worked.
# online.py reads an explicit connectivity value from the availability reply when Volvo sends one.
# If there is none, it may use the newest car-side timestamp. That fallback is OFF (0) on purpose:
# a parked, online car also keeps its old values for hours (on 16 Nov the sensors did not change from 15:53,
# but the car was online until 19:32), so "old timestamp" alone would refuse commands on a healthy car
# every morning. Set this to a number of seconds only after the live timestamp fields are known to be a heartbeat.
OFFLINE_AFTER_S = 0
