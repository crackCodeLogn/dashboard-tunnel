import pprint
from datetime import datetime
import pandas as pd

import yfinance as yf
from flask import Flask, request
from flask_cors import CORS
from Investment import Investment
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model.output import mkt_data_pb2 as MarketData

# import model.output.mkt_data_pb2 as MarketData

app = Flask(__name__)
CORS(app)

start_date = '2016-10-18'
end_date = '2023-10-10'

ticker_name_map = {}
country_code_map = {
    "CA": ".TO",
    "US": "",
    "IN": ".NS",  # Nifty-50
}


def download_financial_data(symbol, start=start_date, end=end_date, country_code="CA", use_original_symbol=True):
    if not use_original_symbol: symbol = f"{symbol}{country_code_map[country_code]}"
    data = yf.download(symbol, start=start, end=end)
    return data[["Adj Close"]], symbol


def convert_to_date(dt: datetime):
    return dt.strftime("%Y-%m-%d")


def generate_proto_Ticker(symbol: str, name: str = "", sector: str = "", type: str = ""):
    ticker = MarketData.Ticker()
    ticker.symbol = symbol
    ticker.name = name
    ticker.sector = sector
    ticker.type = MarketData.InstrumentType.Value(type)
    return ticker


def generate_proto_Value(date: str, price: float):
    value = MarketData.Value()
    value.date = date
    value.price = price
    return value


def generate_proto_Portfolio():
    return MarketData.Portfolio()


def generate_proto_Investment(portfolio, investment: Investment):
    global ticker_name_map
    invest = MarketData.Investment()
    invest.ticker.symbol = investment.symbol

    if invest.ticker.symbol not in ticker_name_map:
        ticker_name_map[invest.ticker.symbol] = get_ticker_name_without_country(invest.ticker.symbol)
    ticker_name = ticker_name_map[invest.ticker.symbol]

    invest.ticker.name = ticker_name
    invest.ticker.sector = investment.sector
    invest.ticker.type = MarketData.InstrumentType.Value(investment.type)
    value_data = generate_proto_Value(investment.dt, investment.ticker_price)
    invest.ticker.data.append(value_data)
    invest.qty = investment.qty
    invest.accountType = MarketData.AccountType.Value(investment.account)
    portfolio.investments.append(invest)


@app.route('/mkt/<country_code>/ticker/type/<symbol>', methods=['GET'])
def get_ticker_type(country_code, symbol):
    # http://localhost:8083/mkt/CA/ticker/type/CCO
    ticker = yf.Ticker(symbol + country_code_map[country_code])
    return ticker.info['quoteType']


@app.route('/mkt/ticker/type/<symbol>', methods=['GET'])
def get_ticker_type_without_country(symbol):
    # http://localhost:8083/mkt/ticker/type/CCO
    ticker = yf.Ticker(symbol)
    return ticker.info['quoteType']


@app.route('/mkt/<country_code>/ticker/name/<symbol>', methods=['GET'])
def get_ticker_name(country_code, symbol):
    # http://localhost:8083/mkt/CA/ticker/name/CCO
    ticker = yf.Ticker(symbol + country_code_map[country_code])
    return ticker.info['longName']


@app.route('/mkt/ticker/name/<symbol>', methods=['GET'])
def get_ticker_name_without_country(symbol):
    # http://localhost:8083/mkt/ticker/name/CCO
    ticker = yf.Ticker(symbol)
    return ticker.info['longName']


# @app.route('/proto/mkt/<country_code>/ticker/name/<symbol>', methods=['GET'])
# def get_ticker_name_proto(country_code, symbol):
#     # http://localhost:8083/proto/mkt/CA/ticker/name/CCO
#     ticker = yf.Ticker(symbol + country_code_map[country_code])
#     ticker_proto = generate_proto_Ticker(symbol=symbol, name=ticker.info['longName'])
#     print(ticker_proto)
#
#     return ticker_proto.SerializeToString(), 200, {'Content-Type': 'application/x-protobuf'}


@app.route('/mkt/<country_code>/ticker/sector/<symbol>', methods=['GET'])
def get_ticker_sector(country_code, symbol):
    # http://localhost:8083/mkt/CA/ticker/sector/CCO
    return yf.Ticker(symbol + country_code_map[country_code]).info.get('sector', 'Unknown')


