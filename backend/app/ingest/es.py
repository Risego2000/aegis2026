"""Titulares de las fuentes en español.

Las fuentes abiertas publican en inglés (USGS, GDACS, NWS y los nombres de país
de GDELT). La interfaz es en español, así que los titulares se redactan aquí:
se traducen las fórmulas repetidas (magnitud + distancia + rumbo + país, tipo de
amenaza, avisos meteorológicos) y se dejan intactos los topónimos menores y los
nombres propios, que no se traducen.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# países y territorios (nombre inglés -> español)
# --------------------------------------------------------------------------- #
PAIS_ES: dict[str, str] = {
    "Afghanistan": "Afganistán", "Albania": "Albania", "Algeria": "Argelia",
    "Angola": "Angola", "Argentina": "Argentina", "Armenia": "Armenia",
    "Australia": "Australia", "Austria": "Austria", "Azerbaijan": "Azerbaiyán",
    "Bahamas": "Bahamas", "Bangladesh": "Bangladés", "Barbados": "Barbados",
    "Belarus": "Bielorrusia", "Belgium": "Bélgica", "Belize": "Belice",
    "Bolivia": "Bolivia", "Bosnia and Herzegovina": "Bosnia y Herzegovina",
    "Botswana": "Botsuana", "Brazil": "Brasil", "Bulgaria": "Bulgaria",
    "Cambodia": "Camboya", "Cameroon": "Camerún", "Canada": "Canadá",
    "Chile": "Chile", "China": "China", "Colombia": "Colombia",
    "Costa Rica": "Costa Rica", "Croatia": "Croacia", "Cuba": "Cuba",
    "Cyprus": "Chipre", "Czechia": "Chequia", "Czech Republic": "República Checa",
    "Denmark": "Dinamarca", "Dominican Republic": "República Dominicana",
    "Ecuador": "Ecuador", "Egypt": "Egipto", "El Salvador": "El Salvador",
    "Estonia": "Estonia", "Ethiopia": "Etiopía", "Fiji": "Fiyi",
    "Finland": "Finlandia", "France": "Francia", "Georgia": "Georgia",
    "Germany": "Alemania", "Ghana": "Ghana", "Greece": "Grecia",
    "Guatemala": "Guatemala", "Haiti": "Haití", "Honduras": "Honduras",
    "Hungary": "Hungría", "Iceland": "Islandia", "India": "India",
    "Indonesia": "Indonesia", "Iran": "Irán", "Iraq": "Irak", "Ireland": "Irlanda",
    "Israel": "Israel", "Italy": "Italia", "Jamaica": "Jamaica", "Japan": "Japón",
    "Jordan": "Jordania", "Kazakhstan": "Kazajistán", "Kenya": "Kenia",
    "Kuwait": "Kuwait", "Kyrgyzstan": "Kirguistán", "Laos": "Laos",
    "Lebanon": "Líbano", "Libya": "Libia", "Lithuania": "Lituania",
    "Madagascar": "Madagascar", "Malaysia": "Malasia", "Mali": "Mali",
    "Mexico": "México", "Moldova": "Moldavia", "Mongolia": "Mongolia",
    "Montenegro": "Montenegro", "Morocco": "Marruecos", "Mozambique": "Mozambique",
    "Myanmar": "Birmania", "Namibia": "Namibia", "Nepal": "Nepal",
    "Netherlands": "Países Bajos", "New Zealand": "Nueva Zelanda",
    "Nicaragua": "Nicaragua", "Niger": "Níger", "Nigeria": "Nigeria",
    "North Macedonia": "Macedonia del Norte", "Norway": "Noruega",
    "Oman": "Omán", "Pakistan": "Pakistán", "Panama": "Panamá",
    "Papua New Guinea": "Papúa Nueva Guinea", "Paraguay": "Paraguay",
    "Peru": "Perú", "Philippines": "Filipinas", "Poland": "Polonia",
    "Portugal": "Portugal", "Qatar": "Catar", "Romania": "Rumanía",
    "Russia": "Rusia", "Rwanda": "Ruanda", "Saudi Arabia": "Arabia Saudí",
    "Senegal": "Senegal", "Serbia": "Serbia", "Slovakia": "Eslovaquia",
    "Slovenia": "Eslovenia", "Somalia": "Somalia", "South Africa": "Sudáfrica",
    "South Korea": "Corea del Sur", "North Korea": "Corea del Norte",
    "Spain": "España", "Sri Lanka": "Sri Lanka", "Sudan": "Sudán",
    "Sweden": "Suecia", "Switzerland": "Suiza", "Syria": "Siria",
    "Taiwan": "Taiwán", "Tajikistan": "Tayikistán", "Tanzania": "Tanzania",
    "Thailand": "Tailandia", "Tunisia": "Túnez", "Turkey": "Turquía",
    "Turkmenistan": "Turkmenistán", "Uganda": "Uganda", "Ukraine": "Ucrania",
    "United Arab Emirates": "Emiratos Árabes Unidos",
    "United Kingdom": "Reino Unido", "United States": "Estados Unidos",
    "Uruguay": "Uruguay", "Uzbekistan": "Uzbekistán", "Venezuela": "Venezuela",
    "Vietnam": "Vietnam", "Yemen": "Yemen", "Zambia": "Zambia", "Zimbabwe": "Zimbabue",
    "Puerto Rico": "Puerto Rico", "Guam": "Guam", "Hawaii": "Hawái",
    "Alaska": "Alaska", "California": "California", "Canary Islands": "Islas Canarias",
    "Balearic Islands": "Islas Baleares", "Azores": "Azores",
    "Mid-Atlantic Ridge": "Dorsal mesoatlántica",
    "South Sandwich Islands": "Islas Sandwich del Sur",
    "South Georgia and the South Sandwich Islands": "Islas Georgias del Sur y Sandwich del Sur",
    "Solomon Islands": "Islas Salomón", "Vanuatu": "Vanuatu", "Tonga": "Tonga",
    "Samoa": "Samoa", "New Caledonia": "Nueva Caledonia", "Fiji Islands": "Islas Fiyi",
    "Cape Verde": "Cabo Verde", "Cabo Verde": "Cabo Verde",
    "Democratic Republic of the Congo": "República Democrática del Congo",
    "Republic of the Congo": "República del Congo", "Congo": "Congo",
    "Ivory Coast": "Costa de Marfil", "Burkina Faso": "Burkina Faso",
    "Central African Republic": "República Centroafricana",
    "South Sudan": "Sudán del Sur", "Eritrea": "Eritrea", "Djibouti": "Yibuti",
    "Mauritania": "Mauritania", "Chad": "Chad", "Gabon": "Gabón",
    "Equatorial Guinea": "Guinea Ecuatorial", "Guinea": "Guinea",
    "Sierra Leone": "Sierra Leona", "Liberia": "Liberia", "Togo": "Togo",
    "Benin": "Benín", "Gambia": "Gambia", "Guinea-Bissau": "Guinea-Bisáu",
    "Malawi": "Malaui", "Lesotho": "Lesoto", "Eswatini": "Esuatini",
    "Bermuda": "Bermudas", "Greenland": "Groenlandia", "Faroe Islands": "Islas Feroe",
}

ROOT_LABELS_ES = {
    "public statement": "Declaración pública",
    "appeal": "Llamamiento",
    "intent to cooperate": "Intención de cooperar",
    "consultation": "Consulta",
    "diplomatic cooperation": "Cooperación diplomática",
    "material cooperation": "Cooperación material",
    "provide aid": "Ayuda material",
    "yield": "Cese",
    "investigate": "Investigación",
    "demand": "Exigencia",
    "disapprove": "Desaprobación",
    "reject": "Rechazo",
    "threaten": "Amenaza",
    "protest": "Protesta",
    "force posture": "Demostración de fuerza",
    "reduce force posture": "Retirada de fuerzas",
    "coerce": "Coacción",
    "assault": "Agresión",
    "armed clash": "Choque armado",
    "mass violence": "Violencia masiva",
    "event": "Suceso",
}

# Nombres de actor CAMEO más frecuentes (van en los titulares).
ACTOR_ES = {
    "UNITED STATES": "Estados Unidos",
    "UNITED KINGDOM": "Reino Unido",
    "RUSSIA": "Rusia",
    "RUSSIAN": "Ruso",
    "UKRAINE": "Ucrania",
    "UKRAINIAN": "Ucraniano",
    "ISRAEL": "Israel",
    "ISRAELI": "Israelí",
    "IRAN": "Irán",
    "IRANIAN": "Iraní",
    "MOROCCO": "Marruecos",
    "MOROCCAN": "Marroquí",
    "MEXICO": "México",
    "MEXICAN": "Mexicano",
    "CANADA": "Canadá",
    "CANADIAN": "Canadiense",
    "NIGERIA": "Nigeria",
    "NIGERIAN": "Nigeriano",
    "SWEDEN": "Suecia",
    "SWEDISH": "Sueco",
    "GERMANY": "Alemania",
    "GERMAN": "Alemán",
    "FRANCE": "Francia",
    "FRENCH": "Francés",
    "SPAIN": "España",
    "SPANISH": "Español",
    "ITALY": "Italia",
    "ITALIAN": "Italiano",
    "PORTUGAL": "Portugal",
    "POLAND": "Polonia",
    "POLISH": "Polaco",
    "TURKEY": "Turquía",
    "TURKISH": "Turco",
    "SYRIA": "Siria",
    "SYRIAN": "Sirio",
    "LEBANON": "Líbano",
    "LEBANESE": "Libio",
    "IRAQ": "Irak",
    "IRAQI": "Iraquí",
    "AFGHANISTAN": "Afganistán",
    "AFGHAN": "Afgano",
    "PAKISTAN": "Pakistán",
    "PAKISTANI": "Pakistaní",
    "INDIA": "India",
    "INDIAN": "Indio",
    "CHINA": "China",
    "CHINESE": "Chino",
    "JAPAN": "Japón",
    "JAPANESE": "Japonés",
    "SOUTH KOREA": "Corea del Sur",
    "NORTH KOREA": "Corea del Norte",
    "BRAZIL": "Brasil",
    "BRAZILIAN": "Brasileño",
    "ARGENTINA": "Argentina",
    "ARGENTINIAN": "Argentino",
    "COLOMBIA": "Colombia",
    "COLOMBIAN": "Colombiano",
    "VENEZUELA": "Venezuela",
    "VENEZUELAN": "Venezolano",
    "CHILE": "Chile",
    "CHILEAN": "Chileno",
    "PERU": "Perú",
    "PERUVIAN": "Peruano",
    "CUBA": "Cuba",
    "CUBAN": "Cubano",
    "SEPARATIST": "Separatista",
    "CATALAN": "Catalán",
    "BASQUE": "Vasco",
    "GALICIAN": "Gallego",
    "SPANIARD": "Español",
    "CATALONIA": "Cataluña",
    "BASQUE COUNTRY": "País Vasco",
    "GALICIA": "Galicia",
    "ANDALUSIAN": "Andaluz",
    "MADRID": "Madrid",
    "BARCELONA": "Barcelona",
    "TRADE UNION": "Sindicato",
    "UNION": "Sindicato",
    "EMPLOYEE": "Empleado",
    "EMPLOYER": "Empresario",
    "FARMER": "Agricultor",
    "DOCTOR": "Médico",
    "NURSE": "Enfermero",
    "SOLDIER": "Soldado",
    "OFFICER": "Agente",
    "SUSPECT": "Sospechoso",
    "VICTIM": "Víctima",
    "WITNESS": "Testigo",
    "GANG": "Banda",
    "SMUGGLER": "Traficante",
    "MIGRANT": "Migrante",
    "OPPOSITION": "Oposición",
    "GOVERNOR": "Gobernador",
    "MAYOR": "Alcalde",
    "SENATOR": "Senador",
    "CONGRESS": "Congreso",
    "SENATE": "Senado",
    "ELECTION COMMISSION": "Comisión electoral",
    "CENTRAL BANK": "Banco central",
    "RED CROSS": "Cruz Roja",
    "WORLD HEALTH ORGANIZATION": "Organización Mundial de la Salud",
    "HUMAN RIGHTS": "Derechos Humanos",
    "HAITI": "Haití",
    "HAITIAN": "Haitiano",
    "EGYPT": "Egipto",
    "EGYPTIAN": "Egipcio",
    "LIBYA": "Libia",
    "LIBYAN": "Libio",
    "ALGERIA": "Argelia",
    "ALGERIAN": "Argelino",
    "TUNISIA": "Túnez",
    "SUDAN": "Sudán",
    "ETHIOPIA": "Etiopía",
    "SOMALIA": "Somalia",
    "SALVADORAN": "Salvadoreño",
    "HONDURAN": "Hondureño",
    "GUATEMALAN": "Guatemalteco",
    "NICARAGUAN": "Nicaragüense",
    "COSTA RICAN": "Costarricense",
    "PANAMANIAN": "Panameño",
    "ECUADORIAN": "Ecuatoriano",
    "BOLIVIAN": "Boliviano",
    "DOMINICAN": "Dominicano",
    "HAITIAN": "Haitiano",
    "JAMAICAN": "Jamaicano",
    "DUTCH": "Neerlandés",
    "BELGIAN": "Belga",
    "SWISS": "Suizo",
    "AUSTRIAN": "Austriaco",
    "DANISH": "Danés",
    "NORWEGIAN": "Noruego",
    "FINNISH": "Finlandés",
    "SCOTTISH": "Escocés",
    "WELSH": "Galés",
    "CUBAN": "Cubano",
    "KENYA": "Kenia",
    "SOUTH AFRICA": "Sudáfrica",
    "AFRICA": "África",
    "AFRICAN": "Africano",
    "EUROPE": "Europa",
    "EUROPEAN": "Europeo",
    "ASIA": "Asia",
    "ASIAN": "Asiático",
    "LATIN AMERICA": "América Latina",
    "MIDDLE EAST": "Oriente Próximo",
    "POLICE": "Policía",
    "MILITARY": "Ejército",
    "GOVERNMENT": "Gobierno",
    "PRESIDENT": "Presidente",
    "PRIME MINISTER": "Primer ministro",
    "MINISTER": "Ministro",
    "PARLIAMENT": "Parlamento",
    "COURT": "Tribunal",
    "FEDERAL JUDGE": "Juez federal",
    "JUDGE": "Juez",
    "JUDICIAL": "Justicia",
    "PRISON": "Prisión",
    "CRIMINAL": "Delincuente",
    "FIGHTER": "Combatiente",
    "MILITANT": "Militante",
    "REBEL": "Rebelde",
    "TERRORIST": "Terrorista",
    "PROTESTER": "Manifestante",
    "VOTER": "Votante",
    "IMMIGRANT": "Inmigrante",
    "REFUGEE": "Refugiado",
    "AUTHORITIES": "Autoridades",
    "OFFICIAL": "Cargo público",
    "STUDENT": "Estudiante",
    "TEACHER": "Docente",
    "WORKER": "Trabajador",
    "CIVILIAN": "Civil",
    "BUSINESS": "Empresa",
    "COMPANY": "Compañía",
    "BANK": "Banco",
    "MEDIA": "Medios de comunicación",
    "JOURNALIST": "Periodista",
    "ACTIVIST": "Activista",
    "LEGAL": "Justicia",
    "UNITED NATIONS": "Naciones Unidas",
    "NATO": "OTAN",
    "EU": "UE",
    "AMERICAN": "Estadounidense",
    "BRITISH": "Británico",
    "AUSTRALIA": "Australia",
    "AUSTRALIAN": "Australiano",
    "INDONESIA": "Indonesia",
    "PHILIPPINES": "Filipinas",
    "THAILAND": "Tailandia",
    "VIETNAM": "Vietnam",
    "BANGLADESH": "Bangladés",
    "SRI LANKA": "Sri Lanka",
    "NEPAL": "Nepal",
    "MYANMAR": "Birmania",
    "SAUDI ARABIA": "Arabia Saudí",
    "UNITED ARAB EMIRATES": "Emiratos Árabes Unidos",
    "QATAR": "Catar",
    "KUWAIT": "Kuwait",
    "JORDAN": "Jordania",
    "YEMEN": "Yemen",
    "GREECE": "Grecia",
    "GREEK": "Griego",
    "HUNGARY": "Hungría",
    "ROMANIA": "Rumanía",
    "SERBIA": "Serbia",
    "CROATIA": "Croacia",
    "BULGARIA": "Bulgaria",
    "CZECH REPUBLIC": "República Checa",
    "AUSTRIA": "Austria",
    "SWITZERLAND": "Suiza",
    "BELGIUM": "Bélgica",
    "NETHERLANDS": "Países Bajos",
    "DENMARK": "Dinamarca",
    "NORWAY": "Noruega",
    "FINLAND": "Finlandia",
    "IRELAND": "Irlanda",
    "ICELAND": "Islandia",
    "NEW ZEALAND": "Nueva Zelanda",
    "SOUTH AMERICA": "América del Sur",
    "NORTH AMERICA": "América del Norte",
}
KEEP_ACTOR = {"?"}


def _actor_es(name: str) -> str:
    """Traduce los nombres de actor CAMEO; deja intactos los topónimos."""
    if not name:
        return name
    key = name.strip().upper()
    if key in KEEP_ACTOR:
        return name
    if key in ACTOR_ES:
        return ACTOR_ES[key]
    # topónimos y nombres propios sin traducción: se pasan a mayúscula inicial
    return name.title() if name.isupper() else name


RUMBO_ES = {"W": "O"}  # el resto de rumbos se escribe igual en español


def pais_es(nombre: str) -> str:
    """Traduce el nombre de un país, respetando el resto del texto."""
    limpio = (nombre or "").strip()
    return PAIS_ES.get(limpio, limpio)


def _rumbo(dir_: str) -> str:
    return "".join(RUMBO_ES.get(ch, ch) for ch in dir_.upper())


_USGS = re.compile(
    r"^M\s*(?P<mag>\d+(?:\.\d+)?)\s*-\s*(?P<dist>\d+(?:\.\d+)?)\s*km\s+"
    r"(?P<dir>[NSEW]{1,3})\s+of\s+(?P<place>.+)$",
    re.IGNORECASE,
)
_USGS_MAG_ONLY = re.compile(r"^M\s*(?P<mag>\d+(?:\.\d+)?)\s+earthquake$", re.IGNORECASE)


def _lugar_es(place: str) -> str:
    """«Tateyama, Japan» -> «Tateyama (Japón)»; conserva el topónimo menor."""
    lugar = (place or "").strip()
    ciudad, _, pais = lugar.rpartition(",")
    if ciudad and pais.strip():
        return f"{ciudad.strip()} ({pais_es(pais.strip())})"
    return pais_es(lugar)


_USGS_PLAIN = re.compile(r"^M\s*(?P<mag>\d+(?:\.\d+)?)\s*-\s*(?P<place>.+)$")


def es_usgs(title: str) -> str:
    """«M 4.6 - 68 km SSE of Tateyama, Japan» -> «Sismo M 4,6 · 68 km al SSE de Tateyama (Japón)»."""
    t = (title or "").strip()
    m = _USGS.match(t)
    if m:
        mag = m.group("mag").replace(".", ",")
        dist = m.group("dist").replace(".0", "").replace(".", ",")
        lugar = m.group("place").strip()
        ciudad, _, pais = lugar.rpartition(",")
        if ciudad:
            lugar_es = f"{ciudad.strip()} ({pais_es(pais)})" if pais.strip() else ciudad.strip()
        else:
            lugar_es = pais_es(lugar)
        return f"Sismo M {mag} · {dist} km al {_rumbo(m.group('dir'))} de {lugar_es}"
    m2 = _USGS_MAG_ONLY.match(t)
    if m2:
        return f"Sismo M {m2.group('mag').replace('.', ',')}"
    m3 = _USGS_PLAIN.match(t)
    if m3:
        return f"Sismo M {m3.group('mag').replace('.', ',')} · {_lugar_es(m3.group('place'))}"
    return t


AMENAZA_ES = {
    "Tropical Cyclone": "Ciclón tropical",
    "Tropical Storm": "Tormenta tropical",
    "Extra-Tropical Cyclone": "Ciclón extratropical",
    "Earthquake": "Terremoto",
    "Flood": "Inundación",
    "Flash Flood": "Inundación repentina",
    "Volcanic Eruption": "Erupción volcánica",
    "Volcano": "Volcán",
    "Drought": "Sequía",
    "Wildfire": "Incendio forestal",
    "Forest Fire": "Incendio forestal",
    "Storm": "Tormenta",
    "Storm Surge": "Marea de tempestad",
    "Tsunami": "Tsunami",
    "Cyclone": "Ciclón",
    "Landslide": "Deslizamiento de tierra",
    "Heat Wave": "Ola de calor",
    "Cold Wave": "Ola de frío",
}
ALERTA_ES = {"Green": "verde", "Orange": "naranja", "Red": "roja"}


def es_gdacs(title: str, alert_level: str = "") -> str:
    """«Earthquake in Peru» -> «Terremoto en Perú»; conserva nombres propios."""
    t = (title or "").strip()
    m = re.match(r"^(?P<hazard>[A-Za-z\- ]+?)\s+in\s+(?P<place>.+)$", t)
    if m:
        haz = m.group("hazard").strip()
        haz_es = AMENAZA_ES.get(haz, haz)
        # «Tropical Cyclone XAVIER-26» no sigue el patrón «en <país>»
        t = f"{haz_es} en {pais_es(m.group('place').strip())}"
    else:
        for en, es in sorted(AMENAZA_ES.items(), key=lambda kv: -len(kv[0])):
            if t.startswith(en + " "):
                t = es + t[len(en):]
                break
    nivel = ALERTA_ES.get((alert_level or "").capitalize())
    return f"Alerta {nivel} · {t}" if nivel else t


NWS_ES = {
    "Flood Warning": "Aviso de inundación",
    "Flood Advisory": "Aviso por inundación",
    "Flash Flood Warning": "Aviso de inundación repentina",
    "Flash Flood Watch": "Vigilancia de inundación repentina",
    "Coastal Flood Warning": "Aviso de inundación costera",
    "Coastal Flood Advisory": "Aviso por inundación costera",
    "Severe Thunderstorm Warning": "Aviso de tormenta severa",
    "Severe Thunderstorm Watch": "Vigilancia de tormenta severa",
    "Tornado Warning": "Aviso de tornado",
    "Tornado Watch": "Vigilancia de tornado",
    "Winter Storm Warning": "Aviso de tormenta invernal",
    "Winter Weather Advisory": "Aviso por nieve y hielo",
    "Ice Storm Warning": "Aviso de tormenta de hielo",
    "Blizzard Warning": "Aviso de ventisca",
    "High Wind Warning": "Aviso de viento fuerte",
    "Wind Advisory": "Aviso por viento",
    "Excessive Heat Warning": "Aviso por calor extremo",
    "Excessive Heat Watch": "Vigilancia por calor extremo",
    "Heat Advisory": "Aviso por calor",
    "Dense Fog Advisory": "Aviso por niebla densa",
    "Freeze Warning": "Aviso de heladas",
    "Frost Advisory": "Aviso por escarcha",
    "Red Flag Warning": "Aviso de riesgo extremo de incendio",
    "Fire Weather Watch": "Vigilancia de riesgo de incendio",
    "Special Weather Statement": "Aviso meteorológico especial",
    "Hydrologic Outlook": "Perspectiva hidrológica",
}


def es_nws(title: str) -> str:
    """«Flood Warning · Seminole, FL» -> «Aviso de inundación · Seminole, FL»."""
    t = (title or "").strip()
    nombre, sep, resto = t.partition(" · ")
    traducido = NWS_ES.get(nombre.strip())
    if traducido:
        return f"{traducido}{sep}{resto}" if sep else traducido
    return t


def es_titulo(title: str, source: str, **extra) -> str:
    """Punto único de traducción de titulares por fuente."""
    if source == "usgs":
        return es_usgs(title)
    if source == "gdacs":
        return es_gdacs(title, extra.get("alert_level", ""))
    if source == "nws":
        return es_nws(title)
    return title or ""


def es_emsc(title: str) -> str:
    """«M3.2 · KEPULAUAN TALAUD, INDONESIA» -> «Sismo M 3,2 · Kepulauan Talaud (Indonesia)»."""
    t = (title or "").strip()
    m = re.match(r"^M\s*(?P<mag>\d+(?:\.\d+)?)\s*·\s*(?P<place>.+)$", t, re.IGNORECASE)
    if m:
        lugar = m.group("place").strip()
        if lugar.isupper() or lugar.upper() == lugar:
            lugar = lugar.title()
        return f"Sismo M {m.group('mag').replace('.', ',')} · {_lugar_es(lugar)}"
    if t.lower().startswith("sismo · "):
        region = t.split("·", 1)[1].strip()
        return f"Sismo · {_lugar_es(region.title() if region.isupper() else region)}"
    return t


# --------------------------------------------------------------------------- #
# red de seguridad en lectura: cualquier titular que llegue en inglés se
# redacta en español al servirlo (idempotente con los ya traducidos)
# --------------------------------------------------------------------------- #
CATEGORIA_ES = {
    "earthquake": "Sismo",
    "disaster": "Desastre",
    "wildfire": "Incendio",
    "conflict": "Conflicto",
    "protest": "Protesta",
    "military": "Militar",
    "diplomacy": "Diplomacia",
    "economy": "Economía",
    "news": "Noticias",
    "health": "Salud",
    "weather": "Meteorología",
    "flood": "Inundación",
    "volcano": "Volcán",
    "cyber": "Ciberataque",
    "trafico": "Tráfico",
    "transporte": "Transporte",
}

SEVERIDAD_ES = {
    "critical": "crítica",
    "high": "alta",
    "medium": "media",
    "low": "baja",
    "info": "informativa",
    "green": "verde",
    "yellow": "amarilla",
    "orange": "naranja",
    "red": "roja",
    "info": "informativa",
    "informacion": "informativa",
}

_GDELT_TITULO = re.compile(r"^(?P<label>[A-Za-z][A-Za-z ]{2,30}):\s*(?P<resto>.+)$")


def es_gdelt_title(title: str) -> str:
    """«Coerce: SPAIN → SALVADORAN · Madrid» -> «Coacción: España → Salvadoreño · Madrid»."""
    t = (title or "").strip()
    m = _GDELT_TITULO.match(t)
    if not m:
        return t
    etiqueta = ROOT_LABELS_ES.get(m.group("label").strip().lower())
    if not etiqueta:
        return t
    resto = m.group("resto")
    actores, sep, lugar = resto.partition(" · ")
    piezas = [_actor_es(a.strip()) for a in actores.split("→")]
    return f"{etiqueta}: {' → '.join(piezas)}" + (f" · {lugar}" if sep else "")


def es_region(texto: str) -> str:
    """«Madrid, Madrid, Spain» -> «Madrid, Madrid, España»."""
    partes = [p.strip() for p in (texto or "").split(",")]
    if not partes:
        return texto or ""
    partes[-1] = pais_es(partes[-1])
    return ", ".join(p for p in partes if p)


def es_titulo_cualquiera(title: str, source: str) -> str:
    """Traduce el titular venga ya en español o en inglés."""
    if source == "gdelt":
        return es_gdelt_title(title)
    if source == "usgs":
        return es_usgs(title)
    if source == "gdacs":
        return es_gdacs(title)
    if source == "nws":
        return es_nws(title)
    if source == "emsc":
        return es_emsc(title)
    return title or ""
