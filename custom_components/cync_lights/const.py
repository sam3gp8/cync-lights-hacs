"""Constants for the Cync Lights integration."""
from homeassistant.const import Platform

DOMAIN = "cync_lights"

CONF_OTP = "otp"

# -- Local control (optional) --------------------------------------------------
# When enabled, the integration runs a local TLS server impersonating
# cm.gelighting.com and (optionally) manages an AdGuard Home DNS rewrite so
# physical devices connect to Home Assistant instead of the Cync cloud.
# When set, entities stay available (controllable) whenever the cloud
# connection is healthy, instead of being gated on each device's reported
# online flag. Some hardware (e.g. Gen1 Wi-Fi wall switches) is controllable
# through the cloud/hub and shown online in the Cync app, yet never answers the
# mesh status query the integration uses to learn online state - so it reads as
# permanently "unavailable" in HA. This option makes those devices usable.
CONF_ASSUME_AVAILABLE = "assume_available"

CONF_ENABLE_LOCAL = "enable_local"
CONF_HOST_IP = "host_ip"                # HA's LAN IP that devices should reach
CONF_MANAGE_ADGUARD = "manage_adguard"  # let the integration set the DNS rewrite
CONF_ADGUARD_URL = "adguard_url"
CONF_ADGUARD_USERNAME = "adguard_username"
CONF_ADGUARD_PASSWORD = "adguard_password"

LOCAL_SERVER_PORT = 23779

PLATFORMS = [Platform.LIGHT, Platform.SWITCH, Platform.FAN]

DEFAULT_SCAN_INTERVAL = 60  # seconds between forced state refreshes

# If no state has been pushed from the cloud in this long — despite us actively
# requesting it every DEFAULT_SCAN_INTERVAL — treat the connection as dead and
# rebuild it. pycync reconnects its own socket, but nothing re-syncs device
# state afterwards, which is how devices get stuck "unavailable" indefinitely.
STALE_PUSH_SECONDS = 300

# Refresh the access token when it's within this many seconds of expiring.
TOKEN_REFRESH_MARGIN = 86400  # 24 hours

# Device classification by Cync device_type_id range
PLUG_TYPE_IDS = set(range(64, 78))     # 64-77
FAN_TYPE_IDS = {113, 114, 115, 116}

CYNC_CAPABILITY_DIMMING = "DIMMING"
CYNC_CAPABILITY_CCT = "CCT_COLOR"
CYNC_CAPABILITY_RGB = "RGB_COLOR"

# Mireds range used for color_temp conversion (matches Cync's reported range)
MIN_MIREDS = 154
MAX_MIREDS = 370
