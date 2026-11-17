"""Where each court sits in India's court structure: level, and the State(s) or Union Territory(ies) it serves. A fixed table, plain code: nothing is stored on the 18 million judgment records and
nothing is guessed from a title.

Country (India) -> State or Union Territory -> court level. The levels below the High Court (District and Sessions, Magistrate, Civil Judge, Family, Commercial) are in LEVELS so a filter and a record can
name them, but NO data for them is loaded: there is no free bulk dataset of district court judgments (docs/DISTRICT_COURT_LAYER_PROPOSAL.md). `district` and `court_complex` are therefore not fields yet.

One High Court can serve several States and Union Territories (Bombay: Maharashtra, Goa and Dadra and Nagar Haveli and Daman and Diu), and a State has one High Court: so a State filter selects the
High Court(s) serving it. The Supreme Court serves all of India: it is chosen with court_level "supreme", never by a State."""

LEVELS = ("supreme", "high", "district_sessions", "chief_judicial_magistrate", "civil_judge_senior", "civil_judge_junior", "family", "commercial", "other")
LOADED_LEVELS = ("supreme", "high")  # the levels that have records

# court code (as in the public dataset) -> the State(s)/Union Territory(ies) the High Court serves; the first is where its principal seat is
HIGH_COURTS: dict[str, tuple[str, ...]] = {
    "10_8": ("Bihar",),
    "11_24": ("Sikkim",),
    "14_25": ("Manipur",),
    "16_20": ("Tripura",),
    "17_21": ("Meghalaya",),
    "18_6": ("Assam", "Nagaland", "Mizoram", "Arunachal Pradesh"),
    "19_16": ("West Bengal", "Andaman and Nicobar Islands"),
    "1_12": ("Jammu and Kashmir", "Ladakh"),
    "20_7": ("Jharkhand",),
    "21_11": ("Odisha",),
    "22_18": ("Chhattisgarh",),
    "23_23": ("Madhya Pradesh",),
    "24_17": ("Gujarat",),
    "27_1": ("Maharashtra", "Goa", "Dadra and Nagar Haveli and Daman and Diu"),
    "28_2": ("Andhra Pradesh",),
    "29_3": ("Karnataka",),
    "2_5": ("Himachal Pradesh",),
    "32_4": ("Kerala", "Lakshadweep"),
    "33_10": ("Tamil Nadu", "Puducherry"),
    "36_29": ("Telangana",),
    "3_22": ("Punjab", "Haryana", "Chandigarh"),
    "5_15": ("Uttarakhand",),
    "7_26": ("Delhi",),
    "8_9": ("Rajasthan",),
    "9_13": ("Uttar Pradesh",),
}
SUPREME = "SC"
STATES = tuple(sorted({s for v in HIGH_COURTS.values() for s in v}))


def level_of(court_code: str | None) -> str | None:
    """"supreme", "high", or None for a code this table does not know (never guessed)."""
    return "supreme" if court_code == SUPREME else "high" if court_code in HIGH_COURTS else None


def states_served(court_code: str | None) -> list[str]:
    return list(HIGH_COURTS.get(court_code or "", ()))


def courts_for_state(state: str) -> list[str]:
    """The High Court code(s) serving a State or Union Territory (matched exactly, ignoring case); empty for a name that is not one."""
    want = (state or "").strip().casefold()
    return sorted(code for code, served in HIGH_COURTS.items() if any(s.casefold() == want for s in served))


def courts_for_level(level: str) -> list[str]:
    if level == "supreme":
        return [SUPREME]
    if level == "high":
        return sorted(HIGH_COURTS)
    return []


def describe(court_code: str | None) -> dict:
    return {"court_level": level_of(court_code), "states": states_served(court_code)}
