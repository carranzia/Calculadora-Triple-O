"""
Generador de Informe PDF — Huella de Carbono de Evento
Branding: Objetivo 17 Alliance | verde oscuro #25662e | verde lima #bae36c

Uso:
    python generar_informe_pdf.py
    python generar_informe_pdf.py --evento "Nombre del Evento" --fecha "25 feb 2026"
                                  --cliente "Empresa S.L." --output informe.pdf
"""

import os
import sys
import argparse
import io
import math
from datetime import date

# Forzar UTF-8 en Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    Table, TableStyle, Image, HRFlowable, NextPageTemplate,
    PageBreak, KeepTogether,
)

try:
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPDF, renderPM
    SVGLIB_OK = True
except ImportError:
    SVGLIB_OK = False

# ── Constantes de marca ────────────────────────────────────────────────────────

VERDE_OSCURO = colors.HexColor("#25662e")
VERDE_LIMA   = colors.HexColor("#bae36c")
BLANCO       = colors.white
GRIS_CLARO   = colors.HexColor("#f5f5f5")
GRIS_TEXTO   = colors.HexColor("#222222")
GRIS_MEDIO   = colors.HexColor("#777777")
VERDE_LIMA_M = "#bae36c"   # versión string para matplotlib
VERDE_OSC_M  = "#25662e"

BRAND_NAME  = "Objetivo 17 Alliance"
TAGLINE     = "Conectando soluciones, creamos alianzas"
LOGO_PATH   = "public/logo-017.svg"
W, H        = A4   # 595 x 842 pts

FACTORES_PUBLICO = {"tren": 0.035, "metro": 0.03, "autobus": 0.06, "pie": 0.0}
PRIVADOS = {"taxi", "gasolina", "diesel", "hibrido", "electrico", "compartido"}

# ── Capitalización de orígenes ─────────────────────────────────────────────────

# Partículas que van en minúscula salvo que sean la primera palabra
_PARTICULAS = {
    "de", "del", "de la", "de las", "de los",
    "la", "las", "los", "el",
    "a", "al", "y", "e", "en", "por", "con",
    "calle", "avenida", "plaza", "paseo",   # se capitalizan → tratadas aparte
}
_PARTICULAS_LOWER = {"de", "del", "la", "las", "los", "el", "a", "al", "y", "e", "en", "por", "con"}

# Correcciones manuales: texto normalizado → forma canónica
_CORRECCIONES_ORIGEN = {
    "puerta del sol madrid":       "Puerta del Sol, Madrid",
    "puerta del sol, madrid":      "Puerta del Sol, Madrid",
    "metro legazpi":               "Metro Legazpi",
    "conde casal":                 "Conde Casal",
    "nuevos ministerios":          "Nuevos Ministerios",
    "puerta del ángel":            "Puerta del Ángel",
    "puerta del angel":            "Puerta del Ángel",
    "el encinar de los reyes":     "El Encinar de los Reyes",
    "canillejas calle barbastro":  "Canillejas, Calle Barbastro",
    "mejorada del campo":          "Mejorada del Campo",
    "calle prim":                  "Calle Prim",
    "calle san juan de ortega 52": "Calle San Juan de Ortega, 52",
    "nuñez de balboa":             "Núñez de Balboa",
    "núñez de balboa":             "Núñez de Balboa",
}

def capitalizar_origen(texto: str) -> str:
    """Devuelve el origen con capitalización correcta en español."""
    texto = str(texto).strip()
    clave = texto.lower()

    # 1. Corrección manual exacta
    if clave in _CORRECCIONES_ORIGEN:
        return _CORRECCIONES_ORIGEN[clave]

    # 2. Title-case respetando partículas en minúscula (salvo primera palabra)
    palabras = texto.split()
    resultado = []
    for i, p in enumerate(palabras):
        if i == 0 or p.lower() not in _PARTICULAS_LOWER:
            # Capitalizar preservando tildes y caracteres especiales
            resultado.append(p[0].upper() + p[1:] if p else p)
        else:
            resultado.append(p.lower())
    return " ".join(resultado)

# ── Estilos ────────────────────────────────────────────────────────────────────

def build_styles():
    def s(name, **kw):
        return ParagraphStyle(name, **kw)

    return {
        # Portada
        "cover_title":    s("cover_title",    fontName="Helvetica-Bold",    fontSize=22,
                             textColor=VERDE_OSCURO, alignment=TA_CENTER, leading=28, spaceAfter=10),
        "cover_evento":   s("cover_evento",   fontName="Helvetica-Bold",    fontSize=15,
                             textColor=GRIS_TEXTO,  alignment=TA_CENTER, leading=20, spaceAfter=8),
        "cover_body":     s("cover_body",     fontName="Helvetica",         fontSize=11,
                             textColor=GRIS_MEDIO,  alignment=TA_CENTER, leading=16, spaceAfter=4),
        "cover_tagline":  s("cover_tagline",  fontName="Helvetica-Oblique", fontSize=9,
                             textColor=GRIS_MEDIO,  alignment=TA_CENTER),
        # Contenido
        "seccion":        s("seccion",        fontName="Helvetica-Bold",    fontSize=15,
                             textColor=VERDE_OSCURO, spaceBefore=20, spaceAfter=10, leading=19),
        "subseccion":     s("subseccion",     fontName="Helvetica-Bold",    fontSize=11,
                             textColor=VERDE_OSCURO, spaceBefore=12, spaceAfter=6,  leading=15),
        "cuerpo":         s("cuerpo",         fontName="Helvetica",         fontSize=10,
                             textColor=GRIS_TEXTO,  leading=15, spaceAfter=6),
        "nota":           s("nota",           fontName="Helvetica-Oblique", fontSize=8,
                             textColor=GRIS_MEDIO,  leading=11, spaceAfter=4),
        "kpi_valor":      s("kpi_valor",      fontName="Helvetica-Bold",    fontSize=22,
                             textColor=VERDE_OSCURO, alignment=TA_CENTER, leading=26),
        "kpi_etiq":       s("kpi_etiq",       fontName="Helvetica",         fontSize=8,
                             textColor=GRIS_MEDIO,   alignment=TA_CENTER, leading=11),
        "tabla_cab":      s("tabla_cab",      fontName="Helvetica-Bold",    fontSize=9,
                             textColor=BLANCO,       alignment=TA_CENTER),
        "tabla_cel":      s("tabla_cel",      fontName="Helvetica",         fontSize=9,
                             textColor=GRIS_TEXTO,   alignment=TA_LEFT),
        "tabla_cel_c":    s("tabla_cel_c",    fontName="Helvetica",         fontSize=9,
                             textColor=GRIS_TEXTO,   alignment=TA_CENTER),
        "tabla_cel_neg":  s("tabla_cel_neg",  fontName="Helvetica-Bold",    fontSize=9,
                             textColor=GRIS_TEXTO,   alignment=TA_LEFT),
    }

# ── Callbacks de página ────────────────────────────────────────────────────────

def on_cover(canv, doc):
    canv.saveState()
    # Fondo blanco (por defecto en PDF — no se dibuja nada)
    # Barra superior verde oscuro, minimalista
    canv.setFillColor(VERDE_OSCURO)
    canv.rect(0, H - 1.2*cm, W, 1.2*cm, fill=1, stroke=0)
    canv.setFillColor(BLANCO)
    canv.setFont("Helvetica-Bold", 10)
    canv.drawCentredString(W / 2, H - 0.78*cm, BRAND_NAME)
    # Línea de acento verde lima en la parte inferior
    canv.setFillColor(VERDE_LIMA)
    canv.rect(0, 0, W, 0.6*cm, fill=1, stroke=0)
    # Tagline sobre la línea lima
    canv.setFillColor(VERDE_OSCURO)
    canv.setFont("Helvetica-Oblique", 8)
    canv.drawCentredString(W / 2, 0.18*cm, TAGLINE)
    canv.restoreState()

