import time
from datetime import datetime
from datetime import time as dt_time
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

# -------------------------------------------------
# PAGE CONFIG
# -------------------------------------------------
st.set_page_config(page_title="NIFTY Option Chain", layout="wide")
st.title("📊 NIFTY Option Chain (Live)")
st.caption("Data Source: NSE India")

# -------------------------------------------------
# FETCH DATA FUNCTION
# -------------------------------------------------


def fetch_option_chain(symbol, expiry):
    url = f"https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol={symbol}&expiry={expiry}"

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/",
    }

    session = requests.Session()
    session.headers.update(headers)

    # warm-up (important)
    session.get("https://www.nseindia.com", timeout=10)

    resp = session.get(url, timeout=10)

    if resp.status_code != 200:
        return None

    if not resp.text or not resp.text.strip().startswith("{"):
        return None

    return resp.json()


# -------------------------------------------------
# INITIAL LOAD
# -------------------------------------------------
DEFAULT_EXPIRY = "28-Apr-2026"
if "selected_expiry" not in st.session_state:
    st.session_state.selected_expiry = DEFAULT_EXPIRY
    st.session_state.prev_oi = {}
else:
    DEFAULT_EXPIRY = st.session_state.selected_expiry

if "prev_expiry" not in st.session_state:
    st.session_state.prev_expiry = DEFAULT_EXPIRY

base_url = f"https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol=NIFTY&expiry={DEFAULT_EXPIRY}"
session = requests.Session()
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/",
    }
)

print("Calling API to refresh data")
resp = session.get(base_url, timeout=10)

if resp.status_code != 200:
    st.error(f"NSE blocked request (HTTP {resp.status_code})")
    st.stop()

if not resp.text or not resp.text.strip().startswith("{"):
    st.error("NSE returned non-JSON response (blocked by NSE)")
    st.stop()

base_data = resp.json()

expiries = base_data["records"]["expiryDates"]
underlying = base_data["records"]["underlyingValue"]
timestamp = base_data["records"]["timestamp"]

# -------------------------------------------------
# SIDEBAR SETTINGS
# -------------------------------------------------
st.sidebar.header("⚙️ Settings")
expiry = st.sidebar.selectbox("Select Expiry Date", expiries, key="selected_expiry")
auto_refresh = st.sidebar.checkbox("🔁 Auto Refresh", value=True)
refresh_interval = st.sidebar.slider("Refresh interval (seconds)", 30, 120, 30)

if st.session_state.prev_expiry != expiry:
    st.session_state.prev_oi = {}
    st.session_state.prev_expiry = expiry

# -------------------------------------------------
# FETCH OPTION CHAIN DATA
# -------------------------------------------------
data = fetch_option_chain("NIFTY", expiry)
if data is None:
    st.error("Failed to fetch option chain data from NSE.")
    st.stop()

records = data["records"]["data"]

# -------------------------------------------------
# PROCESS DATA
# -------------------------------------------------


def build_option_row(item, underlying):
    strike = item["strikePrice"]
    if abs(strike - underlying) > 500:
        return None
    ce = item.get("CE", {})
    pe = item.get("PE", {})

    ce_oi = ce.get("openInterest") or 0
    pe_oi = pe.get("openInterest") or 0

    prev = st.session_state.prev_oi.get(strike, {"ce": ce_oi, "pe": pe_oi})

    ce_diff = ce_oi - prev["ce"]
    pe_diff = pe_oi - prev["pe"]

    # update stored value
    st.session_state.prev_oi[strike] = {"ce": ce_oi, "pe": pe_oi}

    return {
        "IV_Call": ce.get("impliedVolatility"),
        "OI_Call": ce_oi,
        "OI_Call (current - prev)": ce_diff,
        "OI_Chg%_Call": ce.get("pchangeinOpenInterest"),
        "LTP_Call": ce.get("lastPrice"),
        "Strike": strike,
        "LTP_Put": pe.get("lastPrice"),
        "OI_Chg%_Put": pe.get("pchangeinOpenInterest"),
        "OI_Put": pe_oi,
        "OI_Put (current - prev)": pe_diff,
        "IV_Put": pe.get("impliedVolatility"),
        "D%_D": (ce_oi - pe_oi) * 100 / (ce_oi + pe_oi) if (ce_oi + pe_oi) else 0,
    }


rows = []
for item in records:
    row = build_option_row(item, underlying)
    if row is not None:
        rows.append(row)

