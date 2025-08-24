"""
Tweede Kamer OData API tools for querying Dutch Parliament data.
"""

import requests
from typing import Dict, List, Optional, Any, Literal
from datetime import datetime, timedelta
import urllib.parse
from langchain_core.tools import tool
from pydantic import BaseModel, Field

BASE_URL = "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0"


@tool
def clarification_tool(
    target_tool: str,
    missing_or_unclear_params: List[str],
    user_request_context: str,
    suggestions: Optional[Dict[str, List[str]]] = None
) -> str:
    """
    Vraag om aanvullende informatie om API-calls te verbeteren.
    Geeft intelligente suggesties en opties aan de gebruiker.

    Args:
        target_tool: De tool waarvoor meer informatie nodig is (bijv. 'search_kamerleden', 'get_kamerstukken')
        missing_or_unclear_params: Lijst van parameters die ontbreken of onduidelijk zijn
        user_request_context: Context van het oorspronkelijke verzoek van de gebruiker
        suggestions: Optionele suggesties per parameter (bijv. {"functie": ["Tweede Kamerlid", "Eerste Kamerlid"]})
    """
    
    # Tool-specifieke parameter uitleg en suggesties
    param_explanations = {
        "naam": "naam van een Kamerlid (voor- en/of achternaam)",
        "functie": "functie in het parlement",
        "commissie": "naam van een commissie",
        "soort": "type kamerstuk of activiteit",
        "zoekterm": "zoekwoord in titel of onderwerp",
        "dagen_terug": "aantal dagen terug om te zoeken",
        "dagen_vooruit": "aantal dagen vooruit om te zoeken",
        "zaak_onderwerp": "onderwerp van de zaak",
        "actief": "of alleen actieve personen/commissies getoond moeten worden"
    }
    
    # Standaard suggesties per parameter
    default_suggestions = {
        "functie": ["Tweede Kamerlid", "Eerste Kamerlid", "Minister", "Staatssecretaris"],
        "soort": {
            "kamerstukken": ["Motie", "Amendement", "Wetsvoorstel", "Initiatiefnota", "Brief regering"],
            "activiteiten": ["Plenair debat", "Commissievergadering", "Hoorzitting", "Werkbezoek"]
        },
        "dagen_terug": ["7 (laatste week)", "14 (laatste 2 weken)", "30 (laatste maand)", "90 (laatste 3 maanden)"],
        "dagen_vooruit": ["7 (komende week)", "14 (komende 2 weken)", "30 (komende maand)"],
        "commissie": ["Financiën", "Justitie en Veiligheid", "Infrastructuur en Waterstaat", "Volksgezondheid", "Onderwijs", "Defensie", "Buitenlandse Zaken", "Economische Zaken", "Binnenlandse Zaken", "Sociale Zaken"],
        "actief": ["true (alleen actieve)", "false (ook niet-actieve)"]
    }
    
    # Bouw de clarificatie vraag op
    result = f"Om uw vraag over '{user_request_context}' goed te kunnen beantwoorden met de {target_tool} functie, heb ik aanvullende informatie nodig:\n\n"
    
    for param in missing_or_unclear_params:
        explanation = param_explanations.get(param, param)
        result += f"**{param.upper()}**: {explanation}\n"
        
        # Voeg suggesties toe als beschikbaar
        param_suggestions = []
        if suggestions and param in suggestions:
            param_suggestions = suggestions[param]
        elif param in default_suggestions:
            if isinstance(default_suggestions[param], dict) and target_tool in ["get_kamerstukken", "search_vergaderingen"]:
                # Kies de juiste suggesties op basis van tool type
                if "kamerstuk" in target_tool:
                    param_suggestions = default_suggestions[param].get("kamerstukken", [])
                else:
                    param_suggestions = default_suggestions[param].get("activiteiten", [])
            elif isinstance(default_suggestions[param], list):
                param_suggestions = default_suggestions[param]
        
        if param_suggestions:
            result += f"   Mogelijke opties: {', '.join(param_suggestions)}\n"
        
        result += "\n"
    
    # Voeg praktische voorbeelden toe
    examples = {
        "search_kamerleden": "Bijvoorbeeld: 'Mark Rutte' of 'Tweede Kamerlid actief'",
        "get_kamerstukken": "Bijvoorbeeld: 'Motie over klimaat laatste maand' of 'Wetsvoorstel zorg'",
        "search_vergaderingen": "Bijvoorbeeld: 'Commissie Financiën komende week' of 'Plenair debat'",
        "get_stemmingen": "Bijvoorbeeld: 'Stemmingen over begroting laatste week'",
        "search_commissies": "Bijvoorbeeld: 'Commissie met 'zorg' in de naam'"
    }
    
    if target_tool in examples:
        result += f"**Voorbeeld**: {examples[target_tool]}\n\n"
    
    result += "Kunt u deze informatie aanvullen zodat ik een gerichte zoekopdracht kan uitvoeren?\n\n"
    result += "STOP: Waiting for user clarification. Use send_email_tool to ask for more information."
    
    return result

