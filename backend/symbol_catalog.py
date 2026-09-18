"""熱門標的字典（台股 / 台灣 ETF / 美股 / 美股 ETF）。

這份清單是「離線」的：即使 yfinance 的搜尋 API 不可用，前端的自動完成仍然能運作。
欄位說明：
    code      使用者輸入用的代號（台股不含 .TW 後綴）
    symbol    yfinance 實際查詢用的代號
    name_zh   中文名稱
    name_en   英文名稱
    market    TW（上市）/ TWO（上櫃）/ US
    kind      etf / stock / index
    tags      額外的搜尋關鍵字（俗名、別稱）
"""

from __future__ import annotations

Entry = dict


def _e(code: str, symbol: str, name_zh: str, name_en: str, market: str, kind: str,
       tags: tuple[str, ...] = ()) -> Entry:
    return {
        "code": code,
        "symbol": symbol,
        "name_zh": name_zh,
        "name_en": name_en,
        "market": market,
        "kind": kind,
        "tags": list(tags),
    }


TW_ETFS: list[Entry] = [
    _e("0050", "0050.TW", "元大台灣50", "Yuanta Taiwan Top 50 ETF", "TW", "etf", ("台灣50", "市值型", "大盤")),
    _e("0056", "0056.TW", "元大高股息", "Yuanta Taiwan Dividend Plus ETF", "TW", "etf", ("高股息", "配息")),
    _e("006208", "006208.TW", "富邦台50", "Fubon Taiwan Top 50 ETF", "TW", "etf", ("台灣50", "市值型")),
    _e("00878", "00878.TW", "國泰永續高股息", "Cathay Sustainability High Dividend ETF", "TW", "etf", ("高股息", "ESG", "月月配")),
    _e("00919", "00919.TW", "群益台灣精選高息", "Capital Taiwan Select High Dividend ETF", "TW", "etf", ("高股息",)),
    _e("00929", "00929.TW", "復華台灣科技優息", "Fuh Hwa Taiwan Technology Dividend ETF", "TW", "etf", ("高股息", "科技", "月配")),
    _e("00940", "00940.TW", "元大台灣價值高息", "Yuanta Taiwan Value High Dividend ETF", "TW", "etf", ("高股息", "價值")),
    _e("00939", "00939.TW", "統一台灣高息動能", "Uni-President Taiwan High Dividend Momentum ETF", "TW", "etf", ("高股息",)),
    _e("00713", "00713.TW", "元大台灣高息低波", "Yuanta Taiwan Low Volatility High Dividend ETF", "TW", "etf", ("高股息", "低波動")),
    _e("00692", "00692.TW", "富邦公司治理", "Fubon Corporate Governance 100 ETF", "TW", "etf", ("市值型", "ESG")),
    _e("00881", "00881.TW", "國泰台灣5G+", "Cathay Taiwan 5G Plus ETF", "TW", "etf", ("5G", "科技")),
    _e("00891", "00891.TW", "中信關鍵半導體", "CTBC Taiwan Semiconductor ETF", "TW", "etf", ("半導體", "科技")),
    _e("00892", "00892.TW", "富邦台灣半導體", "Fubon Taiwan Semiconductor ETF", "TW", "etf", ("半導體",)),
    _e("0052", "0052.TW", "富邦科技", "Fubon Taiwan Technology ETF", "TW", "etf", ("科技",)),
    _e("00646", "00646.TW", "元大S&P500", "Yuanta S&P 500 ETF", "TW", "etf", ("美股", "標普", "S&P")),
    _e("00662", "00662.TW", "富邦NASDAQ", "Fubon NASDAQ-100 ETF", "TW", "etf", ("美股", "那斯達克", "NASDAQ")),
    _e("00757", "00757.TW", "統一FANG+", "Uni-President NYSE FANG+ ETF", "TW", "etf", ("美股", "科技")),
    _e("00830", "00830.TW", "國泰費城半導體", "Cathay PHLX Semiconductor ETF", "TW", "etf", ("半導體", "美股", "費半")),
    _e("00679B", "00679B.TW", "元大美債20年", "Yuanta US Treasury 20+ Year Bond ETF", "TW", "etf", ("債券", "美債")),
    _e("00937B", "00937B.TW", "群益ESG投等債", "Capital ESG Investment Grade Bond ETF", "TW", "etf", ("債券", "ESG")),
    _e("00687B", "00687B.TW", "國泰20年美債", "Cathay US Treasury 20+ Year Bond ETF", "TW", "etf", ("債券", "美債")),
    _e("00885", "00885.TW", "富邦越南", "Fubon FTSE Vietnam ETF", "TW", "etf", ("越南", "新興市場")),
    _e("00631L", "00631L.TW", "元大台灣50正2", "Yuanta Taiwan 50 Leveraged 2x ETF", "TW", "etf", ("槓桿", "正2")),
    _e("00636", "00636.TW", "國泰中國A50", "Cathay FTSE China A50 ETF", "TW", "etf", ("中國", "A股")),
    _e("0051", "0051.TW", "元大中型100", "Yuanta Taiwan Mid-Cap 100 ETF", "TW", "etf", ("中型股",)),
]

