"""
Interaktive Landnutzungskarte als HTML (Folium).
Verwendung: python3 interaktive_karte.py [Stadtname] [--buildings]

--buildings  Gebäude-Layer einschließen (erhöht Dateigröße stark).
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import geopandas as gpd
import folium
from folium import FeatureGroup, GeoJson, GeoJsonTooltip, LayerControl
from folium.plugins import Fullscreen
from branca.element import Template, MacroElement

# Gemeinsame Konfiguration aus der PNG-Karte importieren
sys.path.insert(0, "/home/tahira/geoai-maps")
from landnutzungskarte import STYLE, LAYER_TAGS, lade_geodaten

# --- Konfiguration -----------------------------------------------------------

STADT = sys.argv[1] if len(sys.argv) > 1 else "Frankfurt am Main, Germany"
GEBAEUDE_EINSCHLIESSEN = "--buildings" in sys.argv

# Welche Tag-Spalten gehören zu welchem Layer
LAYER_SPALTEN: dict[str, list[str]] = {
    "landuse":  ["landuse"],
    "leisure":  ["leisure"],
    "water":    ["natural", "waterway"],
    "building": ["building"],
}

# Anzeigename je Layer für den Ebenen-Schalter
LAYER_LABEL: dict[str, str] = {
    "landuse":  "Landnutzung",
    "leisure":  "Parks & Freizeit",
    "water":    "Gewässer",
    "building": "Gebäude",
}

# Vereinfachungstoleranz in Metern (EPSG:3857) – reduziert HTML-Dateigröße
VEREINFACHEN = 8

# --- Hilfsfunktionen ---------------------------------------------------------

def bestimme_klasse(row: pd.Series, tag_spalten: list[str]) -> str:
    for col in tag_spalten:
        if col in row.index and pd.notna(row[col]):
            val = str(row[col]).lower()
            if val in STYLE:
                return val
    return "other"


def osm_tag_str(row: pd.Series, tag_spalten: list[str]) -> str:
    for col in tag_spalten:
        if col in row.index and pd.notna(row[col]):
            return f"{col}={row[col]}"
    return "–"


def bereite_vor(gdf: gpd.GeoDataFrame | None,
                tag_spalten: list[str]) -> gpd.GeoDataFrame | None:
    """Berechnet Fläche, Klasse, Label und OSM-Tag; konvertiert auf WGS84."""
    if gdf is None or gdf.empty:
        return None

    gdf = gdf.copy()

    # Fläche in m² (EPSG:3857 ist metrisch)
    gdf["flaeche_m2"] = gdf.geometry.area.round(0).astype(int)

    # Klasse & Anzeigename
    gdf["klasse"] = gdf.apply(lambda r: bestimme_klasse(r, tag_spalten), axis=1)
    gdf["klasse_label"] = gdf["klasse"].map(lambda k: STYLE[k][4])
    gdf["osm_tag"]      = gdf.apply(lambda r: osm_tag_str(r, tag_spalten), axis=1)

    # Geometrie vereinfachen (spart Dateigröße, bleibt topologisch korrekt)
    gdf.geometry = gdf.geometry.simplify(VEREINFACHEN, preserve_topology=True)

    # Auf WGS84 für Folium
    return gdf[["geometry", "klasse", "klasse_label", "flaeche_m2", "osm_tag"]].to_crs(epsg=4326)


def style_fn(feature: dict) -> dict:
    klasse = feature["properties"].get("klasse", "other")
    fc, ec, alpha, _, _ = STYLE.get(klasse, STYLE["other"])
    return {
        "fillColor":   fc,
        "color":       ec,
        "weight":      0.8,
        "fillOpacity": alpha * 0.85,
        "opacity":     0.9,
    }


def highlight_fn(feature: dict) -> dict:
    return {"weight": 2.5, "fillOpacity": 0.97, "color": "#222222"}


def tooltip_felder() -> GeoJsonTooltip:
    return GeoJsonTooltip(
        fields=["klasse_label", "flaeche_m2", "osm_tag"],
        aliases=["Nutzungsklasse:", "Fläche (m²):", "OSM-Tag:"],
        localize=True,
        sticky=True,
        style=(
            "background-color: white;"
            "border: 1px solid #aaa;"
            "border-radius: 4px;"
            "padding: 6px 10px;"
            "font-family: Arial, sans-serif;"
            "font-size: 13px;"
            "box-shadow: 2px 2px 6px rgba(0,0,0,.25);"
        ),
    )


# --- Legende -----------------------------------------------------------------

def erstelle_legende(vorhandene_klassen: set[str]) -> MacroElement:
    """Baut eine HTML-Legende mit den tatsächlich vorhandenen Klassen."""
    eintraege = [
        (STYLE[k][0], STYLE[k][4])
        for k in STYLE
        if k in vorhandene_klassen
    ]
    items_html = "\n".join(
        f'<div style="display:flex;align-items:center;margin:3px 0">'
        f'<span style="display:inline-block;width:16px;height:16px;'
        f'background:{fc};border:1px solid #888;margin-right:7px;'
        f'flex-shrink:0;border-radius:2px"></span>'
        f'<span style="font-size:12px">{label}</span></div>'
        for fc, label in eintraege
    )

    template = f"""
    {{% macro html(this, kwargs) %}}
    <div id="legende" style="
        position: fixed;
        bottom: 30px; left: 30px;
        z-index: 9999;
        background: rgba(255,255,255,0.95);
        border: 1px solid #ccc;
        border-radius: 6px;
        padding: 10px 14px;
        font-family: Arial, sans-serif;
        box-shadow: 2px 2px 8px rgba(0,0,0,.2);
        max-height: 80vh;
        overflow-y: auto;
        min-width: 160px;
    ">
      <b style="font-size:13px;display:block;margin-bottom:6px">Landnutzung</b>
      {items_html}
      <div style="margin-top:8px;font-size:10px;color:#888;border-top:1px solid #eee;padding-top:6px">
        © OpenStreetMap-Mitwirkende (ODbL)
      </div>
    </div>
    {{% endmacro %}}
    """
    macro = MacroElement()
    macro._template = Template(template)
    return macro


# --- Hauptfunktion -----------------------------------------------------------

def erstelle_interaktive_karte(daten: dict, stadtname: str) -> None:
    grenze_wgs84 = daten["grenze"].to_crs(epsg=4326)
    center = [
        grenze_wgs84.geometry.centroid.y.mean(),
        grenze_wgs84.geometry.centroid.x.mean(),
    ]

    karte = folium.Map(location=center, zoom_start=12,
                       tiles="CartoDB positron", control_scale=True)
    Fullscreen().add_to(karte)

    # Stadtgrenze
    folium.GeoJson(
        grenze_wgs84.__geo_interface__,
        name="Stadtgrenze",
        style_function=lambda _: {
            "color": "#222222", "weight": 2.5,
            "fillOpacity": 0.0, "opacity": 1.0,
        },
        tooltip=None,
    ).add_to(karte)

    vorhandene_klassen: set[str] = set()

    layer_reihenfolge = ["landuse", "leisure", "water"]
    if GEBAEUDE_EINSCHLIESSEN:
        layer_reihenfolge.append("building")

    for layer_name in layer_reihenfolge:
        gdf_raw = daten.get(layer_name)
        tag_spalten = LAYER_SPALTEN[layer_name]
        gdf = bereite_vor(gdf_raw, tag_spalten)
        if gdf is None:
            continue

        vorhandene_klassen.update(gdf["klasse"].unique())

        gruppe = FeatureGroup(name=LAYER_LABEL[layer_name], show=True)
        GeoJson(
            gdf.__geo_interface__,
            style_function=style_fn,
            highlight_function=highlight_fn,
            tooltip=tooltip_felder(),
        ).add_to(gruppe)
        gruppe.add_to(karte)

    # Legende & Ebenen-Schalter
    karte.add_child(erstelle_legende(vorhandene_klassen))
    LayerControl(collapsed=False).add_to(karte)

    kurzer_name = stadtname.split(",")[0].strip()
    dateiname = f"landnutzung_{kurzer_name.replace(' ', '_').lower()}_interaktiv.html"
    karte.save(dateiname)

    groesse_mb = __import__("os").path.getsize(dateiname) / 1_048_576
    print(f"\nKarte gespeichert: {dateiname}  ({groesse_mb:.1f} MB)")
    if not GEBAEUDE_EINSCHLIESSEN:
        print("Tipp: --buildings hinzufügen, um Gebäude einzuschließen.")


# --- Einstiegspunkt ----------------------------------------------------------

if __name__ == "__main__":
    print(f"\n=== Interaktive Karte: {STADT} ===\n")
    daten = lade_geodaten(STADT)
    print("\nErstelle Folium-Karte …")
    erstelle_interaktive_karte(daten, STADT)
