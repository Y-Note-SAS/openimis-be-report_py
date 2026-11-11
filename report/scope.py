"""
Central check of the location parameters a report is run with.

The report queries take their location and health-facility parameters straight
from the request and never compare them with the user's districts, so a district
officer could run a report on any other district by changing an id. Rather than
patching every query (they live in many modules, some installed from PyPI), the
report view refuses a parameter naming a location or a health facility outside
the user's scope before the query runs.

"All" values (empty, 0 or the negative ALL_* sentinels of the queries) are not a
specific location. Most queries then report on every district, so a location-restricted
user (not an IMIS admin, without the unscoped-location right) must name a location in
scope for the reports of LOCATION_REPORTS, and may not run NATIONAL_REPORTS (national
figures only) at all. The queries limiting an unrestricted run themselves
(`insuree_family_overview`, `insuree_missing_photo`) are in neither set.
"""
from django.conf import settings

#: parameters carrying a Location primary key
LOCATION_ID_PARAMS = (
    "locationId", "location_id", "regionId", "region_id", "districtId", "district_id",
    "requested_region_id", "requested_district_id",
)
#: parameters carrying a Location code (reportcsu)
LOCATION_CODE_PARAMS = ("location0", "location1", "location2", "district")
#: parameters carrying a HealthFacility primary key / code
HF_ID_PARAMS = ("requested_hf_id", "hfId", "hf_id")
HF_CODE_PARAMS = ("hflocation",)


#: reports narrowed by their location / health facility parameters: run on "all" they
#: cover every district
LOCATION_REPORTS = frozenset((
    "claim_percentage_referrals", "claims_overview", "claim_history",
    "claims_primary_operational_indicators", "premium_collection", "payment_category_overview",
    "registers_status", "insurees_pending_enrollment", "enrolled_families", "policy_renewals",
    "policy_primary_operational_indicators", "product_sales",
))
#: reports with no location parameter: national figures only
NATIONAL_REPORTS = frozenset((
    "contributions_distribution", "product_derived_operational_indicators",
))


def _specific_id(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _specific_code(value):
    if value is None:
        return None
    value = str(value).strip()
    return value if value and value not in ("0", "-1") else None


def _scoped_user(user):
    """The InteractiveUser to check, or None when no location check applies."""
    from core.models import InteractiveUser
    if not settings.ROW_SECURITY:
        return None
    from location.models import is_location_unscoped
    i_user = getattr(user, "_u", user)
    if not isinstance(i_user, InteractiveUser) or is_location_unscoped(i_user):
        return None
    return i_user


def out_of_scope_parameters(user, params):
    """Names of the parameters in `params` pointing outside `user`'s scope."""
    i_user = _scoped_user(user)
    if i_user is None:
        return []
    from location.models import HealthFacility, Location, LocationManager

    location_ids = {k: _specific_id(params.get(k)) for k in LOCATION_ID_PARAMS}
    location_codes = {k: _specific_code(params.get(k)) for k in LOCATION_CODE_PARAMS}
    hf_ids = {k: _specific_id(params.get(k)) for k in HF_ID_PARAMS}
    hf_codes = {k: _specific_code(params.get(k)) for k in HF_CODE_PARAMS}
    refused = []

    if any(location_ids.values()) or any(location_codes.values()):
        # strict: a region only counts when every district of it is assigned
        allowed = LocationManager().allowed(i_user.id, loc_types=["R", "D", "W", "V"], strict=True)
        for name, value in location_ids.items():
            if value and not allowed.filter(id=value).exists():
                refused.append(name)
        for name, value in location_codes.items():
            if value and not allowed.filter(code=value, validity_to__isnull=True).exists():
                refused.append(name)

    if any(hf_ids.values()) or any(hf_codes.values()):
        visible = HealthFacility.get_queryset(None, user)
        for name, value in hf_ids.items():
            if value and not visible.filter(id=value).exists():
                refused.append(name)
        for name, value in hf_codes.items():
            if value and not visible.filter(code=value, validity_to__isnull=True).exists():
                refused.append(name)
    return refused


def unscoped_run_refused(user, report_name, params):
    """
    Why a location-restricted `user` may not run `report_name` with `params`, or None:
    a national-only report, or a location report run on "all" (no specific location or
    health facility, which would cover every district).
    """
    if _scoped_user(user) is None:
        return None
    if report_name in NATIONAL_REPORTS:
        return "national report"
    if report_name in LOCATION_REPORTS:
        specific = (
            any(_specific_id(params.get(k)) for k in LOCATION_ID_PARAMS + HF_ID_PARAMS)
            or any(_specific_code(params.get(k)) for k in LOCATION_CODE_PARAMS + HF_CODE_PARAMS)
        )
        if not specific:
            return "no location in scope given"
    return None

