# warmup.py

from script_loader import load_scripts
from server_price_connect import get_sheet
import time


def preload_all():
    """
    Warm up scripts + sheets for all markets.
    Safe to call multiple times.
    """

    markets = ("PDX", "DFW", "PHX")

    # --- preload scripts ---
    for m in markets:
        try:
            load_scripts(m)
        except Exception as e:
            print("Script preload error:", m, e)
            raise RuntimeError(f"Sheet preld failed for {m}: {e}")

    # --- preload pricing sheets ---
    for m in markets:
        try:
            sheet = get_sheet(m.lower())
            sheet.batch_get(["E3"], value_render_option="UNFORMATTED_VALUE")
        except Exception as e:
            print("Sheet preload error:", m, e)
            raise RuntimeError(f"Sheet preload failed for {m}: {e}")

    print("Warmup complete.")