@app.route('/mkt/ticker/sector/<symbol>', methods=['GET'])
def get_ticker_sector_without_country(symbol):
    # http://localhost:8083/mkt/ticker/sector/CCO
    return yf.Ticker(symbol).info.get('sector', 'Unknown')


# @app.route('/proto/mkt/<country_code>/ticker/sector/<symbol>', methods=['GET'])
# def get_ticker_sector_proto(country_code, symbol):
#     # http://localhost:8083/proto/mkt/CA/ticker/sector/CCO
#     ticker = yf.Ticker(symbol + country_code_map[country_code])
#     ticker_proto = generate_proto_Ticker(symbol=symbol, sector=ticker.info['sector'])
#     print(ticker_proto)
#
#     return ticker_proto.SerializeToString(), 200, {'Content-Type': 'application/x-protobuf'}


@app.route('/mkt', methods=['GET'])
def get_mkt_data():
    # http://localhost:8083/mkt?symbol=CM&start=2023-10-01&end=2023-10-09
    symbol = request.args.get('symbol')
    start = request.args.get('start')
    end = request.args.get('end')
    country_code = request.args.get('country', '')
    if country_code == '':
        country_ext = symbol[symbol.rindex('.'):]
        for key in country_code_map.keys():
            if country_ext == country_code_map[key]:
                country_code = key
                break
        symbol = symbol[:symbol.rindex('.')]

    data, actual_symbol = download_financial_data(symbol, start, end, country_code, use_original_symbol=False)
    values = [{"date": convert_to_date(index), "price": row['Adj Close']} for index, row in data.iterrows()]
    return {
        "symbol": actual_symbol,
        "name": get_ticker_name(country_code, symbol),
        "sector": get_ticker_sector(country_code, symbol),
        "type": get_ticker_type(country_code, symbol),
        "data": values
    }


@app.route('/proto/mkt', methods=['GET'])
def get_mkt_data_proto():
    # http://localhost:8083/proto/mkt?symbol=CM&start=2023-10-01&end=2023-10-09
    symbol = request.args.get('symbol')
    start = request.args.get('start')
    end = request.args.get('end')
    country_code = request.args.get('country', '')
    if country_code == '':
        country_ext = symbol[symbol.rindex('.'):]
        for key in country_code_map.keys():
            if country_ext == country_code_map[key]:
                country_code = key
                break
        symbol = symbol[:symbol.rindex('.')]

    data, actual_symbol = download_financial_data(symbol, start, end, country_code, use_original_symbol=False)
    ticker = generate_proto_Ticker(actual_symbol,
                                   name=get_ticker_name(country_code, symbol),
                                   sector=get_ticker_sector(country_code, symbol),
                                   type=get_ticker_type(country_code, symbol))
    for index, row in data.iterrows(): ticker.data.append(generate_proto_Value(convert_to_date(index), row['Adj Close']))
    print(ticker)

    return ticker.SerializeToString(), 200, {'Content-Type': 'application/x-protobuf'}


## Only for CA
@app.route('/proto/mkt/portfolio', methods=['GET'])
def get_mkt_portfolio_data():
    exempt_ticker_in_data_source = ["Total invested"]
    purchases = []

    import platform
    src_mkt_data = "/var/mkt-data.txt" if platform.system() == "Linux" else "C:\\mkt-data.txt"

    data_source = pd.read_csv(open(src_mkt_data).readline())
    for index, row in data_source.iterrows():
        ticker = row['Stock code']
        if type(ticker) == float or ticker in exempt_ticker_in_data_source: continue
        qty = row['Qty bought']
        dt = str(row['Trade date'])
        ticker_price = float(row['Price per share'])
        sector = str(row['Sector'])
        account = str(row['Account'])
        imnt_type = get_ticker_type("CA", ticker)
        investment = Investment(f"{ticker}.TO", qty, dt, ticker_price, sector, account, imnt_type)
        print(investment)
        purchases.append(investment)

    portfolio = generate_proto_Portfolio()
    [generate_proto_Investment(portfolio, investment) for investment in purchases]
    print(portfolio)

    return portfolio.SerializeToString(), 200, {'Content-Type': 'application/x-protobuf'}


if __name__ == '__main__':
    app.run(port=8083, debug=True)
