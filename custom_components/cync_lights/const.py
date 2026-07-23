"""Constants for the Cync Lights integration."""
from homeassistant.const import Platform

DOMAIN = "cync_lights"

CONF_OTP = "otp"

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