def on_content(canv, doc):
    canv.saveState()
    # Cabecera verde oscuro
    canv.setFillColor(VERDE_OSCURO)
    canv.rect(0, H - 1.5*cm, W, 1.5*cm, fill=1, stroke=0)
    canv.setFillColor(BLANCO)
    canv.setFont("Helvetica-Bold", 9)
    canv.drawString(1.5*cm, H - 0.95*cm, BRAND_NAME)
    canv.setFillColor(VERDE_LIMA)
    canv.setFont("Helvetica", 8)
    canv.drawRightString(W - 1.5*cm, H - 0.95*cm, TAGLINE)
    # Línea lima separadora bajo cabecera
    canv.setStrokeColor(VERDE_LIMA)
    canv.setLineWidth(1.5)
    canv.line(0, H - 1.5*cm, W, H - 1.5*cm)
    # Pie de página
    canv.setFillColor(VERDE_OSCURO)
    canv.rect(0, 0, W, 1.2*cm, fill=1, stroke=0)
    canv.setFillColor(BLANCO)
    canv.setFont("Helvetica", 8)
    canv.drawString(1.5*cm, 0.45*cm, f"Informe de Huella de Carbono  ·  {BRAND_NAME}")
    canv.setFont("Helvetica-Bold", 8)
    canv.drawRightString(W - 1.5*cm, 0.45*cm, f"Página {doc.page}")
    canv.restoreState()

# ── Logo ───────────────────────────────────────────────────────────────────────

def get_logo_drawing(max_w=6*cm, max_h=6*cm):
    """Devuelve un Drawing de ReportLab con el logo SVG, escalado."""
    if SVGLIB_OK and os.path.exists(LOGO_PATH):
        try:
            drawing = svg2rlg(LOGO_PATH)
            if drawing:
                sx = max_w / drawing.width
                sy = max_h / drawing.height
                scale = min(sx, sy)
                drawing.width  *= scale
                drawing.height *= scale
                drawing.transform = (scale, 0, 0, scale, 0, 0)
                return drawing
        except Exception:
            pass
    return None

# ── Gráfico de barras ──────────────────────────────────────────────────────────

def crear_grafico_transporte(desglose_df) -> io.BytesIO:
    """Bar chart horizontal CO<sub>2</sub> por medio de transporte, colores de marca."""
    labels = desglose_df["Transporte"].tolist()
    valores = desglose_df["CO2 (kg)"].tolist()

    bar_colors = []
    for lbl in labels:
        if lbl in FACTORES_PUBLICO:
            bar_colors.append(VERDE_LIMA_M)
        else:
            bar_colors.append(VERDE_OSC_M)

    fig, ax = plt.subplots(figsize=(4, 3))
    bars = ax.barh(labels, valores, color=bar_colors, edgecolor="white", height=0.6)

    # Etiquetas de valor
    for bar, val in zip(bars, valores):
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height()/2,
                f"{val:.1f} kg", va="center", ha="left", fontsize=8,
                color=VERDE_OSC_M, fontweight="bold")

    ax.set_xlabel("kg CO2", fontsize=9, color="#444")
    ax.set_xlim(0, max(valores) * 1.25 if valores else 1)
    ax.tick_params(axis="both", labelsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_facecolor("#fafafa")
    fig.patch.set_facecolor("white")

    leyenda = [
        mpatches.Patch(color=VERDE_OSC_M, label="Transporte privado"),
        mpatches.Patch(color=VERDE_LIMA_M, label="Transporte público / a pie"),
    ]
    ax.legend(handles=leyenda, fontsize=7, loc="lower center",
              bbox_to_anchor=(0.5, -0.45), ncol=2, frameon=False)
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)
    buf.seek(0)
    return buf

def crear_grafico_escenarios(total_real, total_optimo) -> io.BytesIO:
    """Gráfico comparativo de dos escenarios."""
    fig, ax = plt.subplots(figsize=(4, 3))
    etiquetas = ["Escenario real", "Escenario óptimo\n(todo transporte público)"]
    valores   = [total_real, total_optimo]
    bar_cols  = [VERDE_OSC_M, VERDE_LIMA_M]

    bars = ax.bar(etiquetas, valores, color=bar_cols, width=0.45, edgecolor="white")
    for bar, val in zip(bars, valores):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f"{val:.1f} kg", ha="center", va="bottom", fontsize=9,
                fontweight="bold", color=VERDE_OSC_M)

    ax.set_ylabel("kg CO2", fontsize=9, color="#444")
    ax.set_ylim(0, max(valores) * 1.3 if valores else 1)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="both", labelsize=8)
    ax.set_facecolor("#fafafa")
    fig.patch.set_facecolor("white")
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)
    buf.seek(0)
    return buf

# ── Estadísticas ───────────────────────────────────────────────────────────────

def calcular_estadisticas(df):
    total_co2        = df["co2_total"].sum()
    total_transporte = df["co2_transporte"].sum()
    total_local      = df["co2_local"].sum() if "co2_local" in df.columns else 0.0
    total_aloj       = df["co2_alojamiento"].sum()
    n                = len(df)
    media_co2        = total_co2 / n if n else 0

    # Estadísticas de nuevos campos
    n_combinado = int((df["transporte_secundario"] != "").sum()) if "transporte_secundario" in df.columns else 0
    n_parcial   = int((df["factor_atribucion"] == 0.5).sum()) if "factor_atribucion" in df.columns else 0
    n_no_atrib  = int((df["factor_atribucion"] == 0.0).sum()) if "factor_atribucion" in df.columns else 0
    n_avion     = int((df["transporte_clave"] == "avion").sum())

    # Etiquetas legibles para el transporte_clave
    etiquetas_transp = {
        "gasolina":  "Coche (gasolina/diésel)",
        "hibrido":   "Coche híbrido",
        "electrico": "Coche eléctrico",
        "taxi":      "Taxi / VTC",
        "tren":      "Tren / AVE / Cercanías",
        "metro":     "Metro / Tranvía",
        "autobus":   "Autobús interurbano",
        "avion":     "Avión",
        "pie":       "A pie / Bicicleta",
    }

    # Desglose por transporte principal
    desglose = (
        df.groupby("transporte_clave", dropna=False)
        .agg(
            asistentes=("id", "count"),
            co2_kg=("co2_transporte", "sum"),
            dist_media=("distancia_km", "mean"),
        )
        .reset_index()
        .sort_values("co2_kg", ascending=False)
    )
    desglose["Transporte"] = desglose["transporte_clave"].map(
        lambda x: etiquetas_transp.get(str(x), str(x).capitalize())
    )
    desglose = desglose.rename(columns={
        "asistentes": "Asistentes",
        "co2_kg":     "CO2 (kg)",
        "dist_media": "Dist. media (km)",
    })[["Transporte", "Asistentes", "CO2 (kg)", "Dist. media (km)"]]

    # Desglose alojamiento
    aloj_df = df[df["co2_alojamiento"] > 0].copy()
    n_aloj = len(aloj_df)
    total_aloj_co2 = aloj_df["co2_alojamiento"].sum()

    # Escenario óptimo: privados → tren (0.035 kg/km)
    PUBLICO_KEYS = {"tren", "metro", "autobus", "pie"}

    def co2_optimo(row):
        tk   = str(row.get("transporte_clave", ""))
        dist = row.get("distancia_km")
        atrib = float(row.get("factor_atribucion", 1.0)) if "factor_atribucion" in row.index else 1.0
        try:
            dist_f = float(dist)
        except (TypeError, ValueError):
            return row["co2_transporte"]
        if math.isnan(dist_f) or tk in PUBLICO_KEYS or tk == "avion":
            return row["co2_transporte"]
        return round(dist_f * 2 * 0.035 * atrib, 3)

    df["co2_transporte_opt"] = df.apply(co2_optimo, axis=1)
    total_optimo = df["co2_transporte_opt"].sum() + total_local + total_aloj

    return {
        "total_co2":        round(total_co2, 2),
        "total_transporte": round(total_transporte, 2),
        "total_local":      round(total_local, 2),
        "total_aloj":       round(total_aloj, 2),
        "n":                n,
        "media_co2":        round(media_co2, 2),
        "desglose":         desglose,
        "n_aloj":           n_aloj,
        "total_aloj_co2":   round(total_aloj_co2, 2),
        "total_optimo":     round(total_optimo, 2),
        "ahorro_potencial": round(total_co2 - total_optimo, 2),
        "n_combinado":      n_combinado,
        "n_parcial":        n_parcial,
        "n_no_atrib":       n_no_atrib,
        "n_avion":          n_avion,
    }