TW_STOCKS: list[Entry] = [
    _e("2330", "2330.TW", "台積電", "TSMC", "TW", "stock", ("晶圓", "半導體", "護國神山")),
    _e("2317", "2317.TW", "鴻海", "Hon Hai Precision", "TW", "stock", ("代工", "富士康")),
    _e("2454", "2454.TW", "聯發科", "MediaTek", "TW", "stock", ("IC設計", "晶片")),
    _e("2412", "2412.TW", "中華電", "Chunghwa Telecom", "TW", "stock", ("電信", "定存股")),
    _e("2308", "2308.TW", "台達電", "Delta Electronics", "TW", "stock", ("電源", "電子")),
    _e("2303", "2303.TW", "聯電", "UMC", "TW", "stock", ("晶圓", "半導體")),
    _e("3711", "3711.TW", "日月光投控", "ASE Technology", "TW", "stock", ("封測",)),
    _e("2881", "2881.TW", "富邦金", "Fubon Financial", "TW", "stock", ("金融", "金控")),
    _e("2882", "2882.TW", "國泰金", "Cathay Financial", "TW", "stock", ("金融", "金控")),
    _e("2891", "2891.TW", "中信金", "CTBC Financial", "TW", "stock", ("金融", "金控")),
    _e("2886", "2886.TW", "兆豐金", "Mega Financial", "TW", "stock", ("金融", "金控")),
    _e("2884", "2884.TW", "玉山金", "E.SUN Financial", "TW", "stock", ("金融", "金控")),
    _e("2892", "2892.TW", "第一金", "First Financial", "TW", "stock", ("金融", "金控")),
    _e("5880", "5880.TW", "合庫金", "Taiwan Cooperative Financial", "TW", "stock", ("金融", "金控")),
    _e("1301", "1301.TW", "台塑", "Formosa Plastics", "TW", "stock", ("塑化",)),
    _e("1303", "1303.TW", "南亞", "Nan Ya Plastics", "TW", "stock", ("塑化",)),
    _e("6505", "6505.TW", "台塑化", "Formosa Petrochemical", "TW", "stock", ("塑化", "油價")),
    _e("2002", "2002.TW", "中鋼", "China Steel", "TW", "stock", ("鋼鐵",)),
    _e("1216", "1216.TW", "統一", "Uni-President", "TW", "stock", ("食品",)),
    _e("2912", "2912.TW", "統一超", "President Chain Store", "TW", "stock", ("超商", "7-11")),
    _e("2207", "2207.TW", "和泰車", "Hotai Motor", "TW", "stock", ("汽車",)),
    _e("2379", "2379.TW", "瑞昱", "Realtek", "TW", "stock", ("IC設計",)),
    _e("3034", "3034.TW", "聯詠", "Novatek", "TW", "stock", ("IC設計",)),
    _e("3008", "3008.TW", "大立光", "Largan Precision", "TW", "stock", ("光學", "鏡頭")),
    _e("2603", "2603.TW", "長榮", "Evergreen Marine", "TW", "stock", ("航運", "貨櫃")),
    _e("2609", "2609.TW", "陽明", "Yang Ming Marine", "TW", "stock", ("航運",)),
    _e("2615", "2615.TW", "萬海", "Wan Hai Lines", "TW", "stock", ("航運",)),
    _e("2357", "2357.TW", "華碩", "ASUS", "TW", "stock", ("電腦", "品牌")),
    _e("2382", "2382.TW", "廣達", "Quanta Computer", "TW", "stock", ("AI伺服器", "代工")),
    _e("3231", "3231.TW", "緯創", "Wistron", "TW", "stock", ("AI伺服器", "代工")),
    _e("6669", "6669.TW", "緯穎", "Wiwynn", "TW", "stock", ("AI伺服器",)),
    _e("2377", "2377.TW", "微星", "MSI", "TW", "stock", ("電腦", "顯卡")),
    _e("2301", "2301.TW", "光寶科", "Lite-On Technology", "TW", "stock", ("電子",)),
    _e("4938", "4938.TW", "和碩", "Pegatron", "TW", "stock", ("代工",)),
    _e("3661", "3661.TW", "世芯-KY", "Alchip Technologies", "TW", "stock", ("ASIC", "IC設計")),
    _e("2408", "2408.TW", "南亞科", "Nanya Technology", "TW", "stock", ("記憶體", "DRAM")),
    _e("2409", "2409.TW", "友達", "AUO", "TW", "stock", ("面板",)),
    _e("1101", "1101.TW", "台泥", "Taiwan Cement", "TW", "stock", ("水泥",)),
    _e("9910", "9910.TW", "豐泰", "Feng Tay Enterprises", "TW", "stock", ("鞋類", "Nike")),
    _e("2105", "2105.TW", "正新", "Cheng Shin Rubber", "TW", "stock", ("輪胎",)),
    _e("6488", "6488.TWO", "環球晶", "GlobalWafers", "TWO", "stock", ("矽晶圓", "上櫃")),
    _e("5274", "5274.TWO", "信驊", "Aspeed Technology", "TWO", "stock", ("BMC", "上櫃")),
    _e("3105", "3105.TWO", "穩懋", "Win Semiconductors", "TWO", "stock", ("砷化鎵", "上櫃")),
    _e("6415", "6415.TWO", "矽力-KY", "Silergy", "TWO", "stock", ("電源IC", "上櫃")),
    _e("4966", "4966.TWO", "譜瑞-KY", "Parade Technologies", "TWO", "stock", ("IC設計", "上櫃")),
    _e("8299", "8299.TWO", "群聯", "Phison Electronics", "TWO", "stock", ("記憶體", "上櫃")),
    _e("5483", "5483.TWO", "中美晶", "Sino-American Silicon", "TWO", "stock", ("矽晶圓", "上櫃")),
]

