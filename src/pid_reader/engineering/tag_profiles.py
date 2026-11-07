"""Rev L bounded, configurable site tag conventions; not an AI training stage.

No user-provided regular expressions or executable templates are evaluated.
Profiles classify observed source text only; they do not amend PDF observations
or prove the classification is correct. Different interpretations are retained.
"""
from __future__ import annotations

from ..api import canonical_json, sha256_hex

SCHEMA = "pid-reader-standalone-profiled-tags-v1"
ALGORITHM = "versioned-tag-profile-0.1"
CLASSES = {"INSTRUMENT","PUMP","VESSEL","TANK","COLUMN","HEAT_EXCHANGER","FILTER",
           "COMPRESSOR","VALVE_MANUAL","VALVE_CONTROL","VALVE_ONOFF","PSV","OTHER"}


def validate_profile(profile: dict) -> None:
    if type(profile) is not dict or set(profile)!={"name","version","separators","digit_min","digit_max","suffix_max","prefix_classes"}:
        raise ValueError("Tag profile must contain exact supported fields")
    if not isinstance(profile["name"],str) or not profile["name"].strip() or len(profile["name"])>80:
        raise ValueError("Invalid tag profile name")
    if type(profile["version"]) is not int or not 1<=profile["version"]<=1000000:
        raise ValueError("Invalid tag profile version")
    sep=profile["separators"]
    if not isinstance(sep,list) or not sep or len(sep)>4 or len(set(sep))!=len(sep) or any(x not in ("","-","_",".") for x in sep):
        raise ValueError("Invalid tag separators")
    if any(type(profile[x]) is not int for x in ("digit_min","digit_max","suffix_max")) or not 1<=profile["digit_min"]<=profile["digit_max"]<=8 or not 0<=profile["suffix_max"]<=4:
        raise ValueError("Invalid numeric/suffix bounds")
    pairs=profile["prefix_classes"]
    if not isinstance(pairs,dict) or not pairs or len(pairs)>150:
        raise ValueError("Invalid prefix catalogue")
    for k, v in pairs.items():
        if not isinstance(k,str) or not 1<=len(k)<=12 or not k.isascii() or not k.isalpha() or k!=k.upper():
            raise ValueError("Prefixes must be uppercase ASCII letters")
        if not isinstance(v,list) or not v or len(v)>5 or len(set(v))!=len(v) or any(x not in CLASSES for x in v):
            raise ValueError("Invalid or ambiguous class list")


def example_profile() -> dict:
    return {"name":"Illustrative generic tags - edit for each project","version":1,
            "separators":["-",""],"digit_min":2,"digit_max":6,"suffix_max":2,
            "prefix_classes":{"PT":["INSTRUMENT"],"PIT":["INSTRUMENT"],"LT":["INSTRUMENT"],
                              "TT":["INSTRUMENT"],"XV":["VALVE_ONOFF"],
                              "PSV":["PSV"],"V":["VESSEL"],"P":["PUMP"]}}


def profile_hash(profile: dict) -> str:
    validate_profile(profile)
    return sha256_hex(canonical_json(profile).encode("utf-8"))


def parse_tag(text: str, profile: dict) -> list[dict]:
    validate_profile(profile)
    if not isinstance(text,str) or not 1<=len(text)<=100 or not text.isascii():
        return []
    tag=text.upper().strip()
    result=[]
    for prefix in sorted(profile["prefix_classes"],key=lambda x:(-len(x),x)):
        if not tag.startswith(prefix):
            continue
        remain=tag[len(prefix):]
        for sep in profile["separators"]:
            if sep and not remain.startswith(sep):
                continue
            rest=remain[len(sep):]
            for k in range(profile["digit_min"],profile["digit_max"]+1):
                number,suffix=rest[:k],rest[k:]
                if not (len(number)==k and number.isascii() and number.isdigit() and
                        len(suffix)<=profile["suffix_max"] and suffix.isascii() and
                        (suffix=="" or (suffix.isalpha() and suffix==suffix.upper()))):
                    continue
                for cls in profile["prefix_classes"][prefix]:
                    item={"text":text,"prefix":prefix,"separator":sep,"number":number,"suffix":suffix,"class_proposal":cls}
                    if item not in result:
                        result.append(item)
    return sorted(result,key=lambda r: canonical_json(r))


def evaluate_text_links(links: dict, profile: dict) -> dict:
    validate_profile(profile)
    if not isinstance(links,dict) or links.get("schema") != "pid-reader-standalone-text-links-v1":
        raise ValueError("Requires standalone text associations")
    entries=[]
    for proposal in links["proposals"]:
        alternatives=[]
        for option in proposal["options"]:
            alternatives.append({"source_text":option["text_candidate"],
                                 "class_hypotheses":parse_tag(option["text_candidate"],profile),
                                 "source_proposal_id":proposal["id"]})
        entries.append({"proposal_id":proposal["id"],"symbol_id":proposal["symbol_id"],
                        "alternatives":alternatives,"review_state":"PROPOSED_UNVERIFIED"})
    body={"schema":SCHEMA,"algorithm":ALGORITHM,"source_sha256":links["source_sha256"],
          "text_link_sha256":links["result_sha256"],"tag_profile_sha256":profile_hash(profile),
          "tag_profile":profile,"entries":entries,
          "limitations":"Tag parsing follows the supplied project convention, not a validated instrument function."}
    body["result_sha256"]=sha256_hex(canonical_json(body).encode("utf-8"))
    return body


def validate_profiled_tags(result: dict, links: dict) -> list[str]:
    try:
        if result != evaluate_text_links(links,result["tag_profile"]):
            return ["Profiled tags differ from immutable source interpretations"]
        return []
    except (KeyError,TypeError,ValueError):
        return ["Cannot reconstruct profiled tag output"]
