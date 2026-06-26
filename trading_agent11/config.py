import os

# ── API Credentials ────────────────────────────────────────────────────────────
API_KEY            = os.getenv("BITUNIX_API_KEY", "")
API_SECRET         = os.getenv("BITUNIX_API_SECRET", "")
CLAUDE_API_KEY     = os.getenv("ANTHROPIC_API_KEY", "")

# ── Agent identity ─────────────────────────────────────────────────────────────
GUARD_NAME         = "trading_agent11"
MAIN_LOCK          = "main11.lock"
DASHBOARD_LOCK     = "dashboard11.lock"

# ── Mode ───────────────────────────────────────────────────────────────────────
PAPER_TRADING      = True
DASHBOARD_PORT     = 5014

# ── Capital & risk ────────────────────────────────────────────────────────────
INITIAL_CAPITAL    = 10_000.0          # USDT
RISK_PER_TRADE     = 0.01              # 1 % of equity per trade
MAX_POSITIONS      = 5
MAX_LEVERAGE       = 10

# ── Timing ────────────────────────────────────────────────────────────────────
SCAN_INTERVAL_MIN  = 15                # minutes between pair scans
MONITOR_INTERVAL_S = 60               # seconds between position checks

# ── Technical params ──────────────────────────────────────────────────────────
ATR_PERIOD         = 14
ATR_MULTIPLIER_SL  = 1.5
ATR_MULTIPLIER_TP  = 2.5

# SuperTrend
ST_PERIOD          = 10
ST_MULTIPLIER      = 3.0

# EMA Crossover
EMA_FAST           = 9
EMA_SLOW           = 21

# DTDS
DTDS_EMA_FAST      = 9
DTDS_EMA_MID       = 21
DTDS_EMA_SLOW      = 50
DTDS_EMA_TREND     = 200

# VWAP
VWAP_STD_MULT      = 1.5

# ── Pair selection ─────────────────────────────────────────────────────────────
VOLUME_THRESHOLD   = 5_000_000        # min 24 h USDT volume
MAX_PAIRS          = 30
EXCLUDED_PAIRS     = {"USDCUSDT", "BUSDUSDT", "TUSDUSDT", "FDUSDUSDT"}

# ── Scoring / filtering ────────────────────────────────────────────────────────
MIN_SIGNAL_SCORE   = 60               # 0-100 score to accept a signal

# ── Shadow learning ────────────────────────────────────────────────────────────
SHADOW_MIN_SAMPLES = 5                # min decisions before insights are shown

# ── State files (relative to project root) ────────────────────────────────────
BASE_DIR           = "trading_agent11"
STATE_FILE         = f"{BASE_DIR}/state.json"
PORTFOLIO_FILE     = f"{BASE_DIR}/virtual_portfolio.json"
JOURNAL_FILE       = f"{BASE_DIR}/agent11_journal.json"
SHADOW_FILE        = f"{BASE_DIR}/shadow_decisions.json"
COSTS_FILE         = f"{BASE_DIR}/api_costs.json"
PAIR_PERF_FILE     = f"{BASE_DIR}/pair_performance.json"
TRADES_FILE        = f"{BASE_DIR}/trades_history.xlsx"

# ── Bitunix API ────────────────────────────────────────────────────────────────
BITUNIX_BASE_URL   = "https://fapi.bitunix.com"
REQUEST_TIMEOUT    = 10               # seconds
MAX_RETRIES        = 3

# ── Claude model ──────────────────────────────────────────────────────────────
CLAUDE_MODEL       = "claude-haiku-4-5-20251001"   # fast/cheap for frequent calls
CLAUDE_MAX_TOKENS  = 512