TW_INDEX: list[Entry] = [
    _e("TAIEX", "^TWII", "台股加權指數", "TAIEX Index", "TW", "index", ("大盤", "加權", "指數")),
]

US_ETFS: list[Entry] = [
    _e("SPY", "SPY", "SPDR 標普500 ETF", "SPDR S&P 500 ETF Trust", "US", "etf", ("標普", "S&P500", "大盤")),
    _e("VOO", "VOO", "Vanguard 標普500 ETF", "Vanguard S&P 500 ETF", "US", "etf", ("標普", "S&P500")),
    _e("IVV", "IVV", "iShares 標普500 ETF", "iShares Core S&P 500 ETF", "US", "etf", ("標普",)),
    _e("QQQ", "QQQ", "Invesco 那斯達克100 ETF", "Invesco QQQ Trust", "US", "etf", ("那斯達克", "NASDAQ", "科技")),
    _e("VTI", "VTI", "Vanguard 美股全市場 ETF", "Vanguard Total Stock Market ETF", "US", "etf", ("全市場",)),
    _e("DIA", "DIA", "道瓊工業 ETF", "SPDR Dow Jones Industrial Average ETF", "US", "etf", ("道瓊",)),
    _e("IWM", "IWM", "羅素2000 ETF", "iShares Russell 2000 ETF", "US", "etf", ("小型股", "羅素")),
    _e("SOXX", "SOXX", "iShares 半導體 ETF", "iShares Semiconductor ETF", "US", "etf", ("半導體", "費半")),
    _e("SMH", "SMH", "VanEck 半導體 ETF", "VanEck Semiconductor ETF", "US", "etf", ("半導體",)),
    _e("SCHD", "SCHD", "Schwab 高股息 ETF", "Schwab U.S. Dividend Equity ETF", "US", "etf", ("高股息", "配息")),
    _e("JEPI", "JEPI", "JPMorgan 高息權益 ETF", "JPMorgan Equity Premium Income ETF", "US", "etf", ("月配", "高息")),
    _e("ARKK", "ARKK", "ARK 創新 ETF", "ARK Innovation ETF", "US", "etf", ("創新", "成長")),
    _e("XLK", "XLK", "科技類股 ETF", "Technology Select Sector SPDR Fund", "US", "etf", ("科技",)),
    _e("XLF", "XLF", "金融類股 ETF", "Financial Select Sector SPDR Fund", "US", "etf", ("金融",)),
    _e("XLE", "XLE", "能源類股 ETF", "Energy Select Sector SPDR Fund", "US", "etf", ("能源", "油")),
    _e("VGT", "VGT", "Vanguard 資訊科技 ETF", "Vanguard Information Technology ETF", "US", "etf", ("科技",)),
    _e("TLT", "TLT", "iShares 20年期美債 ETF", "iShares 20+ Year Treasury Bond ETF", "US", "etf", ("債券", "美債")),
    _e("GLD", "GLD", "SPDR 黃金 ETF", "SPDR Gold Shares", "US", "etf", ("黃金", "避險")),
    _e("SLV", "SLV", "iShares 白銀 ETF", "iShares Silver Trust", "US", "etf", ("白銀",)),
    _e("EEM", "EEM", "新興市場 ETF", "iShares MSCI Emerging Markets ETF", "US", "etf", ("新興市場",)),
    _e("VEA", "VEA", "成熟市場 ETF", "Vanguard FTSE Developed Markets ETF", "US", "etf", ("成熟市場",)),
    _e("BND", "BND", "Vanguard 總體債券 ETF", "Vanguard Total Bond Market ETF", "US", "etf", ("債券",)),
    _e("VT", "VT", "Vanguard 全世界股票 ETF", "Vanguard Total World Stock ETF", "US", "etf", ("全球", "全世界")),
    _e("VYM", "VYM", "Vanguard 高股息 ETF", "Vanguard High Dividend Yield ETF", "US", "etf", ("高股息", "配息")),
    _e("QYLD", "QYLD", "Global X 那斯達克100掩護性買權 ETF", "Global X NASDAQ 100 Covered Call ETF", "US", "etf", ("月配", "高息")),
    _e("IEF", "IEF", "iShares 7-10年美債 ETF", "iShares 7-10 Year Treasury Bond ETF", "US", "etf", ("債券", "美債")),
    _e("XLV", "XLV", "醫療類股 ETF", "Health Care Select Sector SPDR Fund", "US", "etf", ("醫療",)),
    _e("XLY", "XLY", "非必需消費類股 ETF", "Consumer Discretionary Select Sector SPDR Fund", "US", "etf", ("消費",)),
    _e("IBIT", "IBIT", "iShares 比特幣信託 ETF", "iShares Bitcoin Trust ETF", "US", "etf", ("比特幣", "加密貨幣")),
]

