# Memory Extractor Service
import re
from typing import List, Dict, Any
from schemas.memory import UserMemory

COUNTRIES = {
    "Portugal",
    "Spain",
    "France",
    "Germany",
    "Italy",
    "Netherlands",
    "Belgium",
    "England",
    "Brazil",
    "Argentina",
    "Uruguay",
}

def extract_memory(message: str):
    text = message.strip()

    # My name is John Doe
    match = re.search(r"My name Is (.+)", text, re.IGNORECASE)
    if match:
        return {
            "type": "name",
            "value": match.group(1).strip()
        }

    # My nickname is Johnny
    match = re.search(r"My nickname Is (.+)", text, re.IGNORECASE) or re.search(r"Call me (.+)", text, re.IGNORECASE)
    if match:
        return {
            "type": "nickname",
            "value": match.group(1).strip()
        }

    # My favorite club is FC Barcelona
    match = re.search(r"My favorite club Is (.+)", text, re.IGNORECASE) or re.search(r"I support (.+)", text, re.IGNORECASE)
    if match:
        value = match.group(1).strip()

        if value.lower() in COUNTRIES:
            return {
                "type": "supported_country",
                "value": value
            }
        return {
            "type": "favorite_club",
            "value": value
        }

    # My favorite player is Lionel Messi
    match = re.search(r"My favorite player Is (.+)", text, re.IGNORECASE) or re.search(r"My favorite footballer Is (.+)", text, re.IGNORECASE)
    if match:
        return {
            "type": "favorite_player",
            "value": match.group(1).strip()
        }

    # Prediction
    if "will win" in text.lower() or "I predict" in text.lower() or "will lose" in text.lower() or "i think" in text.lower():
        return {
            "type": "prediction",
            "value": text
        }

    # Opinion
    opinion_keywords = [
        "In my opinion", 
        "overrated", 
        "underrated", 
        "best team", 
        "worst team"
    ]

    for keyword in opinion_keywords:
        if keyword.lower() in text.lower():
            return {
                "type": "opinion",
                "value": text
            }
    
    return None