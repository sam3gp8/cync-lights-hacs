"""Constants for the Cync Lights integration."""
from homeassistant.const import Platform

DOMAIN = "cync_lights"

CONF_OTP = "otp"

PLATFORMS = [Platform.LIGHT, Platform.SWITCH, Platform.FAN]

DEFAULT_SCAN_INTERVAL = 30  # seconds between forced state refreshes

# Device classification by Cync device_type_id range
PLUG_TYPE_IDS = set(range(64, 78))     # 64-77
FAN_TYPE_IDS = {113, 114, 115, 116}

CYNC_CAPABILITY_DIMMING = "DIMMING"
CYNC_CAPABILITY_CCT = "CCT_COLOR"
CYNC_CAPABILITY_RGB = "RGB_COLOR"

# Mireds range used for color_temp conversion (matches Cync's reported range)
MIN_MIREDS = 154
MAX_MIREDS = 370
