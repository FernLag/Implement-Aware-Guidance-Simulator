"""How each machine looks, kept apart from how it behaves.

Nothing in this module can change a simulation result. It decides paint and
proportions, so an error here makes a picture wrong, not a number.

The same honesty rule as the catalog applies. A colour taken from a published
brand palette is marked `verified` with its source. A colour that is simply
what the machines look like, with no palette published anywhere I could find,
is marked unverified and says so in the interface. Nothing is presented as a
manufacturer specification when it is not.

A caution that is recorded rather than glossed: a brand palette is the colour
of the logo and marketing, which is not always the paint code on the sheet
metal. These are close enough to identify a machine at a glance, which is the
job, and they are not paint matches.

Manufacturer names and liveries are trademarks of their owners and are used
here only to depict the machine whose published specifications the catalog
cites.
"""

from __future__ import annotations

BRANDCOLORCODE = "https://www.brandcolorcode.com/"
USBRAND = "https://usbrandcolors.com/john-deere-colors/"


def _livery(body, trim, wheel, roof=None, verified=False, source=None, note=None):
    return {
        "body": body, "trim": trim, "wheel": wheel, "roof": roof or trim,
        "verified": verified, "source": source, "note": note,
    }


# Verified against a published brand palette.
LIVERY = {
    "John Deere": _livery(
        "#367C2B", "#27251F", "#FFDE00", roof="#3F3B36", verified=True, source=USBRAND,
        note="John Deere green #367C2B and yellow #FFDE00 as published."),
    "Case IH": _livery(
        "#D0002D", "#1A1A1A", "#B8B5AE", roof="#2B2B2B", verified=True,
        source=BRANDCOLORCODE + "case-ih", note="Case IH red #D0002D as published."),
    "New Holland": _livery(
        "#003F7D", "#1E2A38", "#B8B5AE", roof="#E8E4DA", verified=True,
        source=BRANDCOLORCODE + "new-holland-agriculture",
        note="New Holland blue #003F7D and yellow #FECD1A as published."),
    "Fendt": _livery(
        "#004713", "#2A2A28", "#9A9A96", roof="#006225", verified=True,
        source=BRANDCOLORCODE + "fendt",
        note="Fendt green #004713 with light green #006225 as published."),
    "Massey Ferguson": _livery(
        "#C71121", "#606163", "#A8A6A2", roof="#606163", verified=True,
        source=BRANDCOLORCODE + "massey-ferguson",
        note="Massey Ferguson red #C71121 and grey #606163 as published."),
    "CLAAS": _livery(
        "#4E6A2E", "#2E2E2C", "#B4C618", roof="#B4C618", verified=True,
        source=BRANDCOLORCODE + "claas",
        note="CLAAS palette green #B4C618 is the bright logo green, used here "
             "for trim; the body is the darker green the Axion is painted."),
    "Deutz-Fahr": _livery(
        "#76B824", "#3A3A38", "#AFB1B7", roof="#AFB1B7", verified=True,
        source=BRANDCOLORCODE + "deutz-fahr",
        note="Deutz-Fahr green #76B824 and greys as published, which that page "
             "itself notes are the closest numbers rather than official codes."),
    "Kubota": _livery(
        "#EB603F", "#2E2E2C", "#9A9A96", roof="#D8D5CC", verified=True,
        source="https://encycolorpedia.com/eb603f",
        note="Kubota orange #EB603F, matched to a Kubota orange paint code."),

    # No published palette found. Recognisable livery, recorded as unverified.
    "Valtra": _livery("#C8102E", "#1C1C1C", "#8E8B85", roof="#1C1C1C",
                      note="Valtra is offered in many colours; red is the common one."),
    "Mahindra": _livery("#B3282D", "#2A2A28", "#9A9A96", roof="#9A9A96"),
    "Monarch": _livery("#E8E6E0", "#2F3336", "#4A4E52", roof="#2F3336",
                       note="The MK-V is white and dark grey rather than a farm livery."),
}

IMPLEMENT_LIVERY = {
    "John Deere": _livery("#367C2B", "#27251F", "#FFDE00", verified=True, source=USBRAND),
    "Case IH": _livery("#D0002D", "#1A1A1A", "#B8B5AE", verified=True,
                       source=BRANDCOLORCODE + "case-ih"),
    "KUHN Krause": _livery("#C8102E", "#2A2A28", "#8E8B85"),
    "Vaderstad": _livery("#C8102E", "#2A2A28", "#8E8B85"),
    "HORSCH": _livery("#1E4620", "#141414", "#7A7A76"),
    "AMAZONE": _livery("#F07E13", "#2E5A2E", "#8E8B85",
                       note="AMAZONE machines are green and orange."),
    "Great Plains": _livery("#2E6B33", "#2A2A28", "#D8C22A"),
    "Land Pride": _livery("#E4661E", "#1C1C1C", "#8E8B85"),
    "Carbon Robotics": _livery("#F2F1ED", "#26262A", "#4A4E52",
                               note="The LaserWeeder is a white machine with dark modules."),
    "Verdant Robotics": _livery("#F2F1ED", "#2B4C6F", "#8E8B85"),
}

DEFAULT_LIVERY = _livery("#6E6B64", "#2E2E2C", "#8E8B85",
                         note="No livery recorded for this manufacturer.")


# Shape, as fractions of the wheelbase and body height, so a compact utility
# tractor is not just a scaled row-crop one. Drawing only.
PROFILES = {
    "utility": {
        "bonnet_len": 0.62, "bonnet_drop": 0.34, "bonnet_taper": 0.70,
        "cab_pos": -0.02, "cab_len": 0.52, "cab_height": 1.05,
        "exhaust": "stack_short", "front_weights": False, "fenders": True,
    },
    "midrange": {
        "bonnet_len": 0.74, "bonnet_drop": 0.28, "bonnet_taper": 0.76,
        "cab_pos": 0.04, "cab_len": 0.58, "cab_height": 1.18,
        "exhaust": "stack", "front_weights": True, "fenders": True,
    },
    "rowcrop": {
        "bonnet_len": 0.86, "bonnet_drop": 0.22, "bonnet_taper": 0.80,
        "cab_pos": 0.02, "cab_len": 0.64, "cab_height": 1.30,
        "exhaust": "stack", "front_weights": True, "fenders": True,
    },
    "electric": {
        "bonnet_len": 0.54, "bonnet_drop": 0.40, "bonnet_taper": 0.66,
        "cab_pos": 0.00, "cab_len": 0.46, "cab_height": 0.95,
        "exhaust": "none", "front_weights": False, "fenders": False,
    },
}

# Machines whose shape is not what their size alone would suggest.
PROFILE_OVERRIDES = {
    "monarch_mk_v": "electric",
}


def profile_for(tractor) -> tuple[str, dict]:
    """Pick a body shape from the machine's own sourced figures."""
    name = PROFILE_OVERRIDES.get(tractor.id)
    if name is None:
        power_kw = tractor.engine_power.value / 1000.0
        if power_kw < 95:
            name = "utility"
        elif power_kw < 175:
            name = "midrange"
        else:
            name = "rowcrop"
    return name, PROFILES[name]


def livery_for(manufacturer: str, implement: bool = False) -> dict:
    table = IMPLEMENT_LIVERY if implement else LIVERY
    return table.get(manufacturer, DEFAULT_LIVERY)
