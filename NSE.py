import time
from datetime import datetime

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


@st.cache_data(ttl=30)
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
else:
    DEFAULT_EXPIRY = st.session_state.selected_expiry

base_url = f"https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol=NIFTY&expiry={DEFAULT_EXPIRY}"
session = requests.Session()
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/",
    }
)


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
refresh_interval = st.sidebar.slider("Refresh interval (seconds)", 15, 120, 15)

# -------------------------------------------------
# FETCH OPTION CHAIN DATA
# -------------------------------------------------
data = fetch_option_chain("NIFTY", expiry)
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
    return {
        # Call columns
        "IV_Call": ce.get("impliedVolatility"),
        "BuyVol_Call": ce.get("totalBuyQuantity"),
        "SellVol_Call": ce.get("totalSellQuantity"),
        "NetVol_Call": (ce.get("totalBuyQuantity") or 0)
        - (ce.get("totalSellQuantity") or 0),
        "OI_Call": ce.get("openInterest"),
        "OI_Chg%_Call": ce.get("pchangeinOpenInterest"),
        "LTP_Call": ce.get("lastPrice"),
        # Strike
        "Strike": strike,
        # Put columns
        "LTP_Put": pe.get("lastPrice"),
        "OI_Chg%_Put": pe.get("pchangeinOpenInterest"),
        "OI_Put": pe.get("openInterest"),
        "NetVol_Put": (pe.get("totalBuyQuantity") or 0)
        - (pe.get("totalSellQuantity") or 0),
        "SellVol_Put": pe.get("totalSellQuantity"),
        "BuyVol_Put": pe.get("totalBuyQuantity"),
        "IV_Put": pe.get("impliedVolatility"),
        # D
        "D%_D": (ce.get("openInterest") - pe.get("openInterest"))
        * 100
        / (ce.get("openInterest") + pe.get("openInterest")),
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


def highlight(df):
    styled = df.style
    # Highlight max/min for key columns
    for col in [
        ("Call", "NetVol"),
        ("Put", "NetVol"),
        ("Call", "OI_Chg%"),
        ("Put", "OI_Chg%"),
    ]:
        styled = styled.highlight_max(subset=[col], color="#006400")
        styled = styled.highlight_min(subset=[col], color="#ff6666")
    # Highlight ATM strike row
    atm = min(df[("", "Strike")], key=lambda x: abs(x - underlying))
    styled = styled.apply(
        lambda r: [
            "background-color:#ff0000" if r[("", "Strike")] == atm else "" for _ in r
        ],
        axis=1,
    )
    # Highlight Strike column
    styled = styled.applymap(
        lambda v: "font-weight:bold; background-color:#917D7D", subset=[("", "Strike")]
    )

    styled = styled.applymap(
        lambda v: (
            "font-weight:bold; background-color:#ff0000"
            if v > 0
            else "font-weight:bold; background-color:#006400"
            if v < 0
            else ""
        ),
        subset=[("D", "D%")],
    )

    return styled


# -------------------------------------------------
# DISPLAY DATA
# -------------------------------------------------
st.subheader("📈 Option Chain")
st.dataframe(highlight(df), width="stretch", height=800)

# -------------------------------------------------
# AUTO REFRESH
# -------------------------------------------------
if auto_refresh:
    time.sleep(refresh_interval)
    st.rerun()
    st.rerun()