US_STOCKS: list[Entry] = [
    _e("AAPL", "AAPL", "蘋果", "Apple Inc.", "US", "stock", ("iPhone",)),
    _e("MSFT", "MSFT", "微軟", "Microsoft Corporation", "US", "stock", ("雲端", "AI")),
    _e("NVDA", "NVDA", "輝達", "NVIDIA Corporation", "US", "stock", ("GPU", "AI")),
    _e("GOOGL", "GOOGL", "谷歌", "Alphabet Inc.", "US", "stock", ("Google", "搜尋")),
    _e("AMZN", "AMZN", "亞馬遜", "Amazon.com Inc.", "US", "stock", ("電商", "AWS")),
    _e("META", "META", "Meta", "Meta Platforms Inc.", "US", "stock", ("臉書", "Facebook")),
    _e("TSLA", "TSLA", "特斯拉", "Tesla Inc.", "US", "stock", ("電動車",)),
    _e("AVGO", "AVGO", "博通", "Broadcom Inc.", "US", "stock", ("半導體",)),
    _e("TSM", "TSM", "台積電ADR", "Taiwan Semiconductor ADR", "US", "stock", ("台積電", "ADR")),
    _e("NFLX", "NFLX", "網飛", "Netflix Inc.", "US", "stock", ("串流",)),
    _e("AMD", "AMD", "超微", "Advanced Micro Devices", "US", "stock", ("CPU", "GPU")),
    _e("INTC", "INTC", "英特爾", "Intel Corporation", "US", "stock", ("CPU",)),
    _e("MU", "MU", "美光", "Micron Technology", "US", "stock", ("記憶體",)),
    _e("QCOM", "QCOM", "高通", "Qualcomm Inc.", "US", "stock", ("手機晶片",)),
    _e("ORCL", "ORCL", "甲骨文", "Oracle Corporation", "US", "stock", ("資料庫", "雲端")),
    _e("CRM", "CRM", "Salesforce", "Salesforce Inc.", "US", "stock", ("SaaS",)),
    _e("ADBE", "ADBE", "Adobe", "Adobe Inc.", "US", "stock", ("軟體",)),
    _e("PLTR", "PLTR", "Palantir", "Palantir Technologies", "US", "stock", ("AI", "數據")),
    _e("COIN", "COIN", "Coinbase", "Coinbase Global", "US", "stock", ("加密貨幣",)),
    _e("UBER", "UBER", "優步", "Uber Technologies", "US", "stock", ("叫車",)),
    _e("BABA", "BABA", "阿里巴巴", "Alibaba Group", "US", "stock", ("中概股",)),
    _e("JPM", "JPM", "摩根大通", "JPMorgan Chase", "US", "stock", ("金融",)),
    _e("V", "V", "Visa", "Visa Inc.", "US", "stock", ("支付",)),
    _e("MA", "MA", "萬事達卡", "Mastercard Inc.", "US", "stock", ("支付",)),
    _e("DIS", "DIS", "迪士尼", "The Walt Disney Company", "US", "stock", ("娛樂",)),
    _e("KO", "KO", "可口可樂", "The Coca-Cola Company", "US", "stock", ("消費",)),
    _e("PEP", "PEP", "百事", "PepsiCo Inc.", "US", "stock", ("消費",)),
    _e("COST", "COST", "好市多", "Costco Wholesale", "US", "stock", ("零售",)),
    _e("WMT", "WMT", "沃爾瑪", "Walmart Inc.", "US", "stock", ("零售",)),
    _e("BRK-B", "BRK-B", "波克夏B", "Berkshire Hathaway Inc. Class B", "US", "stock", ("巴菲特", "波克夏")),
    _e("ASML", "ASML", "艾司摩爾", "ASML Holding N.V.", "US", "stock", ("光刻機", "EUV", "半導體設備")),
    _e("AMAT", "AMAT", "應用材料", "Applied Materials Inc.", "US", "stock", ("半導體設備",)),
    _e("LRCX", "LRCX", "科林研發", "Lam Research Corporation", "US", "stock", ("半導體設備",)),
    _e("ARM", "ARM", "安謀", "Arm Holdings plc", "US", "stock", ("IP", "晶片架構")),
    _e("TXN", "TXN", "德州儀器", "Texas Instruments", "US", "stock", ("類比晶片",)),
    _e("IBM", "IBM", "國際商業機器", "International Business Machines", "US", "stock", ("藍色巨人", "雲端")),
    _e("CSCO", "CSCO", "思科", "Cisco Systems Inc.", "US", "stock", ("網通",)),
    _e("SBUX", "SBUX", "星巴克", "Starbucks Corporation", "US", "stock", ("咖啡", "消費")),
    _e("MCD", "MCD", "麥當勞", "McDonald's Corporation", "US", "stock", ("速食", "消費")),
    _e("NKE", "NKE", "耐吉", "NIKE Inc.", "US", "stock", ("運動", "球鞋")),
    _e("JNJ", "JNJ", "嬌生", "Johnson & Johnson", "US", "stock", ("醫療", "製藥")),
    _e("LLY", "LLY", "禮來", "Eli Lilly and Company", "US", "stock", ("製藥", "減肥藥")),
    _e("PFE", "PFE", "輝瑞", "Pfizer Inc.", "US", "stock", ("製藥", "疫苗")),
    _e("UNH", "UNH", "聯合健康", "UnitedHealth Group", "US", "stock", ("醫療保險",)),
    _e("XOM", "XOM", "埃克森美孚", "Exxon Mobil Corporation", "US", "stock", ("石油", "能源")),
    _e("CVX", "CVX", "雪佛龍", "Chevron Corporation", "US", "stock", ("石油", "能源")),
    _e("BA", "BA", "波音", "The Boeing Company", "US", "stock", ("航太", "飛機")),
    _e("CAT", "CAT", "卡特彼勒", "Caterpillar Inc.", "US", "stock", ("重機械",)),
    _e("GS", "GS", "高盛", "The Goldman Sachs Group", "US", "stock", ("投資銀行", "金融")),
    _e("MS", "MS", "摩根士丹利", "Morgan Stanley", "US", "stock", ("投資銀行", "金融")),
    _e("BAC", "BAC", "美國銀行", "Bank of America", "US", "stock", ("金融",)),
    _e("AXP", "AXP", "美國運通", "American Express Company", "US", "stock", ("支付", "金融")),
    _e("HD", "HD", "家得寶", "The Home Depot Inc.", "US", "stock", ("零售", "居家")),
    _e("PG", "PG", "寶僑", "The Procter & Gamble Company", "US", "stock", ("日用品", "消費")),
    _e("MCHP", "MCHP", "微芯科技", "Microchip Technology", "US", "stock", ("MCU", "半導體")),
]

CATALOG: list[Entry] = TW_ETFS + TW_STOCKS + TW_INDEX + US_ETFS + US_STOCKS

# 首頁快速選取用的熱門清單
QUICK_PICKS: list[str] = ["2330", "0050", "00878", "006208", "2454", "SPY", "QQQ", "NVDA"]
