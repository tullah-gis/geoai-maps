"""
Automatische Landnutzungskarten-Generierung mit OpenStreetMap-Daten.
Verwendung: python3 landnutzungskarte.py [Stadtname]
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import osmnx as ox
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import contextily as ctx
from shapely.geometry import box

# --- Konfiguration -----------------------------------------------------------

STADT = sys.argv[1] if len(sys.argv) > 1 else "Frankfurt am Main, Germany"

# OSM-Tags für jeden Layer
LAYER_TAGS = {
    "landuse":  {"landuse": True},
    "leisure":  {"leisure": ["park", "garden", "nature_reserve", "golf_course"]},
    "water":    {"natural": ["water", "wetland"], "waterway": ["river", "stream", "canal"]},
    "building": {"building": True},
}

# Stil: (Füllfarbe, Randfarbe, Alpha, Z-Order, Legendentext)
# Schlüssel entsprechen OSM-Werten in den jeweiligen Tag-Spalten
STYLE: dict[str, tuple] = {
    # landuse-Werte
    "residential":   ("#f5deb3", "#e0c080", 0.85, 2, "Wohngebiet"),
    "commercial":    ("#f4a460", "#c8783c", 0.85, 2, "Gewerbe/Handel"),
    "industrial":    ("#b0b0b0", "#808080", 0.85, 2, "Industrie"),
    "retail":        ("#ffa07a", "#cc6040", 0.85, 2, "Einzelhandel"),
    "construction":  ("#d3c0a0", "#a08060", 0.75, 2, "Baustelle"),
    "farmland":      ("#e8f4c8", "#b8d898", 0.85, 1, "Landwirtschaft"),
    "farmyard":      ("#dce8b0", "#a8c878", 0.85, 1, "Hofstelle"),
    "forest":        ("#228b22", "#1a6b1a", 0.75, 3, "Wald"),
    "grass":         ("#90ee90", "#60c060", 0.80, 2, "Grünfläche"),
    "meadow":        ("#adff2f", "#80cc20", 0.75, 2, "Wiese"),
    # leisure-Werte
    "park":          ("#32cd32", "#228b22", 0.80, 3, "Park/Garten"),
    "garden":        ("#50c050", "#228b22", 0.80, 3, "Garten"),
    "nature_reserve":("#006400", "#004000", 0.70, 3, "Naturschutz"),
    "golf_course":   ("#7cfc00", "#50c000", 0.75, 2, "Golfplatz"),
    # natural/waterway-Werte
    "water":         ("#4fc3f7", "#1e88e5", 0.90, 12, "Gewässer"),
    "wetland":       ("#80cbc4", "#4db6ac", 0.80, 12, "Feuchtgebiet"),
    "river":         ("#4fc3f7", "#1e88e5", 0.90, 12, "Fluss"),
    "stream":        ("#81d4fa", "#1e88e5", 0.85, 12, "Bach"),
    "canal":         ("#4fc3f7", "#1e88e5", 0.85, 12, "Kanal"),
    # Gebäude (gesamter Layer)
    "building":      ("#e57373", "#c62828", 0.55, 5, "Gebäude"),
    # Fallback
    "other":         ("#d0d0d0", "#a0a0a0", 0.55, 1, "Sonstige Nutzung"),
}

DPI = 300
FIGSIZE = (20, 17)

# --- Datenabruf --------------------------------------------------------------

def lade_geodaten(stadtname: str) -> dict:
    print(f"Lade Stadtgrenze: {stadtname}")
    grenze = ox.geocode_to_gdf(stadtname).to_crs(epsg=3857)
    clip_box = gpd.GeoDataFrame(geometry=[box(*grenze.total_bounds)], crs="EPSG:3857")

    daten = {"grenze": grenze}
    for name, tags in LAYER_TAGS.items():
        print(f"  → {name} …", end=" ", flush=True)
        try:
            gdf = ox.features_from_place(stadtname, tags=tags)
            gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
            if gdf.empty:
                print("leer")
                daten[name] = None
                continue
            gdf = gdf.to_crs(epsg=3857)
            gdf = gpd.clip(gdf, clip_box)
            print(f"{len(gdf)} Objekte")
            daten[name] = gdf
        except Exception as e:
            print(f"Fehler: {e}")
            daten[name] = None

    return daten


# --- Kartenerstellung --------------------------------------------------------

def zeichne_farbig(ax, gdf: gpd.GeoDataFrame, tag_spalten: list[str],
                   legend_keys: set, legend_handles: list) -> None:
    """Zeichnet Features eines Layers nach Wert in tag_spalten eingefärbt."""
    if gdf is None or gdf.empty:
        return

    # Klassifizierungsspalte: erste gefundene tag_spalte im GDF
    spalte = next((s for s in tag_spalten if s in gdf.columns), None)

    if spalte is None:
        # Kein bekannter Tag → alles als "other"
        _plot_subset(ax, gdf, "other", legend_keys, legend_handles)
        return

    # Bekannte Werte einzeln zeichnen
    gezeichnet_mask = gdf[spalte].fillna("").str.lower().isin(STYLE)
    for key in STYLE:
        subset = gdf[gdf[spalte].fillna("").str.lower() == key]
        if subset.empty:
            continue
        _plot_subset(ax, subset, key, legend_keys, legend_handles)

    # Unbekannte Werte → "other"
    rest = gdf[~gezeichnet_mask]
    if not rest.empty:
        _plot_subset(ax, rest, "other", legend_keys, legend_handles)


def _plot_subset(ax, gdf, style_key: str, legend_keys: set, legend_handles: list) -> None:
    fc, ec, alpha, zorder, label = STYLE[style_key]
    gdf.plot(ax=ax, color=fc, edgecolor=ec, linewidth=0.3, alpha=alpha, zorder=zorder)
    if style_key not in legend_keys:
        legend_handles.append(mpatches.Patch(facecolor=fc, edgecolor=ec, label=label))
        legend_keys.add(style_key)


def erstelle_karte(daten: dict, stadtname: str) -> None:
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=DPI)

    grenze = daten["grenze"]
    extent = grenze.total_bounds

    # Hintergrundkarte zuerst
    try:
        ctx.add_basemap(ax, crs="EPSG:3857", source=ctx.providers.CartoDB.Positron,
                        zoom="auto", alpha=0.45)
    except Exception:
        ax.set_facecolor("#eeeeee")

    legend_handles: list = []
    legend_keys: set = set()

    # Zeichenreihenfolge: Landnutzung → Parks → Gewässer → Gebäude → Grenze
    zeichne_farbig(ax, daten.get("landuse"),   ["landuse"],           legend_keys, legend_handles)
    zeichne_farbig(ax, daten.get("leisure"),   ["leisure"],           legend_keys, legend_handles)
    zeichne_farbig(ax, daten.get("water"),     ["natural", "waterway"], legend_keys, legend_handles)
    # Gebäude als einheitliche Farbe
    if daten.get("building") is not None:
        _plot_subset(ax, daten["building"], "building", legend_keys, legend_handles)

    # Stadtgrenze über alles
    grenze.boundary.plot(ax=ax, color="#222222", linewidth=2.0, zorder=10)

    ax.set_xlim(extent[0], extent[2])
    ax.set_ylim(extent[1], extent[3])
    ax.set_axis_off()

    # Legende
    leg = ax.legend(
        handles=legend_handles,
        loc="lower left",
        fontsize=12,
        title="Landnutzung",
        title_fontsize=13,
        framealpha=0.93,
        edgecolor="#bbbbbb",
        borderpad=1.2,
        labelspacing=0.7,
        handlelength=1.8,
        handleheight=1.4,
    )
    leg.get_frame().set_linewidth(1.0)
    leg.set_zorder(20)

    # Titel
    kurzer_name = stadtname.split(",")[0].strip()
    ax.set_title(f"Landnutzungskarte – {kurzer_name}",
                 fontsize=24, fontweight="bold", pad=16, color="#111111")

    # Nordpfeil
    ax.annotate("N",  xy=(0.974, 0.975), xycoords="axes fraction",
                fontsize=18, fontweight="bold", ha="center", va="top", color="#222222")
    ax.annotate("▲", xy=(0.974, 0.948), xycoords="axes fraction",
                fontsize=20, ha="center", va="top", color="#222222")

    # Quellenangabe
    fig.text(0.5, 0.008,
             "Datenquelle: © OpenStreetMap-Mitwirkende (ODbL)  |  Hintergrund: CartoDB Positron",
             ha="center", fontsize=10, color="#666666")

    plt.tight_layout(pad=0.4)

    dateiname = f"landnutzung_{kurzer_name.replace(' ', '_').lower()}.png"
    fig.savefig(dateiname, dpi=DPI, bbox_inches="tight", facecolor="white")
    print(f"\nKarte gespeichert: {dateiname}")
    plt.show()


# --- Einstiegspunkt ----------------------------------------------------------

if __name__ == "__main__":
    print(f"\n=== Landnutzungskarte: {STADT} ===\n")
    daten = lade_geodaten(STADT)
    print("\nErstelle Karte …")
    erstelle_karte(daten, STADT)
