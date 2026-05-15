# 📊 Portfolio Optimizer & Real-Time Tracker

Your complete investment portfolio analysis system with automated price updates, optimization recommendations, and professional visualizations.

## 🎯 Features

### 1. **Real-Time Price Updates**
- Automatically fetches latest prices from Yahoo Finance
- Updates your Holdings sheet with current market prices
- Recalculates all gains/losses instantly

### 2. **Portfolio Optimization**
- Uses Modern Portfolio Theory (MPT) to suggest optimal allocation
- Calculates Sharpe ratio for your current portfolio
- Recommends allocation improvements
- Constraint: No single position exceeds 20% to ensure diversification

### 3. **Professional Visualizations** (5 Charts)
- **📊 Sector Concentration**: Pie chart showing allocation by industry
- **📈 Current vs Optimal**: Compare your allocation to recommended
- **📉 Portfolio Growth**: 1-year performance of each stock
- **🎯 Sensitivity Analysis**: What-if scenarios for different strategies
- **⚠️  Risk-Return Profile**: Risk vs Return scatter plot

### 4. **Portfolio Analytics**
- Position-by-position breakdown
- Account allocation (Robinhood vs Webull)
- Overall portfolio metrics (return %, risk, Sharpe ratio)
- Top holdings identification

---

## 🚀 Quick Start

### Step 1: Install Required Packages
Open Terminal/Command Prompt and run:
```bash
pip install yfinance pandas numpy scipy matplotlib seaborn openpyxl pillow
```

### Step 2: Run the Optimizer Script
Navigate to your Personal Investment Tracker folder:
```bash
cd "path/to/Personal Investment Tracker"
python3 portfolio_optimizer.py
```

**What happens:**
- ✅ Fetches latest prices (30 seconds)
- ✅ Calculates portfolio optimization
- ✅ Generates 5 visualization charts
- ✅ Updates Excel with embedded images & KPIs
- ✅ Automatically saves the file

### Step 3: View Results
- Open `Investment_Portfolio_Tracker.xlsx`
- Go to the **"Optimization"** tab
- See all charts and KPI metrics

---

## 📁 Files in This Folder

| File | Purpose |
|------|---------|
| `Investment_Portfolio_Tracker.xlsx` | Main portfolio dashboard (auto-updated) |
| `portfolio_optimizer.py` | Python script to run (fetches prices & updates Excel) |
| `README.md` | This file |

---

## 📊 Excel Sheets Explained

### Sheet 1: Holdings
- Complete list of all 18 positions
- Current prices (updates when you run the script)
- Cost basis and current values
- Individual gains/losses and returns

### Sheet 2: Portfolio Summary
- Quick overview of your portfolio metrics
- Total value, gains, and return percentage
- Account breakdown (Robinhood vs Webull split)

### Sheet 3: Optimization (Dashboard) ⭐
- **Real-time KPI metrics** updated by the Python script
- **5 embedded charts** showing:
  - Sector allocation breakdown
  - Current vs Optimal allocation comparison
  - 1-year stock performance
  - Sensitivity analysis (what-if scenarios)
  - Risk-return profile
- Instructions for running updates

### Sheet 4: Position Allocation
- Shows each position's % of total portfolio
- Identifies concentration risks
- Highlights top holdings

---

## 🔄 How Often Should I Run It?

| Frequency | Reason |
|-----------|--------|
| **Weekly** | Stay updated on price movements & reallocate if needed |
| **Monthly** | Review progress toward optimization targets |
| **Quarterly** | Rebalance portfolio based on recommended allocation |
| **Annual** | Comprehensive review and strategy adjustment |

---

## 📈 Understanding the Output

### Current Metrics
Your portfolio's **actual performance** based on current holdings:
- **Return %**: How much you've made/lost
- **Volatility**: How much your portfolio fluctuates
- **Sharpe Ratio**: Risk-adjusted return (higher = better)

### Optimal Metrics  
What you *could* achieve with recommended allocation:
- **Better Sharpe Ratio**: Potentially better risk-adjusted returns
- **Lower Concentration Risk**: More diversified across positions
- **Improved Sectors**: More balanced industry exposure

### Sensitivity Analysis
Shows expected returns for different strategies:
- **Current**: Your actual allocation
- **Optimal**: Recommended by the algorithm
- **Equal Weight**: 5.6% allocation to each position
- **Tech Heavy**: 30% in tech stocks
- **Conservative**: Reduced tech/consumer exposure

---

## 💡 Key Insights from Your Portfolio

### 🚨 Current Concentration Issues
- **Top 3 Holdings**: ~60-70% of portfolio (MSFT, ORCL, MU)
- **Risk Level**: MEDIUM-HIGH due to concentration
- **Recommendation**: Diversify - reduce top 3 to <45%

