"""ThinkScript export — translate the reversal rules into a thinkorSwim study.

Generated from the Python `ReversalParams` so the two stay in sync. It mirrors
the confluence logic (climax + relative volume + value-area-edge + causal swing
pivots). Two approximations vs the Python engine, noted in the header:
  * Value-area-edge uses VWAP stretch (ToS `VolumeProfile` VAH/VAL can replace it).
  * Market internals ($TICK/$TRIN) aren't included here — in ToS they'd be added
    via secondary-symbol references (`close("$TICK")`), which yfinance can't see.
"""

from __future__ import annotations

from intradayx.signals.params import ReversalParams


def reversal_thinkscript(params: ReversalParams) -> str:
    p = params
    return f"""\
# intraday-x — Reversal (tops/bottoms) scanner  [params {p.version}]
# Auto-generated from the Python ReversalParams. Plots buy/sell arrows on the
# price chart. Approximation for thinkorSwim — see the module docstring.

input rvolFull   = {p.rvol_full};
input pivotK     = {p.pivot_k};
input atrLength  = 14;
input threshold  = {p.threshold};
input wClimax    = {p.w_climax};
input wVolume    = {p.w_volume};
input wValueArea = {p.w_value_area};

def vwap   = reference VWAP();
def avgVol = Average(volume, 20)[1];
def rvol   = if avgVol > 0 then volume / avgVol else 0;
def atr    = Average(TrueRange(high, low, close), atrLength);

def rng       = high - low;
def bodyTop   = Max(open, close);
def bodyBot   = Min(open, close);
def upperWick = if rng > 0 then (high - bodyTop) / rng else 0;
def lowerWick = if rng > 0 then (bodyBot - low) / rng else 0;
def closePos  = if rng > 0 then (close - low) / rng else 0;

def volFactor   = Min(rvol / rvolFull, 1);
def rangeFactor = if atr > 0 then Min(rng / atr / 2, 1) else 0;
def climaxUp    = volFactor * (0.4 * rangeFactor + 0.3 * upperWick + 0.3 * (1 - closePos));
def climaxDown  = volFactor * (0.4 * rangeFactor + 0.3 * lowerWick + 0.3 * closePos);

# Causal confirmed swing pivots: confirmed pivotK bars AFTER the extreme.
def isPivotHigh   = high == Highest(high, 2 * pivotK + 1);
def isPivotLow    = low  == Lowest(low,  2 * pivotK + 1);
def confPivotHigh = isPivotHigh[pivotK];
def confPivotLow  = isPivotLow[pivotK];

# VWAP stretch as a Value-Area-edge proxy.
def stretchUp = if atr > 0 then Min((close - vwap) / atr, 1) else 0;
def stretchDn = if atr > 0 then Min((vwap - close) / atr, 1) else 0;

def confluenceTop = wClimax * climaxUp   + wVolume * volFactor + wValueArea * Max(stretchUp, 0);
def confluenceBot = wClimax * climaxDown + wVolume * volFactor + wValueArea * Max(stretchDn, 0);

def topSignal = confPivotHigh and confluenceTop >= threshold;
def botSignal = confPivotLow  and confluenceBot >= threshold;

plot Top = if topSignal then high else Double.NaN;
Top.SetPaintingStrategy(PaintingStrategy.BOOLEAN_ARROW_DOWN);
Top.SetDefaultColor(Color.RED);

plot Bot = if botSignal then low else Double.NaN;
Bot.SetPaintingStrategy(PaintingStrategy.BOOLEAN_ARROW_UP);
Bot.SetDefaultColor(Color.GREEN);

plot VWAPLine = vwap;
VWAPLine.SetDefaultColor(Color.YELLOW);
"""
