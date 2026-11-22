"""GÉNÉRÉ par `scripts/generate_schema.py` — ne pas modifier à la main.

Types des 122 features du modèle `home-credit-serving` v2. Les règles métier sont dans
`credit_scoring/api/schemas.py`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

FEATURE_ORDER: tuple[str, ...] = (
    "autoFE_f_25",
    "INST_DBD_MEAN",
    "autoFE_f_18",
    "autoFE_f_95",
    "autoFE_f_131",
    "FLAG_EMAIL",
    "autoFE_f_29",
    "INST_COUNT",
    "INST_PREV_COUNT",
    "autoFE_f_43",
    "autoFE_f_16",
    "autoFE_f_5",
    "autoFE_f_36",
    "autoFE_f_61",
    "INST_PAYMENT_RATIO_MEAN",
    "autoFE_f_13",
    "autoFE_f_31",
    "POS_CNT_INSTALMENT_FUTURE_MEAN",
    "autoFE_f_121",
    "AMT_CREDIT",
    "PREV_DAYS_DECISION_MEAN",
    "autoFE_f_40",
    "EMERGENCYSTATE_MODE",
    "autoFE_f_41",
    "HOUSETYPE_MODE",
    "autoFE_f_44",
    "autoFE_f_7",
    "INST_AMT_PAYMENT_SUM",
    "autoFE_f_258",
    "autoFE_f_84",
    "autoFE_f_132",
    "autoFE_f_206",
    "autoFE_f_86",
    "autoFE_f_107",
    "OCCUPATION_TYPE",
    "autoFE_f_65",
    "autoFE_f_53",
    "autoFE_f_118",
    "DAYS_REGISTRATION",
    "PREV_DAYS_LAST_DUE_1ST_VERSION_MAX",
    "CNT_FAM_MEMBERS",
    "HOUR_APPR_PROCESS_START",
    "PREV_DAYS_TERMINATION_MAX",
    "FLAG_CONT_MOBILE",
    "autoFE_f_39",
    "INST_PAYMENT_DIFF_SUM",
    "autoFE_f_110",
    "INST_AMT_PAYMENT_MEAN",
    "POS_SK_DPD_DEF_MEAN",
    "PREV_APR_AMT_CREDIT_MEAN",
    "autoFE_f_32",
    "autoFE_f_9",
    "autoFE_f_14",
    "BUR_DAYS_CREDIT_MIN",
    "autoFE_f_1",
    "autoFE_f_261",
    "autoFE_f_37",
    "autoFE_f_88",
    "autoFE_f_42",
    "PREV_AMT_DOWN_PAYMENT_MEAN",
    "CC_AMT_BALANCE_MAX",
    "autoFE_f_100",
    "autoFE_f_82",
    "PREV_APP_CREDIT_RATIO_MIN",
    "autoFE_f_35",
    "autoFE_f_50",
    "autoFE_f_104",
    "FLAG_OWN_CAR",
    "OWN_CAR_AGE",
    "INST_PAYMENT_DIFF_MEAN",
    "autoFE_f_12",
    "autoFE_f_47",
    "autoFE_f_4",
    "autoFE_f_197",
    "autoFE_f_46",
    "autoFE_f_103",
    "autoFE_f_83",
    "autoFE_f_10",
    "autoFE_f_11",
    "BUR_AMT_CREDIT_SUM_SUM",
    "NAME_TYPE_SUITE",
    "autoFE_f_27",
    "REG_CITY_NOT_WORK_CITY",
    "PREV_CNT_PAYMENT_MEAN",
    "BUR_DEBT_CREDIT_RATIO_MEAN",
    "autoFE_f_3",
    "autoFE_f_15",
    "autoFE_f_23",
    "autoFE_f_2",
    "autoFE_f_74",
    "PREV_CANCELED_COUNT",
    "autoFE_f_17",
    "autoFE_f_94",
    "autoFE_f_38",
    "FLAG_DOCUMENT_3",
    "autoFE_f_136",
    "OBS_60_CNT_SOCIAL_CIRCLE",
    "autoFE_f_64",
    "autoFE_f_91",
    "autoFE_f_21",
    "autoFE_f_93",
    "autoFE_f_34",
    "autoFE_f_87",
    "autoFE_f_30",
    "autoFE_f_112",
    "autoFE_f_8",
    "autoFE_f_163",
    "PREV_REF_DAYS_DECISION_MAX",
    "DEF_30_CNT_SOCIAL_CIRCLE",
    "autoFE_f_98",
    "CODE_GENDER",
    "autoFE_f_19",
    "PREV_APP_CREDIT_RATIO_MEAN",
    "autoFE_f_6",
    "autoFE_f_22",
    "autoFE_f_58",
    "autoFE_f_119",
    "autoFE_f_28",
    "BUR_ACT_DAYS_CREDIT_MEAN",
    "INST_DAYS_ENTRY_PAYMENT_MAX",
    "autoFE_f_33",
    "autoFE_f_0",
)

NULLABLE_FEATURES: frozenset[str] = frozenset(
    {
        "autoFE_f_5",
        "autoFE_f_36",
        "autoFE_f_31",
        "autoFE_f_206",
        "autoFE_f_65",
        "autoFE_f_110",
        "autoFE_f_9",
        "autoFE_f_42",
        "autoFE_f_50",
        "autoFE_f_47",
        "autoFE_f_103",
        "autoFE_f_11",
        "autoFE_f_136",
        "autoFE_f_34",
        "autoFE_f_87",
        "autoFE_f_112",
        "autoFE_f_163",
        "autoFE_f_58",
        "autoFE_f_119",
    }
)

# Client synthétique : médianes et modalités les plus fréquentes du train.
EXAMPLE_CLIENT: dict[str, Any] = {
    "autoFE_f_25": 0.468136,
    "INST_DBD_MEAN": 10.117647,
    "autoFE_f_18": 0.489759,
    "autoFE_f_95": 0.274814,
    "autoFE_f_131": 0.510687,
    "FLAG_EMAIL": 0.0,
    "autoFE_f_29": 12.0,
    "INST_COUNT": 23.0,
    "INST_PREV_COUNT": 2.0,
    "autoFE_f_43": 0.526738,
    "autoFE_f_16": 1.058335,
    "autoFE_f_5": 1203531.534,
    "autoFE_f_36": 0.669575,
    "autoFE_f_61": 0.288054,
    "INST_PAYMENT_RATIO_MEAN": 1.0,
    "autoFE_f_13": 2.279559,
    "autoFE_f_31": 0.530591,
    "POS_CNT_INSTALMENT_FUTURE_MEAN": 6.948276,
    "autoFE_f_121": 99001.522576,
    "AMT_CREDIT": 514777.5,
    "PREV_DAYS_DECISION_MEAN": -789.0,
    "autoFE_f_40": 0.51898,
    "EMERGENCYSTATE_MODE": "No",
    "autoFE_f_41": 34.149576,
    "HOUSETYPE_MODE": "block of flats",
    "autoFE_f_44": 0.535276,
    "autoFE_f_7": 0.05135,
    "INST_AMT_PAYMENT_SUM": 318900.2175,
    "autoFE_f_258": 0.499662,
    "autoFE_f_84": 104780.766486,
    "autoFE_f_132": 0.491741,
    "autoFE_f_206": 0.590703,
    "autoFE_f_86": 108156.521739,
    "autoFE_f_107": 0.317885,
    "OCCUPATION_TYPE": "Laborers",
    "autoFE_f_65": 1e-06,
    "autoFE_f_53": 3.998339,
    "autoFE_f_118": 0.270553,
    "DAYS_REGISTRATION": 12.33,
    "PREV_DAYS_LAST_DUE_1ST_VERSION_MAX": 12.0,
    "CNT_FAM_MEMBERS": 2.0,
    "HOUR_APPR_PROCESS_START": 12.0,
    "PREV_DAYS_TERMINATION_MAX": -337.0,
    "FLAG_CONT_MOBILE": 1.0,
    "autoFE_f_39": 0.761063,
    "INST_PAYMENT_DIFF_SUM": 0.0,
    "autoFE_f_110": 2.462271,
    "INST_AMT_PAYMENT_MEAN": 12226.016939,
    "POS_SK_DPD_DEF_MEAN": 0.0,
    "PREV_APR_AMT_CREDIT_MEAN": 125462.25,
    "autoFE_f_32": 0.59705,
    "autoFE_f_9": 0.633087,
    "autoFE_f_14": 155898.382861,
    "BUR_DAYS_CREDIT_MIN": -1828.0,
    "autoFE_f_1": 0.05,
    "autoFE_f_261": 1e-06,
    "autoFE_f_37": 0.489546,
    "autoFE_f_88": 3.628608,
    "autoFE_f_42": 45.230475,
    "PREV_AMT_DOWN_PAYMENT_MEAN": 3375.0,
    "CC_AMT_BALANCE_MAX": 97555.41,
    "autoFE_f_100": -160.582875,
    "autoFE_f_82": 0.498656,
    "PREV_APP_CREDIT_RATIO_MIN": 0.898787,
    "autoFE_f_35": -0.447162,
    "autoFE_f_50": 36.202,
    "autoFE_f_104": 6048.641724,
    "FLAG_OWN_CAR": "N",
    "OWN_CAR_AGE": 9.0,
    "INST_PAYMENT_DIFF_MEAN": 0.0,
    "autoFE_f_12": 0.217391,
    "autoFE_f_47": 0.000395,
    "autoFE_f_4": 0.761063,
    "autoFE_f_197": 4.51,
    "autoFE_f_46": 2e-05,
    "autoFE_f_103": 53.16,
    "autoFE_f_83": 22.22467,
    "autoFE_f_10": 22.502435,
    "autoFE_f_11": 0.070039,
    "BUR_AMT_CREDIT_SUM_SUM": 961290.0,
    "NAME_TYPE_SUITE": "Unaccompanied",
    "autoFE_f_27": 2e-05,
    "REG_CITY_NOT_WORK_CITY": 0.0,
    "PREV_CNT_PAYMENT_MEAN": 12.0,
    "BUR_DEBT_CREDIT_RATIO_MEAN": 0.188542,
    "autoFE_f_3": 0.542445,
    "autoFE_f_15": 0.23591,
    "autoFE_f_23": 0.505446,
    "autoFE_f_2": 1.040722,
    "autoFE_f_74": 0.495666,
    "PREV_CANCELED_COUNT": 0.0,
    "autoFE_f_17": 0.480342,
    "autoFE_f_94": -151.63366,
    "autoFE_f_38": 9.905489,
    "FLAG_DOCUMENT_3": 1.0,
    "autoFE_f_136": 2.441963,
    "OBS_60_CNT_SOCIAL_CIRCLE": 0.0,
    "autoFE_f_64": 0.461849,
    "autoFE_f_91": 9.628512,
    "autoFE_f_21": 0.495396,
    "autoFE_f_93": -0.255617,
    "autoFE_f_34": 20.746,
    "autoFE_f_87": 2.325049,
    "autoFE_f_30": -25.272277,
    "autoFE_f_112": 0.068886,
    "autoFE_f_8": 0.271656,
    "autoFE_f_163": 0.683674,
    "PREV_REF_DAYS_DECISION_MAX": -395.0,
    "DEF_30_CNT_SOCIAL_CIRCLE": 0.0,
    "autoFE_f_98": 2.398835,
    "CODE_GENDER": "F",
    "autoFE_f_19": 12.0,
    "PREV_APP_CREDIT_RATIO_MEAN": 0.971391,
    "autoFE_f_6": 0.505446,
    "autoFE_f_22": 161453.860598,
    "autoFE_f_58": 0.000353,
    "autoFE_f_119": 187.22,
    "autoFE_f_28": 5335.434783,
    "BUR_ACT_DAYS_CREDIT_MEAN": -537.333333,
    "INST_DAYS_ENTRY_PAYMENT_MAX": -66.0,
    "autoFE_f_33": 14.15,
    "autoFE_f_0": 1.063909,
}


class GeneratedFeatures(BaseModel):
    """Les 122 features : toutes obligatoires, `null` seulement si nullable."""

    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, json_schema_extra={"examples": [EXAMPLE_CLIENT]}
    )

    autoFE_f_25: float
    INST_DBD_MEAN: float
    autoFE_f_18: float
    autoFE_f_95: float
    autoFE_f_131: float
    FLAG_EMAIL: float
    autoFE_f_29: float
    INST_COUNT: float
    INST_PREV_COUNT: float
    autoFE_f_43: float
    autoFE_f_16: float
    autoFE_f_5: float | None
    autoFE_f_36: float | None
    autoFE_f_61: float
    INST_PAYMENT_RATIO_MEAN: float
    autoFE_f_13: float
    autoFE_f_31: float | None
    POS_CNT_INSTALMENT_FUTURE_MEAN: float
    autoFE_f_121: float
    AMT_CREDIT: float
    PREV_DAYS_DECISION_MEAN: float
    autoFE_f_40: float
    EMERGENCYSTATE_MODE: Literal["No", "Yes"]
    autoFE_f_41: float
    HOUSETYPE_MODE: Literal["block of flats", "specific housing", "terraced house"]
    autoFE_f_44: float
    autoFE_f_7: float
    INST_AMT_PAYMENT_SUM: float
    autoFE_f_258: float
    autoFE_f_84: float
    autoFE_f_132: float
    autoFE_f_206: float | None
    autoFE_f_86: float
    autoFE_f_107: float
    OCCUPATION_TYPE: Literal[
        "Accountants",
        "Cleaning staff",
        "Cooking staff",
        "Core staff",
        "Drivers",
        "HR staff",
        "High skill tech staff",
        "IT staff",
        "Laborers",
        "Low-skill Laborers",
        "Managers",
        "Medicine staff",
        "Private service staff",
        "Realty agents",
        "Sales staff",
        "Secretaries",
        "Security staff",
        "Waiters/barmen staff",
    ]
    autoFE_f_65: float | None
    autoFE_f_53: float
    autoFE_f_118: float
    DAYS_REGISTRATION: float
    PREV_DAYS_LAST_DUE_1ST_VERSION_MAX: float
    CNT_FAM_MEMBERS: float
    HOUR_APPR_PROCESS_START: float
    PREV_DAYS_TERMINATION_MAX: float
    FLAG_CONT_MOBILE: float
    autoFE_f_39: float
    INST_PAYMENT_DIFF_SUM: float
    autoFE_f_110: float | None
    INST_AMT_PAYMENT_MEAN: float
    POS_SK_DPD_DEF_MEAN: float
    PREV_APR_AMT_CREDIT_MEAN: float
    autoFE_f_32: float
    autoFE_f_9: float | None
    autoFE_f_14: float
    BUR_DAYS_CREDIT_MIN: float
    autoFE_f_1: float
    autoFE_f_261: float
    autoFE_f_37: float
    autoFE_f_88: float
    autoFE_f_42: float | None
    PREV_AMT_DOWN_PAYMENT_MEAN: float
    CC_AMT_BALANCE_MAX: float
    autoFE_f_100: float
    autoFE_f_82: float
    PREV_APP_CREDIT_RATIO_MIN: float
    autoFE_f_35: float
    autoFE_f_50: float | None
    autoFE_f_104: float
    FLAG_OWN_CAR: Literal["N", "Y"]
    OWN_CAR_AGE: float
    INST_PAYMENT_DIFF_MEAN: float
    autoFE_f_12: float
    autoFE_f_47: float | None
    autoFE_f_4: float
    autoFE_f_197: float
    autoFE_f_46: float
    autoFE_f_103: float | None
    autoFE_f_83: float
    autoFE_f_10: float
    autoFE_f_11: float | None
    BUR_AMT_CREDIT_SUM_SUM: float
    NAME_TYPE_SUITE: Literal[
        "Children",
        "Family",
        "Group of people",
        "Other_A",
        "Other_B",
        "Spouse, partner",
        "Unaccompanied",
    ]
    autoFE_f_27: float
    REG_CITY_NOT_WORK_CITY: float
    PREV_CNT_PAYMENT_MEAN: float
    BUR_DEBT_CREDIT_RATIO_MEAN: float
    autoFE_f_3: float
    autoFE_f_15: float
    autoFE_f_23: float
    autoFE_f_2: float
    autoFE_f_74: float
    PREV_CANCELED_COUNT: float
    autoFE_f_17: float
    autoFE_f_94: float
    autoFE_f_38: float
    FLAG_DOCUMENT_3: float
    autoFE_f_136: float | None
    OBS_60_CNT_SOCIAL_CIRCLE: float
    autoFE_f_64: float
    autoFE_f_91: float
    autoFE_f_21: float
    autoFE_f_93: float
    autoFE_f_34: float | None
    autoFE_f_87: float | None
    autoFE_f_30: float
    autoFE_f_112: float | None
    autoFE_f_8: float
    autoFE_f_163: float | None
    PREV_REF_DAYS_DECISION_MAX: float
    DEF_30_CNT_SOCIAL_CIRCLE: float
    autoFE_f_98: float
    CODE_GENDER: Literal["F", "M", "XNA"]
    autoFE_f_19: float
    PREV_APP_CREDIT_RATIO_MEAN: float
    autoFE_f_6: float
    autoFE_f_22: float
    autoFE_f_58: float | None
    autoFE_f_119: float | None
    autoFE_f_28: float
    BUR_ACT_DAYS_CREDIT_MEAN: float
    INST_DAYS_ENTRY_PAYMENT_MAX: float
    autoFE_f_33: float
    autoFE_f_0: float