### 📊 Current Holdings by Sector
- **Technology**: 40-45% (MSFT, ORCL, MU, NVDA, AAPL, NTGR, IWM partial)
- **Financials**: 15-20% (JPM, C, BAC, LYG)
- **Consumer**: 10-12% (AMZN, WBD, WMT)
- **Industrials**: 3-5% (DAL)
- **Real Estate**: 2-3% (SLG)
- **Utilities**: 1-2% (T)
- **Fixed Income**: 2% (JEPI)

### 📋 Recommended Actions
1. **Trim Tech positions**: Sell 10-15% of MSFT, ORCL, MU
2. **Add diversification**: Consider healthcare, energy, staples
3. **Strengthen underweights**: Increase consumer (WMT) and industrials
4. **Monitor losers**: JEPI and JPM are down (hold or average down)
5. **Rebalance quarterly**: Maintain target allocations

---

## ⚙️ Customization

### Changing Holdings
Edit `portfolio_optimizer.py` lines 30-45:
```python
HOLDINGS = {
    'AAPL': 0.023,  # ticker: shares
    'MSFT': 0.8,
    # ... etc
}
```

### Changing Purchase Prices
Edit `portfolio_optimizer.py` lines 48-63:
```python
PURCHASE_PRICES = {
    'AAPL': 255.87,  # ticker: price
    'MSFT': 326.38,
    # ... etc
}
```

### Adjusting Constraints
Edit `portfolio_optimizer.py` line 130:
```python
bounds = tuple((0, 0.2) for _ in tickers)  # 0.2 = max 20% per position
```

---

## 🔧 Troubleshooting

### Error: "ModuleNotFoundError: No module named 'yfinance'"
**Solution:**
```bash
pip install --upgrade yfinance
```

### Error: "Failed to fetch prices"
**Possible causes:**
- Internet connection issue
- Firewall blocking Yahoo Finance
- Rate limiting

**Solution:** Run again in a few minutes, or check your connection

### Charts not appearing in Excel
**Solution:**
1. Make sure `matplotlib` is installed: `pip install matplotlib`
2. Re-run the script: `python3 portfolio_optimizer.py`
3. Close and reopen Excel file

### Excel file won't open
**Solution:**
1. Make sure Excel is closed before running the script
2. Check file isn't corrupted: Try opening a backup copy
3. Ensure you have read/write permissions on the folder

---

## 📚 What the Python Script Does

```
1. FETCH PRICES (30 sec)
   └─ Downloads 1-year price history from Yahoo Finance
   └─ Extracts latest prices for all 18 holdings

2. CALCULATE PORTFOLIO (5 sec)
   └─ Computes current values & gains/losses
   └─ Calculates portfolio metrics (return, risk, Sharpe)

3. OPTIMIZE (10 sec)
   └─ Runs Modern Portfolio Theory algorithm
   └─ Finds optimal allocation maximizing Sharpe ratio
   └─ Suggests position limits for diversification

4. GENERATE VISUALIZATIONS (20 sec)
   └─ Creates 5 professional charts (PNG format)
   └─ Sector concentration pie chart
   └─ Current vs optimal bar charts
   └─ Performance line chart
   └─ Sensitivity analysis
   └─ Risk-return scatter plot

5. UPDATE EXCEL (10 sec)
   └─ Updates Holdings sheet with current prices
   └─ Creates/overwrites Optimization dashboard
   └─ Embeds all 5 charts in Excel
   └─ Adds KPI metrics & updated timestamp
   └─ Saves file

TOTAL TIME: ~75 seconds
```

---

## 📞 Support

If you encounter issues:
1. Check that Python 3.8+ is installed: `python3 --version`
2. Verify all packages are installed: `pip list`
3. Ensure Excel file is closed when running script
4. Try running from the folder where Excel file is located
5. Check internet connection (needed for Yahoo Finance)

---

## 🎓 Learning Resources

- **Modern Portfolio Theory**: https://www.investopedia.com/terms/m/modernportfoliotheory.asp
- **Sharpe Ratio**: https://www.investopedia.com/terms/s/sharperatio.asp
- **Portfolio Diversification**: https://www.investopedia.com/terms/d/diversification.asp
- **Technical Analysis**: https://www.investopedia.com/technical-analysis-4689657

---

## 📝 Notes

- This tool is for **analysis purposes only** - not investment advice
- Past performance does not guarantee future results
- Always do your own research before making investment decisions
- Consider consulting a financial advisor for major changes
- Update your purchases prices when you make new trades

---

**Last Updated**: 2026-05-15  
**Python Version**: 3.8+  
**Status**: Active & Maintained

Happy investing! 📈