df = pd.DataFrame(rows)

if df.empty:
    st.warning("No option data available near ATM")
    st.stop()

df = df.sort_values("Strike")

# -------------------------------------------------
# CREATE MULTIINDEX COLUMNS FOR CALL/PUT
# -------------------------------------------------
columns = []
for col in df.columns:
    if col.endswith("_Call"):
        columns.append(("Call", col.replace("_Call", "")))
    elif col.endswith("_Put"):
        columns.append(("Put", col.replace("_Put", "")))
    elif col.endswith("_D"):
        columns.append(("D", col.replace("_D", "")))
    else:
        columns.append(("", col))
df.columns = pd.MultiIndex.from_tuples(columns)

# Reorder columns: Call | Strike | Put | D
df = df[["Call", "", "Put", "D"]]

# -------------------------------------------------
# HEADER METRICS
# -------------------------------------------------
c1, c2, c3 = st.columns(3)
c1.metric("Underlying", underlying)
c2.metric("Expiry", expiry)
dt = datetime.strptime(timestamp, "%d-%b-%Y %H:%M:%S")
c3.metric("Last Updated", dt.strftime("%H:%M:%S"))

# -------------------------------------------------
# STYLING FUNCTION
# -------------------------------------------------


def color_scale(v):
    max_val = 50
    intensity = min(abs(v) / max_val, 1)

    if v > 0:
        g = int(255 * intensity)
        text = "black" if g > 150 else "white"
        return f"background-color: rgb(0,{g},0); color:{text}"
    elif v < 0:
        r = int(255 * intensity)
        text = "black" if r > 150 else "white"
        return f"background-color: rgb({r},0,0); color:{text}"
    return ""

def highlight(df):

    styled = df.style

    # Highlight max/min OI change %
    # for col in [
    #     ("Call", "OI_Chg%"),
    #     ("Put", "OI_Chg%"),
    # ]:
    #     styled = styled.highlight_max(subset=[col], color="#006400")
    #     styled = styled.highlight_min(subset=[col], color="#ff6666")

    # ATM strike
    atm = min(df[("", "Strike")], key=lambda x: abs(x - underlying))

    styled = styled.apply(
        lambda r: [
            "background-color:#ff4d4d" if r[("", "Strike")] == atm else ""
            for _ in r
        ],
        axis=1,
    )

    styled = styled.map(
        color_scale,
        subset=[("Call", "OI_Chg%"), ("Put", "OI_Chg%")],
    )

    # Strike column styling
    styled = styled.map(
        lambda v: "font-weight:bold; background-color:#917D7D",
        subset=[("", "Strike")]
    )

    # D% coloring
    styled = styled.map(
        lambda v: (
            "font-weight:bold; background-color:#ff0000"
            if v > 0
            else "font-weight:bold; background-color:#006400"
            if v < 0
            else ""
        ),
        subset=[("D", "D%")],
    )

    # Detect diff column names safely
    call_diff_col = [c for c in df.columns if c[0] == "Call" and "prev" in c[1]]
    put_diff_col = [c for c in df.columns if c[0] == "Put" and "prev" in c[1]]

    # CALL difference (positive green, negative red)
    if call_diff_col:
        styled = styled.map(
            lambda v: (
                "background-color:#006400; color:white"
                if v > 0 else
                "background-color:#8B0000; color:white"
                if v < 0 else ""
            ),
            subset=call_diff_col
        )

    # PUT difference (positive red, negative green)
    if put_diff_col:
        styled = styled.map(
            lambda v: (
                "background-color:#8B0000; color:white"
                if v > 0 else
                "background-color:#006400; color:white"
                if v < 0 else ""
            ),
            subset=put_diff_col
        )
    return styled


# -------------------------------------------------
# DISPLAY DATA
# -------------------------------------------------
st.subheader("📈 Option Chain")
st.table(highlight(df))

IST = ZoneInfo("Asia/Kolkata")

now = datetime.now(IST)

# Check weekday (Mon=0 ... Sun=6)
is_weekday = now.weekday() < 5

# Market hours
start = dt_time(9, 0)
end = dt_time(15, 30)

is_market_time = start <= now.time() <= end

# -------------------------------------------------
# AUTO REFRESH
# -------------------------------------------------
if auto_refresh and is_weekday and is_market_time:
    print("✅ Rerunning the job")
    time.sleep(refresh_interval)
    st.rerun()
else:
    print("⛔ Market Closed")