# ── Construcción del PDF ───────────────────────────────────────────────────────

def build_pdf(stats, df, args):
    ST = build_styles()
    out_path = args.output

    # ── Document ──────────────────────────────────────────────────────────────
    doc = BaseDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=1.8*cm,
        rightMargin=1.8*cm,
        topMargin=2.2*cm,
        bottomMargin=2*cm,
    )

    cover_frame = Frame(0, 0.8*cm, W, H - 2.0*cm, leftPadding=2.5*cm, rightPadding=2.5*cm,
                        topPadding=1.5*cm, bottomPadding=0.5*cm, id="cover")
    content_frame = Frame(1.8*cm, 1.8*cm, W - 3.6*cm, H - 3.5*cm,
                          leftPadding=0, rightPadding=0, topPadding=0.3*cm,
                          bottomPadding=0, id="content")

    doc.addPageTemplates([
        PageTemplate(id="cover",   frames=[cover_frame],   onPage=on_cover),
        PageTemplate(id="content", frames=[content_frame], onPage=on_content),
    ])

    story = []

    # ── PORTADA ───────────────────────────────────────────────────────────────
    story.append(NextPageTemplate("cover"))

    # Logo grande centrado
    story.append(Spacer(1, 0.6*cm))
    logo_drawing = get_logo_drawing(max_w=300, max_h=300)
    if logo_drawing:
        logo_table = Table([[logo_drawing]], colWidths=[W - 5*cm])
        logo_table.setStyle(TableStyle([
            ("ALIGN",  (0,0), (-1,-1), "CENTER"),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]))
        story.append(logo_table)
    else:
        story.append(Paragraph("017", ParagraphStyle("logo_fb", fontName="Helvetica-Bold",
                     fontSize=96, textColor=VERDE_LIMA, alignment=TA_CENTER)))
    story.append(Spacer(1, 1.0*cm))

    # Línea separadora verde lima
    story.append(HRFlowable(width="80%", thickness=2, color=VERDE_LIMA,
                             spaceAfter=0.6*cm, spaceBefore=0))

    # Título principal
    story.append(Paragraph("INFORME DE HUELLA DE CARBONO", ST["cover_title"]))
    story.append(Spacer(1, 0.3*cm))

    # Nombre del evento
    story.append(Paragraph(args.evento, ST["cover_evento"]))
    story.append(Spacer(1, 0.6*cm))

    # Línea separadora gris ligera
    story.append(HRFlowable(width="60%", thickness=0.5, color=colors.HexColor("#cccccc"),
                             spaceAfter=0.5*cm, spaceBefore=0))

    # Datos del evento
    story.append(Paragraph(args.venue, ST["cover_body"]))
    story.append(Paragraph(args.fecha, ST["cover_body"]))
    story.append(Spacer(1, 0.4*cm))
    if args.cliente:
        story.append(Paragraph(f"Elaborado para: <b>{args.cliente}</b>", ST["cover_body"]))
    story.append(Paragraph(f"Fecha del informe: {date.today().strftime('%d/%m/%Y')}", ST["cover_body"]))

    # ── RESUMEN EJECUTIVO ─────────────────────────────────────────────────────
    story.append(NextPageTemplate("content"))
    story.append(PageBreak())

    story.append(Paragraph("1. Resumen Ejecutivo", ST["seccion"]))
    story.append(Paragraph(
        f"Este informe cuantifica las emisiones de gases de efecto invernadero (GEI) asociadas "
        f"al desplazamiento y alojamiento de los asistentes al evento <b>{args.evento}</b>, "
        f"celebrado en <b>{args.venue}</b> el <b>{args.fecha}</b>. "
        f"El cálculo se basa en el protocolo GHG Protocol y los factores de emisión DEFRA "
        f"(Department for Environment, Food & Rural Affairs, UK).",
        ST["cuerpo"]
    ))
    story.append(Spacer(1, 0.3*cm))

    # KPIs — tabla 3 columnas
    kpi_data = [
        [
            Paragraph(f"{stats['total_co2']:.1f} kg", ST["kpi_valor"]),
            Paragraph(f"{stats['media_co2']:.2f} kg", ST["kpi_valor"]),
            Paragraph(f"{stats['n']}", ST["kpi_valor"]),
        ],
        [
            Paragraph("CO<sub>2</sub> total del evento", ST["kpi_etiq"]),
            Paragraph("Media por asistente", ST["kpi_etiq"]),
            Paragraph("Asistentes incluidos", ST["kpi_etiq"]),
        ],
    ]
    cw = (W - 3.6*cm) / 3
    kpi_table = Table(kpi_data, colWidths=[cw, cw, cw], rowHeights=[1.5*cm, 0.6*cm])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (0,-1), colors.HexColor("#eaf5eb")),
        ("BACKGROUND",  (1,0), (1,-1), colors.HexColor("#f0fae0")),
        ("BACKGROUND",  (2,0), (2,-1), colors.HexColor("#eaf5eb")),
        ("BOX",         (0,0), (0,-1), 1, VERDE_OSCURO),
        ("BOX",         (1,0), (1,-1), 1, VERDE_OSCURO),
        ("BOX",         (2,0), (2,-1), 1, VERDE_OSCURO),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING",(0,0), (-1,-1), 6),
        ("TOPPADDING",  (0,0), (-1,-1), 8),
        ("BOTTOMPADDING",(0,0),(-1,-1), 4),
        ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 0.4*cm))

    # Desglose transporte / movilidad local / alojamiento
    total_co2_ref = stats['total_co2'] if stats['total_co2'] else 1
    resumen_data = [
        [Paragraph("Concepto", ST["tabla_cab"]),
         Paragraph("kg CO<sub>2</sub>", ST["tabla_cab"]),
         Paragraph("% del total", ST["tabla_cab"])],
        [Paragraph("Transporte principal (ida y vuelta)", ST["tabla_cel"]),
         Paragraph(f"{stats['total_transporte']:.2f}", ST["tabla_cel_c"]),
         Paragraph(f"{stats['total_transporte']/total_co2_ref*100:.1f}%", ST["tabla_cel_c"])],
        [Paragraph("Movilidad local (alojamiento → venue)", ST["tabla_cel"]),
         Paragraph(f"{stats['total_local']:.2f}", ST["tabla_cel_c"]),
         Paragraph(f"{stats['total_local']/total_co2_ref*100:.1f}%", ST["tabla_cel_c"])],
        [Paragraph("Alojamiento", ST["tabla_cel"]),
         Paragraph(f"{stats['total_aloj']:.2f}", ST["tabla_cel_c"]),
         Paragraph(f"{stats['total_aloj']/total_co2_ref*100:.1f}%", ST["tabla_cel_c"])],
        [Paragraph("<b>TOTAL</b>", ST["tabla_cel_neg"]),
         Paragraph(f"<b>{stats['total_co2']:.2f}</b>", ST["tabla_cel_c"]),
         Paragraph("<b>100%</b>", ST["tabla_cel_c"])],
    ]
    tw = W - 3.6*cm
    res_table = Table(resumen_data, colWidths=[tw*0.55, tw*0.225, tw*0.225])
    res_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),  (-1,0),  VERDE_OSCURO),
        ("BACKGROUND",    (0,4),  (-1,4),  colors.HexColor("#eaf5eb")),
        ("ROWBACKGROUNDS",(0,1),  (-1,3),  [BLANCO, GRIS_CLARO, BLANCO]),
        ("GRID",          (0,0),  (-1,-1), 0.5, colors.HexColor("#cccccc")),
        ("TOPPADDING",    (0,0),  (-1,-1), 5),
        ("BOTTOMPADDING", (0,0),  (-1,-1), 5),
        ("LEFTPADDING",   (0,0),  (-1,-1), 8),
        ("RIGHTPADDING",  (0,0),  (-1,-1), 8),
    ]))
    story.append(res_table)
    story.append(Spacer(1, 0.5*cm))

    # ── Comparativa dos escenarios ────────────────────────────────────────────
    story.append(Paragraph("Comparativa de Escenarios", ST["subseccion"]))
    story.append(Paragraph(
        "Se comparan las emisiones reales con un escenario óptimo en el que todos los "
        "asistentes que usaron transporte privado (coche, taxi, híbrido o eléctrico) "
        "hubieran optado por tren (factor DEFRA: 0,035 kg CO<sub>2</sub>/km).",
        ST["cuerpo"]
    ))

    esc_img_buf = crear_grafico_escenarios(stats["total_co2"], stats["total_optimo"])
    esc_img = Image(esc_img_buf, width=350, height=262)
    story.append(esc_img)
    story.append(Spacer(1, 0.3*cm))

    ahorro_pct = (stats["ahorro_potencial"] / stats["total_co2"] * 100) if stats["total_co2"] else 0
    esc_tabla_data = [
        [Paragraph("", ST["tabla_cab"]),
         Paragraph("kg CO<sub>2</sub>", ST["tabla_cab"]),
         Paragraph("kg CO<sub>2</sub>/asistente", ST["tabla_cab"])],
        [Paragraph("Escenario real", ST["tabla_cel"]),
         Paragraph(f"{stats['total_co2']:.2f}", ST["tabla_cel_c"]),
         Paragraph(f"{stats['media_co2']:.2f}", ST["tabla_cel_c"])],
        [Paragraph("Escenario óptimo (todo tren)", ST["tabla_cel"]),
         Paragraph(f"{stats['total_optimo']:.2f}", ST["tabla_cel_c"]),
         Paragraph(f"{stats['total_optimo']/stats['n']:.2f}" if stats['n'] else "—", ST["tabla_cel_c"])],
        [Paragraph("<b>Ahorro potencial</b>", ST["tabla_cel_neg"]),
         Paragraph(f"<b>{stats['ahorro_potencial']:.2f}</b>", ST["tabla_cel_c"]),
         Paragraph(f"<b>{ahorro_pct:.1f}%</b>", ST["tabla_cel_c"])],
    ]
    esc_table = Table(esc_tabla_data, colWidths=[tw*0.5, tw*0.25, tw*0.25])
    esc_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), VERDE_OSCURO),
        ("BACKGROUND",    (0,3), (-1,3), colors.HexColor("#eaf5eb")),
        ("ROWBACKGROUNDS",(0,1), (-1,2), [BLANCO, GRIS_CLARO]),
        ("GRID",          (0,0), (-1,-1), 0.5, colors.HexColor("#cccccc")),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
    ]))
    story.append(esc_table)

    # ── DESGLOSE POR TRANSPORTE ───────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("2. Desglose por Medio de Transporte", ST["seccion"]))

    des = stats["desglose"]
    transp_header = [
        Paragraph("Transporte",    ST["tabla_cab"]),
        Paragraph("Asistentes",   ST["tabla_cab"]),
        Paragraph("CO<sub>2</sub> (kg)",    ST["tabla_cab"]),
        Paragraph("Dist. media",  ST["tabla_cab"]),
        Paragraph("% del transp.",ST["tabla_cab"]),
    ]
    transp_rows = [transp_header]
    total_transp_co2 = des["CO2 (kg)"].sum()
    for _, row in des.iterrows():
        pct = row["CO2 (kg)"] / total_transp_co2 * 100 if total_transp_co2 else 0
        dist_str = f"{row['Dist. media (km)']:.1f} km" if not math.isnan(float(row["Dist. media (km)"] if row["Dist. media (km)"] == row["Dist. media (km)"] else float("nan"))) else "N/A"
        transp_rows.append([
            Paragraph(str(row["Transporte"]).capitalize(), ST["tabla_cel"]),
            Paragraph(str(int(row["Asistentes"])), ST["tabla_cel_c"]),
            Paragraph(f"{row['CO2 (kg)']:.2f}", ST["tabla_cel_c"]),
            Paragraph(dist_str, ST["tabla_cel_c"]),
            Paragraph(f"{pct:.1f}%", ST["tabla_cel_c"]),
        ])
    # Fila total
    transp_rows.append([
        Paragraph("<b>TOTAL</b>", ST["tabla_cel_neg"]),
        Paragraph(f"<b>{int(des['Asistentes'].sum())}</b>", ST["tabla_cel_c"]),
        Paragraph(f"<b>{total_transp_co2:.2f}</b>", ST["tabla_cel_c"]),
        Paragraph("—", ST["tabla_cel_c"]),
        Paragraph("<b>100%</b>", ST["tabla_cel_c"]),
    ])

    transp_cw = [tw*0.28, tw*0.14, tw*0.18, tw*0.2, tw*0.2]
    transp_table = Table(transp_rows, colWidths=transp_cw, repeatRows=1)
    n_data = len(transp_rows)
    transp_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), VERDE_OSCURO),
        ("BACKGROUND",    (0,n_data-1), (-1,n_data-1), colors.HexColor("#eaf5eb")),
        ("ROWBACKGROUNDS",(0,1), (-1,n_data-2), [BLANCO, GRIS_CLARO]),
        ("GRID",          (0,0), (-1,-1), 0.5, colors.HexColor("#cccccc")),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("RIGHTPADDING",  (0,0), (-1,-1), 6),
    ]))
    story.append(transp_table)
    story.append(Spacer(1, 0.5*cm))

    # Gráfico de barras
    story.append(Paragraph("Emisiones por medio de transporte (kg CO<sub>2</sub>)", ST["subseccion"]))
    chart_buf = crear_grafico_transporte(des)
    chart_h = max(3.5*cm, len(des) * 1.3*cm)
    chart_img = Image(chart_buf, width=350, height=262)
    story.append(chart_img)
    story.append(Paragraph(
        "Las barras en verde oscuro corresponden a transporte privado; en verde lima, "
        "a transporte público o desplazamiento a pie.",
        ST["nota"]
    ))

    # ── Viajes combinados ─────────────────────────────────────────────────────
    if stats["n_combinado"] > 0:
        story.append(Spacer(1, 0.4*cm))
        story.append(Paragraph("Viajes con transporte combinado", ST["subseccion"]))
        story.append(Paragraph(
            f"<b>{stats['n_combinado']}</b> asistentes declararon haber combinado dos medios "
            "de transporte. Para el tramo secundario se aplica el factor DEFRA correspondiente "
            f"sobre una distancia fija de 10 km (5 km ida × 2), que representa el tramo urbano "
            "de último kilómetro hasta el venue.",
            ST["cuerpo"]
        ))
        # Tabla de viajes combinados
        if "transporte_secundario" in df.columns:
            comb_df = df[df["transporte_secundario"] != ""][
                ["id", "origen", "transporte_clave", "transporte_secundario", "co2_secundario"]
            ].copy()
            if not comb_df.empty:
                comb_header = [
                    Paragraph("ID",          ST["tabla_cab"]),
                    Paragraph("Origen",      ST["tabla_cab"]),
                    Paragraph("T. principal",ST["tabla_cab"]),
                    Paragraph("T. secundario",ST["tabla_cab"]),
                    Paragraph("CO<sub>2</sub> sec. (kg)", ST["tabla_cab"]),
                ]
                comb_rows = [comb_header]
                for _, row in comb_df.iterrows():
                    comb_rows.append([
                        Paragraph(str(int(row["id"])),                  ST["tabla_cel_c"]),
                        Paragraph(capitalizar_origen(row["origen"])[:30], ST["tabla_cel"]),
                        Paragraph(str(row["transporte_clave"]).capitalize(), ST["tabla_cel"]),
                        Paragraph(str(row["transporte_secundario"])[:20],   ST["tabla_cel"]),
                        Paragraph(f"{row['co2_secundario']:.3f}",       ST["tabla_cel_c"]),
                    ])
                comb_cw = [tw*0.08, tw*0.30, tw*0.20, tw*0.24, tw*0.18]
                comb_table = Table(comb_rows, colWidths=comb_cw, repeatRows=1)
                nc = len(comb_rows)
                comb_table.setStyle(TableStyle([
                    ("BACKGROUND",    (0,0), (-1,0),    VERDE_OSCURO),
                    ("ROWBACKGROUNDS",(0,1), (-1,nc-1), [BLANCO, GRIS_CLARO]),
                    ("GRID",          (0,0), (-1,-1),   0.5, colors.HexColor("#cccccc")),
                    ("TOPPADDING",    (0,0), (-1,-1),   5),
                    ("BOTTOMPADDING", (0,0), (-1,-1),   5),
                    ("LEFTPADDING",   (0,0), (-1,-1),   6),
                    ("RIGHTPADDING",  (0,0), (-1,-1),   6),
                ]))
                story.append(comb_table)

    # ── Atribución por exclusividad del viaje ─────────────────────────────────
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph("Atribución por exclusividad del viaje", ST["subseccion"]))
    story.append(Paragraph(
        "Cuando el asistente indicó que el viaje fue realizado <i>parcialmente</i> para asistir al "
        "evento, se aplica un factor de atribución del 50% sobre las emisiones de transporte y "
        "alojamiento. Si el viaje no estaba relacionado con el evento, la atribución es 0%.",
        ST["cuerpo"]
    ))
    n_excl  = stats["n"] - stats["n_parcial"] - stats["n_no_atrib"]
    atrib_data = [
        [Paragraph("Exclusividad del viaje",    ST["tabla_cab"]),
         Paragraph("Asistentes",                ST["tabla_cab"]),
         Paragraph("Factor atribución",          ST["tabla_cab"])],
        [Paragraph("Viaje exclusivo para el evento", ST["tabla_cel"]),
         Paragraph(str(n_excl),                 ST["tabla_cel_c"]),
         Paragraph("100%",                       ST["tabla_cel_c"])],
        [Paragraph("Viaje parcialmente relacionado", ST["tabla_cel"]),
         Paragraph(str(stats["n_parcial"]),      ST["tabla_cel_c"]),
         Paragraph("50%",                        ST["tabla_cel_c"])],
        [Paragraph("Viaje no relacionado con el evento", ST["tabla_cel"]),
         Paragraph(str(stats["n_no_atrib"]),     ST["tabla_cel_c"]),
         Paragraph("0%",                         ST["tabla_cel_c"])],
    ]
    atrib_cw = [tw*0.55, tw*0.2, tw*0.25]
    atrib_table = Table(atrib_data, colWidths=atrib_cw, repeatRows=1)
    atrib_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  VERDE_OSCURO),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [BLANCO, GRIS_CLARO, BLANCO]),
        ("GRID",          (0,0), (-1,-1), 0.5, colors.HexColor("#cccccc")),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
    ]))
    story.append(atrib_table)

    # ── DESGLOSE POR ALOJAMIENTO ───────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("3. Desglose por Alojamiento", ST["seccion"]))
    story.append(Paragraph(
        f"De los {stats['n']} asistentes incluidos en el cálculo, "
        f"<b>{stats['n_aloj']}</b> indicaron haber necesitado alojamiento, "
        f"generando un total de <b>{stats['total_aloj_co2']:.2f} kg CO<sub>2</sub></b>.",
        ST["cuerpo"]
    ))

    # Etiquetas legibles para tipos de alojamiento
    ETIQ_ALOJ = {
        "hotel":       "Hotel",
        "apartamento": "Apartamento turístico",
        "familiares":  "Casa de familiares/amigos",
        "otro":        "Otro",
    }

    aloj_cols = ["id", "origen", "alojamiento_tipo", "noches", "co2_alojamiento"]
    aloj_cols_ok = [c for c in aloj_cols if c in df.columns]
    aloj_df = df[df["co2_alojamiento"] > 0][aloj_cols_ok].copy()

    aloj_header = [
        Paragraph("ID",               ST["tabla_cab"]),
        Paragraph("Origen",           ST["tabla_cab"]),
        Paragraph("Tipo alojamiento", ST["tabla_cab"]),
        Paragraph("Noches",           ST["tabla_cab"]),
        Paragraph("CO<sub>2</sub> (kg)", ST["tabla_cab"]),
    ]
    aloj_rows = [aloj_header]
    for _, row in aloj_df.iterrows():
        tipo_raw = str(row.get("alojamiento_tipo", "")).strip()
        tipo_etiq = ETIQ_ALOJ.get(tipo_raw, tipo_raw.capitalize() if tipo_raw else "—")
        noches_v  = int(row["noches"]) if "noches" in row.index and str(row["noches"]) not in ("nan","") else "—"
        aloj_rows.append([
            Paragraph(str(int(row["id"])),                         ST["tabla_cel_c"]),
            Paragraph(capitalizar_origen(row["origen"])[:35],      ST["tabla_cel"]),
            Paragraph(tipo_etiq,                                   ST["tabla_cel"]),
            Paragraph(str(noches_v),                               ST["tabla_cel_c"]),
            Paragraph(f"{row['co2_alojamiento']:.2f}",             ST["tabla_cel_c"]),
        ])
    aloj_rows.append([
        Paragraph("", ST["tabla_cel"]),
        Paragraph("", ST["tabla_cel"]),
        Paragraph("", ST["tabla_cel"]),
        Paragraph("<b>TOTAL</b>", ST["tabla_cel_neg"]),
        Paragraph(f"<b>{stats['total_aloj_co2']:.2f}</b>", ST["tabla_cel_c"]),
    ])

    aloj_cw = [tw*0.08, tw*0.33, tw*0.27, tw*0.1, tw*0.22]
    aloj_table = Table(aloj_rows, colWidths=aloj_cw, repeatRows=1)
    n_aloj_rows = len(aloj_rows)
    aloj_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),              VERDE_OSCURO),
        ("BACKGROUND",    (0,n_aloj_rows-1), (-1,n_aloj_rows-1), colors.HexColor("#eaf5eb")),
        ("ROWBACKGROUNDS",(0,1), (-1,n_aloj_rows-2),  [BLANCO, GRIS_CLARO]),
        ("GRID",          (0,0), (-1,-1),              0.5, colors.HexColor("#cccccc")),
        ("TOPPADDING",    (0,0), (-1,-1),              5),
        ("BOTTOMPADDING", (0,0), (-1,-1),              5),
        ("LEFTPADDING",   (0,0), (-1,-1),              6),
        ("RIGHTPADDING",  (0,0), (-1,-1),              6),
    ]))
    story.append(aloj_table)
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(
        "Factores aplicados: Hotel = 20 kg CO<sub>2</sub>/noche · "
        "Apartamento turístico = 15 kg CO<sub>2</sub>/noche · "
        "Casa de familiares/amigos = 0 kg CO<sub>2</sub>/noche "
        "(fuente: Carbon Trust / DEFRA). "
        "Se aplica el factor de atribución cuando el viaje fue parcialmente motivado por el evento.",
        ST["nota"]
    ))

    # Movilidad local alojamiento → venue
    if stats["total_local"] > 0:
        story.append(Spacer(1, 0.4*cm))
        story.append(Paragraph("Movilidad local: alojamiento → venue", ST["subseccion"]))
        story.append(Paragraph(
            f"Los asistentes con alojamiento generaron <b>{stats['total_local']:.2f} kg CO<sub>2</sub></b> "
            "adicionales en los desplazamientos diarios entre su alojamiento y el venue. "
            "Se asume una distancia de 3 km por trayecto (6 km/día ida y vuelta) "
            "multiplicada por el número de noches.",
            ST["cuerpo"]
        ))

    # ── EXTRAPOLACIÓN AL TOTAL DEL EVENTO ────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("4. Extrapolación al Total del Evento", ST["seccion"]))

    TOTAL_ASISTENTES = 443
    n_muestra        = stats["n"]
    media_muestra    = stats["media_co2"]
    pct_muestra      = n_muestra / TOTAL_ASISTENTES * 100
    co2_extrapolado  = media_muestra * TOTAL_ASISTENTES
    ahorro_extrap    = (stats["ahorro_potencial"] / n_muestra * TOTAL_ASISTENTES) if n_muestra else 0

    story.append(Paragraph(
        f"La muestra analizada comprende <b>{n_muestra} asistentes</b> de un total de "
        f"<b>{TOTAL_ASISTENTES} participantes</b> registrados en el evento "
        f"({pct_muestra:.1f}% del total). Aplicando la media de emisiones observada en la muestra "
        f"(<b>{media_muestra:.2f} kg CO<sub>2</sub>/asistente</b>) al conjunto completo de "
        f"participantes, se obtiene la siguiente estimación de la huella total del evento.",
        ST["cuerpo"]
    ))
    story.append(Spacer(1, 0.4*cm))

    # KPI destacado — huella extrapolada
    extrap_kpi_data = [
        [
            Paragraph(f"{co2_extrapolado:.1f} kg", ST["kpi_valor"]),
            Paragraph(f"{co2_extrapolado/1000:.2f} t", ST["kpi_valor"]),
            Paragraph(f"{TOTAL_ASISTENTES}", ST["kpi_valor"]),
        ],
        [
            Paragraph("CO<sub>2</sub> estimado total evento", ST["kpi_etiq"]),
            Paragraph("Equivalente en toneladas", ST["kpi_etiq"]),
            Paragraph("Total asistentes evento", ST["kpi_etiq"]),
        ],
    ]
    extrap_kpi_table = Table(extrap_kpi_data, colWidths=[cw, cw, cw], rowHeights=[1.5*cm, 0.6*cm])
    extrap_kpi_table.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (0,-1), colors.HexColor("#eaf5eb")),
        ("BACKGROUND",   (1,0), (1,-1), colors.HexColor("#f0fae0")),
        ("BACKGROUND",   (2,0), (2,-1), colors.HexColor("#eaf5eb")),
        ("BOX",          (0,0), (0,-1), 1, VERDE_OSCURO),
        ("BOX",          (1,0), (1,-1), 1, VERDE_OSCURO),
        ("BOX",          (2,0), (2,-1), 1, VERDE_OSCURO),
        ("LEFTPADDING",  (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING",   (0,0), (-1,-1), 8),
        ("BOTTOMPADDING",(0,0), (-1,-1), 4),
        ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(extrap_kpi_table)
    story.append(Spacer(1, 0.5*cm))

    # Tabla comparativa muestra vs total
    story.append(Paragraph("Comparativa: Muestra Analizada vs. Total del Evento", ST["subseccion"]))
    comp_data = [
        [
            Paragraph("", ST["tabla_cab"]),
            Paragraph("Asistentes", ST["tabla_cab"]),
            Paragraph("% sobre total", ST["tabla_cab"]),
            Paragraph("CO<sub>2</sub> (kg)", ST["tabla_cab"]),
            Paragraph("CO<sub>2</sub> (t)", ST["tabla_cab"]),
        ],
        [
            Paragraph("Muestra analizada", ST["tabla_cel"]),
            Paragraph(str(n_muestra), ST["tabla_cel_c"]),
            Paragraph(f"{pct_muestra:.1f}%", ST["tabla_cel_c"]),
            Paragraph(f"{stats['total_co2']:.2f}", ST["tabla_cel_c"]),
            Paragraph(f"{stats['total_co2']/1000:.3f}", ST["tabla_cel_c"]),
        ],
        [
            Paragraph("<b>Total evento (extrapolado)</b>", ST["tabla_cel_neg"]),
            Paragraph(f"<b>{TOTAL_ASISTENTES}</b>", ST["tabla_cel_c"]),
            Paragraph("<b>100%</b>", ST["tabla_cel_c"]),
            Paragraph(f"<b>{co2_extrapolado:.2f}</b>", ST["tabla_cel_c"]),
            Paragraph(f"<b>{co2_extrapolado/1000:.3f}</b>", ST["tabla_cel_c"]),
        ],
    ]
    comp_cw = [tw*0.36, tw*0.14, tw*0.16, tw*0.17, tw*0.17]
    comp_table = Table(comp_data, colWidths=comp_cw, repeatRows=1)
    comp_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), VERDE_OSCURO),
        ("BACKGROUND",    (0,2), (-1,2), colors.HexColor("#eaf5eb")),
        ("ROWBACKGROUNDS",(0,1), (-1,1), [BLANCO]),
        ("GRID",          (0,0), (-1,-1), 0.5, colors.HexColor("#cccccc")),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
    ]))
    story.append(comp_table)
    story.append(Spacer(1, 0.5*cm))

    # Nota metodológica
    story.append(Paragraph(
        "<b>Nota metodológica:</b> Los valores de esta sección son <i>estimaciones estadísticas</i> "
        "obtenidas mediante extrapolación simple: se multiplica la media de emisiones de la muestra "
        f"analizada ({n_muestra} asistentes, {pct_muestra:.1f}% del total) por el número total de "
        f"participantes ({TOTAL_ASISTENTES}). Este método asume que la distribución de medios de "
        "transporte y hábitos de desplazamiento de la muestra es representativa del conjunto. "
        "La precisión de la estimación mejora a medida que aumenta el tamaño muestral y su "
        "representatividad respecto al universo total de asistentes. No deben interpretarse como "
        "mediciones directas sino como órdenes de magnitud orientativos para la planificación "
        "de medidas de compensación o reducción de emisiones.",
        ST["nota"]
    ))

    # ── METODOLOGÍA ───────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("5. Metodología", ST["seccion"]))
    story.append(Paragraph(
        "El presente informe sigue el marco del <b>GHG Protocol Corporate Standard</b> "
        "(World Resources Institute / WBCSD), cuantificando las emisiones de Alcance 3 "
        "asociadas al desplazamiento de empleados/asistentes a un evento.",
        ST["cuerpo"]
    ))

    story.append(Paragraph("Geocodificación y cálculo de distancias", ST["subseccion"]))
    story.append(Paragraph(
        "Los orígenes (ciudad/municipio) declarados en el formulario fueron geocodificados "
        "mediante la API de <b>OpenRouteService (ORS)</b>. Para transportes por carretera se "
        "calcula la ruta real ORS (perfil <i>driving-car</i>); para avión se utiliza la distancia "
        "aérea (Haversine). Se asume viaje de ida y vuelta (distancia × 2). "
        "Los orígenes no geocodificables fueron excluidos del cálculo.",
        ST["cuerpo"]
    ))

    story.append(Paragraph("Factores de emisión DEFRA 2023", ST["subseccion"]))
    story.append(Paragraph(
        "Se aplican los factores del Departamento de Medio Ambiente, Alimentación y Asuntos "
        "Rurales del Reino Unido (DEFRA 2023), expresados en kg CO<sub>2</sub>e por km:",
        ST["cuerpo"]
    ))

    factores_data = [
        [Paragraph("Medio de transporte",       ST["tabla_cab"]),
         Paragraph("Factor (kg CO<sub>2</sub>e/km)", ST["tabla_cab"]),
         Paragraph("Notas",                     ST["tabla_cab"])],
        [Paragraph("Taxi / VTC",                ST["tabla_cel"]),
         Paragraph("0,190",                     ST["tabla_cel_c"]),
         Paragraph("—",                          ST["tabla_cel"])],
        [Paragraph("Coche (gasolina o diésel)", ST["tabla_cel"]),
         Paragraph("0,180",                     ST["tabla_cel_c"]),
         Paragraph("Se divide por nº ocupantes si > 1", ST["tabla_cel"])],
        [Paragraph("Coche híbrido",             ST["tabla_cel"]),
         Paragraph("0,120",                     ST["tabla_cel_c"]),
         Paragraph("Se divide por nº ocupantes si > 1", ST["tabla_cel"])],
        [Paragraph("Coche eléctrico",           ST["tabla_cel"]),
         Paragraph("0,050",                     ST["tabla_cel_c"]),
         Paragraph("Se divide por nº ocupantes si > 1", ST["tabla_cel"])],
        [Paragraph("Autobús interurbano",        ST["tabla_cel"]),
         Paragraph("0,060",                     ST["tabla_cel_c"]),
         Paragraph("—",                          ST["tabla_cel"])],
        [Paragraph("Tren / AVE / Cercanías",    ST["tabla_cel"]),
         Paragraph("0,035",                     ST["tabla_cel_c"]),
         Paragraph("—",                          ST["tabla_cel"])],
        [Paragraph("Metro / Tranvía",            ST["tabla_cel"]),
         Paragraph("0,030",                     ST["tabla_cel_c"]),
         Paragraph("—",                          ST["tabla_cel"])],
        [Paragraph("Avión corto radio (&lt;1.500 km)", ST["tabla_cel"]),
         Paragraph("0,255",                     ST["tabla_cel_c"]),
         Paragraph("Incluye forzamiento radiativo", ST["tabla_cel"])],
        [Paragraph("Avión largo radio (≥1.500 km)", ST["tabla_cel"]),
         Paragraph("0,195",                     ST["tabla_cel_c"]),
         Paragraph("Incluye forzamiento radiativo", ST["tabla_cel"])],
        [Paragraph("A pie / Bicicleta",          ST["tabla_cel"]),
         Paragraph("0,000",                     ST["tabla_cel_c"]),
         Paragraph("—",                          ST["tabla_cel"])],
    ]
    fact_cw = [tw*0.38, tw*0.18, tw*0.44]
    fact_table = Table(factores_data, colWidths=fact_cw, repeatRows=1)
    fact_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  VERDE_OSCURO),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [BLANCO, GRIS_CLARO]),
        ("GRID",          (0,0), (-1,-1), 0.5, colors.HexColor("#cccccc")),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
    ]))
    story.append(fact_table)
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(
        "<b>Factor de ocupación:</b> para coches privados con más de un ocupante, el factor "
        "de emisión se divide por el número de ocupantes declarado (hasta 4). "
        "<b>Transporte secundario:</b> si el asistente combinó medios, se añade el factor "
        "del medio secundario aplicado sobre 10 km fijos (tramo urbano de último kilómetro). "
        "<b>Factor de atribución:</b> viajes parcialmente motivados por el evento contribuyen "
        "al 50% de sus emisiones de transporte y alojamiento.",
        ST["nota"]
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("Alcance e incertidumbre", ST["subseccion"]))
    story.append(Paragraph(
        "El cálculo incluye las emisiones de Alcance 3, categoría 6 (desplazamientos "
        "de negocio/evento) y categoría 1 (alojamiento). No se han considerado las emisiones "
        "asociadas a la producción de energía del venue ni a la cadena de suministro. "
        "Los factores DEFRA incorporan emisiones directas (Tank-to-Wheel) e indirectas "
        "de producción de energía (Well-to-Wheel) donde aplica.",
        ST["cuerpo"]
    ))
    story.append(Paragraph(
        f"Informe generado el {date.today().strftime('%d/%m/%Y')} · "
        f"{BRAND_NAME} · {TAGLINE}",
        ST["nota"]
    ))

    # ── APÉNDICE A: INFORME DE ANOMALÍAS ──────────────────────────────────────
    anom_cols = ["anomalia_tipo", "anomalia_accion"]
    tiene_anomalias = all(c in df.columns for c in anom_cols)

    story.append(PageBreak())
    story.append(Paragraph("Apéndice A: Informe de Anomalías Detectadas", ST["seccion"]))

    ETIQ_ACCION = {
        "reclasificar": "Reclasificado automáticamente",
        "excluir":      "Excluido del cálculo de transporte",
        "revisar":      "Marcado para revisión manual",
    }
    ETIQ_TIPO = {
        "TAXI_DIST>100km":     "Taxi con distancia > 100 km",
        "METRO_DIST>80km":     "Metro/Tranvía con distancia > 80 km",
        "PIE_DIST>20km":       "A pie/Bicicleta con distancia > 20 km",
        "AUTOBUS_DIST>500km":  "Autobús con distancia > 500 km",
        "DIST>1500km_NO_AVION":"Distancia > 1 500 km (no avión)",
    }

    if not tiene_anomalias:
        story.append(Paragraph(
            "El fichero de datos no contiene columnas de anomalías. "
            "Regenere el CSV ejecutando calcular_huella_evento.py.",
            ST["cuerpo"]
        ))
    else:
        df_anom = df[df["anomalia_tipo"].astype(str).str.strip() != ""].copy()

        if df_anom.empty:
            story.append(Paragraph(
                "✓  No se detectaron anomalías en los datos de esta muestra. "
                "Todos los registros superaron las verificaciones de consistencia "
                "entre medio de transporte declarado y distancia geocodificada.",
                ST["cuerpo"]
            ))
        else:
            story.append(Paragraph(
                f"Se detectaron <b>{len(df_anom)} registro(s)</b> con inconsistencias entre el "
                "medio de transporte declarado y la distancia calculada. "
                "El sistema aplicó las correcciones automáticas descritas a continuación "
                "antes de calcular las emisiones.",
                ST["cuerpo"]
            ))
            story.append(Spacer(1, 0.4*cm))

            # ── Tabla de anomalías ────────────────────────────────────────────
            anom_header = [
                Paragraph("ID",           ST["tabla_cab"]),
                Paragraph("Origen",       ST["tabla_cab"]),
                Paragraph("T. declarado", ST["tabla_cab"]),
                Paragraph("T. corregido", ST["tabla_cab"]),
                Paragraph("Dist. (km)",   ST["tabla_cab"]),
                Paragraph("Regla",        ST["tabla_cab"]),
                Paragraph("Acción",       ST["tabla_cab"]),
            ]
            anom_rows = [anom_header]

            for _, row in df_anom.iterrows():
                t_orig = str(row.get("transporte_original", row.get("transporte_clave", "")))
                t_fin  = str(row.get("transporte_clave", ""))
                tipo_raw = str(row.get("anomalia_tipo", "")).split("|")[0].strip()
                accion_raw = str(row.get("anomalia_accion", "")).split("|")[0].strip()
                dist_v = row.get("distancia_km")
                dist_s = f"{float(dist_v):.1f}" if pd.notna(dist_v) and dist_v else "N/A"

                regla_label  = ETIQ_TIPO.get(tipo_raw, tipo_raw)
                accion_label = ETIQ_ACCION.get(accion_raw, accion_raw)

                # Color de fila por acción
                anom_rows.append([
                    Paragraph(str(int(row["id"])),                         ST["tabla_cel_c"]),
                    Paragraph(capitalizar_origen(row["origen"])[:28],      ST["tabla_cel"]),
                    Paragraph(t_orig.capitalize(),                         ST["tabla_cel"]),
                    Paragraph(t_fin.capitalize()  if accion_raw == "reclasificar" else "—",
                              ST["tabla_cel"]),
                    Paragraph(dist_s,                                      ST["tabla_cel_c"]),
                    Paragraph(regla_label,                                 ST["tabla_cel"]),
                    Paragraph(accion_label,                                ST["tabla_cel"]),
                ])

            anom_cw = [tw*0.05, tw*0.22, tw*0.11, tw*0.11, tw*0.08, tw*0.26, tw*0.17]
            anom_table = Table(anom_rows, colWidths=anom_cw, repeatRows=1)
            na = len(anom_rows)
            # Colores por acción
            style_cmds = [
                ("BACKGROUND",    (0,0), (-1,0),   VERDE_OSCURO),
                ("GRID",          (0,0), (-1,-1),  0.5, colors.HexColor("#cccccc")),
                ("TOPPADDING",    (0,0), (-1,-1),  4),
                ("BOTTOMPADDING", (0,0), (-1,-1),  4),
                ("LEFTPADDING",   (0,0), (-1,-1),  5),
                ("RIGHTPADDING",  (0,0), (-1,-1),  5),
            ]
            for i, row in enumerate(anom_rows[1:], start=1):
                accion_cell = str(row[6].text if hasattr(row[6], "text") else "")
                if "Excluido" in accion_cell:
                    bg = colors.HexColor("#fdecea")   # rojo muy suave
                elif "Reclasificado" in accion_cell:
                    bg = colors.HexColor("#fff8e1")   # amarillo suave
                else:
                    bg = colors.HexColor("#e8f4fd")   # azul suave
                style_cmds.append(("BACKGROUND", (0,i), (-1,i), bg))
            anom_table.setStyle(TableStyle(style_cmds))
            story.append(anom_table)
            story.append(Spacer(1, 0.4*cm))

            # ── Resumen por regla ─────────────────────────────────────────────
            story.append(Paragraph("Resumen por regla aplicada", ST["subseccion"]))
            tipos_count = df_anom["anomalia_tipo"].value_counts()
            resumen_anom = [
                [Paragraph("Regla", ST["tabla_cab"]),
                 Paragraph("Registros", ST["tabla_cab"]),
                 Paragraph("Acción", ST["tabla_cab"])],
            ]
            for tipo, cnt in tipos_count.items():
                tipo_s = tipo.split("|")[0].strip()
                accion_s = df_anom[df_anom["anomalia_tipo"].str.contains(tipo_s, regex=False)]["anomalia_accion"].iloc[0].split("|")[0].strip()
                resumen_anom.append([
                    Paragraph(ETIQ_TIPO.get(tipo_s, tipo_s), ST["tabla_cel"]),
                    Paragraph(str(cnt),                       ST["tabla_cel_c"]),
                    Paragraph(ETIQ_ACCION.get(accion_s, accion_s), ST["tabla_cel"]),
                ])
            res_anom_table = Table(resumen_anom, colWidths=[tw*0.55, tw*0.15, tw*0.30])
            res_anom_table.setStyle(TableStyle([
                ("BACKGROUND",    (0,0), (-1,0),  VERDE_OSCURO),
                ("ROWBACKGROUNDS",(0,1), (-1,-1), [BLANCO, GRIS_CLARO]),
                ("GRID",          (0,0), (-1,-1), 0.5, colors.HexColor("#cccccc")),
                ("TOPPADDING",    (0,0), (-1,-1), 5),
                ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                ("LEFTPADDING",   (0,0), (-1,-1), 8),
                ("RIGHTPADDING",  (0,0), (-1,-1), 8),
            ]))
            story.append(res_anom_table)
            story.append(Spacer(1, 0.3*cm))

            story.append(Paragraph(
                "<b>Criterios de detección aplicados:</b> "
                "(1) Taxi > 100 km → Coche gasolina. "
                "(2) Metro/Tranvía > 80 km → excluido. "
                "(3) A pie/Bicicleta > 20 km → Metro. "
                "(4) Autobús > 500 km → revisión manual. "
                "(5) Cualquier medio (excepto avión) > 1 500 km → Avión. "
                "Las reglas se evalúan en orden de prioridad; la primera que aplica detiene la evaluación.",
                ST["nota"]
            ))

    # ── Build ──────────────────────────────────────────────────────────────────
    doc.build(story)
    print(f"  ✅  Informe generado: {out_path}")

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Genera informe PDF de huella de carbono")
    parser.add_argument("--csv",     default="huella_carbono_resultados.csv",
                        help="Fichero CSV generado por calcular_huella_evento.py")
    parser.add_argument("--evento",  default="Premios Madrid Alimenta 2026",
                        help="Nombre del evento")
    parser.add_argument("--venue",   default="Real Casa de Correos, Puerta del Sol 7, 28013 Madrid",
                        help="Nombre y dirección del venue")
    parser.add_argument("--fecha",   default="25 de febrero de 2026",
                        help="Fecha del evento")
    parser.add_argument("--cliente", default="",
                        help="Nombre del cliente (opcional)")
    parser.add_argument("--output",  default="informe_huella_carbono.pdf",
                        help="Fichero PDF de salida")
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        sys.exit(f"❌  No se encontró '{args.csv}'. Ejecuta primero calcular_huella_evento.py")

    print(f"\n  Leyendo datos: {args.csv}")
    df = pd.read_csv(args.csv, sep=";")

    # Asegurar tipos numéricos
    for col in ["co2_total", "co2_transporte", "co2_alojamiento", "distancia_km",
                "co2_local", "co2_principal", "co2_secundario",
                "factor_atribucion", "factor_ocupacion", "noches"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    # Asegurar columnas de texto
    for col in ["anomalia_tipo", "anomalia_accion", "transporte_secundario",
                "alojamiento_tipo", "transporte_principal"]:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)

    print(f"  Calculando estadísticas...")
    stats = calcular_estadisticas(df)

    print(f"  Generando PDF...")
    build_pdf(stats, df, args)
    print(f"  {'='*50}\n")

if __name__ == "__main__":
    main()
