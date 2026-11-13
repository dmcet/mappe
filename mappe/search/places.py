"""Where a job is: in Germany, abroad, or remote and open to people in Germany."""

from __future__ import annotations

import re

# Without places to search, onsite jobs are hidden when their location is abroad: it names
# a German state or Germany -> domestic; else a foreign country, region or city -> abroad.
_GERMANY = re.compile(
    r"\b(germany|deutschland|bayern|bavaria|baden|württemberg|wuerttemberg|hessen|hesse|"
    r"sachsen|saxony|thüringen|thuringia|brandenburg|mecklenburg|niedersachsen|"
    r"lower saxony|nordrhein|westfalen|north rhine|rheinland|pfalz|saarland|schleswig|"
    r"holstein|mittelfranken|oberfranken|unterfranken|oberbayern|niederbayern|schwaben)\b",
    re.I,
)
_ABROAD = re.compile(
    r"\b(netherlands|nederland|holland|gelderland|utrecht|brabant|limburg|overijssel|"
    r"groningen|friesland|eindhoven|amsterdam|rotterdam|den haag|the hague|"
    r"united kingdom|uk|england|scotland|wales|london|manchester|edinburgh|ireland|dublin|"
    r"france|paris|lyon|spain|españa|barcelona|madrid|valencia|portugal|lisbon|lisboa|porto|"
    r"italy|italia|milan|milano|rome|roma|poland|polska|warsaw|warszawa|krakow|kraków|"
    r"wroclaw|wrocław|czech|prague|praha|brno|slovakia|hungary|budapest|romania|bucharest|"
    r"bulgaria|sofia|croatia|serbia|greece|athens|cyprus|malta|"
    r"switzerland|schweiz|suisse|zurich|zürich|bern|basel|geneva|genf|lausanne|luzern|"
    r"lucerne|zug|winterthur|st\. gallen|"
    r"austria|österreich|wien|vienna|graz|linz|salzburg|innsbruck|klagenfurt|"
    r"steiermark|tirol|kärnten|vorarlberg|burgenland|oberösterreich|niederösterreich|"
    r"belgium|belgique|brussels|bruxelles|antwerp|luxembourg|denmark|copenhagen|sweden|"
    r"stockholm|norway|oslo|finland|helsinki|estonia|tallinn|latvia|riga|lithuania|vilnius|"
    r"usa|united states|canada|toronto|mexico|brazil|india|bangalore|singapore|"
    r"australia|israel|tel aviv|turkey|istanbul|dubai|uae)\b",
    re.I,
)


def abroad(location: str) -> bool:
    if _GERMANY.search(location):
        return False
    return bool(_ABROAD.search(location))


_OPEN_TO_GERMANY = re.compile(
    r"worldwide|anywhere|global|europe|\beu\b|emea|germany|deutschland|dach|\bcet\b|\bcest\b",
    re.I,
)


def open_to_germany(location: str | None) -> bool:
    """For remote listings: no restriction stated, or one that includes Germany."""
    return not (location or "").strip() or bool(_OPEN_TO_GERMANY.search(location or ""))