@tool
def search_kamerleden(
    naam: Optional[str] = None,
    functie: Optional[str] = None,
    actief: bool = True,
    limit: int = 25
) -> str:
    """
    Zoek Kamerleden op basis van naam, functie of status.
    
    Args:
        naam: Deel van de naam om op te zoeken
        functie: 'Tweede Kamerlid', 'Eerste Kamerlid', etc.
        actief: True voor alleen actieve leden
        limit: Maximum aantal resultaten
    """
    print(f"🔍 TWEEDE KAMER API CALL: search_kamerleden(naam={naam}, functie={functie}, actief={actief}, limit={limit})")
    
    filters = ["Verwijderd eq false"]
    
    if naam:
        filters.append(f"(contains(Roepnaam, '{naam}') or contains(Achternaam, '{naam}'))")
    
    if functie:
        filters.append(f"Functie eq '{functie}'")
    
    if actief:
        filters.append("FractieZetelPersoon/any(a:a/TotEnMet eq null)")
    
    filter_str = " and ".join(filters)
    
    url = f"{BASE_URL}/Persoon"
    params = {
        "$filter": filter_str,
        "$top": limit,
        "$format": "application/json;odata.metadata=none"
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if 'value' in data and data['value']:
            result = f"Gevonden {len(data['value'])} Kamerleden:\n"
            for persoon in data['value']:
                naam_volledig = f"{persoon.get('Roepnaam', '')} {persoon.get('Achternaam', '')}"
                functie_str = persoon.get('Functie', 'Onbekend')
                result += f"- {naam_volledig} ({functie_str})\n"
            return result
        else:
            return "STOP: This completes the search. Use this information to provide your final answer. Ask user for more specific criteria. Send Email to user."

    except requests.RequestException as e:
        return f"Fout bij ophalen Kamerleden: {str(e)}"

@tool
def get_kamerstukken(
    soort: Optional[str] = None,
    dagen_terug: int = 30,
    zoekterm: Optional[str] = None,
    limit: int = 25
) -> str:
    """
    Haal recente kamerstukken op (moties, amendementen, wetsvoorstellen).
    
    Args:
        soort: 'Motie', 'Amendement', 'Wetsvoorstel', etc.
        dagen_terug: Aantal dagen terug om te zoeken
        zoekterm: Zoekterm in titel/onderwerp
        limit: Maximum aantal resultaten
    """
    print(f"📋 TWEEDE KAMER API CALL: get_kamerstukken(soort={soort}, dagen_terug={dagen_terug}, zoekterm={zoekterm}, limit={limit})")
    
    filters = ["Verwijderd eq false"]
    
    # Datum filter
    datum_vanaf = datetime.now() - timedelta(days=dagen_terug)
    datum_str = datum_vanaf.strftime("%Y-%m-%dT%H:%M:%SZ")
    filters.append(f"GestartOp ge {datum_str}")
    
    if soort:
        filters.append(f"Soort eq '{soort}'")
    
    if zoekterm:
        filters.append(f"contains(Onderwerp, '{zoekterm}')")
    
    filter_str = " and ".join(filters)
    
    url = f"{BASE_URL}/Zaak"
    params = {
        "$filter": filter_str,
        "$top": limit,
        "$orderby": "GestartOp desc",
        "$format": "application/json;odata.metadata=none"
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if 'value' in data and data['value']:
            result = f"Gevonden {len(data['value'])} kamerstukken:\n"
            for zaak in data['value']:
                onderwerp = zaak.get('Onderwerp', 'Geen onderwerp')
                soort_str = zaak.get('Soort', 'Onbekend')
                datum = zaak.get('GestartOp', '')[:10] if zaak.get('GestartOp') else 'Onbekend'
                result += f"- {onderwerp} ({soort_str}) - {datum}\n"
            return result
        else:
            return f"STOP: This completes the search. Use this information to provide your final answer. Ask user for more specific criteria. Send Email to user."

    except requests.RequestException as e:
        return f"Fout bij ophalen kamerstukken: {str(e)}"

@tool
def search_vergaderingen(
    commissie: Optional[str] = None,
    dagen_vooruit: int = 14,
    dagen_terug: int = 7,
    limit: int = 25
) -> str:
    """
    Zoek vergaderingen van commissies of plenaire sessies.
    
    Args:
        commissie: Naam van de commissie
        dagen_vooruit: Aantal dagen vooruit om te zoeken
        dagen_terug: Aantal dagen terug om te zoeken
        limit: Maximum aantal resultaten
    """
    print(f"📅 TWEEDE KAMER API CALL: search_vergaderingen(commissie={commissie}, dagen_vooruit={dagen_vooruit}, dagen_terug={dagen_terug}, limit={limit})")
    
    filters = ["Verwijderd eq false"]
    
    # Datum filter - zoek van X dagen terug tot Y dagen vooruit
    datum_vanaf = datetime.now() - timedelta(days=dagen_terug)
    datum_tot = datetime.now() + timedelta(days=dagen_vooruit)
    datum_vanaf_str = datum_vanaf.strftime("%Y-%m-%dT%H:%M:%SZ")
    datum_tot_str = datum_tot.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    filters.append(f"Aanvangstijd ge {datum_vanaf_str} and Aanvangstijd le {datum_tot_str}")
    
    if commissie:
        filters.append(f"contains(Onderwerp, '{commissie}')")
    
    filter_str = " and ".join(filters)
    
    url = f"{BASE_URL}/Activiteit"
    params = {
        "$filter": filter_str,
        "$top": limit,
        "$orderby": "Aanvangstijd asc",
        "$format": "application/json;odata.metadata=none"
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if 'value' in data and data['value']:
            result = f"Gevonden {len(data['value'])} vergaderingen:\n"
            for activiteit in data['value']:
                onderwerp = activiteit.get('Onderwerp', 'Geen onderwerp')
                soort = activiteit.get('Soort', 'Onbekend')
                begin = activiteit.get('Aanvangstijd', '')[:16] if activiteit.get('Aanvangstijd') else 'Onbekend'
                begin_formatted = begin.replace('T', ' om ') if 'T' in begin else begin
                result += f"- {onderwerp} ({soort}) - {begin_formatted}\n"
            return result
        else:
            return "STOP: This completes the search. Use this information to provide your final answer. Ask user for more specific criteria. Send Email to user."

    except requests.RequestException as e:
        return f"Fout bij ophalen vergaderingen: {str(e)}"

@tool
def get_stemmingen(
    dagen_terug: int = 7,
    zaak_onderwerp: Optional[str] = None,
    limit: int = 25
) -> str:
    """
    Haal recente stemmingen op.
    
    Args:
        dagen_terug: Aantal dagen terug om te zoeken
        zaak_onderwerp: Zoekterm in het onderwerp van de zaak
        limit: Maximum aantal resultaten
    """
    print(f"🗳️ TWEEDE KAMER API CALL: get_stemmingen(dagen_terug={dagen_terug}, zaak_onderwerp={zaak_onderwerp}, limit={limit})")
    
    filters = ["Verwijderd eq false"]
    
    # Datum filter
    datum_vanaf = datetime.now() - timedelta(days=dagen_terug)
    datum_str = datum_vanaf.strftime("%Y-%m-%dT%H:%M:%SZ")
    filters.append(f"GestartOp ge {datum_str}")
    
    if zaak_onderwerp:
        filters.append(f"Zaak/Onderwerp ne null and contains(Zaak/Onderwerp, '{zaak_onderwerp}')")
    
    filter_str = " and ".join(filters)
    
    url = f"{BASE_URL}/Stemming"
    params = {
        "$filter": filter_str,
        "$top": limit,
        "$orderby": "GestartOp desc",
        "$expand": "Zaak",
        "$format": "application/json;odata.metadata=none"
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if 'value' in data and data['value']:
            result = f"Gevonden {len(data['value'])} stemmingen:\n"
            for stemming in data['value']:
                soort = stemming.get('Soort', 'Onbekend')
                datum = stemming.get('GestartOp', '')[:10] if stemming.get('GestartOp') else 'Onbekend'
                zaak_info = stemming.get('Zaak', {})
                onderwerp = zaak_info.get('Onderwerp', 'Geen onderwerp') if zaak_info else 'Geen zaak'
                result += f"- {soort}: {onderwerp} - {datum}\n"
            return result
        else:
            return "STOP: This completes the search. Use this information to provide your final answer. Ask user for more specific criteria. Send Email to user."

    except requests.RequestException as e:
        return f"Fout bij ophalen stemmingen: {str(e)}"

@tool
def search_commissies(
    naam: Optional[str] = None,
    actief: bool = True,
    limit: int = 25
) -> str:
    """
    Zoek commissies op basis van naam.
    
    Args:
        naam: Deel van de commissienaam om op te zoeken
        actief: True voor alleen actieve commissies
        limit: Maximum aantal resultaten
    """
    print(f"🏛️ TWEEDE KAMER API CALL: search_commissies(naam={naam}, actief={actief}, limit={limit})")
    
    filters = ["Verwijderd eq false"]
    
    if naam:
        filters.append(f"contains(NaamNL, '{naam}')")
    
    if actief:
        filters.append("(Ingesteld le now() and (Opgeheven eq null or Opgeheven ge now()))")
    
    filter_str = " and ".join(filters)
    
    url = f"{BASE_URL}/Commissie"
    params = {
        "$filter": filter_str,
        "$top": limit,
        "$format": "application/json;odata.metadata=none"
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if 'value' in data and data['value']:
            result = f"Gevonden {len(data['value'])} commissies:\n"
            for commissie in data['value']:
                naam_nl = commissie.get('NaamNL', 'Geen naam')
                soort = commissie.get('Soort', 'Onbekend')
                ingesteld = commissie.get('Ingesteld', '')[:10] if commissie.get('Ingesteld') else 'Onbekend'
                result += f"- {naam_nl} ({soort}) - Ingesteld: {ingesteld}\n"
            return result
        else:
            return "STOP: This completes the search. Use this information to provide your final answer. Ask user for more specific criteria. Send Email to user."

    except requests.RequestException as e:
        return f"Fout bij ophalen commissies: {str(e)}"